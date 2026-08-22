"""Hash-chained append-only custody ledger with a sealed head anchor.

Why a chain is not enough on its own
------------------------------------
A hash chain detects any edit that leaves a *witness* later in the file: the
edited row's own digest stops matching its body, or the following row's
``prev_sha256`` stops matching.  It cannot, by construction, detect an edit
whose witness was removed or rewritten:

* dropping rows off the tail leaves a shorter but perfectly valid chain;
* rewriting a suffix and recomputing every digest in it leaves a valid chain;
* appending a well-formed row leaves a valid chain.

So the ledger keeps a *sealed head anchor* beside it.  The anchor is written
with a write-ahead intent (``pending_seq`` before the append, ``committed_seq``
after it) which is what lets verification tell a legitimate crash window apart
from a forged append:

============================  =========================================
observed relation             ruling
============================  =========================================
rows == committed_seq         normal; head digest must match the anchor
rows == committed_seq + 1     benign in-flight append, and only when the
  and pending_seq == rows     extra row is byte-for-byte the row the
  and tail == pending_head    writer announced before writing it
rows <  committed_seq         TRUNCATED
anything else                 FORGED_APPEND / ANCHOR_MISMATCH
============================  =========================================

The intent records ``pending_head``, the digest of the row about to be
appended, not merely its sequence number.  Without it the crash window would be
a hole an adversary could aim at: any well-formed row chaining to the current
head would pass as "the append that was in flight".

Stated limitation, not a claim
------------------------------
An adversary able to rewrite the ledger *and* the anchor together can produce a
consistent pair.  Closing that requires an anchor outside the writer's reach,
so ``verify`` accepts ``expected_head``: the coordinator pins the head digest
in an immutable git commit and passes it back.  ``NOT_SUPPORTED`` is the honest
answer for tamper detection against an attacker who controls both files and the
external anchor.

Row format is byte-compatible with ``tools/control_plane.py``: identical field
set, identical canonical encoding and identical digest rule, so either verifier
accepts either writer's ledger.  ``test_a1_ledger_chain.py`` asserts that
interoperability rather than assuming it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .canonical import (
    GENESIS_HASH,
    atomic_write_json,
    canonical,
    exclusive_lock,
    read_json,
    sha256_text,
    utc_now,
)

# The 21 event kinds the coordinator's control plane recognises.  Kept as a
# separate constant so a ledger written here stays ingestible there.
OBZIO_EVENT_KINDS = frozenset(
    {
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
)

# Additive engine observations.  They never advance Obzio custody state, so the
# coordinator's projection ignores them safely.
ENGINE_EVENT_KINDS = frozenset(
    {
        "HEARTBEAT",
        "STEP_COMMITTED",
        "OUTBOX_ENQUEUED",
        "OUTBOX_CLAIMED",
        "OUTBOX_APPLIED",
        "ARTIFACT_STORED",
        "ARTIFACT_CORRUPT",
        "RESULT_PUBLISHED",
    }
)

ALL_EVENT_KINDS = frozenset(OBZIO_EVENT_KINDS | ENGINE_EVENT_KINDS)

ROW_BODY_FIELDS = (
    "seq",
    "ts",
    "unit_id",
    "event",
    "obzio_state",
    "provider_state",
    "actor",
    "fence_token",
    "payload",
    "prev_sha256",
)

TAMPER = "TAMPER"
INFO = "INFO"


class LedgerError(RuntimeError):
    """Raised when an append would violate an append-only invariant."""


class LedgerTampered(LedgerError):
    """Raised by :meth:`HashChainedLedger.rows` when the chain does not verify."""


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    detail: str
    seq: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "detail": self.detail, "seq": self.seq}


@dataclass(frozen=True)
class Verification:
    ok: bool
    row_count: int
    head_sha256: str
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def tamper_codes(self) -> tuple[str, ...]:
        return tuple(f.code for f in self.findings if f.severity == TAMPER)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "row_count": self.row_count,
            "head_sha256": self.head_sha256,
            "findings": [f.as_dict() for f in self.findings],
        }


def row_digest(body: dict[str, Any]) -> str:
    """Digest of a row body, excluding the digest field itself."""
    return sha256_text(canonical({k: v for k, v in body.items() if k != "row_sha256"}))


class HashChainedLedger:
    """Append-only event log; the only source of truth for unit custody."""

    def __init__(
        self,
        path: Path | str,
        *,
        event_kinds: Iterable[str] = ALL_EVENT_KINDS,
        verify_on_append: bool = True,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.path = Path(path)
        self.anchor_path = self.path.with_suffix(self.path.suffix + ".anchor.json")
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.event_kinds = frozenset(event_kinds)
        self.verify_on_append = verify_on_append
        self._fault_hook = fault_hook

    # -- reading -----------------------------------------------------------

    def read_rows(self) -> tuple[list[dict[str, Any]], list[Finding]]:
        """Parse every row, reporting rather than raising on damaged bytes."""
        findings: list[Finding] = []
        if not self.path.exists():
            return [], findings
        raw = self.path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            findings.append(Finding("NOT_UTF8", TAMPER, f"ledger bytes are not valid UTF-8: {exc}"))
            return [], findings
        rows: list[dict[str, Any]] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                findings.append(Finding("UNPARSABLE_ROW", TAMPER, f"line {lineno}: {exc}", seq=lineno))
                continue
            if not isinstance(parsed, dict):
                findings.append(Finding("NON_OBJECT_ROW", TAMPER, f"line {lineno}: row is not an object", seq=lineno))
                continue
            rows.append(parsed)
        return rows, findings

    def rows(self) -> list[dict[str, Any]]:
        """Return verified rows, refusing to hand a caller tampered history."""
        verification = self.verify()
        if not verification.ok:
            raise LedgerTampered(
                f"{self.path}: refusing to read a tampered ledger: "
                + "; ".join(f"{f.code}:{f.detail}" for f in verification.findings if f.severity == TAMPER)
            )
        rows, _ = self.read_rows()
        return rows

    def head(self) -> str:
        rows, _ = self.read_rows()
        return rows[-1]["row_sha256"] if rows else GENESIS_HASH

    def read_anchor(self) -> dict[str, Any] | None:
        if not self.anchor_path.exists():
            return None
        try:
            anchor = read_json(self.anchor_path)
        except (json.JSONDecodeError, OSError):
            return {"__unreadable__": True}
        return anchor if isinstance(anchor, dict) else {"__unreadable__": True}

    # -- verification ------------------------------------------------------

    def verify(self, *, expected_head: str | None = None, require_anchor: bool = True) -> Verification:
        rows, findings = self.read_rows()
        findings = list(findings)
        findings.extend(self._verify_chain(rows))
        findings.extend(self._verify_anchor(rows, require_anchor=require_anchor))
        head = rows[-1].get("row_sha256", GENESIS_HASH) if rows else GENESIS_HASH
        if expected_head is not None and head != expected_head:
            findings.append(
                Finding(
                    "EXTERNAL_ANCHOR_MISMATCH",
                    TAMPER,
                    f"head {head} does not match the externally pinned head {expected_head}",
                )
            )
        ok = not any(f.severity == TAMPER for f in findings)
        return Verification(ok=ok, row_count=len(rows), head_sha256=head, findings=tuple(findings))

    def _verify_chain(self, rows: list[dict[str, Any]]) -> list[Finding]:
        findings: list[Finding] = []
        previous = GENESIS_HASH
        seen_seqs: set[int] = set()
        for index, row in enumerate(rows):
            expected_seq = index + 1
            actual_seq = row.get("seq")
            if actual_seq != expected_seq:
                findings.append(
                    Finding(
                        "SEQ_NOT_MONOTONIC",
                        TAMPER,
                        f"row at position {index} carries seq {actual_seq!r}, expected {expected_seq}",
                        seq=expected_seq,
                    )
                )
            if isinstance(actual_seq, int):
                if actual_seq in seen_seqs:
                    findings.append(
                        Finding("SEQ_DUPLICATED", TAMPER, f"seq {actual_seq} appears more than once", seq=actual_seq)
                    )
                seen_seqs.add(actual_seq)
            if row.get("prev_sha256") != previous:
                findings.append(
                    Finding(
                        "CHAIN_BREAK",
                        TAMPER,
                        f"row at position {index} has prev_sha256 {row.get('prev_sha256')!r}, "
                        f"which does not chain to {previous}",
                        seq=expected_seq,
                    )
                )
            computed = row_digest(row)
            if row.get("row_sha256") != computed:
                findings.append(
                    Finding(
                        "ROW_DIGEST_MISMATCH",
                        TAMPER,
                        f"row at position {index} has row_sha256 {row.get('row_sha256')!r} "
                        f"but its canonical body digests to {computed}",
                        seq=expected_seq,
                    )
                )
            missing = [name for name in ROW_BODY_FIELDS if name not in row]
            if missing:
                findings.append(
                    Finding(
                        "ROW_FIELDS_MISSING",
                        TAMPER,
                        f"row at position {index} is missing {', '.join(missing)}",
                        seq=expected_seq,
                    )
                )
            previous = row.get("row_sha256", GENESIS_HASH)
        return findings

    def _verify_anchor(self, rows: list[dict[str, Any]], *, require_anchor: bool) -> list[Finding]:
        anchor = self.read_anchor()
        if anchor is None:
            severity = TAMPER if require_anchor and rows else INFO
            return [
                Finding(
                    "ANCHOR_ABSENT",
                    severity,
                    "no sealed head anchor: tail truncation and suffix rewrite are undetectable",
                )
            ]
        if anchor.get("__unreadable__"):
            return [Finding("ANCHOR_UNREADABLE", TAMPER, f"{self.anchor_path} is not readable JSON")]

        committed_seq = anchor.get("committed_seq")
        committed_head = anchor.get("committed_head")
        pending_seq = anchor.get("pending_seq")
        pending_head = anchor.get("pending_head")
        if not isinstance(committed_seq, int) or not isinstance(committed_head, str):
            return [Finding("ANCHOR_MALFORMED", TAMPER, f"{self.anchor_path} lacks committed_seq/committed_head")]

        findings: list[Finding] = []
        row_count = len(rows)
        if row_count < committed_seq:
            findings.append(
                Finding(
                    "TRUNCATED",
                    TAMPER,
                    f"ledger holds {row_count} rows but the sealed anchor committed seq {committed_seq}",
                    seq=committed_seq,
                )
            )
            return findings
        if committed_seq >= 1:
            anchored_row = rows[committed_seq - 1]
            if anchored_row.get("row_sha256") != committed_head:
                findings.append(
                    Finding(
                        "ANCHOR_HEAD_MISMATCH",
                        TAMPER,
                        f"row {committed_seq} digests to {anchored_row.get('row_sha256')!r} but the sealed "
                        f"anchor pins {committed_head}",
                        seq=committed_seq,
                    )
                )
        elif committed_head != GENESIS_HASH:
            findings.append(
                Finding("ANCHOR_MALFORMED", TAMPER, "committed_seq 0 must pin the genesis digest")
            )

        extra = row_count - committed_seq
        if extra == 1 and pending_seq == row_count and rows[-1].get("row_sha256") == pending_head:
            findings.append(
                Finding(
                    "APPEND_IN_FLIGHT",
                    INFO,
                    f"row {row_count} matches the digest the writer announced before appending it, so this "
                    "is the append/seal crash window rather than a forged append",
                    seq=row_count,
                )
            )
        elif extra > 0:
            findings.append(
                Finding(
                    "FORGED_APPEND",
                    TAMPER,
                    f"ledger holds {row_count} rows but the sealed anchor committed seq {committed_seq} "
                    f"with pending_seq {pending_seq!r} and pending_head {pending_head!r}; the tail row "
                    f"digests to {rows[-1].get('row_sha256')!r}",
                    seq=committed_seq + 1,
                )
            )
        return findings

    # -- appending ---------------------------------------------------------

    def append(
        self,
        unit_id: str,
        event: str,
        *,
        actor: str,
        obzio_state: str | None = None,
        provider_state: str | None = None,
        fence_token: int | None = None,
        payload: dict[str, Any] | None = None,
        ts: str | None = None,
    ) -> dict[str, Any]:
        """Append one row, sealing the head anchor around the write.

        The write-ahead ``pending_seq`` is what distinguishes a crash between
        append and seal from a forged append, so it is written *before* the row
        even though that costs an extra fsync.
        """
        if event not in self.event_kinds:
            raise LedgerError(f"unknown event kind: {event}")
        with exclusive_lock(self.lock_path):
            rows, parse_findings = self.read_rows()
            if self.verify_on_append:
                verification = self.verify()
                if not verification.ok:
                    raise LedgerTampered(
                        f"{self.path}: refusing to extend a tampered ledger: "
                        + "; ".join(f.code for f in verification.findings if f.severity == TAMPER)
                    )
            elif parse_findings:
                raise LedgerTampered(f"{self.path}: unparsable rows present; refusing to append")

            seq = len(rows) + 1
            body: dict[str, Any] = {
                "seq": seq,
                "ts": ts or utc_now(),
                "unit_id": unit_id,
                "event": event,
                "obzio_state": obzio_state or event,
                "provider_state": provider_state,
                "actor": actor,
                "fence_token": fence_token,
                "payload": payload or {},
                "prev_sha256": rows[-1]["row_sha256"] if rows else GENESIS_HASH,
            }
            body["row_sha256"] = row_digest(body)

            self._fire("before_anchor_intent")
            self._write_anchor(
                committed_seq=seq - 1,
                committed_head=body["prev_sha256"],
                pending_seq=seq,
                pending_head=body["row_sha256"],
            )
            self._fire("after_anchor_intent")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(canonical(body) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._fire("after_append_before_seal")
            self._write_anchor(
                committed_seq=seq,
                committed_head=body["row_sha256"],
                pending_seq=None,
                pending_head=None,
            )
            self._fire("after_seal")
            return body

    def _write_anchor(
        self,
        *,
        committed_seq: int,
        committed_head: str,
        pending_seq: int | None,
        pending_head: str | None,
    ) -> None:
        atomic_write_json(
            self.anchor_path,
            {
                "ledger": self.path.name,
                "committed_seq": committed_seq,
                "committed_head": committed_head,
                "pending_seq": pending_seq,
                "pending_head": pending_head,
                "sealed_at": utc_now(),
            },
        )

    def _fire(self, point: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(point)

    def set_fault_hook(self, hook: Callable[[str], None] | None) -> None:
        """Install a fault-injection hook for the named append checkpoints.

        Exposed rather than private because injecting a fault *inside* the
        append is the only way to exercise the append/seal crash window from a
        real process, and a recovery claim that is only tested at clean
        boundaries is not a recovery claim.
        """
        self._fault_hook = hook

    # -- convenience -------------------------------------------------------

    def events_for(self, unit_id: str) -> list[dict[str, Any]]:
        return [row for row in self.rows() if row["unit_id"] == unit_id]

    def count_events(self, unit_id: str, event: str) -> int:
        return sum(1 for row in self.events_for(unit_id) if row["event"] == event)

    def reseal(self) -> Verification:
        """Re-seal the anchor to the current head after a legitimate crash window.

        Only usable while the sole outstanding finding is ``APPEND_IN_FLIGHT``;
        it must never be a way to launder a tampered ledger into a valid one.
        """
        verification = self.verify()
        codes = {f.code for f in verification.findings}
        if verification.tamper_codes or "APPEND_IN_FLIGHT" not in codes:
            raise LedgerError(
                "reseal only closes the append-in-flight crash window; "
                f"observed findings {sorted(codes)}"
            )
        rows, _ = self.read_rows()
        self._write_anchor(
            committed_seq=len(rows),
            committed_head=rows[-1]["row_sha256"],
            pending_seq=None,
            pending_head=None,
        )
        return self.verify()
