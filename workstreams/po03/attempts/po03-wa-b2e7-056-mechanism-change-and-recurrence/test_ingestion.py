#!/usr/bin/env python3
"""Validate consolidated controller-ingestion artifacts."""

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class IngestionArtifactTests(unittest.TestCase):
    def test_reproduction_ledger_has_six_executed_links(self) -> None:
        entries = [json.loads(line) for line in (ROOT / "reproduction_ledger.jsonl").read_text().splitlines()]
        self.assertEqual(6, len(entries))
        self.assertTrue(all(entry["reproduction_executed"] for entry in entries))
        self.assertTrue(all(entry["decision_changed"] == [] for entry in entries))

    def test_two_changes_and_one_rejection_are_staged(self) -> None:
        changes = json.loads((ROOT / "mechanism_changes.json").read_text())
        self.assertEqual(2, len(changes["mechanism_changes"]))
        self.assertTrue(
            all(change["controller_promotion_status"] == "STAGED_NOT_PROMOTED" for change in changes["mechanism_changes"])
        )
        rejected = [
            item for item in changes["evidence_backed_rejections"]
            if item["status"] == "REJECTED_BY_REPRODUCTION"
        ]
        self.assertGreaterEqual(len(rejected), 1)
        self.assertEqual([], changes["decision_changed"])

    def test_revert_proof_records_expected_failure(self) -> None:
        proof = json.loads((ROOT / "revert_proof.json").read_text())
        self.assertEqual(0, proof["staged_run"]["exit_code"])
        self.assertNotEqual(0, proof["reverted_run"]["exit_code"])
        self.assertEqual(2, proof["mechanism_changes_with_passing_recurrence_tests"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
