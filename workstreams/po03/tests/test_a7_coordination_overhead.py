"""Tests for a7-u05: coordination overhead is a computed ratio derived from
per-unit ledger timestamps, never an asserted intuition.

workstreams/po03/evidence/snapshot-coupling.json: reproduction is asserted
against the exact immutable commit this cohort's own tools last regenerated
work-unit-runs.jsonl and coordination-overhead-report.json in lock-step
(PIN_COMMIT), never against whatever work-unit-runs.jsonl happens to be live
on disk -- that file is itself ledger-derived and mutates as the wave
progresses, so a live-vs-committed comparison here is the same false-red
class as the two originally-flagged instances.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(REPO_ROOT / "workstreams/po03/metrics"))
from pin_support import materialize_commit_subset  # noqa: E402

MODULE_PATH = Path(__file__).parents[1] / "metrics" / "coordination_overhead.py"
SPEC = importlib.util.spec_from_file_location("coordination_overhead", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

REPORT_PATH = REPO_ROOT / "workstreams/po03/metrics/coordination-overhead-report.json"
RUNS_PATH = REPO_ROOT / "workstreams/po03/metrics/work-unit-runs.jsonl"

# Superseded 79453a7033d34cf7cfbbe3e64f4fab6ed1bbd34e (345-row ledger) once
# the coordinator's ledger grew again, to 418 rows, between sessions.
PIN_COMMIT = "e92e6a78d086628ceedda67b43e07ee33bdc0abf"
REQUIRED_RELATIVE_PATHS = ["workstreams/po03/metrics/work-unit-runs.jsonl"]


def _compute_at_pin(commit: str = PIN_COMMIT):
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        materialize_commit_subset(REPO_ROOT, commit, REQUIRED_RELATIVE_PATHS, dest)
        return MODULE.compute(dest)


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

    def test_recomputation_matches_committed_report_at_the_recorded_pin(self):
        recomputed = _compute_at_pin()
        self.assertEqual(recomputed, self.report)

    def test_pinned_reproduction_would_catch_a_mutated_report(self):
        recomputed = _compute_at_pin()
        mutated_report = json.loads(json.dumps(self.report))
        mutated_report["coordination_overhead_ratio"]["numerator_seconds"] += 1
        self.assertNotEqual(recomputed, mutated_report)

    def test_pinned_reproduction_would_catch_a_generator_regression(self):
        """Simulate a change to the ledger-timestamp math (not a corrupted
        input) by nudging every wall_time_seconds value after loading."""
        original_load_jsonl = MODULE.load_jsonl

        def tampered_loader(path):
            rows = original_load_jsonl(path)
            for row in rows:
                if row.get("record_type") == "unit_run" and row.get("wall_time_seconds") is not None:
                    row["wall_time_seconds"] = row["wall_time_seconds"] + 1
            return rows

        try:
            MODULE.load_jsonl = tampered_loader
            tampered = _compute_at_pin()
        finally:
            MODULE.load_jsonl = original_load_jsonl
        self.assertNotEqual(tampered, self.report)

    def test_pinned_reproduction_would_catch_the_wrong_pin(self):
        older = _compute_at_pin("dae059819d845c25dfc22ea7031c0988b07db23d")
        self.assertNotEqual(older["measured_against"]["ledger_rows"], self.report["measured_against"]["ledger_rows"])
        self.assertNotEqual(older, self.report)

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
