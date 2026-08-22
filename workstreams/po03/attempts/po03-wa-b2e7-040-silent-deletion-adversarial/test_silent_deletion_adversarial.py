#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from silent_deletion_adversarial import (
    SilentDeletionDetected,
    assert_no_silent_deletion,
    detect_silent_deletions,
)


class SilentDeletionAdversarialTests(unittest.TestCase):
    def test_guard_catches_simulated_silent_deletion(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            fixture = Path(directory) / "unique-evidence.md"
            fixture.write_bytes(b"unique depended-upon evidence")
            before = {fixture.as_posix(): fixture.read_bytes()}
            after = {}
            with self.assertRaises(SilentDeletionDetected):
                assert_no_silent_deletion(before, after, {fixture.as_posix()})
            self.assertEqual(len(detect_silent_deletions(before, after, {fixture.as_posix()})), 1)
            self.assertTrue(fixture.exists(), "adversarial simulation must not delete fixture")

    def test_guard_accepts_content_preserved_at_renamed_path(self):
        before = {"old.md": b"preserved evidence"}
        after = {"new.md": b"preserved evidence"}
        assert_no_silent_deletion(before, after, {"old.md"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
