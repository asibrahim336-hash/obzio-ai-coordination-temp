import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RESULT = ROOT / "workstreams/po03/evidence/reproduction-results.json"
PACK_SHAS = {
    "1e6f53c323f8326d12af213557082a3665991f19",
    "62c29e1a641932b817592ddc970df11f89b6c0f7",
}
MISSING_NAMES = {
    "06-browser-execution/_spine.py",
    "07-capability-manufacture/_spine.py",
    "08-knowledge-currentness/_spine.py",
    "09-infrastructure-operation/_spine.py",
    "10-economics-measurement/_spine.py",
}


class FrozenPinnedDefectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(RESULT.read_text(encoding="utf-8"))

    def test_exact_missing_spine_defects_remain_frozen(self):
        sources = {
            source["commit_sha"]: source
            for source in self.report["sources"]
            if source["pack_roots"]
        }
        self.assertEqual(set(sources), PACK_SHAS)
        for source in sources.values():
            root_result = source["root_results"][0]
            root = root_result["root"] + "/"
            missing = {
                finding["tree_path"].removeprefix(root)
                for finding in root_result["missing_blobs"]["findings"]
            }
            self.assertEqual(missing, MISSING_NAMES)
        self.assertEqual(
            self.report["summary"]["missing_blob_findings"], 10
        )

    def test_absolute_runner_failure_is_frozen_at_both_shas(self):
        failures = []
        for source in self.report["sources"]:
            for root_result in source["root_results"]:
                boundary = root_result["process_boundary"]
                if boundary["outcome"] == "FAIL":
                    failures.append(boundary)
                    self.assertEqual(boundary["process"]["exit_code"], 1)
                    self.assertIn(
                        "/tmp/packs/strategic-orchestration",
                        boundary["process"]["stderr"],
                    )
        self.assertEqual(len(failures), 2)

    def test_other_detector_counts_are_frozen(self):
        summary = self.report["summary"]
        self.assertEqual(summary["portability_findings"], 68)
        self.assertEqual(
            summary["manifest_gap_findings"],
            {
                "hash_mismatches": 0,
                "unhashed_entries": 0,
                "unlisted_files": 4,
            },
        )
        self.assertEqual(summary["transport_debris_findings"], 16)

    def test_every_repair_candidate_is_isolated_and_unapplied(self):
        candidates = self.report["isolated_repair_candidates"]
        self.assertGreaterEqual(len(candidates), 17)
        self.assertTrue(
            all(
                candidate["state"]
                == "ISOLATED_PO03_CANDIDATE_NOT_APPLIED"
                for candidate in candidates
            )
        )


if __name__ == "__main__":
    unittest.main()
