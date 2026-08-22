from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


UNIT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[6]
SCANNER_PATH = UNIT_ROOT / "scanner" / "opportunity_scanner.py"
FIXTURE_PATH = UNIT_ROOT / "scanner" / "scoring-fixture.json"
SPEC = importlib.util.spec_from_file_location("wa021_opportunity_scanner", SCANNER_PATH)
SCANNER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SCANNER)


class FrozenScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_weights_sum_to_one_hundred(self) -> None:
        weights = self.fixture["scoring"]["weights"]
        self.assertEqual(100, sum(weights.values()))
        self.assertEqual(SCANNER.SCORE_WEIGHTS, weights)

    def test_threshold_and_population_breaks_are_frozen(self) -> None:
        self.assertEqual(55, self.fixture["scoring"]["eligibility_threshold"])
        self.assertEqual([1, 2, 4, 8, 16], [
            item["minimum"] for item in self.fixture["scoring"]["population_thresholds"]
        ])

    def test_scaled_points_obey_frozen_breaks(self) -> None:
        self.assertEqual([0, 5, 10, 15, 20, 25], [
            SCANNER.scaled_points(count, 25) for count in (0, 1, 2, 4, 8, 16)
        ])

    def test_fixture_contains_explicit_adversarial_controls(self) -> None:
        ids = {item["candidate_id"] for item in self.fixture["candidates"]}
        self.assertIn("OP-WA021-90-CIRCULAR-SCANNER-CONFIRMATION", ids)
        self.assertIn("OP-WA021-91-UNSUPPORTED-PRODUCTION-FAILURES", ids)

    def test_fixture_source_is_exact_controller_base(self) -> None:
        self.assertEqual(
            "22af3833bd25e2fa1b4e91111c045907e9534119",
            self.fixture["source_base"],
        )


class LiveImmutableSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = SCANNER.scan(REPO_ROOT, FIXTURE_PATH)

    def test_exact_parent_hypothesis_is_tested(self) -> None:
        self.assertEqual("H-PO03-WA-021", self.report["hypothesis_id"])
        self.assertEqual(
            "Repository evidence can identify useful unnamed work by scoring recurring defects, missing recurrence tests, and high-leverage gaps.",
            self.report["falsifiable_hypothesis"],
        )
        self.assertEqual("SUPPORTED", self.report["hypothesis_outcome"])

    def test_unit_test_discovery_gap_is_top_ranked(self) -> None:
        top = self.report["ranked_opportunities"][0]
        self.assertEqual("OP-WA021-01-UNIT-SUITES-OUTSIDE-CI", top["candidate_id"])
        self.assertEqual(1, top["rank"])
        self.assertEqual(100, top["score"])
        self.assertGreaterEqual(top["measurements"]["recurrence_count"], 16)
        self.assertTrue(top["measurements"]["missing_recurrence_test"])

    def test_runtime_attestation_gap_is_eligible(self) -> None:
        by_id = {
            item["candidate_id"]: item for item in self.report["ranked_opportunities"]
        }
        candidate = by_id["OP-WA021-02-RUNTIME-ATTESTATION-CONTRACT"]
        self.assertGreaterEqual(candidate["score"], 55)
        self.assertGreaterEqual(candidate["measurements"]["recurrence_count"], 4)
        self.assertTrue(candidate["measurements"]["missing_recurrence_test"])

    def test_named_provenance_work_is_rejected(self) -> None:
        by_id = {
            item["candidate_id"]: item for item in self.report["rejected_candidates"]
        }
        candidate = by_id["OP-WA021-03-PROVENANCE-OBJECT-GUARD"]
        self.assertIn("ALREADY_NAMED_WORK", candidate["rejection_reasons"])
        self.assertGreaterEqual(candidate["measurements"]["recurrence_count"], 2)

    def test_circular_candidate_is_rejected(self) -> None:
        by_id = {
            item["candidate_id"]: item for item in self.report["rejected_candidates"]
        }
        self.assertIn(
            "CIRCULAR_EVIDENCE",
            by_id["OP-WA021-90-CIRCULAR-SCANNER-CONFIRMATION"]["rejection_reasons"],
        )

    def test_unsupported_candidate_is_rejected(self) -> None:
        by_id = {
            item["candidate_id"]: item for item in self.report["rejected_candidates"]
        }
        self.assertIn(
            "UNSUPPORTED_REQUIRED_EVIDENCE_FAILED",
            by_id["OP-WA021-91-UNSUPPORTED-PRODUCTION-FAILURES"]["rejection_reasons"],
        )

    def test_evidence_is_pinned_and_non_circular(self) -> None:
        for claim in self.report["source_claims"]:
            self.assertEqual(self.report["source_base"], claim["source_commit"])
            for source in claim["sources"]:
                self.assertFalse(source["path"].startswith(SCANNER.OWNED_PREFIX))
                self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")
                self.assertGreater(source["bytes"], 0)

    def test_separate_registers_are_declared(self) -> None:
        self.assertEqual(
            {
                "source_claims",
                "hypotheses",
                "reproduction",
                "mechanism_changes",
                "strategy_proposals",
            },
            set(self.report["separation"]),
        )

    def test_same_fixture_and_commit_are_byte_deterministic(self) -> None:
        first = SCANNER.canonical_json_bytes(self.report)
        second = SCANNER.canonical_json_bytes(SCANNER.scan(REPO_ROOT, FIXTURE_PATH))
        self.assertEqual(first, second)

    def test_nonexistent_source_base_fails_closed(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        fixture["source_base"] = "f" * 40
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            path.write_text(json.dumps(fixture), encoding="utf-8")
            with self.assertRaises(SCANNER.ScannerError):
                SCANNER.scan(REPO_ROOT, path)

    def test_cli_writes_ranked_machine_readable_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "ranked.json"
            process = subprocess.run(
                [
                    "python3",
                    "-B",
                    str(SCANNER_PATH),
                    "--repo",
                    str(REPO_ROOT),
                    "--fixture",
                    str(FIXTURE_PATH),
                    "--output",
                    str(output),
                    "--check-determinism",
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, process.returncode, process.stderr)
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("PO03-OPPORTUNITY-SCANNER-v1", document["protocol_version"])
            self.assertGreaterEqual(document["summary"]["eligible_count"], 1)


if __name__ == "__main__":
    unittest.main()
