"""Recurrence test for M6: the evidence behind rejecting fuzzing as a substitute.

The rejection is only honest if the campaign genuinely runs, genuinely overlaps
several faults per case, and genuinely compares the same safety properties the
exhaustive matrix evaluates.  These tests check all three, and record the
comparison the rejection rests on.
"""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from harness.fault_injector import ENVIRONMENT_KINDS, FAULT_KINDS, FAULT_POINTS
from harness.fuzz import (
    EXCLUDED_INVARIANTS,
    SAFETY_INVARIANTS,
    build_schedule,
    compare_with_exhaustive,
    run_campaign,
    run_case,
)
from harness.transition_matrix import Cell, run_cell

CAMPAIGN_CASES = 120
CAMPAIGN_MAX_FAULTS = 4


class ScheduleTests(unittest.TestCase):
    def test_a_seed_reproduces_its_schedule(self):
        for seed in (1, 17, 512):
            first_faults, first_env = build_schedule(seed)
            second_faults, second_env = build_schedule(seed)
            self.assertEqual([f.cell_id for f in first_faults], [f.cell_id for f in second_faults])
            self.assertEqual(first_env, second_env)

    def test_different_seeds_produce_different_schedules(self):
        schedules = {
            tuple(f.cell_id for f in build_schedule(seed)[0]) + tuple(sorted(build_schedule(seed)[1].items()))
            for seed in range(40)
        }
        self.assertGreater(len(schedules), 10)

    def test_schedules_stay_inside_the_declared_fault_vocabulary(self):
        for seed in range(80):
            faults, environment = build_schedule(seed, CAMPAIGN_MAX_FAULTS)
            for fault in faults:
                self.assertIn(fault.kind, FAULT_KINDS)
                self.assertIn(fault.point, FAULT_POINTS)
                self.assertNotIn(fault.kind, ENVIRONMENT_KINDS)
            for kind in environment.values():
                self.assertIn(kind, ENVIRONMENT_KINDS)

    def test_the_campaign_really_overlaps_several_faults_per_case(self):
        totals = [
            len(build_schedule(seed, CAMPAIGN_MAX_FAULTS)[0]) + len(build_schedule(seed, CAMPAIGN_MAX_FAULTS)[1])
            for seed in range(200)
        ]
        self.assertGreaterEqual(max(totals), 3)
        self.assertGreater(sum(1 for t in totals if t >= 2), 40)


class ComparisonScopeTests(unittest.TestCase):
    def test_the_compared_and_excluded_sets_partition_every_invariant(self):
        row = run_cell(Cell(transition_id="T01", kind="POST_WRITE_LOSS", point="post_journal_append"))
        self.assertEqual(
            set(row["invariants"]),
            set(SAFETY_INVARIANTS) | set(EXCLUDED_INVARIANTS),
        )
        self.assertEqual(set(), set(SAFETY_INVARIANTS) & set(EXCLUDED_INVARIANTS))

    def test_every_exclusion_states_why(self):
        for name, reason in EXCLUDED_INVARIANTS.items():
            self.assertTrue(reason.strip(), name)

    def test_no_false_completion_is_compared_as_a_safety_property(self):
        self.assertIn("I1_NO_FALSE_COMPLETION", SAFETY_INVARIANTS)


class CaseTests(unittest.TestCase):
    def test_a_fault_during_an_environment_action_does_not_escape_the_driver(self):
        """Recurrence test for M8.

        Seed 257 schedules a stale-lease handover on the step where a
        pre-journal-append loss is armed.  The handover is itself a durable
        write, so the crash used to escape the driver instead of being recovered
        like any other interrupted step.
        """
        row = run_case(257, max_faults=CAMPAIGN_MAX_FAULTS)
        self.assertEqual([], row["safety_violations"])
        self.assertEqual("COMPLETED", row["final_obzio_state"])
        self.assertEqual(["STALE_LEASE@step2"], row["scheduled_environment_faults"])

    def test_a_case_terminates_and_reports_its_own_budget(self):
        row = run_case(7, max_faults=CAMPAIGN_MAX_FAULTS)
        self.assertIn("safety_violations", row)
        self.assertLessEqual(row["distinct_external_effects"], 1)
        self.assertIsInstance(row["budget_exhausted"], bool)

    def test_a_case_replays_identically(self):
        volatile = {"steps", "resumes"}
        first = {k: v for k, v in run_case(99).items() if k not in volatile}
        second = {k: v for k, v in run_case(99).items() if k not in volatile}
        self.assertEqual(first, second)

    def test_a_hostile_schedule_never_reaches_a_false_completion(self):
        for seed in range(1, 41):
            with self.subTest(seed=seed):
                row = run_case(seed, max_faults=CAMPAIGN_MAX_FAULTS)
                self.assertNotIn("I1_NO_FALSE_COMPLETION", row["safety_violations"])
                self.assertLessEqual(row["distinct_external_effects"], 1)


class CampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.campaign = run_campaign(CAMPAIGN_CASES, max_faults=CAMPAIGN_MAX_FAULTS)

    def test_the_campaign_ran_the_cases_it_reports(self):
        self.assertEqual(CAMPAIGN_CASES, self.campaign["case_count"])
        self.assertEqual([1, CAMPAIGN_CASES], self.campaign["seed_range"])

    def test_at_most_one_durable_effect_across_the_whole_campaign(self):
        self.assertLessEqual(self.campaign["max_distinct_external_effects"], 1)

    def test_no_safety_invariant_is_violated_by_any_schedule(self):
        self.assertEqual({}, self.campaign["safety_violation_classes"])
        self.assertEqual(0, self.campaign["cases_with_safety_violations"])
        self.assertEqual([], self.campaign["failing_cases"])

    def test_no_schedule_ends_in_a_completion_it_did_not_earn(self):
        self.assertNotIn("PROVIDER_COMPLETED_UNCOMMITTED", self.campaign["final_state_histogram"])
        for state in self.campaign["final_state_histogram"]:
            self.assertIn(
                state,
                {"COMPLETED", "FAILED_TERMINAL", "RETRY_SCHEDULED", "RECOVERY_REQUIRED", "RESULT_COMMITTED"},
                state,
            )

    def test_fuzz_finds_no_class_the_matrix_missed(self):
        """The rejection itself: measured, not assumed.

        If a randomized schedule ever does find a safety class the exhaustive
        sweep misses, this assertion fails and M6 has to be revisited.
        """
        matrix_summary = {"violation_counts": {}, "cell_count": 101}
        comparison = compare_with_exhaustive(matrix_summary, self.campaign)
        self.assertEqual([], comparison["classes_found_only_by_fuzz"])
        self.assertFalse(comparison["fuzz_found_new_class"])
        self.assertEqual(CAMPAIGN_CASES, comparison["fuzz_cases"])

    def test_the_comparison_reports_a_class_the_matrix_did_not_have(self):
        """The comparison is capable of reporting a difference."""
        contrived = dict(self.campaign, safety_violation_classes={"I1_NO_FALSE_COMPLETION": 3})
        comparison = compare_with_exhaustive({"violation_counts": {}, "cell_count": 101}, contrived)
        self.assertEqual(["I1_NO_FALSE_COMPLETION"], comparison["classes_found_only_by_fuzz"])
        self.assertTrue(comparison["fuzz_found_new_class"])

    def test_a_class_the_matrix_already_covers_is_not_credited_to_fuzz(self):
        contrived = dict(self.campaign, safety_violation_classes={"I6_JOURNAL_INTEGRITY": 1})
        comparison = compare_with_exhaustive(
            {"violation_counts": {"I6_JOURNAL_INTEGRITY": 4}, "cell_count": 101}, contrived
        )
        self.assertEqual([], comparison["classes_found_only_by_fuzz"])


class InvariantWiringTests(unittest.TestCase):
    def test_the_fuzz_driver_evaluates_the_matrix_invariants_and_no_others(self):
        """The comparison is meaningless if the two drivers judge different things."""
        matrix_names = set(
            run_cell(Cell(transition_id="T01", kind="POST_WRITE_LOSS", point="post_journal_append"))["invariants"]
        )
        self.assertTrue(set(run_case(3)["all_violations"]) <= matrix_names)
        self.assertEqual(matrix_names, set(SAFETY_INVARIANTS) | set(EXCLUDED_INVARIANTS))


if __name__ == "__main__":
    unittest.main()
