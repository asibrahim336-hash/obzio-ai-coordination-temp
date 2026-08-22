"""Tests for git-only drift lineage reconstruction and independent comparison."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[3]
CAPSULE_DIR = REPO_ROOT / "workstreams" / "po03" / "capsule"
RECONCILER_PATH = CAPSULE_DIR / "lineage_reconciler.py"
EVIDENCE_PATH = (
    REPO_ROOT / "workstreams" / "po03" / "evidence" / "source-capsule-drift.json"
)
FROZEN_REF = "04827c3cca829ece4ccca87e3d4196cc1b64a7a7"
CURRENT_REF = "b7b1888ad17eb232b9f284c753df79da3c0633ba"
SPEC = importlib.util.spec_from_file_location("a12_lineage_reconciler", RECONCILER_PATH)
RECONCILER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RECONCILER)


class LineageReconcilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # This call has no evidence argument and computes before evidence is loaded.
        cls.computed = RECONCILER.recompute_lineage(
            REPO_ROOT,
            frozen_ref=FROZEN_REF,
            current_ref=CURRENT_REF,
            source_spec_path="workstreams/po03/control/wave-a-spec.json",
        )
        cls.evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))

    def test_git_only_recomputation_finds_all_four_drift_lineages(self):
        self.assertEqual(FROZEN_REF, self.computed["frozen_commit_sha"])
        self.assertEqual(CURRENT_REF, self.computed["current_commit_sha"])
        self.assertEqual(12, self.computed["source_count"])
        self.assertEqual(4, self.computed["drift_count"])
        self.assertEqual(
            {
                ".github/workflows/po03-contracts.yml",
                "workstreams/po03/control/model-capability-register.json",
                "workstreams/po03/control/path-ownership.json",
                "workstreams/po03/tools/control_plane.py",
            },
            {row["path"] for row in self.computed["drifted_sources"]},
        )
        for row in self.computed["drifted_sources"]:
            self.assertRegex(row["frozen_blob_sha"], r"^[0-9a-f]{40}$")
            self.assertRegex(row["current_blob_sha"], r"^[0-9a-f]{40}$")
            self.assertNotEqual(row["frozen_blob_sha"], row["current_blob_sha"])
            self.assertTrue(row["causal_commits"])

    def test_comparison_preserves_eight_commit_subject_discrepancies(self):
        comparison = RECONCILER.compare_with_evidence(
            self.computed, self.evidence
        )
        self.assertFalse(comparison["agrees"])
        self.assertEqual(8, len(comparison["discrepancies"]))
        self.assertTrue(
            all(
                item["field"].endswith(".subject")
                for item in comparison["discrepancies"]
            ),
            comparison,
        )
        self.assertEqual(4, comparison["compared_drift_count"])

    def test_causal_commits_are_full_ordered_git_history(self):
        by_path = {
            row["path"]: row["causal_commits"]
            for row in self.computed["drifted_sources"]
        }
        self.assertEqual(
            ["6f5e386", "075e854"],
            [
                row["sha"][:7]
                for row in by_path["workstreams/po03/tools/control_plane.py"]
            ],
        )
        self.assertEqual(
            ["dd2fcc6", "a23583f", "075e854", "b7b1888"],
            [
                row["sha"][:7]
                for row in by_path[
                    "workstreams/po03/control/path-ownership.json"
                ]
            ],
        )

    def test_disagreement_is_reported_without_mutating_either_input(self):
        computed_before = copy.deepcopy(self.computed)
        evidence_before = copy.deepcopy(self.evidence)
        conflicting = copy.deepcopy(self.evidence)
        conflicting["drifted_sources"][0]["current_sha256"] = "0" * 64

        comparison = RECONCILER.compare_with_evidence(
            self.computed, conflicting
        )

        self.assertFalse(comparison["agrees"])
        self.assertTrue(
            any(
                item["field"] == "current_sha256"
                and item["path"]
                == conflicting["drifted_sources"][0]["path"]
                for item in comparison["discrepancies"]
            ),
            comparison,
        )
        self.assertEqual(computed_before, self.computed)
        self.assertEqual(evidence_before, self.evidence)

    def test_cli_separates_recomputation_from_evidence_comparison(self):
        with tempfile.TemporaryDirectory(
            prefix=".test-reconciler-", dir=CAPSULE_DIR
        ) as temporary:
            computed_path = Path(temporary) / "computed.json"
            comparison_path = Path(temporary) / "comparison.json"
            recompute = subprocess.run(
                [
                    "python3",
                    "-I",
                    str(RECONCILER_PATH),
                    "recompute",
                    "--repo",
                    str(REPO_ROOT),
                    "--frozen-ref",
                    FROZEN_REF,
                    "--current-ref",
                    CURRENT_REF,
                    "--source-spec",
                    "workstreams/po03/control/wave-a-spec.json",
                    "--output",
                    str(computed_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, recompute.returncode, recompute.stdout + recompute.stderr)
            compare = subprocess.run(
                [
                    "python3",
                    "-I",
                    str(RECONCILER_PATH),
                    "compare",
                    "--computed",
                    str(computed_path),
                    "--evidence",
                    str(EVIDENCE_PATH),
                    "--output",
                    str(comparison_path),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(5, compare.returncode, compare.stdout + compare.stderr)
            self.assertFalse(json.loads(comparison_path.read_text())["agrees"])


if __name__ == "__main__":
    unittest.main()
