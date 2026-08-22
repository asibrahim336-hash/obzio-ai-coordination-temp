import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workstreams.po03.packverify.manifest_gaps import audit_entries
from workstreams.po03.packverify.manifest_model import ManifestEntry


class ManifestGapFixtureTests(unittest.TestCase):
    def test_each_closed_set_gap_class_has_a_planted_fixture(self):
        entries = [
            ManifestEntry(
                manifest_path="packs/demo/MANIFEST.json",
                logical_path="unhashed.py",
                tree_path="packs/demo/unhashed.py",
                expected_sha256=None,
                expected_bytes=1,
            ),
            ManifestEntry(
                manifest_path="packs/demo/MANIFEST.json",
                logical_path="mismatch.py",
                tree_path="packs/demo/mismatch.py",
                expected_sha256=hashlib.sha256(b"expected").hexdigest(),
                expected_bytes=8,
            ),
        ]
        blobs = {
            "packs/demo/unhashed.py": b"x",
            "packs/demo/mismatch.py": b"observed",
            "packs/demo/unlisted.py": b"not declared",
        }
        gaps = audit_entries(entries, blobs)
        self.assertEqual(
            [item["tree_path"] for item in gaps["unlisted_files"]],
            ["packs/demo/unlisted.py"],
        )
        self.assertEqual(
            [item["tree_path"] for item in gaps["unhashed_entries"]],
            ["packs/demo/unhashed.py"],
        )
        self.assertEqual(
            [item["tree_path"] for item in gaps["hash_mismatches"]],
            ["packs/demo/mismatch.py"],
        )


if __name__ == "__main__":
    unittest.main()
