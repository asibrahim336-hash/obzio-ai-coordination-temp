#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from renamed_clone_detector import detect


class RenamedCloneDetectorTests(unittest.TestCase):
    def test_flags_exact_renamed_clone_with_hashes(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            (root / "first.md").write_text("same committed artifact\n", encoding="utf-8")
            (root / "renamed.md").write_text("same committed artifact\n", encoding="utf-8")
            pairs = detect([root])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["kind"], "renamed-clone")
        self.assertEqual(pairs[0]["left_sha256"], pairs[0]["right_sha256"])

    def test_flags_near_duplicate_but_not_unrelated_content(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            (root / "source.txt").write_text(
                "alpha beta gamma delta epsilon\n", encoding="utf-8"
            )
            (root / "copy.txt").write_text(
                "alpha beta gamma delta zeta\n", encoding="utf-8"
            )
            (root / "other.txt").write_text("unrelated content\n", encoding="utf-8")
            pairs = detect([root], threshold=0.75)
        self.assertTrue(any(pair["kind"] == "near-duplicate" for pair in pairs))
        self.assertFalse(any("other.txt" in (pair["left"], pair["right"]) for pair in pairs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
