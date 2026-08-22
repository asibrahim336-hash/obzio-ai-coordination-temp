#!/usr/bin/env python3
"""PO03-WA-001 -- custody state machine that rejects skipped and reversed states.

Frozen hypothesis
-----------------
"State transitions reject skipped or reversed custody states."

The Obzio custody ladder is a total order for the happy path.  The defect this
component is built to exclude is the one observed in PO-02: a task presented as
``COMPLETED`` while no result was ever staged, verified or committed.  That is
exactly a *skip* along the ladder.  A permissive machine that only checks "is
the target a member of the state enum" cannot detect it.

Design
------
Legal movement is declared as an explicit edge set, never derived from the
ordinal difference at call time.  Three separate invariants are enforced:

1. **No skip.**  Forward movement along the ladder must advance by exactly one
   rung.  ``CREATED -> COMPLETED`` is rejected even though both are legal
   states and the direction is forward.
2. **No reversal.**  A ladder state may never move to a lower ladder state.
   Retry is expressed by leaving the ladder for ``RETRY_SCHEDULED`` and
   re-entering at ``LEASED`` under a *new* attempt with a higher fence token,
   which the caller must supply; re-entry is not a silent rewind.
3. **No resurrection.**  Terminal states have no outgoing edges at all.

The exception carries a machine-readable reason so a coordinator can classify
``SKIPPED_STATE`` separately from ``REVERSED_STATE``.

Executable entry point::

    python3 custody_fsm.py --demo
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Iterable

#: The ordered custody ladder.  Index is the rung; movement is checked against
#: the declared edge set, not against this index.
LADDER: tuple[str, ...] = (
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

#: Off-ladder states reachable from a live attempt.
OFF_LADDER: tuple[str, ...] = (
    "PROVIDER_COMPLETED_UNCOMMITTED",
    "RECOVERY_REQUIRED",
    "RETRY_SCHEDULED",
    "FAILED_TERMINAL",
    "CANCELLED",
)

ALL_STATES: frozenset[str] = frozenset(LADDER) | frozenset(OFF_LADDER)

#: States from which nothing may move.  ``COMPLETED`` is included: a completed
#: unit that later "moves" is a bookkeeping defect, not a transition.
TERMINAL: frozenset[str] = frozenset({"COMPLETED", "FAILED_TERMINAL", "CANCELLED"})

#: Ladder states after which a durable result exists.  Abandoning an attempt
#: from here must go through recovery, never straight to a retry.
POST_COMMIT: frozenset[str] = frozenset({"RESULT_COMMITTED", "PARENT_INGESTED"})

#: Only the coordinator may drive parent ingestion and completion.
COORDINATOR_ONLY: frozenset[str] = frozenset({"PARENT_INGESTED", "COMPLETED"})

#: The producer ceiling: a worker may not report above this rung.
PRODUCER_CEILING = "RESULT_STAGED"


class TransitionRejected(Exception):
    """A custody transition was refused.  ``reason`` is machine-readable."""

    def __init__(self, source: str, target: str, reason: str, detail: str) -> None:
        super().__init__(f"{source} -> {target} rejected: {reason}: {detail}")
        self.source = source
        self.target = target
        self.reason = reason
        self.detail = detail

    def as_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "target": self.target,
            "reason": self.reason,
            "detail": self.detail,
        }


def _build_edges() -> dict[str, frozenset[str]]:
    """Declare the legal edge set explicitly, one source state at a time."""
    edges: dict[str, set[str]] = {state: set() for state in ALL_STATES}

    # Forward ladder movement, strictly one rung at a time.
    for lower, upper in zip(LADDER, LADDER[1:]):
        edges[lower].add(upper)

    # A live attempt may be abandoned.  Before a durable commit exists this may
    # go to retry directly; after one it must go through recovery so the
    # already-committed result is reconciled rather than recomputed.
    for state in LADDER:
        if state in TERMINAL:
            continue
        edges[state].add("RECOVERY_REQUIRED")
        edges[state].add("CANCELLED")
        if state not in POST_COMMIT:
            edges[state].add("RETRY_SCHEDULED")
            edges[state].add("FAILED_TERMINAL")

    # Provider says finished, Obzio has no durable commit.  Reachable only from
    # states where the result has not been committed yet.
    for state in ("RUNNING", "CHECKPOINTED", "RESULT_STAGING", "RESULT_STAGED", "RESULT_VERIFIED"):
        edges[state].add("PROVIDER_COMPLETED_UNCOMMITTED")

    # Recovery outcomes.
    edges["PROVIDER_COMPLETED_UNCOMMITTED"].update({"RECOVERY_REQUIRED", "CANCELLED"})
    edges["RECOVERY_REQUIRED"].update({"RETRY_SCHEDULED", "FAILED_TERMINAL", "CANCELLED"})
    # Recovery may also reconcile a result that was in fact committed.
    edges["RECOVERY_REQUIRED"].add("RESULT_COMMITTED")
    # A scheduled retry re-enters the ladder at LEASED under a new attempt.
    edges["RETRY_SCHEDULED"].update({"LEASED", "FAILED_TERMINAL", "CANCELLED"})

    for state in TERMINAL:
        edges[state] = set()

    return {state: frozenset(targets) for state, targets in edges.items()}


EDGES: dict[str, frozenset[str]] = _build_edges()


def classify_rejection(source: str, target: str) -> tuple[str, str]:
    """Return ``(reason, detail)`` for an illegal ``source -> target`` move."""
    if source not in ALL_STATES:
        return "UNKNOWN_SOURCE_STATE", f"{source!r} is not a custody state"
    if target not in ALL_STATES:
        return "UNKNOWN_TARGET_STATE", f"{target!r} is not a custody state"
    if source in TERMINAL:
        return "TERMINAL_STATE_RESURRECTION", f"{source} is terminal and has no outgoing edges"
    if source == target:
        return "SELF_TRANSITION", f"{source} cannot transition to itself"
    if source in LADDER and target in LADDER:
        lower, upper = LADDER.index(source), LADDER.index(target)
        if upper < lower:
            return "REVERSED_STATE", f"{target} is {lower - upper} rung(s) below {source}"
        return "SKIPPED_STATE", f"{target} is {upper - lower} rungs above {source}; only 1 is legal"
    if target in LADDER and source in OFF_LADDER:
        return "ILLEGAL_LADDER_REENTRY", f"{source} may not re-enter the ladder at {target}"
    return "UNDECLARED_EDGE", f"no declared edge from {source} to {target}"


def check_transition(source: str, target: str) -> None:
    """Raise :class:`TransitionRejected` unless the move is a declared edge."""
    if target in EDGES.get(source, frozenset()):
        return
    reason, detail = classify_rejection(source, target)
    raise TransitionRejected(source, target, reason, detail)


@dataclass
class CustodyRecord:
    """One work unit's custody position plus its append-only transition log."""

    task_id: str
    state: str = "CREATED"
    fence_token: int = 0
    actor: str = "worker"
    history: list[dict[str, object]] = field(default_factory=list)

    def transition(self, target: str, *, actor: str = "worker", fence_token: int | None = None) -> str:
        """Move to ``target`` or refuse with a machine-readable reason."""
        check_transition(self.state, target)

        if target in COORDINATOR_ONLY and actor != "coordinator":
            raise TransitionRejected(
                self.state,
                target,
                "ACTOR_NOT_PERMITTED",
                f"{target} requires the coordinator, actor was {actor!r}",
            )
        if actor == "worker" and target in LADDER and self.state in LADDER:
            if LADDER.index(target) > LADDER.index(PRODUCER_CEILING):
                raise TransitionRejected(
                    self.state,
                    target,
                    "PRODUCER_CEILING_EXCEEDED",
                    f"a worker may not report above {PRODUCER_CEILING}",
                )

        # Re-entering the ladder after a retry requires a strictly higher fence
        # so a stale attempt cannot resume as though nothing happened.
        if self.state == "RETRY_SCHEDULED" and target == "LEASED":
            if fence_token is None or fence_token <= self.fence_token:
                raise TransitionRejected(
                    self.state,
                    target,
                    "STALE_FENCE_ON_REENTRY",
                    f"re-entry needs a fence above {self.fence_token}, got {fence_token!r}",
                )
            self.fence_token = fence_token
        elif fence_token is not None:
            if fence_token < self.fence_token:
                raise TransitionRejected(
                    self.state,
                    target,
                    "STALE_FENCE",
                    f"fence {fence_token} is below the held fence {self.fence_token}",
                )
            self.fence_token = fence_token

        source = self.state
        self.state = target
        self.actor = actor
        self.history.append(
            {"seq": len(self.history) + 1, "from": source, "to": target, "actor": actor, "fence": self.fence_token}
        )
        return self.state

    def try_transition(self, target: str, **kwargs: object) -> dict[str, object]:
        """Non-raising form used by callers that log rather than abort."""
        try:
            self.transition(target, **kwargs)  # type: ignore[arg-type]
        except TransitionRejected as rejection:
            return {"accepted": False, **rejection.as_dict()}
        return {"accepted": True, "source": self.history[-1]["from"], "target": self.state}


def replay(task_id: str, targets: Iterable[str], *, actor: str = "worker") -> CustodyRecord:
    """Drive a fresh record through ``targets``; the first illegal move raises."""
    record = CustodyRecord(task_id=task_id)
    for target in targets:
        record.transition(target, actor=actor)
    return record


def demo() -> int:
    """Show one legal walk and the three rejection families it excludes."""
    report: dict[str, object] = {"component": "PO03-WA-001 custody_fsm"}

    legal = CustodyRecord(task_id="demo-legal")
    for target in ("LEASED", "RUNNING", "CHECKPOINTED", "RESULT_STAGING", "RESULT_STAGED"):
        legal.transition(target, actor="worker")
    for target in ("RESULT_VERIFIED", "RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"):
        legal.transition(target, actor="coordinator")
    report["legal_walk"] = {"final_state": legal.state, "steps": len(legal.history)}

    rejections = []
    for source, target in (
        ("CREATED", "COMPLETED"),
        ("RUNNING", "RESULT_COMMITTED"),
        ("RESULT_COMMITTED", "RUNNING"),
        ("COMPLETED", "RUNNING"),
    ):
        record = CustodyRecord(task_id="demo-reject", state=source)
        outcome = record.try_transition(target, actor="coordinator")
        rejections.append(outcome)
    report["rejections"] = rejections

    ceiling = CustodyRecord(task_id="demo-ceiling", state="RESULT_STAGED")
    report["producer_ceiling"] = ceiling.try_transition("RESULT_VERIFIED", actor="worker")

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true", help="run the demonstration walk")
    parser.add_argument("--from", dest="source", help="source state")
    parser.add_argument("--to", dest="target", help="target state")
    args = parser.parse_args(argv)
    if args.demo:
        return demo()
    if args.source and args.target:
        try:
            check_transition(args.source, args.target)
        except TransitionRejected as rejection:
            print(json.dumps({"accepted": False, **rejection.as_dict()}, sort_keys=True))
            return 1
        print(json.dumps({"accepted": True, "source": args.source, "target": args.target}, sort_keys=True))
        return 0
    parser.error("use --demo or both --from and --to")
    return 2


if __name__ == "__main__":
    sys.exit(main())
