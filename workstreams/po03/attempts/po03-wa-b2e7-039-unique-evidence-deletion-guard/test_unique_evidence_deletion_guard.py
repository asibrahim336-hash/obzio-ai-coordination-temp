#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from unique_evidence_deletion_guard import DeletionBlocked, assert_deletion_allowed


class UniqueEvidenceDeletionGuardTests(unittest.TestCase):
    def test_refuses_unique_currently_referenced_fixture(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            evidence = Path(directory) / "evidence.md"
            evidence.write_text("唯一 evidence\n", encoding="utf-8")
            with self.assertRaises(DeletionBlocked):
                assert_deletion_allowed(evidence, [evidence], [evidence])
            self.assertTrue(evidence.exists(), "guard must not delete the fixture")

    def test_allows_currently_referenced_duplicate_fixture(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            first = root / "evidence-a.md"
            second = root / "evidence-b.md"
            first.write_text("duplicated evidence\n", encoding="utf-8")
            second.write_text("duplicated evidence\n", encoding="utf-8")
            decision = assert_deletion_allowed(first, [first, second], [first])
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.hash_copies, 2)

    def test_allows_unreferenced_unique_fixture_for_review(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            evidence = Path(directory) / "unreferenced.md"
            evidence.write_text("not routed\n", encoding="utf-8")
            decision = assert_deletion_allowed(evidence, [evidence], [])
        self.assertTrue(decision.allowed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
