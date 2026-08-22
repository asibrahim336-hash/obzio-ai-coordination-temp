import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workstreams.po03.packverify.manifest_model import (
    ManifestDocument,
    ManifestEntry,
    entries_for_document,
)
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

    def test_manifest_all_shared_spine_metadata_is_one_file_claim(self):
        document = ManifestDocument(
            path="packs/MANIFEST_ALL.json",
            value={
                "shared_spine": {
                    "published_at": "packs/_shared/_spine.py",
                    "sha256": "a" * 64,
                    "bytes": 10,
                    "copies_collapsed": 6,
                }
            },
        )
        entries = entries_for_document(document, "packs")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].tree_path, "packs/_shared/_spine.py")


if __name__ == "__main__":
    unittest.main()
