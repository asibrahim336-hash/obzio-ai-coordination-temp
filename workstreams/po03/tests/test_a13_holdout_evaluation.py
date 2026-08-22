"""Recompute the durable a13 holdout score claims from final transcripts."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HOLDOUT = ROOT / "workstreams" / "po03" / "holdout"
EVALUATION = HOLDOUT / "evaluation"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class A13HoldoutEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scores = read_json(EVALUATION / "holdout-scores.json")
        cls.blinding = read_json(EVALUATION / "blinding-map.json")
        cls.novelty = read_json(EVALUATION / "novelty-audit.json")
        cls.gaps = read_json(EVALUATION / "public-vs-holdout-gap.json")
        cls.transcripts = {
            generation: read_json(ROOT / record["transcript"])
            for generation, record in cls.scores["scores"].items()
        }

    def test_transcript_hashes_and_score_summaries_match(self) -> None:
        for generation, record in self.scores["scores"].items():
            transcript_path = ROOT / record["transcript"]
            transcript = self.transcripts[generation]
            summary = transcript["summary"]
            with self.subTest(generation=generation):
                self.assertEqual(record["transcript_sha256"], sha256(transcript_path))
                self.assertEqual(record["cases_passed"], summary["passed_cases"])
                self.assertEqual(record["cases_total"], summary["total_cases"])
                self.assertEqual(record["pass_rate"], summary["pass_rate"])
                self.assertEqual(record["critical_passed"], summary["passed_critical"])
                self.assertEqual(record["critical_total"], summary["total_critical"])
                self.assertEqual(
                    record["critical_pass_rate"], summary["critical_pass_rate"]
                )
                self.assertEqual(
                    record["unsupported_case_count"], len(summary["unsupported"])
                )

    def test_every_generation_received_identical_requests(self) -> None:
        expected = None
        for generation, transcript in self.transcripts.items():
            request_set = [
                (case["case_id"], case["request_sha256"], case["request_bytes"])
                for case in transcript["cases"]
            ]
            if expected is None:
                expected = request_set
            with self.subTest(generation=generation):
                self.assertEqual(expected, request_set)
        self.assertEqual(32, len(expected))

    def test_exact_unsupported_boundaries_are_not_omitted(self) -> None:
        for generation, record in self.scores["scores"].items():
            transcript = self.transcripts[generation]
            observed = {
                case["case_id"]: case["boundary"]
                for case in transcript["cases"]
                if case["status"] == "NOT_SUPPORTED"
            }
            with self.subTest(generation=generation):
                self.assertEqual(record["unsupported"], observed)
                self.assertTrue(all(observed.values()))

    def test_scorer_transcripts_do_not_reveal_generation_identity(self) -> None:
        expected_labels = {
            generation: record["blinded_label"]
            for generation, record in self.scores["scores"].items()
        }
        for generation, transcript in self.transcripts.items():
            serialized = json.dumps(transcript, sort_keys=True)
            with self.subTest(generation=generation):
                self.assertEqual(
                    expected_labels[generation], transcript["candidate_label"]
                )
                self.assertNotIn('"G0"', serialized)
                self.assertNotIn('"G1"', serialized)
                self.assertNotIn('"G2"', serialized)

    def test_blinding_map_is_disclosed_only_in_separate_evidence(self) -> None:
        self.assertEqual(
            {"BLINDED-4F7": "G1", "BLINDED-9A2": "G0", "BLINDED-C31": "G2"},
            self.blinding["slots"],
        )
        self.assertTrue(self.blinding["generation_identity_withheld_from_scorer"])

    def test_case_outcome_sets_recompute(self) -> None:
        for generation, record in self.scores["scores"].items():
            transcript = self.transcripts[generation]
            passed = [
                case["case_id"] for case in transcript["cases"] if case["status"] == "PASS"
            ]
            failed = [
                case["case_id"] for case in transcript["cases"] if case["status"] == "FAIL"
            ]
            with self.subTest(generation=generation):
                self.assertEqual(record["passed_cases"], passed)
                self.assertEqual(record["failed_executed_cases"], failed)

    def test_measured_g2_holdout_lift_and_no_per_case_regression(self) -> None:
        g1 = self.scores["scores"]["G1"]
        g2 = self.scores["scores"]["G2"]
        self.assertEqual(0.21875, g2["pass_rate"] - g1["pass_rate"])
        self.assertGreaterEqual(g2["pass_rate"] - g1["pass_rate"], 0.1)
        self.assertEqual([], self.scores["comparisons"]["G1_to_G2_passed_case_regressions"])
        self.assertTrue(set(g1["passed_cases"]).issubset(g2["passed_cases"]))

    def test_global_false_completion_assurance_is_not_invented(self) -> None:
        for generation, record in self.scores["scores"].items():
            with self.subTest(generation=generation):
                self.assertEqual("NOT_SUPPORTED", record["global_false_completion_count"])
                self.assertGreater(record["unsupported_case_count"], 0)

    def test_post_freeze_novelty_defect_is_explicit(self) -> None:
        summary = self.novelty["summary"]
        self.assertEqual(31, summary["novel_cases"])
        self.assertEqual(1, summary["semantic_restatements"])
        self.assertFalse(summary["every_frozen_case_novel"])
        duplicate = [
            case for case in self.novelty["cases"]
            if case["status"] == "SEMANTIC_RESTATEMENT"
        ]
        self.assertEqual(["H11"], [case["case_id"] for case in duplicate])
        self.assertEqual("NOT_YET", summary["a13_u01_acceptance"])

    def test_poisoned_temp_case_was_non_discriminating(self) -> None:
        for generation, transcript in self.transcripts.items():
            case = next(case for case in transcript["cases"] if case["case_id"] == "H26")
            with self.subTest(generation=generation):
                self.assertEqual("PASS", case["status"])

    def test_public_minus_holdout_gaps_recompute(self) -> None:
        for generation, row in self.gaps["generations"].items():
            public = row["public"]
            holdout = row["holdout"]
            with self.subTest(generation=generation):
                self.assertAlmostEqual(
                    row["public_minus_holdout_pass_rate"],
                    public["pass_rate"] - holdout["pass_rate"],
                    places=4,
                )
                self.assertAlmostEqual(
                    row["public_minus_holdout_critical_pass_rate"],
                    public["critical_pass_rate"] - holdout["critical_pass_rate"],
                    places=4,
                )
        self.assertEqual(
            0.6875,
            self.gaps["generations"]["G2"]["public_minus_holdout_pass_rate"],
        )
        self.assertEqual("SUPPORTED", self.gaps["hypothesis_disposition"])

    def test_gap_analysis_reports_positive_holdout_lift_too(self) -> None:
        positive = self.gaps["positive_result"]
        self.assertEqual(0.21875, positive["G2_minus_G1_holdout_pass_rate"])
        self.assertEqual([], positive["G1_passed_cases_lost_by_G2"])


if __name__ == "__main__":
    unittest.main()
