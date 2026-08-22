#!/usr/bin/env python3
"""The generation-neutral controller contract every scored generation implements.

The successor-generation test compares three controllers (G0, G1, G2) that were
built at different times against one another.  A fair comparison needs a single
interface that none of them was designed around, so this module defines the
operation vocabulary and the reason-code vocabulary once and every generation
adapts to it.

Two properties make the comparison honest:

* A generation that never had a capability answers ``NOT_SUPPORTED`` rather than
  crashing or silently succeeding.  A case that requires the missing capability
  therefore fails, which is the measurement, not a harness defect.
* Reason codes are drawn from a closed vocabulary, so "G1 rejected this" and
  "G2 rejected this" are comparable claims about *why* rather than string
  matching against three different implementations' private wording.

Dependency-free standard library only: the suite has to run in a clean clone and
a clean GitHub Actions runner with no third-party packages.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Operation vocabulary
# ---------------------------------------------------------------------------

OPERATIONS = (
    # Custody lifecycle.
    "create",       # durably record immutable task input before dispatch
    "lease",        # grant a fenced, expiring lease to a named worker
    "submit",       # a worker offers a result for admission into custody
    "ingest",       # the parent admits a submitted result after verification
    "complete",     # declare Obzio completion
    "review",       # independent acceptance or rejection
    "state",        # observe the current custody state of one unit
    # Durability and recovery.
    "restart",      # discard process memory and rebuild from durable state
    "recover",      # run the recovery scanner
    "verify",       # re-verify durable state and artifact bytes
    # Fault injection.
    "tamper",       # mutate durable state to model a real failure mode
    "advance_clock",  # move the injectable clock to reach lease expiry
    "write_artifact",  # place artifact bytes in the durable artifact store
)

# ---------------------------------------------------------------------------
# Reason-code vocabulary
# ---------------------------------------------------------------------------

OK = "OK"
NOT_SUPPORTED = "NOT_SUPPORTED"

REASON_CODES = (
    OK,
    NOT_SUPPORTED,
    # Ownership and authority.
    "NOT_COORDINATOR",        # a non-coordinator principal tried to complete
    "SELF_ACCEPTANCE",        # the producer tried to accept its own work
    "NOT_OWNED",              # a write outside the principal's owned subtree
    "OUT_OF_ALLOWLIST",       # a write outside the commission allowlist
    # Leases and fencing.
    "STALE_FENCE",            # fence lower than the current grant
    "FORGED_FENCE",           # fence never granted to this worker
    "EXPIRED_LEASE",          # the lease deadline had already passed
    # Artifact and accounting integrity.
    "ARTIFACT_MISSING",       # recorded artifact absent on read-back
    "ARTIFACT_HASH_MISMATCH",  # bytes differ from the recorded digest
    "ARTIFACT_DRIFT",         # bytes changed after admission into custody
    "ACCOUNTING_MISMATCH",    # count or byte totals disagree with artifacts
    "DUPLICATE_ARTIFACT_ID",  # two artifacts claim one identity
    "READBACK_MISSING",       # terminal state without read-back evidence
    "LOCATOR_UNRESOLVED",     # the declared immutable locator holds nothing
    # Input and log integrity.
    "INPUT_TAMPERED",         # dispatched immutable input was edited
    "LEDGER_TRUNCATED",       # append-only log lost committed rows
    "LEDGER_CORRUPT",         # log rows reordered or edited in place
    # Completion truthfulness.
    "NO_RESULT_COMMIT",       # completion claimed without a durable commit
    "NOT_INGESTED",           # completion claimed before parent ingestion
    "TERMINAL_STATE",         # a unit already in a terminal state was re-entered
    # Replay semantics.
    "DUPLICATE_IGNORED",      # byte-identical replay, harmlessly discarded
    "CONFLICTING_REPLAY",     # same idempotency key, different content
    # Structural.
    "UNKNOWN_UNIT",
    "INVALID_REQUEST",
)

_REASON_SET = frozenset(REASON_CODES)


@dataclass
class Outcome:
    """The result of one controller operation.

    ``admitted`` answers "did the controller allow this?".  ``reason_code``
    answers "on what named ground?".  ``detail`` carries observable state the
    suite can assert against without knowing which generation produced it.
    """

    admitted: bool
    reason_code: str = OK
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.reason_code not in _REASON_SET:
            raise ValueError(f"reason code outside the closed vocabulary: {self.reason_code}")

    def as_json(self) -> dict[str, Any]:
        return {"admitted": self.admitted, "reason_code": self.reason_code, "detail": self.detail}


def ok(**detail: Any) -> Outcome:
    return Outcome(True, OK, dict(detail))


def refuse(reason_code: str, **detail: Any) -> Outcome:
    return Outcome(False, reason_code, dict(detail))


def unsupported(capability: str) -> Outcome:
    """A capability this generation genuinely never had.

    Returning this rather than raising is deliberate: the absence of durable
    result custody in an early generation is a finding to be measured, and it
    can only be measured if the generation stays runnable while lacking it.
    """
    return Outcome(False, NOT_SUPPORTED, {"missing_capability": capability})


class Controller:
    """Base class for a scored generation.

    A subclass implements ``op_<name>`` for each capability it actually has.
    Anything it does not implement is reported as ``NOT_SUPPORTED``, so the
    scored gap belongs to the generation rather than to the harness.
    """

    generation_id = "abstract"
    generation_label = "abstract controller"
    provenance = "abstract"

    def __init__(self, root, clock) -> None:
        self.root = root
        self.clock = clock

    def apply(self, operation: str, args: dict[str, Any]) -> Outcome:
        if operation not in OPERATIONS:
            return refuse("INVALID_REQUEST", operation=operation)
        handler = getattr(self, f"op_{operation}", None)
        if handler is None:
            return unsupported(operation)
        return handler(**args)

    @classmethod
    def capabilities(cls) -> list[str]:
        """The operations this generation implements, without constructing one."""
        return [name for name in OPERATIONS if getattr(cls, f"op_{name}", None) is not None]


class Clock:
    """Injectable monotonic clock.

    Lease expiry is a custody property that has to be testable without sleeping,
    and a wall-clock dependency would make scores irreproducible.
    """

    def __init__(self, start: float = 1_787_000_000.0) -> None:
        self._now = float(start)

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> float:
        self._now += float(seconds)
        return self._now

    def iso(self, offset: float = 0.0) -> str:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(self._now + offset, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
