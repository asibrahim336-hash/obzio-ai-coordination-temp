import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workstreams.po03.packverify.manifest_model import ManifestEntry
from workstreams.po03.packverify.qualify import find_missing


class MissingBlobFixtureTests(unittest.TestCase):
    def test_planted_manifest_entry_without_blob_is_reported(self):
        entries = [
            ManifestEntry(
                manifest_path="packs/demo/MANIFEST.json",
                logical_path="present.py",
                tree_path="packs/demo/present.py",
                expected_sha256="0" * 64,
                expected_bytes=1,
            ),
            ManifestEntry(
                manifest_path="packs/demo/MANIFEST.json",
                logical_path="missing.py",
                tree_path="packs/demo/missing.py",
                expected_sha256="1" * 64,
                expected_bytes=1,
            ),
        ]
        findings = find_missing(entries, {"packs/demo/present.py"})
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["tree_path"], "packs/demo/missing.py")
        self.assertEqual(findings[0]["class"], "manifest_entry_missing_blob")


if __name__ == "__main__":
    unittest.main()
