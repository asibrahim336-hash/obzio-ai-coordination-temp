#!/usr/bin/env python3
"""Two-phase gate: shared control paths admit only the controller identity.

PO-03 declares certain paths shared - the control ledgers, metrics, evidence,
successor state, receipts, and the CI workflow files.  Route workers own
their own subtree and nothing else.  The requirement this component
implements is stronger than "the write is rejected": the rejection has to
happen *before* commit, so a refused write leaves no trace on disk.

The gate is therefore staged rather than inline:

    stage(...)         records an intended write; touches nothing
    precommit_check()  returns a decision over the whole staged set
    commit()           applies the writes, and only then

``commit`` is fail-closed in three ways:

1. Calling it without a preceding ``precommit_check`` raises
   ``GateNotCheckedError``.  There is no path from ``stage`` to disk that
   skips the decision.
2. Calling it after a decision containing violations raises
   ``GateViolationError`` and writes nothing at all - the whole staged set
   is refused together, so a batch cannot be half-applied.
3. The decision is bound to a digest of the staged set.  If anything is
   staged, removed, or altered between check and commit, the digest no
   longer matches and commit raises ``StagedSetChangedError``.  That closes
   the time-of-check/time-of-use window in which a worker could pass the
   check with a benign set and then swap in a shared-path write.

Identity is not self-asserted.  A writer presents ``(actor_id, fence_token)``
and the gate compares both against the registered controller identity, so a
worker that merely claims the controller's id without its fence token is
still refused.

Exit codes: 0 admissible, 1 violations, 2 usage error.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import posixpath
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Sequence


ALLOWED = "ALLOWED"
REJECTED_NOT_CONTROLLER = "REJECTED_NOT_CONTROLLER"
REJECTED_STALE_FENCE = "REJECTED_STALE_FENCE"
REJECTED_OUTSIDE_OWNED_SUBTREE = "REJECTED_OUTSIDE_OWNED_SUBTREE"
REJECTED_OUTSIDE_ALLOWLIST = "REJECTED_OUTSIDE_ALLOWLIST"


class GateError(RuntimeError):
    """Base class for gate refusals."""


class GateNotCheckedError(GateError):
    """commit() was called without a preceding precommit_check()."""


class GateViolationError(GateError):
    """commit() was called on a staged set the gate refused."""


class StagedSetChangedError(GateError):
    """The staged set changed between check and commit."""


@dataclass(frozen=True)
class Identity:
    actor_id: str
    fence_token: int


@dataclass(frozen=True)
class OwnershipPolicy:
    allowlist: tuple[str, ...]
    shared_path_globs: tuple[str, ...]
    controller: Identity

    @classmethod
    def from_path_ownership(cls, document: dict, controller_fence_token: int) -> "OwnershipPolicy":
        try:
            return cls(
                allowlist=tuple(document["allowlist"]),
                shared_path_globs=tuple(document["controller_shared_paths"]),
                controller=Identity(document["controller_run_id"], controller_fence_token),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"unusable path-ownership document: {exc}") from exc


@dataclass(frozen=True)
class StagedWrite:
    actor_id: str
    path: str
    payload_sha256: str
    payload_bytes: int


@dataclass(frozen=True)
class WriteVerdict:
    actor_id: str
    path: str
    verdict: str
    is_shared_path: bool
    reason: str

    def allowed(self) -> bool:
        return self.verdict == ALLOWED


@dataclass(frozen=True)
class Decision:
    staged_digest: str
    verdicts: tuple[WriteVerdict, ...]

    @property
    def violations(self) -> tuple[WriteVerdict, ...]:
        return tuple(v for v in self.verdicts if not v.allowed())

    @property
    def admissible(self) -> bool:
        return not self.violations


def _normalise(path: str) -> str:
    return posixpath.normpath(path.strip().replace("\\", "/"))


def _within(prefix: str, path: str) -> bool:
    entry = prefix.rstrip("/")
    if entry.endswith("/**"):
        entry = entry[: -len("/**")]
    entry = posixpath.normpath(entry)
    return path == entry or path.startswith(entry + "/")


def is_shared_path(policy: OwnershipPolicy, path: str) -> bool:
    candidate = _normalise(path)
    for pattern in policy.shared_path_globs:
        if pattern.endswith("/**"):
            if _within(pattern[: -len("/**")], candidate):
                return True
        elif fnmatch.fnmatch(candidate, pattern):
            return True
    return False


def _in_allowlist(policy: OwnershipPolicy, path: str) -> bool:
    candidate = _normalise(path)
    return any(
        _within(entry, candidate) if entry.endswith("/") else candidate.startswith(entry)
        for entry in policy.allowlist
    )


def staged_digest(writes: Sequence[StagedWrite]) -> str:
    """Order-independent digest binding a decision to an exact staged set."""
    lines = sorted(f"{w.actor_id}\x1f{_normalise(w.path)}\x1f{w.payload_sha256}\x1f{w.payload_bytes}" for w in writes)
    return hashlib.sha256("\x1e".join(lines).encode("utf-8")).hexdigest()


class SharedPathControllerGate:
    def __init__(self, root: Path, policy: OwnershipPolicy, writer: Identity, owned_subtree: str) -> None:
        self._root = Path(root)
        self._policy = policy
        self._writer = writer
        self._owned = _normalise(owned_subtree.rstrip("/").removesuffix("/**"))
        self._staged: list[tuple[StagedWrite, bytes]] = []
        self._decision: Decision | None = None

    @property
    def staged_writes(self) -> list[StagedWrite]:
        return [entry for entry, _ in self._staged]

    def stage(self, path: str, payload: bytes) -> StagedWrite:
        entry = StagedWrite(
            self._writer.actor_id,
            _normalise(path),
            hashlib.sha256(payload).hexdigest(),
            len(payload),
        )
        self._staged.append((entry, payload))
        # Any change to the staged set invalidates a previous decision.
        self._decision = None
        return entry

    def _judge(self, entry: StagedWrite) -> WriteVerdict:
        shared = is_shared_path(self._policy, entry.path)
        if not _in_allowlist(self._policy, entry.path):
            return WriteVerdict(
                entry.actor_id, entry.path, REJECTED_OUTSIDE_ALLOWLIST, shared,
                "path is outside the PO-03 write allowlist entirely",
            )
        if shared:
            if self._writer.actor_id != self._policy.controller.actor_id:
                return WriteVerdict(
                    entry.actor_id, entry.path, REJECTED_NOT_CONTROLLER, True,
                    "shared control path may only be written by the controller identity",
                )
            if self._writer.fence_token != self._policy.controller.fence_token:
                return WriteVerdict(
                    entry.actor_id, entry.path, REJECTED_STALE_FENCE, True,
                    "controller identity presented without the current fence token",
                )
            return WriteVerdict(entry.actor_id, entry.path, ALLOWED, True, "controller writing a shared path")
        if not _within(self._owned, entry.path):
            return WriteVerdict(
                entry.actor_id, entry.path, REJECTED_OUTSIDE_OWNED_SUBTREE, False,
                f"path is outside the writer's owned subtree {self._owned}",
            )
        return WriteVerdict(entry.actor_id, entry.path, ALLOWED, False, "writer owns this path")

    def precommit_check(self) -> Decision:
        verdicts = tuple(self._judge(entry) for entry, _ in self._staged)
        self._decision = Decision(staged_digest(self.staged_writes), verdicts)
        return self._decision

    def commit(self) -> list[str]:
        if self._decision is None:
            raise GateNotCheckedError("commit refused: precommit_check() has not run for this staged set")
        if self._decision.staged_digest != staged_digest(self.staged_writes):
            raise StagedSetChangedError("commit refused: staged set changed after the precommit decision")
        if not self._decision.admissible:
            reasons = "; ".join(f"{v.path}: {v.verdict}" for v in self._decision.violations)
            raise GateViolationError(f"commit refused: {reasons}")

        written: list[str] = []
        for entry, payload in self._staged:
            target = self._root / entry.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            written.append(entry.path)
        return written


def build_report(decision: Decision) -> dict:
    return {
        "component": "shared_path_controller_gate",
        "staged_digest": decision.staged_digest,
        "staged": len(decision.verdicts),
        "violations": len(decision.violations),
        "admissible": decision.admissible,
        "verdicts": [asdict(v) for v in decision.verdicts],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate shared-path writes on controller identity, before commit.")
    parser.add_argument("--path-ownership", required=True, type=Path)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--fence-token", required=True, type=int)
    parser.add_argument("--controller-fence-token", required=True, type=int)
    parser.add_argument("--owned-subtree", required=True)
    parser.add_argument("--target", action="append", required=True, help="repeatable path to be written")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        document = json.loads(args.path_ownership.read_text(encoding="utf-8"))
        policy = OwnershipPolicy.from_path_ownership(document, args.controller_fence_token)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"USAGE_ERROR: {exc}", file=sys.stderr)
        return 2

    # A dry run: nothing is committed, so the root is never touched.
    gate = SharedPathControllerGate(
        Path("/nonexistent-dry-run"), policy, Identity(args.actor_id, args.fence_token), args.owned_subtree
    )
    for target in args.target:
        gate.stage(target, b"")
    decision = gate.precommit_check()
    report = build_report(decision)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for verdict in report["verdicts"]:
            marker = "ok  " if verdict["verdict"] == ALLOWED else "FAIL"
            print(f"{marker} {verdict['verdict']:<34} {verdict['path']}  ({verdict['reason']})")
        print(f"summary: staged={report['staged']} violations={report['violations']}")
    return 0 if decision.admissible else 1


if __name__ == "__main__":
    raise SystemExit(main())
