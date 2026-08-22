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

REPORTED_SUITE = {
    "status": "REPORTED",
    "scores": {
        "cases_passed": 8,
        "cases_total": 10,
        "pass_rate": 0.8,
        "critical_pass_rate": 0.5,
        "false_completion_count": 2,
        "unsupported_case_count": 0,
    },
}
NOT_YET_SUITE = {"status": "NOT_YET", "scores": None, "boundary": "not reported"}


class TestGenerationComparison(unittest.TestCase):
    def setUp(self):
        self.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    def test_recomputation_matches_committed_report(self):
        recomputed = MODULE.compute(REPO_ROOT)
        self.assertEqual(recomputed, self.report)

    def test_schema_declares_the_expected_path_pattern(self):
        schema = self.report["schema"]
        self.assertEqual(
            schema["expected_path_pattern"],
            "workstreams/po03/successor/transcripts/<g0|g1|g2>-<public|holdout>.txt",
        )

    def test_all_three_generations_present_with_public_and_holdout_suites(self):
        for gen in ("G0", "G1", "G2"):
            entry = self.report["generations"][gen]
            self.assertEqual(entry["generation"], gen)
            self.assertIn(entry["status"], ("REPORTED", "NOT_YET"))
            for suite in ("public", "holdout"):
                suite_entry = entry["suites"][suite]
                self.assertIn(suite_entry["status"], ("REPORTED", "NOT_YET"))
                self.assertTrue(suite_entry["expected_path"].endswith(f"{suite}.txt"))

    def test_summary_line_regex_extracts_the_observed_g0_public_transcript_fields(self):
        """Regression guard against the real, committed transcript shape: this
        is not a synthetic fixture, it is copied from
        workstreams/po03/successor/transcripts/g0-public.txt as landed by a8-u01."""
        line = "[public] 3/31 passed rate=0.0968 critical=0.0 false_completions=3 unsupported_cases=24"
        scores, boundary = MODULE.parse_summary(line, "public")
        self.assertEqual(boundary, "")
        self.assertEqual(scores["cases_passed"], 3)
        self.assertEqual(scores["cases_total"], 31)
        self.assertEqual(scores["pass_rate"], 0.0968)
        self.assertEqual(scores["critical_pass_rate"], 0.0)
        self.assertEqual(scores["false_completion_count"], 3)
        self.assertEqual(scores["unsupported_case_count"], 24)

    def test_summary_line_regex_ignores_the_wrong_suite_tag(self):
        line = "[holdout] 5/5 passed rate=1.0 critical=1.0 false_completions=0 unsupported_cases=0"
        scores, boundary = MODULE.parse_summary(line, "public")
        self.assertIsNone(scores)
        self.assertTrue(boundary)

    def test_never_reports_overall_pass_without_all_three_generations_reported(self):
        for gen_key, gen in self.report["generations"].items():
            if gen["status"] != "REPORTED":
                self.assertNotEqual(self.report["overall_result"], "PASS")
                break

    def test_compare_suite_is_not_yet_when_either_side_unreported(self):
        result = MODULE.compare_suite(NOT_YET_SUITE, REPORTED_SUITE)
        self.assertEqual(result["value"], "NOT_YET")
        result2 = MODULE.compare_suite(REPORTED_SUITE, NOT_YET_SUITE)
        self.assertEqual(result2["value"], "NOT_YET")

    def test_compare_suite_flags_increased_false_completions_as_regression(self):
        later = {
            "status": "REPORTED",
            "scores": dict(REPORTED_SUITE["scores"], pass_rate=0.9, false_completion_count=3),
        }
        result = MODULE.compare_suite(later, REPORTED_SUITE)
        self.assertEqual(result["value"], "FAIL")
        self.assertTrue(result["regression_detected"])

    def test_compare_suite_flags_decreased_critical_pass_rate_as_regression(self):
        later = {
            "status": "REPORTED",
            "scores": dict(REPORTED_SUITE["scores"], pass_rate=0.9, critical_pass_rate=0.4),
        }
        result = MODULE.compare_suite(later, REPORTED_SUITE)
        self.assertEqual(result["value"], "FAIL")
        self.assertTrue(result["regression_detected"])

    def test_compare_suite_passes_only_with_strict_pass_rate_improvement_and_no_regression(self):
        later = {
            "status": "REPORTED",
            "scores": dict(REPORTED_SUITE["scores"], pass_rate=0.9, critical_pass_rate=0.5, false_completion_count=2),
        }
        result = MODULE.compare_suite(later, REPORTED_SUITE)
        self.assertEqual(result["value"], "PASS")
        self.assertFalse(result["regression_detected"])
        self.assertIn("L1-minimum-lift (no preregistration document with lift_rule.minimum_lift has landed)", result["not_evaluated"])

    def test_compare_suite_never_hides_that_it_checks_less_than_a8s_full_rule(self):
        later = {
            "status": "REPORTED",
            "scores": dict(REPORTED_SUITE["scores"], pass_rate=0.9),
        }
        result = MODULE.compare_suite(later, REPORTED_SUITE)
        self.assertEqual(len(result["not_evaluated"]), 2)

    def test_g1_vs_g0_public_lift_matches_the_landed_transcripts_when_both_report(self):
        """Cross-check against the real committed data as of this measurement:
        this assertion documents the runtime observation, not a fixed truth
        that must hold if a8 amends its transcripts later."""
        g0_public = self.report["generations"]["G0"]["suites"]["public"]
        g1_public = self.report["generations"]["G1"]["suites"]["public"]
        if g0_public["status"] == "REPORTED" and g1_public["status"] == "REPORTED":
            lift = self.report["lift"]["g1_vs_g0"]["public"]
            expected_delta = g1_public["scores"]["pass_rate"] - g0_public["scores"]["pass_rate"]
            self.assertAlmostEqual(lift["pass_rate_delta"], expected_delta)

    def test_measured_against_records_the_exact_resolution_attempt(self):
        measured = self.report["measured_against"]
        self.assertEqual(measured["successor_remote_ref"], "origin/cursor/po03-a8-successor-generations-ed20")
        if measured["successor_commit_sha"] is None:
            self.assertTrue(measured["resolution_boundary"])

    def test_lift_metric_names_its_authoritative_source_and_its_own_narrower_check(self):
        prereg = self.report["preregistered_lift_metric"]
        self.assertIn("harness/score.py:compare()", prereg["authoritative_source"])
        self.assertIn("pass_rate_delta > 0", prereg["this_tool_checks"])


if __name__ == "__main__":
    unittest.main()
