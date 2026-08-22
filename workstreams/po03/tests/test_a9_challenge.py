from __future__ import annotations

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "workstreams/po03/strategy/challenge.py"
ARTIFACT_PATH = ROOT / "workstreams/po03/strategy/zero-base-challenge.json"

SPEC = importlib.util.spec_from_file_location("po03_a9_challenge", MODULE_PATH)
assert SPEC and SPEC.loader
challenge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(challenge)


class ZeroBaseChallengeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    def test_artifact_is_reproducible_from_current_committed_evidence(self) -> None:
        self.assertEqual(self.artifact, challenge.build_challenge(ROOT))
        for evidence in self.artifact["evidence"]:
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", evidence["path"]],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(tracked.returncode, 0, evidence["path"])
            self.assertEqual(
                evidence["sha256"],
                challenge.sha256_file(ROOT / evidence["path"]),
                evidence["path"],
            )

    def test_every_non_upheld_assumption_stays_a_nonbinding_proposal(self) -> None:
        self.assertEqual(self.artifact["decision_changed"], [])
        self.assertGreaterEqual(self.artifact["summary"]["undermined"], 1)
        for item in self.artifact["assumptions"]:
            if item["verdict"] == "UPHELD":
                self.assertIsNone(item["proposal"])
                continue
            self.assertIn(item["verdict"], {"UNDERMINED", "NOT_YET_SUPPORTED"})
            self.assertEqual(item["proposal"]["binding_state"], "PROPOSAL_ONLY")
            self.assertFalse(item["proposal"]["applied_to_active_wave"])
            self.assertEqual(item["proposal"]["decision_changed"], [])

    def test_challenges_are_executed_not_unreferenced_assertions(self) -> None:
        required = {
            "A-WAVE-SHAPE",
            "A-SINGLE-INTEGRATOR",
            "A-GIT-SINK",
            "A-HASHED-JSONL",
            "A-CRITERIA-BEHAVIOUR",
            "A-MODEL-MATCH",
            "A-SOURCE-CAPSULE-CLOSURE",
        }
        by_id = {item["assumption_id"]: item for item in self.artifact["assumptions"]}
        self.assertTrue(required.issubset(by_id))
        for item in by_id.values():
            self.assertTrue(item["test"]["method"])
            self.assertTrue(item["test"]["observations"])
            self.assertTrue(item["reason"])

    def test_actual_post_dispatch_source_drift_is_detected(self) -> None:
        item = next(
            assumption
            for assumption in self.artifact["assumptions"]
            if assumption["assumption_id"] == "A-SOURCE-CAPSULE-CLOSURE"
        )
        self.assertEqual(item["verdict"], "UNDERMINED")
        drift_paths = {row["path"] for row in item["test"]["observations"]["drift"]}
        self.assertEqual(
            drift_paths,
            {"workstreams/po03/control/path-ownership.json"},
        )

    def test_integrity_and_quadratic_work_are_distinguished(self) -> None:
        item = next(
            assumption
            for assumption in self.artifact["assumptions"]
            if assumption["assumption_id"] == "A-HASHED-JSONL"
        )
        observations = item["test"]["observations"]
        self.assertTrue(observations["chain_valid"])
        self.assertTrue(observations["append_verifies_full_history"])
        rows = observations["rows_verified"]
        self.assertEqual(
            observations["historical_prior_row_verifications_implied"],
            rows * (rows - 1) // 2,
        )


if __name__ == "__main__":
    unittest.main()
