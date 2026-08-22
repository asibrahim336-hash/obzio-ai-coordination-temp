#!/usr/bin/env python3
"""Falsification suite for PO03-WA-001.

The hypothesis is falsified if any skipped or reversed custody transition is
accepted.  The suite is exhaustive over the ladder rather than example-driven:
every ordered pair of ladder states is enumerated and each one must be either
the single legal forward rung or an explicit rejection carrying the correct
machine-readable reason.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("custody_fsm", Path(__file__).with_name("custody_fsm.py"))
assert SPEC is not None and SPEC.loader is not None
FSM = importlib.util.module_from_spec(SPEC)
# Registered before execution so dataclass field resolution can find the module.
sys.modules["custody_fsm"] = FSM
SPEC.loader.exec_module(FSM)


class LadderExhaustionTests(unittest.TestCase):
    """Every ordered ladder pair is classified, with no silent acceptance."""

    def test_every_ladder_pair_is_classified(self):
        accepted: list[tuple[str, str]] = []
        for source, target in itertools.permutations(FSM.LADDER, 2):
            try:
                FSM.check_transition(source, target)
            except FSM.TransitionRejected as rejection:
                self.assertIn(
                    rejection.reason,
                    {"SKIPPED_STATE", "REVERSED_STATE", "TERMINAL_STATE_RESURRECTION"},
                    f"{source}->{target} rejected for an unexpected reason: {rejection.reason}",
                )
            else:
                accepted.append((source, target))
        expected = list(zip(FSM.LADDER, FSM.LADDER[1:]))
        self.assertEqual(expected, accepted, "only single-rung forward moves may be accepted")

    def test_no_skip_is_accepted(self):
        for distance in range(2, len(FSM.LADDER)):
            for index in range(len(FSM.LADDER) - distance):
                source = FSM.LADDER[index]
                target = FSM.LADDER[index + distance]
                with self.assertRaises(FSM.TransitionRejected) as caught:
                    FSM.check_transition(source, target)
                if source in FSM.TERMINAL:
                    continue
                self.assertEqual("SKIPPED_STATE", caught.exception.reason, f"{source}->{target}")

    def test_no_reversal_is_accepted(self):
        for upper, lower in itertools.permutations(range(len(FSM.LADDER)), 2):
            if upper <= lower:
                continue
            source, target = FSM.LADDER[upper], FSM.LADDER[lower]
            with self.assertRaises(FSM.TransitionRejected) as caught:
                FSM.check_transition(source, target)
            expected = "TERMINAL_STATE_RESURRECTION" if source in FSM.TERMINAL else "REVERSED_STATE"
            self.assertEqual(expected, caught.exception.reason, f"{source}->{target}")

    def test_terminal_states_have_no_outgoing_edges(self):
        for state in FSM.TERMINAL:
            self.assertEqual(frozenset(), FSM.EDGES[state], state)
            for target in FSM.ALL_STATES:
                if target == state:
                    continue
                with self.assertRaises(FSM.TransitionRejected) as caught:
                    FSM.check_transition(state, target)
                self.assertEqual("TERMINAL_STATE_RESURRECTION", caught.exception.reason)

    def test_self_transition_rejected(self):
        for state in FSM.ALL_STATES:
            with self.assertRaises(FSM.TransitionRejected) as caught:
                FSM.check_transition(state, state)
            expected = "TERMINAL_STATE_RESURRECTION" if state in FSM.TERMINAL else "SELF_TRANSITION"
            self.assertEqual(expected, caught.exception.reason, state)


class Po02DefectTests(unittest.TestCase):
    """The concrete shape of the recorded PO-02 Code-2 false completion."""

    def test_created_to_completed_is_rejected_as_a_skip(self):
        record = FSM.CustodyRecord(task_id="po02-code2")
        with self.assertRaises(FSM.TransitionRejected) as caught:
            record.transition("COMPLETED", actor="coordinator")
        self.assertEqual("SKIPPED_STATE", caught.exception.reason)
        self.assertEqual("CREATED", record.state, "a rejected transition must not mutate state")
        self.assertEqual([], record.history)

    def test_running_cannot_jump_over_staging_to_committed(self):
        record = FSM.replay("jump", ("LEASED", "RUNNING"))
        with self.assertRaises(FSM.TransitionRejected) as caught:
            record.transition("RESULT_COMMITTED", actor="coordinator")
        self.assertEqual("SKIPPED_STATE", caught.exception.reason)
        self.assertIn("5 rungs above", caught.exception.detail)

    def test_provider_completion_leaves_the_ladder_instead_of_completing(self):
        record = FSM.replay("provider", ("LEASED", "RUNNING"))
        record.transition("PROVIDER_COMPLETED_UNCOMMITTED")
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", record.state)
        with self.assertRaises(FSM.TransitionRejected) as caught:
            record.transition("COMPLETED", actor="coordinator")
        self.assertEqual("ILLEGAL_LADDER_REENTRY", caught.exception.reason)


class RetryAndFenceTests(unittest.TestCase):
    """Retry is a declared detour, not a silent rewind of the ladder."""

    def test_retry_reentry_requires_a_higher_fence(self):
        record = FSM.CustodyRecord(task_id="retry", state="RUNNING", fence_token=3)
        record.transition("RETRY_SCHEDULED")
        with self.assertRaises(FSM.TransitionRejected) as caught:
            record.transition("LEASED", fence_token=3)
        self.assertEqual("STALE_FENCE_ON_REENTRY", caught.exception.reason)
        record.transition("LEASED", fence_token=4)
        self.assertEqual("LEASED", record.state)
        self.assertEqual(4, record.fence_token)

    def test_retry_cannot_reenter_mid_ladder(self):
        record = FSM.CustodyRecord(task_id="retry-mid", state="RETRY_SCHEDULED", fence_token=1)
        with self.assertRaises(FSM.TransitionRejected) as caught:
            record.transition("RESULT_STAGED", fence_token=9)
        self.assertEqual("ILLEGAL_LADDER_REENTRY", caught.exception.reason)

    def test_committed_result_cannot_be_retried_only_recovered(self):
        record = FSM.CustodyRecord(task_id="post-commit", state="RESULT_COMMITTED")
        with self.assertRaises(FSM.TransitionRejected) as caught:
            record.transition("RETRY_SCHEDULED")
        self.assertEqual("UNDECLARED_EDGE", caught.exception.reason)
        record.transition("RECOVERY_REQUIRED")
        self.assertEqual("RECOVERY_REQUIRED", record.state)

    def test_a_lower_fence_cannot_advance_a_live_record(self):
        record = FSM.CustodyRecord(task_id="fence", state="RUNNING", fence_token=7)
        with self.assertRaises(FSM.TransitionRejected) as caught:
            record.transition("CHECKPOINTED", fence_token=6)
        self.assertEqual("STALE_FENCE", caught.exception.reason)
        self.assertEqual("RUNNING", record.state)


class ActorTests(unittest.TestCase):
    def test_worker_cannot_pass_the_producer_ceiling(self):
        record = FSM.replay("ceiling", ("LEASED", "RUNNING", "CHECKPOINTED", "RESULT_STAGING", "RESULT_STAGED"))
        with self.assertRaises(FSM.TransitionRejected) as caught:
            record.transition("RESULT_VERIFIED", actor="worker")
        self.assertEqual("PRODUCER_CEILING_EXCEEDED", caught.exception.reason)
        self.assertEqual("RESULT_STAGED", record.state)

    def test_worker_cannot_ingest_or_complete(self):
        record = FSM.CustodyRecord(task_id="actor", state="RESULT_COMMITTED")
        with self.assertRaises(FSM.TransitionRejected) as caught:
            record.transition("PARENT_INGESTED", actor="worker")
        self.assertEqual("ACTOR_NOT_PERMITTED", caught.exception.reason)
        record.transition("PARENT_INGESTED", actor="coordinator")
        with self.assertRaises(FSM.TransitionRejected) as caught:
            record.transition("COMPLETED", actor="worker")
        self.assertEqual("ACTOR_NOT_PERMITTED", caught.exception.reason)

    def test_full_legal_walk_reaches_completed_only_through_every_rung(self):
        record = FSM.CustodyRecord(task_id="walk")
        for target in FSM.LADDER[1:]:
            actor = "coordinator" if target in FSM.COORDINATOR_ONLY or FSM.LADDER.index(target) > FSM.LADDER.index(
                FSM.PRODUCER_CEILING
            ) else "worker"
            record.transition(target, actor=actor)
        self.assertEqual("COMPLETED", record.state)
        self.assertEqual(len(FSM.LADDER) - 1, len(record.history))
        visited = ["CREATED"] + [step["to"] for step in record.history]
        self.assertEqual(list(FSM.LADDER), visited)


class UnknownStateTests(unittest.TestCase):
    def test_unknown_states_are_named_not_silently_dropped(self):
        with self.assertRaises(FSM.TransitionRejected) as caught:
            FSM.check_transition("CREATED", "DONE")
        self.assertEqual("UNKNOWN_TARGET_STATE", caught.exception.reason)
        with self.assertRaises(FSM.TransitionRejected) as caught:
            FSM.check_transition("FINISHED", "COMPLETED")
        self.assertEqual("UNKNOWN_SOURCE_STATE", caught.exception.reason)

    def test_edge_set_never_references_an_unknown_state(self):
        for source, targets in FSM.EDGES.items():
            self.assertIn(source, FSM.ALL_STATES)
            for target in targets:
                self.assertIn(target, FSM.ALL_STATES, f"{source}->{target}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
