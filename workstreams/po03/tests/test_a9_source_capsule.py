from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "workstreams/po03/strategy/source_capsule.py"
REPORT_PATH = ROOT / "workstreams/po03/strategy/source-capsule-report.json"

SPEC = importlib.util.spec_from_file_location("po03_a9_source_capsule", MODULE_PATH)
assert SPEC and SPEC.loader
capsule = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capsule)


class SourceCapsuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    def test_report_reproduces_from_immutable_dispatches(self) -> None:
        self.assertEqual(self.report, capsule.build_report(ROOT))
        self.assertEqual(self.report["decision_changed"], [])
        self.assertFalse(self.report["strategy_restarted"])

    def test_intact_dispatch_can_still_resolve_drifted_source_bytes(self) -> None:
        self.assertEqual(self.report["aggregate_state"], "DRIFTED")
        self.assertEqual(self.report["summary"]["dispatches_checked"], 4)
        self.assertEqual(self.report["summary"]["intact_dispatch_manifests"], 4)
        self.assertEqual(self.report["summary"]["intact_acceptance_contracts"], 4)
        for dispatch in self.report["dispatches"]:
            self.assertEqual(dispatch["immutable_manifest"]["state"], "CURRENT")
            self.assertEqual(dispatch["acceptance_contract"]["state"], "CURRENT")
            self.assertEqual(dispatch["capsule_state"], "DRIFTED")

    def test_current_post_dispatch_change_is_reported_for_every_unit(self) -> None:
        expected_path = "workstreams/po03/control/path-ownership.json"
        self.assertEqual(
            self.report["summary"]["unique_drifted_paths"],
            [expected_path],
        )
        self.assertEqual(self.report["summary"]["drifted_source_references"], 4)
        for dispatch in self.report["dispatches"]:
            drift = [row for row in dispatch["sources"] if row["state"] == "DRIFTED"]
            self.assertEqual([row["path"] for row in drift], [expected_path])
            self.assertNotEqual(drift[0]["expected_sha256"], drift[0]["observed_sha256"])

    def test_mechanism_probe_exposes_the_missing_closure_gate(self) -> None:
        probe = self.report["current_mechanism_probe"]
        self.assertTrue(probe["ingest_compares_dispatch_manifest_reference"])
        self.assertFalse(probe["ingest_rehashes_dispatch_sources"])
        self.assertFalse(probe["result_emitter_rehashes_dispatch_sources"])
        self.assertEqual(
            self.report["operating_disposition"]["state"],
            "IMPLEMENTED_AND_TESTED",
        )

    def test_verifier_distinguishes_current_drifted_and_missing_without_writes(self) -> None:
        commission = "workstreams/po03/COMMISSION.md"
        actual = capsule.sha256_file(ROOT / commission)
        current = capsule.verify_source_hashes(ROOT, {commission: actual})
        drifted = capsule.verify_source_hashes(ROOT, {commission: "0" * 64})
        missing = capsule.verify_source_hashes(
            ROOT, {"workstreams/po03/does-not-exist": "0" * 64}
        )
        self.assertEqual(current[0]["state"], "CURRENT")
        self.assertEqual(drifted[0]["state"], "DRIFTED")
        self.assertEqual(missing[0]["state"], "MISSING")

    def test_strict_mode_blocks_nonclosed_capsule(self) -> None:
        self.assertEqual(capsule.strict_exit_code(self.report), 3)
        current = dict(self.report)
        current["aggregate_state"] = "CURRENT"
        self.assertEqual(capsule.strict_exit_code(current), 0)


if __name__ == "__main__":
    unittest.main()
