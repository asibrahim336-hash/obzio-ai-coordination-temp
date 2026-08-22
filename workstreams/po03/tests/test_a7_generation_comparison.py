"""Tests for workstreams/po03/metrics/generate_comparison.py.

generation-comparison.json is a required durable output owned by po03-worker-a7
(workstreams/po03/metrics/). The G0/G1/G2 measurements themselves are owned by
po03-worker-a8 on cursor/po03-a8-successor-generations-ed20; this cohort's job
is only to define the schema those measurements must land in and to compute
the comparison honestly from whatever has actually landed there, recording
NOT_YET -- never an invented score or PASS -- for anything that has not.
"""

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
MODULE_PATH = Path(__file__).parents[1] / "metrics" / "generate_comparison.py"
SPEC = importlib.util.spec_from_file_location("generate_comparison", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

REPORT_PATH = REPO_ROOT / "workstreams/po03/metrics/generation-comparison.json"

REPORTED_GEN = {
    "generation": "G1",
    "status": "REPORTED",
    "frozen_suite": {"total_cases": 10, "passed_cases": 8},
    "holdout": {"total_cases": 10, "passed_cases": 6},
}
NOT_YET_GEN = {"generation": "G2", "status": "NOT_YET", "boundary": "not reported"}


class TestGenerationComparison(unittest.TestCase):
    def setUp(self):
        self.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    def test_recomputation_matches_committed_report(self):
        recomputed = MODULE.compute(REPO_ROOT)
        self.assertEqual(recomputed, self.report)

    def test_schema_declares_the_expected_path_pattern_and_fields(self):
        schema = self.report["schema"]
        self.assertEqual(schema["expected_path_pattern"], "workstreams/po03/successor/<g0|g1|g2>/generation-result.json")
        for field in ("generation", "executable", "frozen_suite.total_cases", "holdout.total_cases"):
            self.assertIn(field, schema["expected_fields"])

    def test_all_three_generations_present_with_a_status_and_expected_path(self):
        for gen in ("G0", "G1", "G2"):
            entry = self.report["generations"][gen]
            self.assertEqual(entry["generation"], gen)
            self.assertIn(entry["status"], ("REPORTED", "NOT_YET"))
            self.assertTrue(entry["expected_path"].startswith("workstreams/po03/successor/"))

    def test_branch_absence_is_recorded_honestly_for_the_current_runtime(self):
        """Cross-check against a direct, independent git ls-remote call: this
        assertion is about the runtime observed when this cohort last measured,
        not an assumption about the future. If po03-worker-a8 has since pushed
        cursor/po03-a8-successor-generations-ed20, this test's premise -- and
        the committed report -- must be regenerated, not silently reinterpreted."""
        proc = subprocess.run(
            ["git", "ls-remote", "--exit-code", "origin", "refs/heads/cursor/po03-a8-successor-generations-ed20"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        branch_exists_on_origin = proc.returncode == 0 and bool(proc.stdout.strip())
        if not branch_exists_on_origin:
            for gen in ("G0", "G1", "G2"):
                self.assertEqual(self.report["generations"][gen]["status"], "NOT_YET")
                self.assertTrue(self.report["generations"][gen]["boundary"])
            self.assertEqual(self.report["overall_result"], "NOT_YET")

    def test_never_reports_overall_pass_without_all_three_generations_reported(self):
        for gen_key, gen in self.report["generations"].items():
            if gen["status"] != "REPORTED":
                self.assertNotEqual(self.report["overall_result"], "PASS")
                break

    def test_score_of_requires_well_formed_integer_counts(self):
        self.assertEqual(MODULE.score_of({"total_cases": 10, "passed_cases": 5}), 0.5)
        self.assertIsNone(MODULE.score_of(None))
        self.assertIsNone(MODULE.score_of({}))
        self.assertIsNone(MODULE.score_of({"total_cases": 0, "passed_cases": 0}))
        self.assertIsNone(MODULE.score_of({"total_cases": "10", "passed_cases": 5}))

    def test_compare_pair_is_not_yet_when_either_side_unreported(self):
        result = MODULE.compare_pair(NOT_YET_GEN, REPORTED_GEN)
        self.assertEqual(result["value"], "NOT_YET")
        self.assertIn("boundary", result)
        result2 = MODULE.compare_pair(REPORTED_GEN, NOT_YET_GEN)
        self.assertEqual(result2["value"], "NOT_YET")

    def test_compare_pair_flags_any_regression_as_fail_never_pass(self):
        later = {
            "generation": "G2",
            "status": "REPORTED",
            "frozen_suite": {"total_cases": 10, "passed_cases": 7},  # worse than earlier's 8
            "holdout": {"total_cases": 10, "passed_cases": 7},  # better than earlier's 6
        }
        result = MODULE.compare_pair(later, REPORTED_GEN)
        self.assertEqual(result["value"], "FAIL")
        self.assertTrue(result["regression_detected"])

    def test_compare_pair_pass_requires_a_strictly_positive_delta_on_both_axes(self):
        later_flat_holdout = {
            "generation": "G2",
            "status": "REPORTED",
            "frozen_suite": {"total_cases": 10, "passed_cases": 9},  # improves
            "holdout": {"total_cases": 10, "passed_cases": 6},  # unchanged, not an improvement
        }
        result = MODULE.compare_pair(later_flat_holdout, REPORTED_GEN)
        self.assertEqual(result["value"], "FAIL")
        self.assertFalse(result["regression_detected"])

        later_improves_both = {
            "generation": "G2",
            "status": "REPORTED",
            "frozen_suite": {"total_cases": 10, "passed_cases": 9},
            "holdout": {"total_cases": 10, "passed_cases": 7},
        }
        result2 = MODULE.compare_pair(later_improves_both, REPORTED_GEN)
        self.assertEqual(result2["value"], "PASS")
        self.assertFalse(result2["regression_detected"])

    def test_lift_metric_is_preregistered_in_the_output_before_any_value(self):
        formula = self.report["preregistered_lift_metric"]["formula"]
        self.assertIn("score(later) - score(earlier)", formula)
        self.assertIn("no_regression_rule", self.report["preregistered_lift_metric"])

    def test_measured_against_records_the_exact_resolution_attempt(self):
        measured = self.report["measured_against"]
        self.assertEqual(measured["successor_remote_ref"], "origin/cursor/po03-a8-successor-generations-ed20")
        if measured["successor_commit_sha"] is None:
            self.assertTrue(measured["resolution_boundary"])


if __name__ == "__main__":
    unittest.main()
