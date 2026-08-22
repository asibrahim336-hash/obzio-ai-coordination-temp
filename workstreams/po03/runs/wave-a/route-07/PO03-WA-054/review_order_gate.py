"""PO03-WA-054 — blind review ordering is enforced, not merely asserted.

Frozen hypothesis: blind review ordering prevents producer conclusions from
changing criteria.

The commission requires reviewers to freeze criteria before receiving producer
conclusions. A prose declaration that this happened is unfalsifiable. This
component makes the ordering a checked property of an append-only access ledger:
the reviewer registers every source it opens, the class of that source is
resolved from a declared classification policy, and the gate refuses the run if a
producer conclusion was opened before the freeze, or if the rubric digest moved
after one was opened.

The gate is deliberately hostile to its own operator: it cannot be satisfied by
re-ordering the narrative afterwards, because the ledger is append-only and every
entry carries a monotonic sequence number.

Standard library only.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum


class SourceClass(str, Enum):
    CRITERIA = "CRITERIA"          # frozen criteria, contracts, schemas, task inputs
    TARGET_ARTIFACT = "TARGET_ARTIFACT"  # immutable code, tests, manifests
    PRODUCER_CONCLUSION = "PRODUCER_CONCLUSION"  # findings, dispositions, receipts


class Phase(str, Enum):
    CRITERIA_INTAKE = "CRITERIA_INTAKE"
    RUBRIC_FROZEN = "RUBRIC_FROZEN"
    OUTCOMES_FROZEN = "OUTCOMES_FROZEN"


class ReviewOrderViolation(RuntimeError):
    """Raised when the blind-review ordering is broken."""


class LedgerTampering(RuntimeError):
    """Raised when an append-only ledger entry is mutated or reordered."""


DEFAULT_POLICY = (
    ("**/evidence/criteria-freeze.json", SourceClass.CRITERIA),
    ("**/evidence/source-lock.json", SourceClass.CRITERIA),
    ("**/contracts/*.schema.json", SourceClass.CRITERIA),
    ("**/control/tasks/*/input.json", SourceClass.CRITERIA),
    ("**/control/tasks/*/acceptance.json", SourceClass.CRITERIA),
    ("**/control/completions/*.json", SourceClass.CRITERIA),
    ("**/metrics/metric-definitions.json", SourceClass.CRITERIA),
    ("**/FINDING.md", SourceClass.PRODUCER_CONCLUSION),
    ("**/README.md", SourceClass.PRODUCER_CONCLUSION),
    ("**/observed-*.txt", SourceClass.PRODUCER_CONCLUSION),
    ("**/observed-*.json", SourceClass.PRODUCER_CONCLUSION),
    ("**/run-log.txt", SourceClass.PRODUCER_CONCLUSION),
    ("**/result.json", SourceClass.PRODUCER_CONCLUSION),
    ("**/control/results/*.json", SourceClass.PRODUCER_CONCLUSION),
    ("**/*-ingestion.json", SourceClass.PRODUCER_CONCLUSION),
    ("**/*.py", SourceClass.TARGET_ARTIFACT),
    ("**/manifest.json", SourceClass.TARGET_ARTIFACT),
    ("**/*manifest*.json", SourceClass.TARGET_ARTIFACT),
)


def classify_source(path: str, policy=DEFAULT_POLICY) -> SourceClass:
    for pattern, klass in policy:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch("/" + path.lstrip("/"), pattern):
            return klass
    return SourceClass.TARGET_ARTIFACT


@dataclass(frozen=True)
class LedgerEntry:
    seq: int
    event: str
    path: str
    source_class: str
    phase: str
    digest: str = ""

    def fingerprint(self, previous: str) -> str:
        payload = json.dumps(
            {
                "seq": self.seq,
                "event": self.event,
                "path": self.path,
                "source_class": self.source_class,
                "phase": self.phase,
                "digest": self.digest,
                "previous": previous,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class ReviewOrderGate:
    policy: tuple = DEFAULT_POLICY
    entries: list = field(default_factory=list)
    chain: list = field(default_factory=lambda: ["genesis"])
    phase: Phase = Phase.CRITERIA_INTAKE
    rubric_digest: str = ""
    violations: list = field(default_factory=list)

    # -- append-only ledger -------------------------------------------------
    def _append(self, event: str, path: str, source_class: str, digest: str = "") -> LedgerEntry:
        entry = LedgerEntry(len(self.entries), event, path, source_class, self.phase.value, digest)
        self.entries.append(entry)
        self.chain.append(entry.fingerprint(self.chain[-1]))
        return entry

    def verify_chain(self) -> bool:
        previous = "genesis"
        if self.chain[0] != "genesis":
            raise LedgerTampering("ledger genesis was replaced")
        if len(self.chain) != len(self.entries) + 1:
            raise LedgerTampering(
                f"chain holds {len(self.chain) - 1} fingerprints for {len(self.entries)} entries; "
                "entries were truncated or inserted"
            )
        for index, entry in enumerate(self.entries):
            if entry.seq != index:
                raise LedgerTampering(f"entry {index} carries sequence {entry.seq}")
            expected = entry.fingerprint(previous)
            if self.chain[index + 1] != expected:
                raise LedgerTampering(f"entry {index} does not match its recorded fingerprint")
            previous = expected
        return True

    # -- review protocol ----------------------------------------------------
    def open_source(self, path: str) -> SourceClass:
        klass = classify_source(path, self.policy)
        if klass is SourceClass.PRODUCER_CONCLUSION and self.phase is Phase.CRITERIA_INTAKE:
            self.violations.append(
                f"producer conclusion {path!r} opened before the rubric was frozen"
            )
            self._append("OPEN_DENIED", path, klass.value)
            raise ReviewOrderViolation(self.violations[-1])
        if klass is SourceClass.TARGET_ARTIFACT and self.phase is Phase.CRITERIA_INTAKE:
            self.violations.append(
                f"target artifact {path!r} opened before the rubric was frozen"
            )
            self._append("OPEN_DENIED", path, klass.value)
            raise ReviewOrderViolation(self.violations[-1])
        self._append("OPEN", path, klass.value)
        return klass

    def freeze_rubric(self, digest: str) -> LedgerEntry:
        if self.phase is not Phase.CRITERIA_INTAKE:
            self.violations.append("rubric freeze attempted more than once")
            raise ReviewOrderViolation(self.violations[-1])
        if not digest:
            raise ValueError("rubric digest must be non-empty")
        self.rubric_digest = digest
        entry = self._append("RUBRIC_FREEZE", "<rubric>", SourceClass.CRITERIA.value, digest)
        self.phase = Phase.RUBRIC_FROZEN
        return entry

    def amend_rubric(self, digest: str, justification: str) -> LedgerEntry:
        """A post-freeze rubric change is permitted only before any producer read."""
        if self.phase is Phase.CRITERIA_INTAKE:
            raise ReviewOrderViolation("cannot amend a rubric that was never frozen")
        if self.producer_conclusions_opened():
            self.violations.append(
                "rubric amended after a producer conclusion was opened; criteria are contaminated"
            )
            raise ReviewOrderViolation(self.violations[-1])
        if not justification.strip():
            raise ValueError("an amendment requires a justification")
        self.rubric_digest = digest
        return self._append("RUBRIC_AMEND", justification, SourceClass.CRITERIA.value, digest)

    def freeze_outcomes(self, digest: str) -> LedgerEntry:
        if self.phase is not Phase.RUBRIC_FROZEN:
            raise ReviewOrderViolation(f"cannot freeze outcomes from phase {self.phase.value}")
        entry = self._append("OUTCOMES_FREEZE", "<outcomes>", SourceClass.CRITERIA.value, digest)
        self.phase = Phase.OUTCOMES_FROZEN
        return entry

    def producer_conclusions_opened(self) -> list:
        return [
            e for e in self.entries
            if e.event == "OPEN" and e.source_class == SourceClass.PRODUCER_CONCLUSION.value
        ]

    def audit(self) -> dict:
        self.verify_chain()
        freeze_seq = next(
            (e.seq for e in self.entries if e.event == "RUBRIC_FREEZE"), None
        )
        outcomes_seq = next(
            (e.seq for e in self.entries if e.event == "OUTCOMES_FREEZE"), None
        )
        early_producer = [
            e.path
            for e in self.entries
            if e.source_class == SourceClass.PRODUCER_CONCLUSION.value
            and (freeze_seq is None or e.seq < freeze_seq)
            and e.event == "OPEN"
        ]
        amended_after_producer = [
            e.seq
            for e in self.entries
            if e.event == "RUBRIC_AMEND"
            and any(
                p.seq < e.seq for p in self.producer_conclusions_opened()
            )
        ]
        blind = (
            freeze_seq is not None
            and not early_producer
            and not amended_after_producer
            and not self.violations
        )
        return {
            "blind_order_held": blind,
            "rubric_freeze_seq": freeze_seq,
            "outcomes_freeze_seq": outcomes_seq,
            "producer_reads_before_freeze": early_producer,
            "rubric_amendments_after_producer_read": amended_after_producer,
            "violations": list(self.violations),
            "ledger_length": len(self.entries),
            "chain_head": self.chain[-1],
        }
