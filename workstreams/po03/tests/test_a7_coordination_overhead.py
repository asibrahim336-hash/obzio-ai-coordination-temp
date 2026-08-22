"""Tests for a7-u05: coordination overhead is a computed ratio derived from
per-unit ledger timestamps, never an asserted intuition."""

import importlib.util
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
MODULE_PATH = Path(__file__).parents[1] / "metrics" / "coordination_overhead.py"
SPEC = importlib.util.spec_from_file_location("coordination_overhead", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

REPORT_PATH = REPO_ROOT / "workstreams/po03/metrics/coordination-overhead-report.json"
RUNS_PATH = REPO_ROOT / "workstreams/po03/metrics/work-unit-runs.jsonl"


class TestCoordinationOverhead(unittest.TestCase):
    def setUp(self):
        self.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    def test_per_unit_table_covers_every_unit_in_work_unit_runs(self):
        runs = [
            json.loads(line)
            for line in RUNS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        run_unit_ids = {r["unit_id"] for r in runs if r["record_type"] == "unit_run"}
        report_unit_ids = {r["unit_id"] for r in self.report["per_unit"]}
        self.assertEqual(run_unit_ids, report_unit_ids)

    def test_per_unit_rows_have_all_four_time_fields(self):
        for row in self.report["per_unit"]:
            for field in ("queue_time_seconds", "active_time_seconds", "wall_time_seconds", "review_time_seconds"):
                self.assertIn(field, row)

    def test_overhead_ratio_never_invents_a_value_with_zero_denominator(self):
        ratio = self.report["coordination_overhead_ratio"]
        if ratio["denominator_seconds"] == 0:
            self.assertEqual(ratio["value"], "UNDEFINED_0_OF_0")
        else:
            self.assertAlmostEqual(ratio["value"], ratio["numerator_seconds"] / ratio["denominator_seconds"])

    def test_overhead_numerator_equals_queue_plus_review_over_the_same_units(self):
        """Cross-check the aggregate numerator against an independent recomputation
        restricted to units that actually have a wall_time_seconds value."""
        runs = [
            json.loads(line)
            for line in RUNS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("record_type") == "unit_run"
        ]
        units_with_wall = [r for r in runs if r["wall_time_seconds"] is not None]
        expected_numerator = sum((r["queue_time_seconds"] or 0) + (r["review_time_seconds"] or 0) for r in units_with_wall)
        self.assertEqual(self.report["coordination_overhead_ratio"]["numerator_seconds"], expected_numerator)

    def test_recomputation_matches_committed_report(self):
        recomputed = MODULE.compute(REPO_ROOT)
        self.assertEqual(recomputed, self.report)

    def test_queue_time_summary_denominator_matches_units_with_a_value(self):
        runs = [
            json.loads(line)
            for line in RUNS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("record_type") == "unit_run"
        ]
        expected = sum(1 for r in runs if r["queue_time_seconds"] is not None)
        self.assertEqual(self.report["queue_time_summary"]["denominator_unit_count"], expected)


if __name__ == "__main__":
    unittest.main()
