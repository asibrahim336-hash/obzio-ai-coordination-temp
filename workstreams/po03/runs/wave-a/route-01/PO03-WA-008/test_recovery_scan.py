#!/usr/bin/env python3
"""Falsification suite for PO03-WA-008.

Two independent claims are under test and each has its own falsifier:

*Completeness* -- falsified if any nonterminal task in the roster is absent from
the resume plan.  Tested by sweeping every declared position across every task.

*Determinism* -- falsified if two permutations of one ledger produce different
plans.  Tested by shuffling with many seeds and comparing canonical bytes, plus
a negative control showing an order-sensitive fold really does diverge under the
same shuffles.
"""

from __future__ import annotations

import importlib.util
import json
import random
import sys
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("recovery_scan", Path(__file__).with_name("recovery_scan.py"))
assert SPEC is not None and SPEC.loader is not None
RS = importlib.util.module_from_spec(SPEC)
sys.modules["recovery_scan"] = RS
SPEC.loader.exec_module(RS)


def order_sensitive_fold(events):
    """Negative control: fold in arrival order, as a naive scan would."""
    positions = {}
    for event in events:
        positions[event["task_id"]] = event["state"]
    return positions


class CompletenessTests(unittest.TestCase):
    def test_every_nonterminal_position_yields_exactly_one_resume_action(self):
        roster = [f"T{index:03d}" for index in range(len(RS.RESUME_ACTIONS))]
        events = [
            {"event_seq": index + 1, "task_id": task_id, "state": position, "fence_token": 1}
            for index, (task_id, position) in enumerate(zip(roster, RS.RESUME_ACTIONS))
        ]
        plan = RS.scan(roster, events)
        self.assertEqual(len(roster), len(plan["resume"]))
        self.assertEqual([], RS.verify_plan(plan, roster))
        self.assertEqual(sorted(roster), [item["task_id"] for item in plan["resume"]])

    def test_a_task_with_no_events_is_still_planned(self):
        roster = ["T1", "T2", "T3"]
        events = [{"event_seq": 1, "task_id": "T1", "state": "RUNNING", "fence_token": 1}]
        plan = RS.scan(roster, events)
        planned = {item["task_id"]: item for item in plan["resume"]}
        self.assertEqual({"T1", "T2", "T3"}, set(planned))
        self.assertEqual("DISPATCH", planned["T2"]["action"], "no events means CREATED, not missing")
        self.assertEqual([], RS.verify_plan(plan, roster))

    def test_terminal_tasks_are_not_scheduled(self):
        roster = ["T1", "T2", "T3"]
        events = [
            {"event_seq": 1, "task_id": task_id, "state": state, "fence_token": 1, "result_commit_id": "c"}
            for task_id, state in zip(roster, RS.TERMINAL)
        ]
        plan = RS.scan(roster, events)
        self.assertEqual([], plan["resume"])
        self.assertEqual(3, len(plan["terminal"]))
        self.assertEqual([], RS.verify_plan(plan, roster))

    def test_coverage_is_exactly_the_roster(self):
        roster, events = RS._synthetic_wave()
        plan = RS.scan(roster, events)
        covered = [item["task_id"] for item in plan["resume"]] + [item["task_id"] for item in plan["terminal"]]
        self.assertEqual(sorted(roster), sorted(covered))
        self.assertEqual(len(covered), len(set(covered)), "no task may be planned twice")

    def test_orphan_events_are_reported_not_planned(self):
        roster = ["T1"]
        events = [
            {"event_seq": 1, "task_id": "T1", "state": "RUNNING", "fence_token": 1},
            {"event_seq": 2, "task_id": "GHOST", "state": "RUNNING", "fence_token": 1},
        ]
        plan = RS.scan(roster, events)
        self.assertEqual(["GHOST"], plan["orphan_events"])
        self.assertEqual(["T1"], [item["task_id"] for item in plan["resume"]])

    def test_an_undeclared_position_raises_rather_than_being_skipped(self):
        with self.assertRaises(RS.UnknownPosition):
            RS.scan(["T1"], [{"event_seq": 1, "task_id": "T1", "state": "MYSTERY", "fence_token": 1}])

    def test_resume_action_map_is_total_over_nonterminal_states(self):
        overlap = set(RS.RESUME_ACTIONS) & set(RS.TERMINAL)
        self.assertEqual(set(), overlap, "no state may be both terminal and resumable")


class DeterminismTests(unittest.TestCase):
    def test_permutations_of_one_ledger_produce_one_plan(self):
        report = RS.determinism_report(permutations=25)
        self.assertEqual([], report["mismatched_permutations"], report)
        self.assertEqual(1, report["distinct_plan_hashes"], report)
        self.assertEqual([], report["coverage_problems"])

    def test_determinism_holds_across_many_seeds(self):
        for seed in range(1, 11):
            report = RS.determinism_report(permutations=10, seed=seed)
            self.assertEqual(1, report["distinct_plan_hashes"], f"seed {seed}: {report}")
            self.assertEqual([], report["coverage_problems"], f"seed {seed}")

    def test_duplicate_events_do_not_change_the_plan(self):
        roster, events = RS._synthetic_wave(seed=3)
        baseline = RS.scan(roster, events)
        tripled = events + events + events
        self.assertEqual(baseline["plan_sha256"], RS.scan(roster, tripled)["plan_sha256"])

    def test_plan_hash_is_stable_across_processes_by_construction(self):
        """Canonical serialisation, no timestamps, no object identity."""
        roster, events = RS._synthetic_wave(seed=5)
        first = RS.scan(roster, events)
        second = RS.scan(roster, list(reversed(events)))
        self.assertEqual(RS.canonical(first), RS.canonical(second))
        self.assertNotIn("scanned_at", first, "a timestamp would break plan determinism")

    def test_a_different_ledger_produces_a_different_plan_hash(self):
        """Determinism must not be achieved by ignoring the input."""
        roster, events = RS._synthetic_wave(seed=5)
        baseline = RS.scan(roster, events)
        changed = list(events)
        changed.append({"event_seq": 9999, "task_id": roster[0], "state": "RESULT_STAGED", "fence_token": 9})
        self.assertNotEqual(baseline["plan_sha256"], RS.scan(roster, changed)["plan_sha256"])


class NegativeControlTests(unittest.TestCase):
    def test_an_order_sensitive_fold_really_does_diverge(self):
        """Prove the shuffle is capable of exposing nondeterminism."""
        _, events = RS._synthetic_wave(seed=11)
        # Give one task two events at different sequence numbers so arrival
        # order genuinely matters.
        events = events + [
            {"event_seq": 1, "task_id": "PO03-WA-001", "state": "RUNNING", "fence_token": 1},
            {"event_seq": 2, "task_id": "PO03-WA-001", "state": "RESULT_STAGED", "fence_token": 2},
        ]
        rng = random.Random(99)
        observed = set()
        for _ in range(40):
            shuffled = list(events)
            rng.shuffle(shuffled)
            observed.add(order_sensitive_fold(shuffled)["PO03-WA-001"])
        self.assertGreater(
            len(observed), 1, "the negative control failed to diverge, so the determinism test proves nothing"
        )

    def test_the_guarded_fold_is_stable_under_the_identical_shuffles(self):
        _, events = RS._synthetic_wave(seed=11)
        events = events + [
            {"event_seq": 1, "task_id": "PO03-WA-001", "state": "RUNNING", "fence_token": 1},
            {"event_seq": 2, "task_id": "PO03-WA-001", "state": "RESULT_STAGED", "fence_token": 2},
        ]
        rng = random.Random(99)
        observed = set()
        for _ in range(40):
            shuffled = list(events)
            rng.shuffle(shuffled)
            observed.add(RS.fold_events(shuffled)["PO03-WA-001"]["position"])
        self.assertEqual({"RESULT_STAGED"}, observed, "highest event_seq must always win")


class FenceAndFalseCompletionTests(unittest.TestCase):
    def test_resume_always_advances_the_fence(self):
        roster = ["T1"]
        events = [{"event_seq": 1, "task_id": "T1", "state": "RUNNING", "fence_token": 4}]
        plan = RS.scan(roster, events)
        self.assertEqual(5, plan["resume"][0]["next_fence_token"])

    def test_false_completion_is_detected(self):
        roster = ["T1", "T2"]
        events = [
            {"event_seq": 1, "task_id": "T1", "state": "COMPLETED", "fence_token": 1, "result_commit_id": None},
            {"event_seq": 2, "task_id": "T2", "state": "COMPLETED", "fence_token": 1, "result_commit_id": "c2"},
        ]
        plan = RS.scan(roster, events)
        self.assertEqual(["T1"], plan["false_completed"])

    def test_verify_plan_detects_a_tampered_plan(self):
        """The verifier must be able to fail, not only to pass."""
        roster = ["T1", "T2"]
        events = [{"event_seq": 1, "task_id": task, "state": "RUNNING", "fence_token": 1} for task in roster]
        plan = RS.scan(roster, events)
        self.assertEqual([], RS.verify_plan(plan, roster))

        dropped = json.loads(json.dumps(plan))
        dropped["resume"] = dropped["resume"][:1]
        self.assertTrue(any("unplanned" in problem for problem in RS.verify_plan(dropped, roster)))

        mislabelled = json.loads(json.dumps(plan))
        mislabelled["resume"][0]["action"] = "DO_NOTHING"
        self.assertTrue(any("inconsistent" in problem for problem in RS.verify_plan(mislabelled, roster)))

        unordered = json.loads(json.dumps(plan))
        unordered["resume"] = list(reversed(unordered["resume"]))
        self.assertTrue(any("deterministically ordered" in problem for problem in RS.verify_plan(unordered, roster)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
