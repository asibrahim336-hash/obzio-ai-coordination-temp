import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "workstreams/po03/evidence"


class SourceAndCriteriaTests(unittest.TestCase):
    def test_source_lock_uses_only_full_immutable_shas(self):
        source_lock = json.loads(
            (EVIDENCE / "source-lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual(source_lock["observation"]["po01_ref_writes"], [])
        self.assertEqual(source_lock["observation"]["po01_ref_write_count"], 0)
        self.assertEqual(len(source_lock["sources"]), 8)
        for source in source_lock["sources"]:
            self.assertRegex(source["commit_sha"], r"^[0-9a-f]{40}$")
            self.assertTrue(source["read_only"])
            self.assertIn("git ls-remote", source["observation_method"])

    def test_criteria_commit_precedes_source_inspection_commit(self):
        criteria_commit = subprocess.run(
            [
                "git",
                "log",
                "-1",
                "--format=%H",
                "--",
                "workstreams/po03/evidence/criteria-freeze.json",
            ],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        source_commit = subprocess.run(
            [
                "git",
                "log",
                "-1",
                "--format=%H",
                "--",
                "workstreams/po03/evidence/source-lock.json",
            ],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        self.assertRegex(criteria_commit, r"^[0-9a-f]{40}$")
        self.assertRegex(source_commit, r"^[0-9a-f]{40}$")
        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", criteria_commit, source_commit],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(ancestry.returncode, 0)
        self.assertNotEqual(criteria_commit, source_commit)

    def test_freeze_excludes_producer_narrative(self):
        freeze = json.loads(
            (EVIDENCE / "criteria-freeze.json").read_text(encoding="utf-8")
        )
        exclusions = freeze["freeze_basis"]["producer_material_excluded_before_freeze"]
        self.assertIn("contents of candidate PO-01 refs", exclusions)
        self.assertEqual(
            freeze["adjudication"]["allowed_outcomes"],
            ["PASS", "FAIL", "NOT_YET", "NOT_SUPPORTED"],
        )


if __name__ == "__main__":
    unittest.main()
