"""Tests for a7-u04: token/cost telemetry is honestly probed and recorded as
NOT_SUPPORTED with the exact boundary, never estimated."""

import importlib.util
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
MODULE_PATH = Path(__file__).parents[1] / "metrics" / "probe_telemetry.py"
SPEC = importlib.util.spec_from_file_location("probe_telemetry", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

RESULT_PATH = REPO_ROOT / "workstreams/po03/metrics/telemetry-probe-result.json"


class TestProbeTelemetry(unittest.TestCase):
    def setUp(self):
        self.result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    def test_five_independent_probes_recorded(self):
        self.assertEqual(len(self.result["probes"]), 5)
        for probe in self.result["probes"]:
            self.assertIn("probe", probe)
            self.assertIn("result", probe)
            self.assertIn(probe["result"], {"POSITIVE", "NEGATIVE"})

    def test_overall_result_is_not_supported_given_current_runtime(self):
        """This assertion is about the runtime observed during this cohort's
        execution window, not a permanent claim; if a future runtime exposes
        telemetry, regenerating this artifact would flip this value honestly."""
        self.assertEqual(self.result["overall_result"], "NOT_SUPPORTED")

    def test_no_estimate_flag_is_asserted(self):
        self.assertTrue(self.result["no_estimate_asserted"])

    def test_metric_availability_table_uses_not_supported_when_negative(self):
        if self.result["overall_result"] == "NOT_SUPPORTED":
            for value in self.result["metric_availability_table"].values():
                self.assertEqual(value, "NOT_SUPPORTED")

    def test_observed_boundary_is_non_empty_prose(self):
        self.assertGreater(len(self.result["observed_boundary"]), 40)

    def test_environment_variable_probe_does_not_false_positive_on_fence_token(self):
        """Regression guard: an earlier version of this probe matched the bare
        substring 'token' and falsely flagged control_plane.py's fence_token
        field as token/cost telemetry evidence."""
        schema_probe = next(p for p in self.result["probes"] if p["probe"] == "dispatch_and_ledger_schema_inspection")
        self.assertNotIn("token", schema_probe["markers_searched"])
        self.assertEqual(schema_probe["result"], "NEGATIVE")

    def test_rerunning_the_probe_reproduces_the_same_structural_findings(self):
        rerun = MODULE.run_all_probes(REPO_ROOT)
        self.assertEqual(rerun["overall_result"], self.result["overall_result"])
        self.assertEqual(rerun["probes"], self.result["probes"])


if __name__ == "__main__":
    unittest.main()
