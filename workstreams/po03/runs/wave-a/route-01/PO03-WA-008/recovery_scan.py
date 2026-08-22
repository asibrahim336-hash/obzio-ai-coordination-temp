#!/usr/bin/env python3
"""PO03-WA-008 -- a recovery scan deterministically resumes every nonterminal task.

Frozen hypothesis
-----------------
"A recovery scan deterministically resumes every nonterminal task."

Two failure modes make a recovery scan untrustworthy, and they are independent:

*Incompleteness* -- some nonterminal task is missed, so work silently stalls
forever with no one waiting on it.

*Nondeterminism* -- the plan depends on ledger arrival order, so two operators
recovering the same wave get different plans and neither can be reviewed or
replayed.  Nondeterminism is the more insidious one, because a scan that is
merely usually right looks fine until the run that matters.

Design
------
The scan folds an append-only event ledger into a per-task position, then emits
a resume plan.  Determinism is obtained structurally rather than by convention:

1. Events are **totally ordered by ``event_seq``** before folding, with
   ``(event_seq, task_id)`` as the tie-break, so the fold never depends on the
   order lines happen to appear in the file.
2. Duplicate ``event_seq`` values for one task are collapsed by content digest,
   so an at-least-once ledger writer cannot change the outcome.
3. The plan is emitted **sorted by task id** and serialised canonically, so the
   output is byte-identical for any input permutation.

Completeness is obtained by construction: the plan is built by iterating the
full task roster, not the events.  A task that appears in the roster with no
events at all is still planned.  ``verify_plan`` re-derives the coverage
invariant independently of how the plan was produced.

Each nonterminal position maps to exactly one resume action, and the mapping is
a total function -- an unrecognised position raises rather than being skipped.

Executable entry point::

    python3 recovery_scan.py --demo
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from typing import Any, Iterable

#: Positions from which no further work is scheduled.
TERMINAL = ("COMPLETED", "FAILED_TERMINAL", "CANCELLED")

#: Exactly one resume action per nonterminal position.  Total by construction.
RESUME_ACTIONS: dict[str, str] = {
    "CREATED": "DISPATCH",
    "LEASED": "REDISPATCH_WITH_NEW_FENCE",
    "RUNNING": "PROBE_PROVIDER",
    "CHECKPOINTED": "RESUME_FROM_CHECKPOINT",
    "RESULT_STAGING": "REVERIFY_AND_RESTAGE",
    "RESULT_STAGED": "VERIFY_AND_COMMIT",
    "RESULT_VERIFIED": "COMMIT_RESULT",
    "RESULT_COMMITTED": "INGEST_TO_PARENT",
    "PARENT_INGESTED": "AWAIT_INDEPENDENT_ACCEPTANCE",
    "PROVIDER_COMPLETED_UNCOMMITTED": "RECONCILE_PROVIDER_CLAIM",
    "RECOVERY_REQUIRED": "RUN_RECOVERY",
    "RETRY_SCHEDULED": "REDISPATCH_WITH_NEW_FENCE",
}


class UnknownPosition(Exception):
    """A task position with no declared resume action; never silently skipped."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def fold_events(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fold an unordered event stream into a deterministic per-task position."""
    # Collapse duplicates by (task_id, event_seq, content) so an at-least-once
    # writer cannot change the fold.
    unique: dict[tuple[str, int, str], dict[str, Any]] = {}
    for event in events:
        key = (event["task_id"], int(event["event_seq"]), digest(event))
        unique[key] = event

    ordered = sorted(unique.values(), key=lambda item: (int(item["event_seq"]), item["task_id"]))

    positions: dict[str, dict[str, Any]] = {}
    for event in ordered:
        task_id = event["task_id"]
        current = positions.setdefault(
            task_id,
            {"task_id": task_id, "position": "CREATED", "last_seq": 0, "fence_token": 0, "result_commit_id": None},
        )
        current["position"] = event["state"]
        current["last_seq"] = int(event["event_seq"])
        current["fence_token"] = max(current["fence_token"], int(event.get("fence_token", 0)))
        if event.get("result_commit_id"):
            current["result_commit_id"] = event["result_commit_id"]
    return positions


def scan(roster: Iterable[str], events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Produce a deterministic, complete resume plan for a wave."""
    roster = sorted(set(roster))
    positions = fold_events(events)

    orphan_events = sorted({task_id for task_id in positions if task_id not in roster})

    resume: list[dict[str, Any]] = []
    terminal: list[dict[str, Any]] = []
    for task_id in roster:
        state = positions.get(task_id, {"position": "CREATED", "last_seq": 0, "fence_token": 0, "result_commit_id": None})
        position = state["position"]
        if position in TERMINAL:
            terminal.append({"task_id": task_id, "position": position})
            continue
        if position not in RESUME_ACTIONS:
            raise UnknownPosition(f"{task_id} is at {position!r}, which has no declared resume action")
        resume.append(
            {
                "task_id": task_id,
                "position": position,
                "action": RESUME_ACTIONS[position],
                "next_fence_token": state["fence_token"] + 1,
                "last_seq": state["last_seq"],
                "result_commit_id": state["result_commit_id"],
            }
        )

    # False completion: claimed COMPLETED with no durable locator.
    false_completed = sorted(
        task_id
        for task_id, state in positions.items()
        if state["position"] == "COMPLETED" and not state["result_commit_id"]
    )

    plan = {
        "plan_version": "PO03-WA-008-RECOVERY-PLAN-v1",
        "roster_size": len(roster),
        "resume": sorted(resume, key=lambda item: item["task_id"]),
        "terminal": sorted(terminal, key=lambda item: item["task_id"]),
        "orphan_events": orphan_events,
        "false_completed": false_completed,
    }
    plan["plan_sha256"] = digest({key: value for key, value in plan.items() if key != "plan_sha256"})
    return plan


def verify_plan(plan: dict[str, Any], roster: Iterable[str]) -> list[str]:
    """Re-derive the coverage invariant independently of how the plan was built."""
    roster = sorted(set(roster))
    problems: list[str] = []

    planned = [item["task_id"] for item in plan["resume"]]
    terminal = [item["task_id"] for item in plan["terminal"]]
    covered = planned + terminal

    if sorted(covered) != roster:
        missing = sorted(set(roster) - set(covered))
        extra = sorted(set(covered) - set(roster))
        if missing:
            problems.append(f"unplanned nonterminal tasks: {missing}")
        if extra:
            problems.append(f"planned tasks absent from the roster: {extra}")
    if len(covered) != len(set(covered)):
        problems.append("a task appears more than once in the plan")
    for item in plan["resume"]:
        if item["position"] in TERMINAL:
            problems.append(f"{item['task_id']} is terminal but was scheduled for resume")
        if RESUME_ACTIONS.get(item["position"]) != item["action"]:
            problems.append(f"{item['task_id']} has an action inconsistent with its position")
    if plan["resume"] != sorted(plan["resume"], key=lambda item: item["task_id"]):
        problems.append("resume list is not deterministically ordered")
    return problems


def _synthetic_wave(task_count: int = 24, seed: int = 7) -> tuple[list[str], list[dict[str, Any]]]:
    """Build a roster and a messy but reproducible event ledger."""
    rng = random.Random(seed)
    roster = [f"PO03-WA-{index:03d}" for index in range(1, task_count + 1)]
    positions = list(RESUME_ACTIONS) + list(TERMINAL)
    events: list[dict[str, Any]] = []
    seq = 0
    for task_id in roster:
        # Some tasks deliberately have no events at all.
        if rng.random() < 0.15:
            continue
        target = rng.choice(positions)
        seq += 1
        commit = f"commit-{task_id}" if target in ("RESULT_COMMITTED", "PARENT_INGESTED") else None
        if target == "COMPLETED" and rng.random() < 0.5:
            commit = None  # a false completion
        elif target == "COMPLETED":
            commit = f"commit-{task_id}"
        events.append(
            {
                "event_seq": seq,
                "task_id": task_id,
                "state": target,
                "fence_token": rng.randint(1, 3),
                "result_commit_id": commit,
            }
        )
        # At-least-once ledger writers duplicate rows.
        if rng.random() < 0.3:
            events.append(dict(events[-1]))
    # Orphan events for tasks outside the roster.
    events.append({"event_seq": seq + 1, "task_id": "PO03-WA-999", "state": "RUNNING", "fence_token": 1})
    return roster, events


def determinism_report(permutations: int = 25, seed: int = 7) -> dict[str, Any]:
    """The same ledger in many orders must yield one byte-identical plan."""
    roster, events = _synthetic_wave(seed=seed)
    baseline = scan(roster, events)
    baseline_bytes = canonical(baseline)

    rng = random.Random(seed + 1)
    mismatches = []
    hashes = {baseline["plan_sha256"]}
    for index in range(permutations):
        shuffled = list(events)
        rng.shuffle(shuffled)
        candidate = scan(roster, shuffled)
        hashes.add(candidate["plan_sha256"])
        if canonical(candidate) != baseline_bytes:
            mismatches.append(index)

    return {
        "permutations": permutations,
        "distinct_plan_hashes": len(hashes),
        "plan_sha256": baseline["plan_sha256"],
        "mismatched_permutations": mismatches,
        "roster_size": baseline["roster_size"],
        "resume_count": len(baseline["resume"]),
        "terminal_count": len(baseline["terminal"]),
        "orphan_events": baseline["orphan_events"],
        "false_completed": baseline["false_completed"],
        "coverage_problems": verify_plan(baseline, roster),
    }


def demo() -> int:
    roster, events = _synthetic_wave()
    plan = scan(roster, events)
    report = {
        "determinism": determinism_report(),
        "sample_resume_actions": plan["resume"][:5],
        "coverage_problems": verify_plan(plan, roster),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv)
    if args.demo:
        return demo()
    parser.error("use --demo")
    return 2


if __name__ == "__main__":
    sys.exit(main())
