"""The matrix runner: coverage, invariant wiring, and the cells that found bugs.

The full 101-cell sweep is exercised by ``harness/run_harness.py``; these tests
check the runner's contract and the specific cells that produced this unit's
mechanism changes, so they stay fast enough to run on every change.
"""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from harness import fixtures
from harness.custody_machine import COMMITTED_STATES
from harness.fault_injector import FAULT_KINDS
from harness.naive_machine import MUTANTS, ProviderTrustingStore
from harness.transition_matrix import (
    ENVIRONMENT_MATRIX,
    EXTRA_POINTS,
    IMMUTABLE_DAMAGE,
    MAX_RESUMES,
    POINT_KINDS,
    TRANSITIONS,
    UNIVERSAL_POINTS,
    Cell,
    enumerate_cells,
    inapplicable_cells,
    run_cell,
)

INVARIANTS = (
    "I1_NO_FALSE_COMPLETION",
    "I2_COMMITTED_RESULT_RECOVERED",
    "I3_UNCOMMITTED_RESUMES_FROM_IMMUTABLE_INPUT",
    "I4_NO_DUPLICATE_EXTERNAL_EFFECT",
    "I5_COMPLETE_HASH_COVERAGE",
    "I6_JOURNAL_INTEGRITY",
    "I7_STALE_FENCE_REJECTED",
    "I8_SEEDED_VALIDATOR_ACCEPTS",
    "I9_RECOVERY_TERMINATES",
    "I10_STRENGTHENED_INVARIANTS_HOLD",
)


class CoverageTests(unittest.TestCase):
    def test_all_ten_custody_transitions_are_enumerated(self):
        self.assertEqual(10, len(TRANSITIONS))
        cells = enumerate_cells()
        self.assertEqual({t["id"] for t in TRANSITIONS}, {c.transition_id for c in cells})

    def test_every_transition_crosses_the_universal_durability_boundaries(self):
        cells = enumerate_cells()
        for transition in TRANSITIONS:
            points = {c.point for c in cells if c.transition_id == transition["id"]}
            self.assertTrue(set(UNIVERSAL_POINTS) <= points, transition["id"])

    def test_every_declared_fault_kind_appears_somewhere(self):
        self.assertEqual(set(FAULT_KINDS), {c.kind for c in enumerate_cells()})

    def test_every_enumerated_point_declares_its_meaningful_kinds(self):
        points = set(UNIVERSAL_POINTS)
        for extra in EXTRA_POINTS.values():
            points |= set(extra)
        self.assertEqual(points, set(POINT_KINDS))

    def test_cell_identifiers_are_unique(self):
        ids = [c.cell_id for c in enumerate_cells()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_omitted_pair_is_recorded_with_a_reason(self):
        applicable = {(c.transition_id, c.kind) for c in enumerate_cells()}
        excluded = {(r["transition_id"], r["fault_kind"]) for r in inapplicable_cells()}
        self.assertEqual(set(), applicable & excluded)
        self.assertEqual(
            {(t["id"], k) for t in TRANSITIONS for k in FAULT_KINDS},
            applicable | excluded,
        )
        for row in inapplicable_cells():
            self.assertEqual("NOT_APPLICABLE", row["disposition"])
            self.assertTrue(row["reason"].strip())

    def test_remote_damage_cells_expect_a_block_rather_than_completion(self):
        for cell in enumerate_cells():
            if cell.kind in IMMUTABLE_DAMAGE and cell.damage_target == "remote":
                self.assertEqual("BLOCKED_NO_FALSE_COMPLETION", cell.expected_outcome)
            else:
                self.assertEqual("COMPLETED", cell.expected_outcome)

    def test_environment_faults_are_only_aimed_at_transitions_that_reach_them(self):
        ids = {t["id"] for t in TRANSITIONS}
        for kind, transitions in ENVIRONMENT_MATRIX.items():
            self.assertTrue(set(transitions) <= ids, kind)


class CellContractTests(unittest.TestCase):
    def test_a_healthy_run_evaluates_every_invariant_and_completes(self):
        row = run_cell(Cell(transition_id="T01", kind="POST_WRITE_LOSS", point="post_journal_append"))
        self.assertEqual(set(INVARIANTS), set(row["invariants"]))
        self.assertEqual([], row["violations"])
        self.assertEqual("COMPLETED", row["final_obzio_state"])
        self.assertTrue(row["fault_fired"])

    def test_the_run_stays_inside_its_resume_budget(self):
        row = run_cell(Cell(transition_id="T08", kind="NETWORK_INTERRUPTION", point="pre_external_effect"))
        self.assertFalse(row["budget_exhausted"])
        self.assertLessEqual(row["resumes"], MAX_RESUMES)
        self.assertEqual([], row["violations"])


class ProcessLossTests(unittest.TestCase):
    def test_loss_at_every_universal_boundary_of_the_commit_transition_survives(self):
        for point in UNIVERSAL_POINTS:
            for kind in POINT_KINDS[point]:
                with self.subTest(point=point, kind=kind):
                    row = run_cell(Cell(transition_id="T08", kind=kind, point=point))
                    self.assertEqual([], row["violations"])
                    self.assertEqual("COMPLETED", row["final_obzio_state"])
                    self.assertLessEqual(row["distinct_external_effects"], 1)

    def test_a_lost_acknowledgement_is_adopted_not_repeated(self):
        row = run_cell(Cell(transition_id="T08", kind="NETWORK_INTERRUPTION", point="post_external_effect"))
        self.assertEqual([], row["violations"])
        self.assertEqual(1, row["distinct_external_effects"])
        self.assertIn("ADOPT_UNACKNOWLEDGED_COMMIT", row["recovery_actions"])

    def test_a_lost_callback_still_reaches_exactly_one_ingestion(self):
        row = run_cell(Cell(transition_id="T09", kind="CALLBACK_LOSS", point="pre_callback_send"))
        self.assertEqual([], row["violations"])
        self.assertEqual("COMPLETED", row["final_obzio_state"])
        self.assertEqual(1, row["history"].count("PARENT_INGESTED"))

    def test_a_duplicated_callback_is_ignored_once(self):
        row = run_cell(Cell(transition_id="T09", kind="DUPLICATE_CALLBACK", point="environment"))
        self.assertEqual([], row["violations"])
        self.assertGreaterEqual(row["duplicate_ingests_ignored"], 1)
        self.assertEqual(1, row["history"].count("PARENT_INGESTED"))

    def test_a_provider_runtime_loss_is_classified_not_believed(self):
        row = run_cell(Cell(transition_id="T02", kind="PROVIDER_RUNTIME_LOSS", point="environment"))
        self.assertEqual([], row["violations"])
        classified = [e["classified_as"] for e in row["environment_events"] if e["kind"] == "PROVIDER_RUNTIME_LOSS"]
        self.assertEqual(["PROVIDER_COMPLETED_UNCOMMITTED"], classified)
        self.assertIn("SCHEDULE_RETRY_FROM_IMMUTABLE_INPUT", row["recovery_actions"])

    def test_a_stale_lease_is_actively_refused(self):
        row = run_cell(Cell(transition_id="T08", kind="STALE_LEASE", point="environment"))
        self.assertEqual([], row["violations"])
        self.assertIn("FENCED_OUT", row["refusals_recorded"])
        self.assertLessEqual(row["distinct_external_effects"], 1)


class RemoteDamageTests(unittest.TestCase):
    def test_remote_damage_terminates_without_completion(self):
        """Recurrence test for M4, driven through the full matrix runner."""
        for kind in sorted(IMMUTABLE_DAMAGE):
            with self.subTest(kind=kind):
                row = run_cell(Cell(transition_id="T08", kind=kind, point="environment", damage_target="remote"))
                self.assertEqual([], row["violations"])
                self.assertEqual("FAILED_TERMINAL", row["final_obzio_state"])
                self.assertNotIn("COMPLETED", row["history"])
                self.assertFalse(row["budget_exhausted"])
                self.assertIn("CLASSIFY_UNRECOVERABLE_REMOTE_DAMAGE", row["recovery_actions"])

    def test_staging_damage_is_repaired_rather_than_published(self):
        for kind in sorted(IMMUTABLE_DAMAGE):
            with self.subTest(kind=kind):
                row = run_cell(Cell(transition_id="T07", kind=kind, point="environment", damage_target="staging"))
                self.assertEqual([], row["violations"])
                self.assertEqual("COMPLETED", row["final_obzio_state"])
                self.assertEqual(1, row["distinct_external_effects"])

    def test_commit_reentry_preserves_commit_time(self):
        """Recurrence test for M5.

        Re-entering RESULT_COMMITTED after a lost acknowledgement must not
        restamp the commit, or custody timestamps claim a commit that happened
        after its own ingestion.
        """
        row = run_cell(Cell(transition_id="T08", kind="POST_WRITE_LOSS", point="post_external_effect"))
        self.assertEqual([], row["violations"])
        self.assertNotIn("I10_STRENGTHENED_INVARIANTS_HOLD", row["violations"])
        self.assertEqual("PASS", row["invariants"]["I10_STRENGTHENED_INVARIANTS_HOLD"]["disposition"])
        self.assertGreaterEqual(row["history"].count("RESULT_COMMITTED"), 1)


class DeterminismTests(unittest.TestCase):
    def test_a_cell_replays_identically(self):
        cell = Cell(transition_id="T06", kind="PARTIAL_WRITE", point="artifact_write_partial")
        first, second = run_cell(cell), run_cell(cell)
        self.assertEqual(first["trace_digest"], second["trace_digest"])
        self.assertEqual(first, second)


class FalsificationPowerTests(unittest.TestCase):
    """A harness that cannot fail proves nothing."""

    def test_the_provider_trusting_mutant_is_caught_completing_falsely(self):
        row = run_cell(
            Cell(transition_id="T02", kind="PROVIDER_RUNTIME_LOSS", point="environment"),
            store_cls=ProviderTrustingStore,
        )
        self.assertIn("I1_NO_FALSE_COMPLETION", row["violations"])
        self.assertEqual("COMPLETED", row["final_obzio_state"])
        self.assertNotIn(row["final_obzio_state"], {"PROVIDER_COMPLETED_UNCOMMITTED"})

    def test_the_snapshot_first_mutant_loses_a_transition(self):
        from harness.naive_machine import SnapshotFirstStore

        row = run_cell(
            Cell(transition_id="T08", kind="PRE_WRITE_LOSS", point="pre_journal_append"),
            store_cls=SnapshotFirstStore,
        )
        self.assertTrue(row["violations"])

    def test_the_torn_tail_mutant_corrupts_its_own_journal(self):
        from harness.naive_machine import TornTailTrustingStore

        row = run_cell(
            Cell(transition_id="T03", kind="PARTIAL_WRITE", point="journal_append_partial"),
            store_cls=TornTailTrustingStore,
        )
        self.assertIn("I6_JOURNAL_INTEGRITY", row["violations"])

    def test_the_unfenced_mutant_lets_a_stale_worker_write(self):
        from harness.naive_machine import UnfencedStore

        row = run_cell(
            Cell(transition_id="T08", kind="STALE_LEASE", point="environment"),
            store_cls=UnfencedStore,
        )
        self.assertIn("I7_STALE_FENCE_REJECTED", row["violations"])
        self.assertNotIn("FENCED_OUT", row["refusals_recorded"])

    def test_every_mutant_is_named_with_the_property_it_removes(self):
        for name, cls, description in MUTANTS:
            self.assertEqual(name, cls.__name__)
            self.assertTrue(description.strip())


class CompletedStateTests(unittest.TestCase):
    def test_committed_states_are_the_states_that_assert_a_durable_result(self):
        self.assertEqual({"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"}, set(COMMITTED_STATES))

    def test_the_payload_is_the_sanitized_repository_native_workload(self):
        names = dict(fixtures.default_payload())
        self.assertEqual(fixtures.CANARY_TEXT, names["canary.txt"])
        self.assertEqual(fixtures.CANARY_BYTES, len(names["canary.txt"]))


if __name__ == "__main__":
    unittest.main()
