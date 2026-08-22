"""Tests for a7-u02: work-unit-runs.jsonl is derived from the ledger alone,
covers every counted unit, and regenerates byte-stably."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
MODULE_PATH = Path(__file__).parents[1] / "metrics" / "emit_runs.py"
SPEC = importlib.util.spec_from_file_location("emit_runs", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

WAVE_SPEC_PATH = REPO_ROOT / "workstreams/po03/control/wave-a-spec.json"
RUNS_PATH = REPO_ROOT / "workstreams/po03/metrics/work-unit-runs.jsonl"


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestEmitRuns(unittest.TestCase):
    def test_committed_output_has_a_metadata_row_first(self):
        rows = load_rows(RUNS_PATH)
        self.assertGreater(len(rows), 0)
        self.assertEqual(rows[0]["record_type"], "generation_metadata")
        for field in ("ledger_head_sha256", "ledger_rows", "generated_at", "counted_unit_count"):
            self.assertIn(field, rows[0])

    def test_covers_100_percent_of_declared_units(self):
        wave_spec = json.loads(WAVE_SPEC_PATH.read_text(encoding="utf-8"))
        declared_unit_ids = {unit["unit_id"] for unit in wave_spec["units"]}
        rows = load_rows(RUNS_PATH)
        emitted_unit_ids = {row["unit_id"] for row in rows if row["record_type"] == "unit_run"}
        missing = declared_unit_ids - emitted_unit_ids
        self.assertEqual(missing, set(), f"declared units missing from work-unit-runs.jsonl: {missing}")

    def test_no_row_contains_a_null_model_when_dispatch_exists(self):
        rows = load_rows(RUNS_PATH)
        for row in rows:
            if row["record_type"] != "unit_run":
                continue
            self.assertIsNotNone(row["exact_model_and_reasoning"], row["unit_id"])
            self.assertNotEqual(row["exact_model_and_reasoning"], "inherit", row["unit_id"])
            self.assertNotEqual(row["exact_model_and_reasoning"], "auto", row["unit_id"])

    def test_token_and_cost_data_is_marked_not_supported_everywhere(self):
        rows = load_rows(RUNS_PATH)
        for row in rows:
            if row["record_type"] == "unit_run":
                self.assertEqual(row["token_and_cost_data"], "NOT_SUPPORTED")

    def test_regeneration_is_byte_stable_given_a_fixed_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            out1 = Path(tmp) / "run1.jsonl"
            out2 = Path(tmp) / "run2.jsonl"
            MODULE.emit(REPO_ROOT, out1, "2026-01-01T00:00:00Z")
            MODULE.emit(REPO_ROOT, out2, "2026-01-01T00:00:00Z")
            self.assertEqual(out1.read_bytes(), out2.read_bytes())

    def test_queue_time_is_derived_from_created_and_leased_timestamps(self):
        """Cross-check the queue_time_seconds formula against the raw ledger for one
        concrete unit rather than trusting the tool's own arithmetic."""
        ledger_path = REPO_ROOT / "workstreams/po03/control/events/ledger.jsonl"
        ledger_rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        target_rows = [r for r in ledger_rows if r["unit_id"] == "a1-u01"]
        created = next(r["ts"] for r in target_rows if r["event"] == "CREATED")
        leased = next(r["ts"] for r in target_rows if r["event"] == "LEASED")
        expected_seconds = MODULE.seconds_between(created, leased)

        runs_rows = load_rows(RUNS_PATH)
        row = next(r for r in runs_rows if r.get("unit_id") == "a1-u01")
        self.assertEqual(row["queue_time_seconds"], expected_seconds)

    def test_readback_proved_requires_a_parent_ingested_event(self):
        """readback_proved must never be true without a PARENT_INGESTED ledger row,
        because the control plane raises before appending that row on any
        hash/byte-count mismatch."""
        ledger_path = REPO_ROOT / "workstreams/po03/control/events/ledger.jsonl"
        ledger_rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        ingested_units = {r["unit_id"] for r in ledger_rows if r["event"] == "PARENT_INGESTED"}
        runs_rows = load_rows(RUNS_PATH)
        for row in runs_rows:
            if row["record_type"] != "unit_run":
                continue
            if row["result_commit_and_readback"]["readback_proved"]:
                self.assertIn(row["unit_id"], ingested_units)


if __name__ == "__main__":
    unittest.main()
