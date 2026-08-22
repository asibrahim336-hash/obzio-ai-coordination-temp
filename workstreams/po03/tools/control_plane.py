#!/usr/bin/env python3
"""PO-03 transactional control plane.

The integration controller is the only writer of shared PO-03 control state.
Subordinate writers own a private subtree and a private branch; their results
enter shared state only through ``ingest``, which re-verifies every artifact by
hash and byte count before the coordinator is permitted to record completion.

Durability model
----------------
``events/ledger.jsonl`` is the append-only source of truth.  Every row carries
a monotonic sequence number and a hash chain over the canonical encoding of the
preceding row, so truncation, reordering and in-place edits are detectable.
``work-unit-registry.jsonl`` and ``recovery-state.json`` are projections that
can be rebuilt from the ledger alone, which is what makes recovery from a lost
parent process possible.

Safety properties enforced here
-------------------------------
* Provider completion never becomes Obzio completion without a verified commit.
* Actor authority and transition order are checked on the single append path,
  so the generic ``event`` subcommand is exactly as safe as ``complete``.
* A declared result commit must resolve to a real git commit object before it
  counts as durable, and an unresolvable one is a false completion.
* A fence token is admissible only if the coordinator issued it in a ``LEASED``
  event for that unit and it is the current lease.
* Appends are serialised by an advisory file lock, so concurrent multi-process
  callbacks cannot duplicate a sequence number or fork the hash chain.
* Duplicate callbacks carrying an identical payload are harmless no-ops.
* Every ingestion rejection leaves a durable ``RECOVERY_REQUIRED`` row.
* A subordinate cannot write outside its owned subtree or the commission
  allowlist, and cannot set ``COMPLETED`` or accept its own work.

Dependency-free by design: it must run in a clean GitHub Actions runner and a
fresh clone with no third-party packages, no ``/tmp`` state and no warm cache.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

CONTROL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CONTROL_ROOT.parents[1]

LEDGER_PATH = CONTROL_ROOT / "control" / "events" / "ledger.jsonl"
REGISTRY_PATH = CONTROL_ROOT / "control" / "work-unit-registry.jsonl"
RECOVERY_PATH = CONTROL_ROOT / "control" / "recovery-state.json"
DISPATCH_DIR = CONTROL_ROOT / "control" / "dispatch"
PATH_OWNERSHIP_PATH = CONTROL_ROOT / "control" / "path-ownership.json"

GENESIS_HASH = "0" * 64
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Wave-one write allowlist, quoted from the commission collision boundary.
ALLOWLIST_PREFIXES = ("workstreams/po03/", "receipts/po03/")
ALLOWLIST_WORKFLOW_DIR = ".github/workflows/"
ALLOWLIST_WORKFLOW_PREFIX = "po03-"
ALLOWLIST_WORKFLOW_SUFFIX = ".yml"

# Terminal Obzio states in which a durable, re-readable result must exist.
COMMITTED_STATES = {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"}
TERMINAL_STATES = COMMITTED_STATES | {"FAILED_TERMINAL", "CANCELLED"}

# Every event the coordinator may append as the outcome of one ingestion.
# Idempotency lookups span all of them so a replayed failure is exactly as
# harmless as a replayed success.
INGESTION_EVENTS = frozenset(
    {"PARENT_INGESTED", "PROVIDER_COMPLETED_UNCOMMITTED", "FAILED_TERMINAL", "CANCELLED", "RECOVERY_REQUIRED"}
)

EVENT_KINDS = {
    "CREATED",
    "LEASED",
    "RUNNING",
    "CHECKPOINTED",
    "RESULT_STAGING",
    "RESULT_STAGED",
    "RESULT_VERIFIED",
    "RESULT_COMMITTED",
    "PARENT_INGESTED",
    "COMPLETED",
    "PROVIDER_COMPLETED_UNCOMMITTED",
    "RECOVERY_REQUIRED",
    "RETRY_SCHEDULED",
    "FAILED_TERMINAL",
    "CANCELLED",
    "ACCEPTED",
    "REJECTED",
    "LEASE_EXPIRED",
    "FENCE_REJECTED",
    "DUPLICATE_IGNORED",
    "FAULT_INJECTED",
}

COORDINATOR = "coordinator"

# Authority is a property of the event kind, not of the entry point.  The defect
# this table closes was that ``cmd_complete`` checked authority while the
# generic ``event`` subcommand did not, so a worker could append COMPLETED with
# a fabricated commit id and the projection believed it.
COORDINATOR_ONLY_EVENTS = frozenset(
    {
        "CREATED",
        "LEASED",
        "PARENT_INGESTED",
        "COMPLETED",
        "PROVIDER_COMPLETED_UNCOMMITTED",
        "RECOVERY_REQUIRED",
        "RETRY_SCHEDULED",
        "CANCELLED",
        "LEASE_EXPIRED",
        "FENCE_REJECTED",
        "DUPLICATE_IGNORED",
    }
)
# A disposition may only come from an actor that is not the unit's producer.
DISPOSITION_EVENTS = frozenset({"ACCEPTED", "REJECTED"})
# Progress a subordinate is entitled to report about its own attempt.
WORKER_EVENTS = frozenset(
    {
        "RUNNING",
        "CHECKPOINTED",
        "RESULT_STAGING",
        "RESULT_STAGED",
        "RESULT_VERIFIED",
        "RESULT_COMMITTED",
        "FAILED_TERMINAL",
        "FAULT_INJECTED",
    }
)

# Custody order.  ``COMPLETED`` is rank 9 and reachable only from rank 8.
LIFECYCLE_RANK = {
    "CREATED": 0,
    "LEASED": 1,
    "RUNNING": 2,
    "CHECKPOINTED": 3,
    "RESULT_STAGING": 4,
    "RESULT_STAGED": 5,
    "RESULT_VERIFIED": 6,
    "RESULT_COMMITTED": 7,
    "PARENT_INGESTED": 8,
    "COMPLETED": 9,
}
PRODUCTION_EVENTS = frozenset(
    {"RUNNING", "CHECKPOINTED", "RESULT_STAGING", "RESULT_STAGED", "RESULT_VERIFIED", "RESULT_COMMITTED"}
)
# Events that legitimately move a unit backwards; recovery is not an attack.
RECOVERY_EVENTS = frozenset({"RECOVERY_REQUIRED", "LEASE_EXPIRED", "RETRY_SCHEDULED"})
# Events that record an observation without advancing custody state.
OBSERVABILITY_EVENTS = frozenset({"DUPLICATE_IGNORED", "FENCE_REJECTED", "FAULT_INJECTED"})

#: A result manifest is a derivation a reader reproduces, not a path to guess.
MANIFEST_SCHEME = "obzio-manifest-sha256"

LOCK_TIMEOUT_SECONDS = 30.0
LOCK_POLL_SECONDS = 0.005


class ControlPlaneError(RuntimeError):
    """Raised when an operation would violate a custody invariant."""


class LedgerLockUnavailable(ControlPlaneError):
    """Raised when the advisory lock cannot be taken within the bounded wait.

    Failing the append is the documented behaviour on lock timeout: an append
    that proceeds without the lock is exactly the defect the lock exists to
    prevent, so a caller must retry or escalate rather than race.
    """


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rows.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ControlPlaneError(f"{path}:{lineno}: corrupt ledger row: {exc}") from exc
    return rows


def write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return sha256_text(text)


# ---------------------------------------------------------------------------
# Git object resolution
# ---------------------------------------------------------------------------
#
# A locator is a claim about bytes.  Until the named object is resolved in an
# object database, "committed" is a string a worker typed.  Everything below
# fails closed: an unavailable git, an unreadable repository and an absent
# object are all "not resolved", never "assume durable".


def _git(args: list[str], *, cwd: Path, stdin: str | None = None, timeout: float = 60.0):
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def git_repo_root(repo: Path | None = None) -> Path | None:
    """Return the repository that owns ``repo``, or None if there is none."""
    candidate = Path(repo) if repo is not None else REPO_ROOT
    if not candidate.exists():
        return None
    proc = _git(["rev-parse", "--show-toplevel"], cwd=candidate)
    if proc is None or proc.returncode != 0:
        return None
    top = proc.stdout.strip()
    return Path(top) if top else None


def resolve_commits(commit_ids: Iterable[str], repo: Path | None = None) -> dict[str, bool]:
    """Resolve each id to a real commit object, in one batch.

    A tree or blob sha is not a commit: ``^{commit}`` peeling makes the type
    check explicit, so a caller cannot be fooled by a well-formed sha that
    names something other than a commit.
    """
    wanted = [cid for cid in dict.fromkeys(commit_ids) if isinstance(cid, str) and cid.strip()]
    resolved = {cid: False for cid in wanted}
    if not wanted:
        return resolved
    root = git_repo_root(repo)
    if root is None:
        return resolved
    stdin = "".join(f"{cid}^{{commit}}\n" for cid in wanted)
    proc = _git(["cat-file", "--batch-check"], cwd=root, stdin=stdin)
    if proc is None or proc.returncode != 0:
        return resolved
    for cid, line in zip(wanted, proc.stdout.splitlines()):
        fields = line.split()
        resolved[cid] = len(fields) >= 2 and fields[1] == "commit"
    return resolved


def commit_resolves(commit_id: str | None, repo: Path | None = None) -> bool:
    if not isinstance(commit_id, str) or not commit_id.strip():
        return False
    return resolve_commits([commit_id], repo).get(commit_id, False)


def read_blob(commit_id: str, relative: str, repo: Path | None = None) -> bytes | None:
    """Return the bytes of ``relative`` as it existed in ``commit_id``.

    This is the read-back that matters: it is anchored to an immutable commit,
    so an honest earlier result still verifies after its branch advances.
    """
    root = git_repo_root(repo)
    if root is None:
        return None
    try:
        # Binary mode: an artifact is bytes, and decoding it would corrupt any
        # non-UTF-8 payload before its hash could be checked.
        proc = subprocess.run(
            ["git", "cat-file", "blob", f"{commit_id}:{relative}"],
            cwd=str(root),
            capture_output=True,
            check=False,
            timeout=120.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def parse_content_uri(content_uri: str) -> tuple[str | None, str | None, str]:
    """Split ``git:<branch>@<commit>:<path>`` into its parts.

    Returns ``(branch, commit, relative_path)``.  Anything that does not carry a
    commit yields ``None`` for the commit so the caller can refuse to treat it
    as an immutable locator instead of quietly reading the working tree.
    """
    text = content_uri.strip()
    scheme, _, remainder = text.partition(":")
    if not remainder:
        return None, None, text
    if scheme != "git":
        return None, None, text.split(":", 2)[-1]
    ref, _, relative = remainder.partition(":")
    if not relative:
        return None, None, remainder
    branch, sep, commit = ref.partition("@")
    if not sep:
        return branch or None, None, relative
    return branch or None, commit or None, relative


# ---------------------------------------------------------------------------
# Advisory locking
# ---------------------------------------------------------------------------

try:  # POSIX advisory locking
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX platforms
    _fcntl = None

try:  # Windows advisory locking
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None

LOCK_MECHANISM = "fcntl.flock" if _fcntl is not None else ("msvcrt.locking" if _msvcrt is not None else "NOT_SUPPORTED")

_THREAD_LOCK = threading.RLock()
_LOCAL = threading.local()


def lock_path() -> Path:
    return LEDGER_PATH.with_suffix(LEDGER_PATH.suffix + ".lock")


def _acquire_os_lock(handle, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if _fcntl is not None:
                _fcntl.flock(handle.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            elif _msvcrt is not None:  # pragma: no cover - Windows only
                _msvcrt.locking(handle.fileno(), _msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover - no advisory locking on this platform
                raise LedgerLockUnavailable(
                    "advisory file locking is NOT_SUPPORTED on this platform: "
                    "neither fcntl nor msvcrt is importable, so concurrent multi-process "
                    "appends cannot be serialised"
                )
            return
        except LedgerLockUnavailable:
            raise
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            if time.monotonic() >= deadline:
                raise LedgerLockUnavailable(
                    f"could not acquire the ledger lock within {timeout:g}s; "
                    "refusing to append without exclusion"
                ) from exc
            time.sleep(LOCK_POLL_SECONDS)


def _release_os_lock(handle) -> None:
    try:
        if _fcntl is not None:
            _fcntl.flock(handle.fileno(), _fcntl.LOCK_UN)
        elif _msvcrt is not None:  # pragma: no cover - Windows only
            _msvcrt.locking(handle.fileno(), _msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


@contextmanager
def ledger_lock(timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Serialise the read-verify-append critical section.

    The lock is reentrant within a thread so ``ingest_result`` can hold it
    across its idempotency check and its append, which is what makes a
    duplicate concurrent callback resolve to exactly one ingestion row.  A
    threading lock is held as well as the file lock because ``flock`` is shared
    between threads of one process and would not exclude them from each other.
    """
    if getattr(_LOCAL, "depth", 0):
        _LOCAL.depth += 1
        try:
            yield
        finally:
            _LOCAL.depth -= 1
        return
    if not _THREAD_LOCK.acquire(timeout=timeout):
        raise LedgerLockUnavailable(f"could not acquire the in-process ledger lock within {timeout:g}s")
    handle = None
    try:
        target = lock_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = target.open("a+")
        _acquire_os_lock(handle, timeout)
        _LOCAL.depth = 1
        yield
    finally:
        _LOCAL.depth = 0
        if handle is not None:
            _release_os_lock(handle)
            handle.close()
        _THREAD_LOCK.release()


# ---------------------------------------------------------------------------
# Path scope
# ---------------------------------------------------------------------------


def normalise_path(path: str) -> str | None:
    """Return a repository-relative path, or None if it is not expressible as one.

    Anything absolute, empty, or containing a ``.`` or ``..`` segment is refused
    outright rather than repaired, because a guard that silently rewrites a
    traversal is a guard an attacker can steer.  Only a leading ``./`` is
    stripped, and a leading dot in a real name such as ``.github`` is preserved.
    """
    candidate = path.strip().replace("\\", "/")
    while candidate.startswith("./"):
        candidate = candidate[2:]
    if not candidate or candidate.startswith("/"):
        return None
    segments = candidate.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return None
    return candidate


def path_in_allowlist(path: str) -> bool:
    normalised = normalise_path(path)
    if normalised is None:
        return False
    if normalised.startswith(ALLOWLIST_PREFIXES):
        return True
    if normalised.startswith(ALLOWLIST_WORKFLOW_DIR):
        leaf = normalised[len(ALLOWLIST_WORKFLOW_DIR) :]
        return (
            "/" not in leaf
            and leaf.startswith(ALLOWLIST_WORKFLOW_PREFIX)
            and leaf.endswith(ALLOWLIST_WORKFLOW_SUFFIX)
        )
    return False


def check_allowlist(paths: Iterable[str]) -> list[str]:
    return sorted({path for path in paths if not path_in_allowlist(path)})


def load_path_ownership() -> dict[str, Any]:
    if not PATH_OWNERSHIP_PATH.exists():
        return {"owners": {}}
    return json.loads(PATH_OWNERSHIP_PATH.read_text(encoding="utf-8"))


def check_ownership(owner: str, paths: Iterable[str]) -> list[str]:
    """Return paths the owner is not entitled to write.

    Ownership is prefix based.  The coordinator owns shared control state; every
    other owner is confined to the subtrees declared in ``path-ownership.json``
    so two subordinates can never contend for the same file.
    """
    ownership = load_path_ownership()
    owners = ownership.get("owners", {})
    entry = owners.get(owner)
    if entry is None:
        return sorted(set(paths))
    prefixes = tuple(entry.get("owned_prefixes", []))
    violations: list[str] = []
    for path in paths:
        normalised = normalise_path(path)
        if normalised is None or not normalised.startswith(prefixes):
            violations.append(normalised if normalised is not None else path)
    return sorted(set(violations))


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def ledger_rows() -> list[dict[str, Any]]:
    return read_jsonl(LEDGER_PATH)


def _rows_for_append() -> list[dict[str, Any]]:
    """Read the ledger inside the append critical section.

    Deliberately not routed through ``ledger_rows`` so that a caller which has
    wrapped the public reader cannot re-open the read-verify-append race the
    lock closes.
    """
    return read_jsonl(LEDGER_PATH)


def verify_chain(rows: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    previous = GENESIS_HASH
    for index, row in enumerate(rows):
        expected_seq = index + 1
        if row.get("seq") != expected_seq:
            errors.append(f"row {index}: seq {row.get('seq')} is not monotonic (expected {expected_seq})")
        if row.get("prev_sha256") != previous:
            errors.append(f"seq {row.get('seq')}: prev_sha256 does not chain to the preceding row")
        body = {key: value for key, value in row.items() if key != "row_sha256"}
        computed = sha256_text(canonical(body))
        if row.get("row_sha256") != computed:
            errors.append(f"seq {row.get('seq')}: row_sha256 does not match its canonical body")
        previous = row.get("row_sha256", GENESIS_HASH)
    return errors


def unit_owner(unit_id: str, unit: dict[str, Any] | None = None) -> str | None:
    """Resolve the producer of a unit from its immutable dispatch record.

    The dispatch record is the authority, because it was written before the
    unit was handed out.  The ``CREATED`` payload is a fallback for a unit whose
    dispatch file is not reachable from this process.
    """
    dispatch_path = DISPATCH_DIR / f"{unit_id}.json"
    if dispatch_path.exists():
        try:
            owner = json.loads(dispatch_path.read_text(encoding="utf-8")).get("owner")
        except (json.JSONDecodeError, OSError):
            owner = None
        if owner:
            return owner
    return (unit or {}).get("owner")


def check_actor_authority(unit_id: str, event: str, actor: str, unit: dict[str, Any] | None) -> None:
    """Refuse an event the actor has no standing to author.

    Enforced here rather than in a command handler so every entry point --
    ``event``, ``complete``, ``review``, ``ingest`` and the recovery actuator --
    inherits the same rule.
    """
    if not isinstance(actor, str) or not actor.strip():
        raise ControlPlaneError(f"{event} requires a named actor")
    if event in COORDINATOR_ONLY_EVENTS and actor != COORDINATOR:
        raise ControlPlaneError(
            f"actor {actor!r} may not append {event} for {unit_id}: "
            f"{event} is coordinator-only custody authority"
        )
    if event in DISPOSITION_EVENTS:
        owner = unit_owner(unit_id, unit)
        if owner is not None and actor == owner:
            raise ControlPlaneError(
                f"actor {actor!r} may not append {event} for {unit_id}: "
                "a producer cannot accept or reject its own work"
            )
        roster = load_path_ownership().get("owners", {})
        if roster and actor != COORDINATOR and actor not in roster:
            raise ControlPlaneError(
                f"actor {actor!r} may not append {event} for {unit_id}: "
                "a disposition requires a registered independent reviewer"
            )
    if event in WORKER_EVENTS:
        owner = unit_owner(unit_id, unit)
        if owner is not None and actor not in (owner, COORDINATOR):
            raise ControlPlaneError(
                f"actor {actor!r} may not append {event} for {unit_id}: "
                f"the unit is leased to {owner!r}"
            )


def check_transition(unit_id: str, event: str, unit: dict[str, Any] | None, payload: dict[str, Any]) -> None:
    """Refuse an event that would advance a unit out of order.

    The rule is a precondition table rather than a strict single-step ladder,
    because ingestion legitimately verifies durability itself and therefore
    admits ``RUNNING -> PARENT_INGESTED``.  What it never admits is reaching a
    terminal claim without the evidence that claim asserts.
    """
    if event == "CREATED":
        if unit is not None:
            raise ControlPlaneError(f"{unit_id} already exists; CREATED is not repeatable")
        return
    if unit is None:
        raise ControlPlaneError(f"unknown unit: {unit_id}; CREATED must come first")
    if event in OBSERVABILITY_EVENTS:
        return

    state = unit["obzio_state"]
    rank = LIFECYCLE_RANK.get(state)
    acceptance = unit.get("acceptance")

    if event in RECOVERY_EVENTS:
        if state == "COMPLETED" and event != "RECOVERY_REQUIRED":
            raise ControlPlaneError(f"{unit_id} is COMPLETED; {event} would regress a completed unit")
        return
    if event == "LEASED":
        if state == "COMPLETED" or acceptance in ("ACCEPTED", "REJECTED"):
            raise ControlPlaneError(f"{unit_id} is {state}/{acceptance}; a completed unit cannot be re-leased")
        return
    if event in PRODUCTION_EVENTS:
        if rank is None and state not in ("RECOVERY_REQUIRED", "RETRY_SCHEDULED", "PROVIDER_COMPLETED_UNCOMMITTED"):
            raise ControlPlaneError(f"{unit_id} is {state}; {event} requires an active lease")
        if rank is not None and rank < LIFECYCLE_RANK["LEASED"]:
            raise ControlPlaneError(f"{unit_id} is {state}; {event} requires a lease granted by the coordinator")
        if rank is not None and rank >= LIFECYCLE_RANK["PARENT_INGESTED"]:
            raise ControlPlaneError(
                f"{unit_id} is {state}; {event} cannot resume production after ingestion without a re-lease"
            )
        return
    if event in ("FAILED_TERMINAL", "CANCELLED", "PROVIDER_COMPLETED_UNCOMMITTED"):
        if state == "COMPLETED":
            raise ControlPlaneError(f"{unit_id} is COMPLETED; {event} would regress a completed unit")
        return
    if event == "PARENT_INGESTED":
        if rank is not None and rank < LIFECYCLE_RANK["LEASED"]:
            raise ControlPlaneError(f"{unit_id} is {state}; ingestion requires a leased attempt")
        if state == "COMPLETED":
            raise ControlPlaneError(f"{unit_id} is already COMPLETED; refusing to re-ingest")
        if not str(payload.get("result_commit_id") or "").strip():
            raise ControlPlaneError(f"{unit_id}: PARENT_INGESTED requires a declared result_commit_id")
        return
    if event == "COMPLETED":
        if state != "PARENT_INGESTED":
            raise ControlPlaneError(f"{unit_id} is {state}; completion requires PARENT_INGESTED")
        commit_id = payload.get("result_commit_id") or unit.get("result_commit_id")
        if not str(commit_id or "").strip():
            raise ControlPlaneError(f"{unit_id} has no durable result commit; cannot complete")
        return
    if event in DISPOSITION_EVENTS:
        if state != "COMPLETED":
            raise ControlPlaneError(f"{unit_id} is {state}; independent disposition requires a COMPLETED unit")
        return


def append_event(
    unit_id: str,
    event: str,
    *,
    actor: str,
    obzio_state: str | None = None,
    provider_state: str | None = None,
    fence_token: int | None = None,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    dedupe_events: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Append one custody row after checking authority, order and integrity.

    ``dedupe_key`` closes the concurrency hole that a lock alone cannot: two
    callbacks can both pass an idempotency check taken before the lock, so the
    check is repeated inside the critical section and the loser is recorded as
    ``DUPLICATE_IGNORED`` instead of appending a second ingestion row.
    """
    if event not in EVENT_KINDS:
        raise ControlPlaneError(f"unknown event kind: {event}")
    payload = dict(payload or {})
    with ledger_lock():
        rows = _rows_for_append()
        chain_errors = verify_chain(rows)
        if chain_errors:
            raise ControlPlaneError("ledger integrity failure: " + "; ".join(chain_errors))
        units = project_units(rows)
        unit = units.get(unit_id)
        check_actor_authority(unit_id, event, actor, unit)
        check_transition(unit_id, event, unit, payload)
        if dedupe_key is not None:
            watched = frozenset(dedupe_events or (event,))
            duplicate = any(
                row["unit_id"] == unit_id
                and row["event"] in watched
                and (row.get("payload") or {}).get("result_sha256") == dedupe_key
                for row in rows
            )
            if duplicate:
                return _write_row(
                    rows,
                    unit_id,
                    "DUPLICATE_IGNORED",
                    actor=COORDINATOR,
                    obzio_state=None,
                    provider_state=None,
                    fence_token=fence_token,
                    payload={
                        "result_sha256": dedupe_key,
                        "reason": "idempotent replay of an already ingested result",
                        "suppressed_event": event,
                    },
                )
        return _write_row(
            rows,
            unit_id,
            event,
            actor=actor,
            obzio_state=obzio_state,
            provider_state=provider_state,
            fence_token=fence_token,
            payload=payload,
        )


def _write_row(
    rows: list[dict[str, Any]],
    unit_id: str,
    event: str,
    *,
    actor: str,
    obzio_state: str | None,
    provider_state: str | None,
    fence_token: int | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Serialise one row.  Only ever called with the ledger lock held."""
    body = {
        "seq": len(rows) + 1,
        "ts": utc_now(),
        "unit_id": unit_id,
        "event": event,
        "obzio_state": obzio_state or event,
        "provider_state": provider_state,
        "actor": actor,
        "fence_token": fence_token,
        "payload": payload,
        "prev_sha256": rows[-1]["row_sha256"] if rows else GENESIS_HASH,
    }
    body["row_sha256"] = sha256_text(canonical(body))
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", encoding="utf-8") as handle:
        handle.write(canonical(body) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return body


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------


def project_units(rows: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Rebuild per-unit state from the ledger alone.

    This is the recovery path: a parent that lost its memory reconstructs the
    entire fleet from immutable rows rather than from any worker's self-report.
    """
    rows = ledger_rows() if rows is None else rows
    units: dict[str, dict[str, Any]] = {}
    for row in rows:
        unit_id = row["unit_id"]
        unit = units.setdefault(
            unit_id,
            {
                "unit_id": unit_id,
                "obzio_state": "CREATED",
                "provider_state": "UNKNOWN",
                "fence_token": 0,
                "checkpoint_seq": 0,
                "first_seen_ts": row["ts"],
                "last_event_ts": row["ts"],
                "last_event_seq": row["seq"],
                "lease": None,
                "owner": None,
                "issued_fence_tokens": [],
                "result_commit_id": None,
                "result_locator": None,
                "artifact_count": 0,
                "total_bytes": 0,
                "attempts": 0,
                "retries": 0,
                "acceptance": "NOT_TESTED",
                "reviewer_id": None,
                "history": [],
            },
        )
        unit["last_event_ts"] = row["ts"]
        unit["last_event_seq"] = row["seq"]
        unit["history"].append({"seq": row["seq"], "event": row["event"], "ts": row["ts"]})
        if row.get("fence_token") is not None:
            unit["fence_token"] = max(unit["fence_token"], int(row["fence_token"]))
        if row.get("provider_state"):
            unit["provider_state"] = row["provider_state"]
        payload = row.get("payload") or {}
        event = row["event"]
        if event in {"DUPLICATE_IGNORED", "FENCE_REJECTED", "FAULT_INJECTED"}:
            # Observability events never advance custody state.
            continue
        if event == "CREATED" and payload.get("owner"):
            unit["owner"] = payload["owner"]
        if event == "LEASED":
            unit["lease"] = {
                "lease_id": payload.get("lease_id"),
                "worker_id": payload.get("worker_id"),
                "granted_at": row["ts"],
                "expires_at": payload.get("expires_at"),
            }
            unit["attempts"] += 1
            # Only a coordinator-issued LEASED row makes a fence token real.
            # Ingestion compares against this list, so an arbitrary higher
            # token cannot be self-promoted into ownership.
            if row.get("fence_token") is not None:
                token = int(row["fence_token"])
                if token not in unit["issued_fence_tokens"]:
                    unit["issued_fence_tokens"].append(token)
        if event == "LEASE_EXPIRED":
            unit["lease"] = None
            unit["obzio_state"] = "RECOVERY_REQUIRED"
            continue
        if event == "RETRY_SCHEDULED":
            unit["retries"] += 1
        if event == "CHECKPOINTED":
            unit["checkpoint_seq"] = max(unit["checkpoint_seq"], int(payload.get("checkpoint_seq", 0)))
        if event in {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"}:
            unit["result_commit_id"] = payload.get("result_commit_id") or unit["result_commit_id"]
            unit["result_locator"] = payload.get("result_locator") or unit["result_locator"]
            unit["artifact_count"] = payload.get("artifact_count", unit["artifact_count"])
            unit["total_bytes"] = payload.get("total_bytes", unit["total_bytes"])
        if event in {"ACCEPTED", "REJECTED"}:
            unit["acceptance"] = event
            unit["reviewer_id"] = payload.get("reviewer_id")
            continue
        if event in EVENT_KINDS:
            unit["obzio_state"] = row.get("obzio_state") or event
    return units


def materialize() -> dict[str, Any]:
    units = project_units()
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [canonical(units[unit_id]) for unit_id in sorted(units)]
    REGISTRY_PATH.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return units


def scan_recovery(now: float | None = None, *, repo: Path | None = None) -> dict[str, Any]:
    """Detect every unit that cannot be truthfully called complete.

    ``false_completion`` is the assertion that matters most: a unit whose
    provider said COMPLETED but which has no verified durable commit must be
    reported as PROVIDER_COMPLETED_UNCOMMITTED and re-run from immutable input.

    Checking only for a *missing* commit id was the defect that let a fabricated
    one through, so every terminal commit id is additionally resolved against
    the object database.  A unit whose obzio state is COMPLETED while its
    declared commit does not resolve is a false completion, not a durable
    result.  Units that merely reached ``RESULT_COMMITTED`` or
    ``PARENT_INGESTED`` with an unresolvable id are reported separately,
    because a locator can also be unresolvable in this checkout simply because
    its branch has not been fetched here.

    The scan is a pure detector: it writes only the recovery projection and
    never appends to the ledger, so it stays safe to run in a read-only clean
    clone check.  Remediation is the explicit job of ``recover_units``.
    """
    now = time.time() if now is None else now
    rows = ledger_rows()
    chain_errors = verify_chain(rows)
    units = project_units(rows)
    terminal_commits = {
        unit["result_commit_id"]
        for unit in units.values()
        if unit["obzio_state"] in COMMITTED_STATES and unit["result_commit_id"]
    }
    resolved = resolve_commits(terminal_commits, repo)
    expired: list[str] = []
    uncommitted: list[str] = []
    orphaned: list[str] = []
    resumable: list[str] = []
    false_completions: list[str] = []
    unresolvable: list[str] = []
    flagged: list[str] = []
    for unit_id, unit in sorted(units.items()):
        lease = unit.get("lease")
        if lease and lease.get("expires_at"):
            try:
                deadline = datetime.strptime(lease["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                deadline = None
            if deadline and deadline.timestamp() < now and unit["obzio_state"] not in TERMINAL_STATES:
                expired.append(unit_id)
        if unit["provider_state"] == "COMPLETED" and not unit["result_commit_id"]:
            uncommitted.append(unit_id)
            if unit["obzio_state"] == "COMPLETED":
                false_completions.append(unit_id)
        if unit["obzio_state"] in COMMITTED_STATES and not unit["result_commit_id"]:
            false_completions.append(unit_id)
        if unit["obzio_state"] in COMMITTED_STATES and unit["result_commit_id"]:
            if not resolved.get(unit["result_commit_id"], False):
                unresolvable.append(unit_id)
                if unit["obzio_state"] == "COMPLETED":
                    false_completions.append(unit_id)
        if unit["obzio_state"] == "RECOVERY_REQUIRED":
            # Something already refused this unit durably.  A scan that reported
            # no recovery needed while a recorded rejection sat in the ledger
            # would make the recording pointless.
            flagged.append(unit_id)
        if unit["obzio_state"] not in TERMINAL_STATES:
            resumable.append(unit_id)
            if not lease:
                orphaned.append(unit_id)
    state = {
        "generated_at": utc_now(),
        "ledger_rows": len(rows),
        "ledger_head_sha256": rows[-1]["row_sha256"] if rows else GENESIS_HASH,
        "ledger_chain_valid": not chain_errors,
        "ledger_chain_errors": chain_errors,
        "units_total": len(units),
        "expired_leases": expired,
        "provider_completed_uncommitted": sorted(set(uncommitted)),
        "orphaned_units": orphaned,
        "resumable_units": resumable,
        "false_completions": sorted(set(false_completions)),
        "unresolvable_result_commits": sorted(set(unresolvable)),
        "recorded_rejections": sorted(set(flagged)),
        "commit_resolution_available": git_repo_root(repo) is not None,
        "recovery_required": bool(
            chain_errors or expired or uncommitted or false_completions or unresolvable or flagged
        ),
    }
    write_json(RECOVERY_PATH, state)
    return state


def _sweep_targets(rows: list[dict[str, Any]], wanted: set[str] | None) -> dict[str, dict[str, Any]]:
    """The latest ingestion row per unit: what was actually admitted, and from where.

    Only ``PARENT_INGESTED`` rows carry verified artifacts read out of a commit.
    A unit whose result was never durably committed has no object to re-read, so
    it is not a sweep target rather than a sweep failure.
    """
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["event"] != "PARENT_INGESTED":
            continue
        if wanted is not None and row["unit_id"] not in wanted:
            continue
        latest[row["unit_id"]] = row
    return latest


def rehash_committed_artifacts(
    *, repo: Path | None = None, unit_ids: Iterable[str] | None = None
) -> dict[str, Any]:
    """Re-read every ingested artifact from the commit it was ingested from.

    A hash taken once at ingestion is a statement about that moment.  It does
    not establish that the bytes are still retrievable: an object store can lose
    an object, a transfer can be incomplete, and a clone can simply never have
    received the commit.  This sweep re-resolves each artifact and compares
    bytes again, so custody is re-proved rather than assumed.

    What corruption can look like is constrained by git itself.  A commit id is
    a hash over its own content, so nobody can make a fixed commit id yield
    different artifact bytes; the reachable failures are an object that has
    become *unreadable*, and a ledger record that no longer *agrees* with the
    object store.  Both are detected and both record RECOVERY_REQUIRED.

    Idempotent: a finding already recorded for a unit is not recorded twice, so
    the sweep is safe to run on a timer.
    """
    rows = ledger_rows()
    wanted = set(unit_ids) if unit_ids is not None else None
    targets = _sweep_targets(rows, wanted)
    available = git_repo_root(repo) is not None
    report: dict[str, Any] = {
        "generated_at": utc_now(),
        "status": "OK" if available else "NOT_SUPPORTED",
        "commit_resolution_available": available,
        "units": sorted(targets),
        "units_swept": 0,
        "artifacts_rehashed": 0,
        "verified": [],
        "corrupt": [],
        "unreadable": [],
        "not_immutably_located": [],
        "recorded": [],
        "recovery_required": False,
    }
    if not available:
        report["detail"] = (
            f"no git object database is reachable from {repo or REPO_ROOT}; committed "
            "artifacts cannot be re-hashed here, so nothing is claimed either way"
        )
        return report

    for unit_id in sorted(targets):
        payload = targets[unit_id].get("payload") or {}
        findings: list[dict[str, Any]] = []
        unlocated: list[str] = []
        report["units_swept"] += 1
        for artifact in payload.get("verified_artifacts") or []:
            read_from = str(artifact.get("read_from") or "")
            scheme, _, locator = read_from.partition(":")
            if scheme != "git" or ":" not in locator:
                # Ingested before the immutable-locator rule, or ingested from a
                # working tree.  There is no commit and path to re-read from, so
                # it is reported as un-sweepable, never counted as verified.
                unlocated.append(str(artifact.get("logical_name") or "?"))
                continue
            commit_id, _, relative = locator.partition(":")
            report["artifacts_rehashed"] += 1
            raw = read_blob(commit_id, relative, repo)
            if raw is None:
                finding = {
                    "unit_id": unit_id,
                    "commit_id": commit_id,
                    "path": relative,
                    "kind": "unreadable",
                    "detail": f"{commit_id}:{relative} can no longer be read from the object database",
                }
                report["unreadable"].append(finding)
                findings.append(finding)
                continue
            actual_sha = sha256_bytes(raw)
            if actual_sha != artifact.get("sha256") or len(raw) != artifact.get("bytes"):
                finding = {
                    "unit_id": unit_id,
                    "commit_id": commit_id,
                    "path": relative,
                    "kind": "corrupt",
                    "detail": (
                        f"{commit_id}:{relative} no longer matches the ingested record "
                        f"(ingested {artifact.get('sha256')} / {artifact.get('bytes')} bytes, "
                        f"read {actual_sha} / {len(raw)} bytes)"
                    ),
                }
                report["corrupt"].append(finding)
                findings.append(finding)
                continue
            report["verified"].append(
                {"unit_id": unit_id, "commit_id": commit_id, "path": relative, "sha256": actual_sha}
            )
        if unlocated:
            report["not_immutably_located"].append(
                {
                    "unit_id": unit_id,
                    "artifacts": len(unlocated),
                    "logical_names": sorted(set(unlocated)),
                    "result_commit_id": payload.get("result_commit_id"),
                    "detail": (
                        "ingested before the immutable read-back rule: the ingestion row "
                        "records no commit and path, so these artifacts cannot be re-hashed "
                        "without re-ingesting the result"
                    ),
                }
            )
        if not findings:
            continue
        report["recovery_required"] = True
        digest = sha256_text(canonical(findings))
        already = any(
            row["unit_id"] == unit_id
            and row["event"] == "RECOVERY_REQUIRED"
            and (row.get("payload") or {}).get("sweep_digest") == digest
            for row in rows
        )
        if already:
            continue
        detail = "; ".join(item["detail"] for item in findings)
        record_rejection(
            unit_id,
            f"re-hash sweep found {len(findings)} artifact(s) no longer verifiable: {detail}",
            extra={
                "reason": "post-commit corruption detected by the re-hash sweep",
                "sweep_digest": digest,
                "findings": findings,
            },
            rejected_by="rehash_sweep",
        )
        report["recorded"].append(unit_id)
    report["units_not_immutably_located"] = [
        item["unit_id"] for item in report["not_immutably_located"]
    ]
    if report["recorded"]:
        materialize()
    return report


# ---------------------------------------------------------------------------
# Recovery actuation
# ---------------------------------------------------------------------------
#
# The scanner detects; this remediates.  They are separate on purpose: the
# scanner is called by ``verify``, by subordinates and by a read-only
# clean-clone check, and a detector that appends to the shared ledger every
# time somebody asks it a question cannot be run safely.  Everything below is
# the writer, and it writes only what a worker needs to continue without a
# human deciding anything.

#: States whose problem is the work itself rather than the lease.
RERUN_STATES = frozenset({"RECOVERY_REQUIRED", "PROVIDER_COMPLETED_UNCOMMITTED", "RETRY_SCHEDULED"})
#: Actions that append to the ledger and hand the unit back to its worker.
ACTUATING_ACTIONS = frozenset({"re_lease", "rerun", "resume"})
DEFAULT_LEASE_TTL_SECONDS = 5400
DEFAULT_MAX_ATTEMPTS = 4


def _lease_deadline(lease: dict[str, Any] | None) -> float | None:
    if not lease or not lease.get("expires_at"):
        return None
    try:
        parsed = datetime.strptime(lease["expires_at"], "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc).timestamp()


def _last_checkpoint(rows: list[dict[str, Any]], unit_id: str) -> dict[str, Any] | None:
    for row in reversed(rows):
        if row["unit_id"] == unit_id and row["event"] == "CHECKPOINTED":
            return dict(row.get("payload") or {})
    return None


def _plan_recovery(
    unit_id: str,
    unit: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    now: float,
    max_attempts: int,
) -> dict[str, Any] | None:
    """Decide what one unit needs, or None if it needs nothing.

    Order matters.  A stale lease is diagnosed before a failed attempt, because
    a unit whose lease has gone has no worker to rerun it, and the projection
    collapses ``LEASE_EXPIRED`` into the same state a refusal produces.
    """
    state = unit["obzio_state"]
    if state == "COMPLETED" or unit.get("acceptance") in ("ACCEPTED", "REJECTED"):
        return None
    if state in ("FAILED_TERMINAL", "CANCELLED"):
        # An honestly declared terminal failure is a result, not a fault.
        return None
    if state == "PARENT_INGESTED":
        # Ingested and waiting on coordinator completion: not a recovery matter.
        return None
    if state == "RESULT_COMMITTED":
        return {
            "unit_id": unit_id,
            "action": "awaiting_ingestion",
            "reason": (
                "the worker committed a durable result that has not been ingested; "
                "re-running would destroy work that already exists"
            ),
            "result_commit_id": unit.get("result_commit_id"),
            "resume_from_checkpoint": unit.get("checkpoint_seq", 0),
        }

    lease = unit.get("lease")
    deadline = _lease_deadline(lease)
    lease_lost = lease is None or (deadline is not None and deadline < now)
    if lease_lost:
        action = "re_lease"
        reason = (
            "the lease expired and was never transferred"
            if lease is not None
            else "the unit holds no lease, so no worker is responsible for it"
        )
    elif state in RERUN_STATES:
        action = "rerun"
        reason = f"the unit is {state}: its last attempt produced nothing durable"
    else:
        return None

    checkpoint_seq = int(unit.get("checkpoint_seq") or 0)
    if checkpoint_seq > 0:
        # Restarting a checkpointed unit at zero throws away work the ledger
        # already proves happened.
        action = "resume"
        reason = f"{reason}; a checkpoint at {checkpoint_seq} is available to resume from"

    attempts = int(unit.get("retries") or 0)
    plan = {
        "unit_id": unit_id,
        "action": action,
        "reason": reason,
        "state_before": state,
        "attempts": attempts,
        "resume_from_checkpoint": checkpoint_seq,
        "resume_checkpoint": _last_checkpoint(rows, unit_id) if checkpoint_seq else None,
        "expire_lease": lease is not None and lease_lost,
        "lease_before": lease,
    }
    if attempts >= max_attempts:
        plan.update(
            action="escalate",
            reason=(
                f"the retry budget is exhausted after {attempts} scheduled retries "
                f"(limit {max_attempts}); unbounded automatic retry is its own defect"
            ),
        )
        return plan

    dispatch_path = DISPATCH_DIR / f"{unit_id}.json"
    if not dispatch_path.exists():
        plan.update(
            action="escalate",
            reason=(
                f"no immutable dispatch record at {dispatch_path}; a rerun input cannot be "
                "reconstructed and must not be guessed"
            ),
        )
        return plan
    try:
        dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        plan.update(action="escalate", reason=f"the dispatch record for {unit_id} is unreadable: {exc}")
        return plan
    owner = dispatch.get("owner") or unit.get("owner")
    if not owner:
        plan.update(
            action="escalate",
            reason="the dispatch record names no owner, so there is no worker to lease to",
        )
        return plan
    plan["worker_id"] = owner
    plan["dispatch"] = {
        "dispatch_path": str(dispatch_path),
        "immutable_input_manifest_sha256": dispatch.get("immutable_input_manifest_sha256"),
        "acceptance_contract_sha256": dispatch.get("acceptance_contract_sha256"),
        "idempotency_key": dispatch.get("idempotency_key"),
        "result_slot": dispatch.get("result_slot"),
    }
    plan["fence_token"] = int(unit.get("fence_token") or 0) + 1
    return plan


def _enact_recovery(plan: dict[str, Any], *, ttl_seconds: int, now: float, rows: list[dict[str, Any]]) -> bool:
    """Apply one plan.  Returns True when the unit was handed back to a worker."""
    unit_id = plan["unit_id"]
    if plan["action"] == "awaiting_ingestion":
        return False
    if plan["action"] == "escalate":
        already = any(
            row["unit_id"] == unit_id
            and (row.get("payload") or {}).get("escalated_after_attempts") == plan["attempts"]
            for row in rows
        )
        if not already:
            record_rejection(
                unit_id,
                f"recovery escalated: {plan['reason']}",
                extra={
                    "reason": "automatic recovery cannot proceed without a decision",
                    "escalated_after_attempts": plan["attempts"],
                    "state_before": plan["state_before"],
                },
                rejected_by="recover_units",
            )
        return False

    fence = plan["fence_token"]
    dispatch = plan["dispatch"]
    if plan["expire_lease"]:
        append_event(
            unit_id,
            "LEASE_EXPIRED",
            actor=COORDINATOR,
            fence_token=(plan["lease_before"] or {}).get("fence_token"),
            payload={
                "reason": "lease deadline passed without a durable result",
                "lease_id": (plan["lease_before"] or {}).get("lease_id"),
                "expired_at": (plan["lease_before"] or {}).get("expires_at"),
                "recovered_by": "recover_units",
            },
        )
    append_event(
        unit_id,
        "RETRY_SCHEDULED",
        actor=COORDINATOR,
        fence_token=fence,
        payload={
            "reason": plan["reason"],
            "action": plan["action"],
            "attempt": plan["attempts"] + 1,
            "resume_from_checkpoint": plan["resume_from_checkpoint"],
            "recovered_by": "recover_units",
            **dispatch,
        },
    )
    expires_at = datetime.fromtimestamp(now + ttl_seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    append_event(
        unit_id,
        "LEASED",
        actor=COORDINATOR,
        provider_state="QUEUED",
        fence_token=fence,
        payload={
            "lease_id": f"lease-{unit_id}-{fence}",
            "worker_id": plan["worker_id"],
            "expires_at": expires_at,
            "ttl_seconds": ttl_seconds,
            "resume_from_checkpoint": plan["resume_from_checkpoint"],
            "resume_checkpoint": plan["resume_checkpoint"],
            "recovered_by": "recover_units",
            "recovery_action": plan["action"],
            "immutable_input_manifest_sha256": dispatch["immutable_input_manifest_sha256"],
            "idempotency_key": dispatch["idempotency_key"],
        },
    )
    return True


def recover_units(
    *,
    unit_ids: Iterable[str] | None = None,
    now: float | None = None,
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    apply: bool = True,
) -> dict[str, Any]:
    """Re-lease, rerun and resume every unit that cannot make progress alone.

    Detection was never the missing half.  Cohort a2 measured seven in-flight
    units and none of them resumed, because nothing in the control plane acted
    on what the scanner reported.  This does:

    * a lease that expired is expired explicitly and re-issued with a fresh
      fence, which also evicts the previous holder, since ingestion admits only
      the current issued token;
    * a unit whose attempt produced nothing durable is rerun from its immutable
      dispatch input, never from a worker's self-report;
    * a unit with a checkpoint resumes at that checkpoint, and the resume point
      is written into the ledger so it survives the actuating process;
    * a unit that has exhausted its retry budget, or that has no immutable
      dispatch record to rerun from, is escalated rather than guessed at.

    Idempotent by construction: every action it takes removes the condition
    that selected the unit, so a second invocation finds nothing to do.
    """
    now_ts = time.time() if now is None else now
    with ledger_lock():
        rows = ledger_rows()
        units = project_units(rows)
        if unit_ids is None:
            selected = dict(units)
        else:
            wanted = list(dict.fromkeys(unit_ids))
            missing = [unit_id for unit_id in wanted if unit_id not in units]
            if missing:
                raise ControlPlaneError(f"unknown unit(s): {', '.join(missing)}")
            selected = {unit_id: units[unit_id] for unit_id in wanted}

        actions: list[dict[str, Any]] = []
        for unit_id in sorted(selected):
            plan = _plan_recovery(
                unit_id, selected[unit_id], rows, now=now_ts, max_attempts=max_attempts
            )
            if plan is not None:
                actions.append(plan)

        actuated = 0
        if apply:
            for plan in actions:
                if _enact_recovery(plan, ttl_seconds=ttl_seconds, now=now_ts, rows=rows):
                    actuated += 1
            if actions:
                materialize()

    report = {
        "generated_at": utc_now(),
        "dry_run": not apply,
        "ttl_seconds": ttl_seconds,
        "max_attempts": max_attempts,
        "units_considered": len(selected),
        "units_planned": len(actions),
        "units_actuated": actuated,
        "actions": actions,
        "re_leased": [item["unit_id"] for item in actions if item["action"] == "re_lease"],
        "rerun": [item["unit_id"] for item in actions if item["action"] == "rerun"],
        "resumed": [item["unit_id"] for item in actions if item["action"] == "resume"],
        "awaiting_ingestion": [
            item["unit_id"] for item in actions if item["action"] == "awaiting_ingestion"
        ],
        "escalated": [item["unit_id"] for item in actions if item["action"] == "escalate"],
    }
    return report


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_create(args: argparse.Namespace) -> int:
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    existing = set(project_units())
    created = 0
    skipped = 0
    for unit in spec["units"]:
        unit_id = unit["unit_id"]
        if unit_id in existing:
            # Re-running create against a spec that has grown must extend the
            # wave, not append a second CREATED row for units already in
            # flight.  CREATED is not repeatable on the append path.
            skipped += 1
            continue
        manifest = {
            "unit_id": unit_id,
            "commission_id": spec["commission_id"],
            "wave_id": spec["wave_id"],
            "cohort_id": unit["cohort_id"],
            "function_id": unit["function_id"],
            "hypothesis": unit["hypothesis"],
            "acceptance": unit["acceptance"],
            "owner": unit["owner"],
            "owned_paths": unit["owned_paths"],
            "model": unit["model"],
            "result_slot": unit["result_slot"],
            "source_hashes": spec["source_hashes"],
        }
        manifest_text = canonical(manifest)
        manifest_sha = sha256_text(manifest_text)
        acceptance_sha = sha256_text(canonical(unit["acceptance"]))
        dispatch_path = DISPATCH_DIR / f"{unit_id}.json"
        record = dict(manifest)
        record["immutable_input_manifest_sha256"] = manifest_sha
        record["acceptance_contract_sha256"] = acceptance_sha
        record["idempotency_key"] = f"{unit_id}:{manifest_sha[:16]}"
        write_json(dispatch_path, record)
        append_event(
            unit_id,
            "CREATED",
            actor="coordinator",
            provider_state="QUEUED",
            payload={
                "immutable_input_manifest_sha256": manifest_sha,
                "acceptance_contract_sha256": acceptance_sha,
                "idempotency_key": record["idempotency_key"],
                "cohort_id": unit["cohort_id"],
                "function_id": unit["function_id"],
                "owner": unit["owner"],
                "model": unit["model"],
            },
        )
        created += 1
    materialize()
    print(f"CREATED {created} units" + (f" (skipped {skipped} already registered)" if skipped else ""))
    return 0


def cmd_lease(args: argparse.Namespace) -> int:
    units = project_units()
    unit = units.get(args.unit_id)
    if unit is None:
        raise ControlPlaneError(f"unknown unit: {args.unit_id}")
    fence = unit["fence_token"] + 1
    expires = datetime.fromtimestamp(time.time() + args.ttl, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    row = append_event(
        args.unit_id,
        "LEASED",
        actor="coordinator",
        provider_state="RUNNING",
        fence_token=fence,
        payload={
            "lease_id": f"lease-{args.unit_id}-{fence}",
            "worker_id": args.worker,
            "expires_at": expires,
            "ttl_seconds": args.ttl,
        },
    )
    materialize()
    print(canonical({"fence_token": fence, "lease_id": row["payload"]["lease_id"], "expires_at": expires}))
    return 0


def cmd_event(args: argparse.Namespace) -> int:
    payload = json.loads(args.payload) if args.payload else {}
    append_event(
        args.unit_id,
        args.event,
        actor=args.actor,
        provider_state=args.provider_state,
        fence_token=args.fence_token,
        payload=payload,
    )
    materialize()
    print(f"{args.event} {args.unit_id}")
    return 0


def _load_validator():
    import importlib.util

    module_path = CONTROL_ROOT / "tools" / "validate_contracts.py"
    spec = importlib.util.spec_from_file_location("validate_contracts", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def record_rejection(
    unit_id: str,
    detail: str,
    *,
    fence_token: int | None = None,
    extra: dict[str, Any] | None = None,
    rejection_event: str | None = None,
    rejected_by: str = "ingest_result",
) -> dict[str, Any]:
    """Write the durable trace of a refusal without raising.

    Separated from ``_reject`` because the re-hash sweep records the same kind
    of finding but is a scanner: it reports every corrupt unit it finds rather
    than aborting on the first one.
    """
    payload = dict(extra or {})
    payload.setdefault("reason", detail)
    payload["detail"] = detail
    if rejection_event:
        append_event(
            unit_id,
            rejection_event,
            actor=COORDINATOR,
            fence_token=fence_token,
            payload=payload,
        )
    row = append_event(
        unit_id,
        "RECOVERY_REQUIRED",
        actor=COORDINATOR,
        fence_token=fence_token,
        payload={
            **{k: v for k, v in payload.items() if k not in {"reason", "detail"}},
            "reason": payload.get("reason"),
            "detail": detail,
            "rejected_by": rejected_by,
            "rejection_event": rejection_event,
        },
    )
    # The registry is the projection an operator reads.  A refusal that is in
    # the ledger but not in the projection is only half durable.
    materialize()
    return row


def _reject(
    unit_id: str,
    detail: str,
    *,
    fence_token: int | None = None,
    extra: dict[str, Any] | None = None,
    rejection_event: str | None = None,
) -> None:
    """Record a rejection durably, then refuse the result.

    Raising without recording was the defect: the unit stayed in whatever state
    it was already in and the rejection was invisible to recovery, so an
    operator reading the ledger could not tell that a result had been refused.
    Cohort a2 measured twenty rejection classes and all twenty left no recovery
    state.  Every rejection now leaves a RECOVERY_REQUIRED row carrying its
    reason before the exception propagates, so the refusal outlives the process
    that made it.
    """
    try:
        record_rejection(
            unit_id,
            detail,
            fence_token=fence_token,
            extra=extra,
            rejection_event=rejection_event,
        )
    except ControlPlaneError as exc:
        # The rejection itself must never be swallowed by a bookkeeping failure.
        raise ControlPlaneError(f"{detail} (and the rejection could not be recorded: {exc})") from exc
    raise ControlPlaneError(detail)


def ingest_result(
    result_doc: dict[str, Any],
    *,
    artifact_root: Path,
    reviewer_required: bool = True,
    repo: Path | None = None,
) -> dict[str, Any]:
    """Verify a subordinate result and admit it into shared custody.

    Every rejection reason here corresponds to a way the PO-02 Code-2 return was
    lost or could have been silently faked.
    """
    # The projection is consulted before the contract check so that a document
    # which fails validation can still be refused *against its unit*.  A
    # contract violation that raises without recording is exactly as invisible
    # to recovery as a corrupt artifact that does.
    unit_id = result_doc.get("task_id") if isinstance(result_doc, dict) else None
    units = project_units()
    unit = units.get(unit_id) if isinstance(unit_id, str) else None

    validator = _load_validator()
    errors = validator.validate_result(result_doc)
    if errors:
        detail = "result contract invalid: " + "; ".join(errors)
        if unit is None:
            # No unit means there is nothing to attach a trace to.  Reported as
            # a boundary rather than silently dropped.
            raise ControlPlaneError(detail)
        _reject(unit_id, detail, extra={"contract_errors": errors})

    if unit is None:
        raise ControlPlaneError(f"unknown unit: {unit_id}")

    # A fence token is a capability the coordinator issued, not an integer the
    # worker chose.  Comparing only ``incoming < current`` made a larger number
    # strictly safer than the truth, so a worker could escalate its own
    # ownership by naming any higher value.
    incoming_fence = int(result_doc["attempt"]["fence_token"])
    issued = list(unit.get("issued_fence_tokens") or [])
    current = max(issued) if issued else None
    if incoming_fence != current:
        if current is None:
            reason = "no lease was ever issued for this unit, so no fence token was ever issued"
            detail = f"fence token {incoming_fence} was never issued: {reason}"
        elif incoming_fence not in issued:
            reason = "fence token was never issued in a coordinator LEASED event for this unit"
            detail = (
                f"fence token {incoming_fence} was never issued; "
                f"the coordinator issued {issued} and the current lease is {current}"
            )
        else:
            reason = "stale worker after ownership transfer"
            detail = (
                f"stale fence token {incoming_fence} < {current}; refusing commit from evicted worker"
            )
        _reject(
            unit_id,
            detail,
            fence_token=current,
            extra={
                "rejected_fence_token": incoming_fence,
                "reason": reason,
                "issued_fence_tokens": issued,
                "current_fence_token": current,
            },
            rejection_event="FENCE_REJECTED",
        )

    dispatch_path = DISPATCH_DIR / f"{unit_id}.json"
    if not dispatch_path.exists():
        _reject(unit_id, f"no immutable dispatch record for {unit_id} at {dispatch_path}")
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    if result_doc["immutable_input_manifest_sha256"] != dispatch["immutable_input_manifest_sha256"]:
        _reject(
            unit_id,
            "result does not reference the dispatched immutable input manifest: "
            f"declared {result_doc['immutable_input_manifest_sha256']}, "
            f"dispatched {dispatch['immutable_input_manifest_sha256']}",
        )
    if result_doc["acceptance_contract_sha256"] != dispatch["acceptance_contract_sha256"]:
        _reject(
            unit_id,
            "result does not reference the frozen acceptance contract: "
            f"declared {result_doc['acceptance_contract_sha256']}, "
            f"dispatched {dispatch['acceptance_contract_sha256']}",
        )

    parsed = [parse_content_uri(artifact["content_uri"]) for artifact in result_doc["artifacts"]]
    relative_paths = [item[2] for item in parsed]
    outside = check_allowlist(relative_paths)
    if outside:
        _reject(unit_id, "artifacts outside the commission allowlist: " + ", ".join(outside))
    not_owned = check_ownership(dispatch["owner"], relative_paths)
    if not_owned:
        _reject(
            unit_id,
            f"owner {dispatch['owner']} attempted to write paths it does not own: " + ", ".join(not_owned),
        )

    # Ingestion records what the subordinate actually achieved.  A subordinate
    # that honestly reports failure, or work that was never durably committed,
    # must not be promoted into a committed state just because the parent read
    # its result document successfully.
    incoming_state = result_doc["obzio_state"]
    txn = result_doc["result_transaction"]
    commit_id = txn["result_commit_id"]
    has_commit = isinstance(commit_id, str) and bool(commit_id.strip())
    claims_durability = incoming_state == "RESULT_COMMITTED"

    if claims_durability:
        # A non-empty string was the entire durability test, so an invented
        # locator passed.  Resolve it, or the claim is not admitted.
        if not has_commit:
            _reject(unit_id, "RESULT_COMMITTED without a result_commit_id")
        if not commit_resolves(commit_id, repo):
            _reject(
                unit_id,
                f"declared result_commit_id {commit_id!r} does not resolve to a commit "
                "object; the result is not durable",
                extra={"unresolvable_result_commit_id": commit_id},
            )

    verified: list[dict[str, Any]] = []
    for artifact, (_branch, artifact_commit, relative) in zip(result_doc["artifacts"], parsed):
        if claims_durability:
            # Read back from the exact commit the artifact names, never from a
            # branch tip.  Reading from a moving tip is what made an honest
            # earlier result fail once a later commit touched the same file.
            if artifact_commit is None:
                _reject(
                    unit_id,
                    f"artifact {relative} declares {artifact['content_uri']!r}, which names no "
                    "commit; a durable artifact must carry an immutable locator",
                )
            if not commit_resolves(artifact_commit, repo):
                _reject(
                    unit_id,
                    f"artifact {relative} names commit {artifact_commit!r}, which does not "
                    "resolve to a commit object",
                )
            raw = read_blob(artifact_commit, relative, repo)
            if raw is None:
                _reject(unit_id, f"artifact missing on read-back at {artifact_commit}:{relative}")
            actual_sha = sha256_bytes(raw)
            actual_bytes = len(raw)
            read_from = f"git:{artifact_commit}:{relative}"
        else:
            # An uncommitted result has nothing in the object database yet, so
            # its artifacts are verified where they actually are.
            target = artifact_root / relative
            if not target.exists():
                _reject(unit_id, f"artifact missing on read-back: {relative}")
            actual_sha = sha256_file(target)
            actual_bytes = target.stat().st_size
            read_from = f"file:{relative}"
        if actual_sha != artifact["sha256"]:
            _reject(
                unit_id,
                f"artifact hash mismatch on read-back: {relative} "
                f"(declared {artifact['sha256']}, read {actual_sha} from {read_from})",
            )
        if actual_bytes != artifact["bytes"]:
            _reject(
                unit_id,
                f"artifact byte count mismatch on read-back: {relative} "
                f"(declared {artifact['bytes']}, read {actual_bytes} from {read_from})",
            )
        verified.append(
            {
                "logical_name": artifact["logical_name"],
                "sha256": actual_sha,
                "bytes": actual_bytes,
                "read_from": read_from,
            }
        )

    # ``manifest_uri`` used to name a git path that never existed, so it could
    # not be checked at all.  The derivable scheme is verified; the legacy
    # scheme is tolerated and flagged, because eight cohorts have already
    # emitted results with it and their artifact bytes are still sound.
    manifest_uri = str(txn.get("manifest_uri") or "")
    if manifest_uri.startswith(MANIFEST_SCHEME + ":"):
        manifest_scheme = MANIFEST_SCHEME
        expected = canonical(
            {
                "unit_id": unit_id,
                "commit": commit_id,
                "artifacts": [
                    {"logical_name": item["logical_name"], "sha256": item["sha256"], "bytes": item["bytes"]}
                    for item in sorted(result_doc["artifacts"], key=lambda item: item["artifact_id"])
                ],
            }
        )
        derived = sha256_text(expected)
        if derived != txn.get("manifest_sha256") or manifest_uri != f"{MANIFEST_SCHEME}:{derived}":
            _reject(
                unit_id,
                f"declared manifest does not derive from the declared artifacts: "
                f"manifest_uri {manifest_uri!r}, manifest_sha256 {txn.get('manifest_sha256')!r}, "
                f"derived {derived}",
            )
    elif manifest_uri:
        manifest_scheme = "legacy-unresolvable-manifest-uri"
    else:
        manifest_scheme = "absent"

    if claims_durability:
        ingest_event = "PARENT_INGESTED"
    elif incoming_state in {"PROVIDER_COMPLETED_UNCOMMITTED", "FAILED_TERMINAL", "CANCELLED"}:
        ingest_event = incoming_state
    else:
        ingest_event = "RECOVERY_REQUIRED"

    result_sha = sha256_text(canonical(result_doc))
    # The idempotency check must happen inside the same critical section as the
    # append.  Checking first and appending afterwards is a race: two concurrent
    # callbacks can both observe "not yet ingested" and both append.
    row = append_event(
        unit_id,
        ingest_event,
        actor="coordinator",
        provider_state=result_doc["provider_state"],
        fence_token=incoming_fence,
        payload={
            "result_sha256": result_sha,
            "reported_obzio_state": incoming_state,
            "result_commit_id": txn["result_commit_id"],
            "result_locator": txn["manifest_uri"],
            "manifest_uri_scheme": manifest_scheme,
            "artifact_count": len(verified),
            "total_bytes": sum(item["bytes"] for item in verified),
            "verified_artifacts": verified,
        },
        dedupe_key=result_sha,
        dedupe_events=INGESTION_EVENTS,
    )
    materialize()
    if row["event"] == "DUPLICATE_IGNORED":
        return {"unit_id": unit_id, "duplicate": True, "verified_artifacts": len(verified)}
    return {
        "unit_id": unit_id,
        "duplicate": False,
        "verified_artifacts": len(verified),
        "ingest_event": ingest_event,
    }


def cmd_ingest(args: argparse.Namespace) -> int:
    doc = json.loads(Path(args.result).read_text(encoding="utf-8"))
    outcome = ingest_result(doc, artifact_root=Path(args.artifact_root).resolve())
    print(canonical(outcome))
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    """Only the coordinator may declare Obzio completion, and only after ingestion."""
    units = project_units()
    unit = units.get(args.unit_id)
    if unit is None:
        raise ControlPlaneError(f"unknown unit: {args.unit_id}")
    if unit["obzio_state"] != "PARENT_INGESTED":
        raise ControlPlaneError(
            f"{args.unit_id} is {unit['obzio_state']}; completion requires PARENT_INGESTED"
        )
    if not unit["result_commit_id"]:
        raise ControlPlaneError(f"{args.unit_id} has no durable result commit; cannot complete")
    append_event(
        args.unit_id,
        "COMPLETED",
        actor="coordinator",
        provider_state="COMPLETED",
        fence_token=unit["fence_token"],
        payload={"result_commit_id": unit["result_commit_id"], "result_locator": unit["result_locator"]},
    )
    materialize()
    print(f"COMPLETED {args.unit_id}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    units = project_units()
    unit = units.get(args.unit_id)
    if unit is None:
        raise ControlPlaneError(f"unknown unit: {args.unit_id}")
    if unit["obzio_state"] != "COMPLETED":
        raise ControlPlaneError("independent disposition requires a COMPLETED unit")
    dispatch = json.loads((DISPATCH_DIR / f"{args.unit_id}.json").read_text(encoding="utf-8"))
    if args.reviewer == dispatch["owner"]:
        raise ControlPlaneError("producer cannot accept or reject its own work")
    append_event(
        args.unit_id,
        args.decision,
        actor=args.reviewer,
        fence_token=unit["fence_token"],
        payload={"reviewer_id": args.reviewer, "receipt_uri": args.receipt, "rationale": args.rationale},
    )
    materialize()
    print(f"{args.decision} {args.unit_id} by {args.reviewer}")
    return 0


def cmd_canary(args: argparse.Namespace) -> int:
    """Prove the durable sink round-trips before material work is dispatched."""
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    nonce = hashlib.sha256(f"{args.worker}:{utc_now()}:{os.getpid()}".encode("utf-8")).hexdigest()
    payload = {"worker_id": args.worker, "nonce": nonce, "written_at": utc_now()}
    target = root / f"canary-{args.worker}.json"
    written_sha = write_json(target, payload)
    readback = json.loads(target.read_text(encoding="utf-8"))
    readback_sha = sha256_file(target)
    ok = readback == payload and readback_sha == written_sha
    print(canonical({"worker_id": args.worker, "canary_sha256": readback_sha, "roundtrip_ok": ok}))
    return 0 if ok else 1


def cmd_verify(args: argparse.Namespace) -> int:
    rows = ledger_rows()
    errors = verify_chain(rows)
    state = scan_recovery()
    materialize()
    for error in errors:
        print(f"INVALID: {error}")
    print(canonical({k: v for k, v in state.items() if k != "ledger_chain_errors"}))
    if errors or state["false_completions"]:
        return 1
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    state = scan_recovery()
    print(canonical(state))
    return 1 if state["recovery_required"] and args.strict else 0


def cmd_recover(args: argparse.Namespace) -> int:
    """Actuate recovery.  Exit 1 when a unit needs a human, not a retry."""
    report = recover_units(
        unit_ids=args.unit or None,
        ttl_seconds=args.ttl,
        max_attempts=args.max_attempts,
        apply=not args.dry_run,
    )
    print(canonical(report))
    return 1 if report["escalated"] else 0


def cmd_rehash(args: argparse.Namespace) -> int:
    """Re-prove that every ingested artifact is still readable at its commit.

    Exit 0 when every artifact re-hashed clean, 2 when a finding was recorded,
    and 1 when no object database was reachable, because "could not check" is a
    different answer from "checked and clean".
    """
    report = rehash_committed_artifacts(
        repo=Path(args.repo).resolve() if args.repo else None,
        unit_ids=args.unit or None,
    )
    print(canonical(report))
    if not report["commit_resolution_available"]:
        return 1
    return 2 if report["recovery_required"] else 0


def cmd_check_paths(args: argparse.Namespace) -> int:
    paths = [line.strip() for line in Path(args.paths).read_text(encoding="utf-8").splitlines() if line.strip()]
    outside = check_allowlist(paths)
    for path in outside:
        print(f"OUT_OF_ALLOWLIST: {path}")
    if outside:
        print(f"FAIL {len(outside)} path(s) outside the PO-03 wave-one allowlist")
        return 1
    print(f"PASS {len(paths)} path(s) inside the PO-03 wave-one allowlist")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PO-03 transactional control plane")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="register work units from a wave spec")
    create.add_argument("spec")
    create.set_defaults(func=cmd_create)

    lease = sub.add_parser("lease", help="grant a fenced lease to a worker")
    lease.add_argument("unit_id")
    lease.add_argument("--worker", required=True)
    lease.add_argument("--ttl", type=int, default=5400)
    lease.set_defaults(func=cmd_lease)

    event = sub.add_parser("event", help="append a custody event")
    event.add_argument("unit_id")
    event.add_argument("event", choices=sorted(EVENT_KINDS))
    event.add_argument("--actor", required=True)
    event.add_argument("--provider-state", dest="provider_state")
    event.add_argument("--fence-token", dest="fence_token", type=int)
    event.add_argument("--payload")
    event.set_defaults(func=cmd_event)

    ingest = sub.add_parser("ingest", help="verify and ingest a subordinate result")
    ingest.add_argument("result")
    ingest.add_argument("--artifact-root", default=str(REPO_ROOT))
    ingest.set_defaults(func=cmd_ingest)

    complete = sub.add_parser("complete", help="coordinator-only completion")
    complete.add_argument("unit_id")
    complete.set_defaults(func=cmd_complete)

    review = sub.add_parser("review", help="independent acceptance or rejection")
    review.add_argument("unit_id")
    review.add_argument("decision", choices=("ACCEPTED", "REJECTED"))
    review.add_argument("--reviewer", required=True)
    review.add_argument("--receipt", required=True)
    review.add_argument("--rationale", default="")
    review.set_defaults(func=cmd_review)

    canary = sub.add_parser("canary", help="prove durable sink round-trip")
    canary.add_argument("--worker", required=True)
    canary.add_argument("--root", required=True)
    canary.set_defaults(func=cmd_canary)

    verify = sub.add_parser("verify", help="verify ledger chain and custody invariants")
    verify.set_defaults(func=cmd_verify)

    scan = sub.add_parser("scan", help="run the recovery scanner")
    scan.add_argument("--strict", action="store_true")
    scan.set_defaults(func=cmd_scan)

    recover = sub.add_parser("recover", help="re-lease, rerun and resume stalled units")
    recover.add_argument("--unit", action="append", default=[])
    recover.add_argument("--ttl", type=int, default=DEFAULT_LEASE_TTL_SECONDS)
    recover.add_argument("--max-attempts", dest="max_attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    recover.add_argument("--dry-run", dest="dry_run", action="store_true")
    recover.set_defaults(func=cmd_recover)

    rehash = sub.add_parser("rehash", help="re-hash ingested artifacts at their commits")
    rehash.add_argument("--repo", default=None)
    rehash.add_argument("--unit", action="append", default=[])
    rehash.set_defaults(func=cmd_rehash)

    check = sub.add_parser("check-paths", help="enforce the wave-one path allowlist")
    check.add_argument("paths")
    check.set_defaults(func=cmd_check_paths)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ControlPlaneError as exc:
        print(f"CONTROL_PLANE_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
