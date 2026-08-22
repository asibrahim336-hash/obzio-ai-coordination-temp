"""PO03-WA-051 — exhaustive hidden cases over legal and prohibited transitions.

Frozen hypothesis: hidden cases cover every legal state transition and every
prohibited skip.

Example-based custody tests only probe the transitions someone happened to think
of. This component takes the opposite approach: it derives the custody graph from
the commission lifecycle, then enumerates the *complete* ordered product of
states so that every pair is classified exactly once as LEGAL, SKIP, REVERSAL,
SELF or UNREACHABLE. A hidden-case suite generated this way cannot silently omit
a transition, because omission is detectable as an unclassified pair.

It is a case oracle, not a state machine implementation: the executable FSM it
checks is supplied by the caller, so the oracle can falsify any custody
implementation rather than only its own.

Standard library only.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from enum import Enum

# The custody lifecycle named by the commission:
# CREATED -> LEASED -> RUNNING -> CHECKPOINTED* -> RESULT_STAGING -> RESULT_STAGED
#   -> RESULT_VERIFIED -> RESULT_COMMITTED -> PARENT_INGESTED -> COMPLETED
HAPPY_PATH = (
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
)

# Off-path states reachable from a fault, not from progress.
FAULT_STATES = (
    "PROVIDER_COMPLETED_UNCOMMITTED",
    "RECOVERY_REQUIRED",
    "RETRY_SCHEDULED",
    "FAILED_TERMINAL",
    "CANCELLED",
)

ALL_STATES = HAPPY_PATH + FAULT_STATES
TERMINAL_STATES = frozenset({"COMPLETED", "FAILED_TERMINAL", "CANCELLED"})

# CHECKPOINTED is the one repeatable state in the lifecycle ("CHECKPOINTED*").
REPEATABLE_STATES = frozenset({"CHECKPOINTED"})

# A fault may be entered from any non-terminal progress state.
FAULT_ENTRY_SOURCES = frozenset(HAPPY_PATH) - TERMINAL_STATES
# Recovery re-enters the pipeline only at these resumption points.
RECOVERY_RESUMPTION = {
    "RECOVERY_REQUIRED": frozenset({"LEASED", "RETRY_SCHEDULED", "FAILED_TERMINAL", "CANCELLED"}),
    "RETRY_SCHEDULED": frozenset({"LEASED", "CANCELLED", "FAILED_TERMINAL"}),
    "PROVIDER_COMPLETED_UNCOMMITTED": frozenset({"RECOVERY_REQUIRED", "RETRY_SCHEDULED", "FAILED_TERMINAL"}),
    "FAILED_TERMINAL": frozenset(),
    "CANCELLED": frozenset(),
}


class Verdict(str, Enum):
    LEGAL = "LEGAL"
    SKIP = "SKIP"
    REVERSAL = "REVERSAL"
    SELF = "SELF"
    UNREACHABLE = "UNREACHABLE"


@dataclass(frozen=True)
class Case:
    source: str
    target: str
    verdict: Verdict
    reason: str

    @property
    def must_be_accepted(self) -> bool:
        return self.verdict is Verdict.LEGAL


def _index(state: str):
    return HAPPY_PATH.index(state) if state in HAPPY_PATH else None


def classify_pair(source: str, target: str) -> Case:
    """Classify one ordered pair. Total over ALL_STATES x ALL_STATES."""
    if source not in ALL_STATES:
        raise ValueError(f"unknown source state {source!r}")
    if target not in ALL_STATES:
        raise ValueError(f"unknown target state {target!r}")

    if source == target:
        if source in REPEATABLE_STATES:
            return Case(source, target, Verdict.LEGAL, "monotonic checkpoint may repeat")
        return Case(source, target, Verdict.SELF, "non-repeatable state cannot re-enter itself")

    if source in TERMINAL_STATES:
        return Case(source, target, Verdict.UNREACHABLE, f"{source} is terminal")

    si, ti = _index(source), _index(target)

    if si is not None and ti is not None:
        if ti == si + 1:
            return Case(source, target, Verdict.LEGAL, "adjacent lifecycle advance")
        if ti > si + 1:
            skipped = HAPPY_PATH[si + 1 : ti]
            return Case(source, target, Verdict.SKIP, f"skips {', '.join(skipped)}")
        return Case(source, target, Verdict.REVERSAL, "moves backwards through custody")

    if si is not None and target in FAULT_STATES:
        if source in FAULT_ENTRY_SOURCES:
            return Case(source, target, Verdict.LEGAL, "fault entry from a live progress state")
        return Case(source, target, Verdict.UNREACHABLE, "fault entry from a terminal state")

    if source in FAULT_STATES:
        if target in RECOVERY_RESUMPTION[source]:
            return Case(source, target, Verdict.LEGAL, "declared recovery resumption")
        if ti is not None:
            return Case(
                source, target, Verdict.SKIP, f"recovery may not resume directly at {target}"
            )
        return Case(source, target, Verdict.UNREACHABLE, "undeclared fault-to-fault edge")

    raise AssertionError(f"unclassified pair {source} -> {target}")


def enumerate_cases() -> list:
    """Every ordered pair of states, each classified exactly once."""
    return [classify_pair(a, b) for a, b in itertools.product(ALL_STATES, repeat=2)]


def legal_cases() -> list:
    return [c for c in enumerate_cases() if c.verdict is Verdict.LEGAL]


def prohibited_cases() -> list:
    return [c for c in enumerate_cases() if c.verdict is not Verdict.LEGAL]


def enumerate_paths(max_length: int = 4) -> list:
    """Bounded walks from CREATED, tagged with whether every edge is legal."""
    paths, frontier = [], [("CREATED",)]
    while frontier:
        path = frontier.pop()
        if len(path) >= max_length:
            continue
        for nxt in ALL_STATES:
            candidate = path + (nxt,)
            edges = [classify_pair(a, b) for a, b in zip(candidate, candidate[1:])]
            legal = all(e.must_be_accepted for e in edges)
            paths.append({"path": candidate, "all_edges_legal": legal})
            if legal and nxt not in TERMINAL_STATES:
                frontier.append(candidate)
    return paths


def falsify(fsm_accepts) -> dict:
    """Run every hidden case against a caller-supplied transition predicate.

    `fsm_accepts(source, target)` must return True iff the implementation permits
    the transition. Returns the false accepts and false rejects it produced.
    """
    false_accepts, false_rejects = [], []
    for case in enumerate_cases():
        try:
            accepted = bool(fsm_accepts(case.source, case.target))
        except Exception:  # noqa: BLE001 - an exception counts as a refusal
            accepted = False
        if accepted and not case.must_be_accepted:
            false_accepts.append(case)
        elif not accepted and case.must_be_accepted:
            false_rejects.append(case)
    return {
        "total_cases": len(enumerate_cases()),
        "false_accepts": false_accepts,
        "false_rejects": false_rejects,
        "sound": not false_accepts and not false_rejects,
    }
