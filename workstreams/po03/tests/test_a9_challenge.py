from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "workstreams/po03/strategy/challenge.py"
SNAPSHOT_MODULE_PATH = ROOT / "workstreams/po03/strategy/snapshot_fixture.py"
ARTIFACT_PATH = ROOT / "workstreams/po03/strategy/zero-base-challenge.json"
SNAPSHOT_COMMIT = "c83da05eccf7331ed20ef3819c58b146addb5156"

SPEC = importlib.util.spec_from_file_location("po03_a9_challenge", MODULE_PATH)
assert SPEC and SPEC.loader
challenge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(challenge)

SNAPSHOT_SPEC = importlib.util.spec_from_file_location(
    "po03_a9_challenge_snapshot", SNAPSHOT_MODULE_PATH
)
assert SNAPSHOT_SPEC and SNAPSHOT_SPEC.loader
snapshot = importlib.util.module_from_spec(SNAPSHOT_SPEC)
SNAPSHOT_SPEC.loader.exec_module(snapshot)


class ZeroBaseChallengeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    def test_artifact_reproduces_from_pinned_committed_evidence(self) -> None:
        with snapshot.materialize_commit(ROOT, SNAPSHOT_COMMIT) as snapshot_root:
            recorded = json.loads(
                (snapshot_root / ARTIFACT_PATH.relative_to(ROOT)).read_text(
                    encoding="utf-8"
                )
            )
            rebuilt = challenge.build_challenge(snapshot_root)
            self.assertEqual(self.artifact, recorded)
            self.assertEqual(self.artifact, rebuilt)
            for evidence in self.artifact["evidence"]:
                pinned_path = snapshot_root / evidence["path"]
                self.assertTrue(pinned_path.is_file(), evidence["path"])
                self.assertEqual(
                    evidence["sha256"],
                    challenge.sha256_file(pinned_path),
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

    def test_pinned_post_dispatch_source_drift_is_detected(self) -> None:
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
