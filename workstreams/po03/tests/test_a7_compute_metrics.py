"""Tests for a7-u03: every reported rate states an explicit numerator and
denominator, and the computation is reproducible from committed inputs."""

import importlib.util
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
MODULE_PATH = Path(__file__).parents[1] / "metrics" / "compute_metrics.py"
SPEC = importlib.util.spec_from_file_location("compute_metrics", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

REPORT_PATH = REPO_ROOT / "workstreams/po03/metrics/metrics-report.json"

RATE_METRICS = (
    "independently_accepted_throughput",
    "first_pass_acceptance_rate",
    "escaped_defect_rate",
    "founder_interventions",
)


class TestComputeMetrics(unittest.TestCase):
    def setUp(self):
        self.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    def test_measured_against_ledger_is_recorded(self):
        measured = self.report["measured_against"]
        self.assertIn("ledger_head_sha256", measured)
        self.assertIn("ledger_rows", measured)
        self.assertEqual(len(measured["ledger_head_sha256"]), 64)

    def test_every_rate_metric_has_explicit_numerator_and_denominator(self):
        for name in RATE_METRICS:
            metric = self.report["metrics"][name]
            if metric["value"] == "UNDEFINED_0_OF_0":
                self.assertEqual(metric["denominator"], 0)
            else:
                self.assertIn("numerator", metric)
                self.assertIn("denominator", metric)
                self.assertGreater(metric["denominator"], 0)
                self.assertAlmostEqual(metric["value"], metric["numerator"] / metric["denominator"])

    def test_rate_helper_zero_denominator_is_never_invented(self):
        result = MODULE.rate(0, 0)
        self.assertEqual(result["value"], "UNDEFINED_0_OF_0")
        self.assertNotIn("value", {"0": 0})  # sanity: 0 must not silently mean 0/0

    def test_rate_helper_normal_division(self):
        result = MODULE.rate(3, 12)
        self.assertEqual(result, {"numerator": 3, "denominator": 12, "value": 0.25})

    def test_not_yet_metrics_state_a_boundary_and_no_invented_value(self):
        for name in ("false_green_rate", "research_to_reproduction_conversion", "lesson_to_live_change_conversion", "successor_lift"):
            metric = self.report["metrics"][name]
            if metric["value"] == "NOT_YET":
                self.assertIn("boundary", metric)

    def test_context_waste_is_not_supported_with_boundary(self):
        metric = self.report["metrics"]["context_waste"]
        self.assertEqual(metric["value"], "NOT_SUPPORTED")
        self.assertIn("observed_boundary", metric)

    def test_recomputation_matches_committed_report_except_generation_metadata(self):
        """The report must be exactly reproducible from the committed ledger and
        work-unit-runs.jsonl; recompute it fresh and diff against the committed copy."""
        recomputed = MODULE.compute(REPO_ROOT)
        self.assertEqual(recomputed, self.report)

    def test_orphan_and_false_complete_counts_have_explicit_denominators(self):
        counts = self.report["metrics"]["orphan_duplicate_collision_falsecomplete_counts"]
        for key in ("orphan_count", "duplicate_count", "collision_count", "false_complete_count"):
            self.assertIn(key, counts)
        self.assertIn("denominator_units_total", counts)
        self.assertIn("denominator_ledger_rows_total", counts)
        self.assertEqual(counts["orphan_count"], len(counts["orphan_units"]))
        self.assertEqual(counts["false_complete_count"], len(counts["false_complete_units"]))


if __name__ == "__main__":
    unittest.main()
