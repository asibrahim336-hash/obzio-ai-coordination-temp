"""Tests for the PO-03 changed-path ownership guard.

Includes the deliberate out-of-allowlist mutation fixture the commission
requires: a commit that writes protected state must be rejected, named and
exit non-zero.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = UNIT_ROOT / "harness" / "ownership_guard.py"
SPEC = importlib.util.spec_from_file_location("po03_ownership_guard", GUARD_PATH)
assert SPEC is not None and SPEC.loader is not None
GUARD = importlib.util.module_from_spec(SPEC)
sys.modules["po03_ownership_guard"] = GUARD
SPEC.loader.exec_module(GUARD)

GIT = shutil.which("git")

OWNED = "workstreams/po03/wave-a/units/wa-003/**"
IMMUTABLE_INPUT = {
    "task_id": "PO03-WA-003",
    "ownership": {
        "allowed_write_globs": [OWNED],
        "prohibited_globs": [
            "state/**",
            "dispatch/**",
            ".cursor/environment.json",
            "receipts/po01/**",
            "workstreams/po01/**",
        ],
    },
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=GUARD.local_git_env(),
    ).stdout


@unittest.skipUnless(GIT, "git is required for ownership fixtures")
class OwnershipGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(
            ["git", "init", "--quiet", "-b", "main", str(self.repo)],
            check=True,
            capture_output=True,
            env=GUARD.local_git_env(),
        )
        git(self.repo, "config", "user.email", "po03-fixture@obzio.invalid")
        git(self.repo, "config", "user.name", "PO03 Fixture")
        self.write("state/operator-system/pointer.json", "{}\n")
        self.write("workstreams/po01/producer.md", "po01\n")
        self.write("workstreams/po03/control/inputs/wave-a/wa-003.json", json.dumps(IMMUTABLE_INPUT, indent=2) + "\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "--quiet", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD").strip()

    def write(self, relative: str, content: str) -> None:
        target = self.repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self, message: str) -> str:
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "--quiet", "-m", message)
        return git(self.repo, "rev-parse", "HEAD").strip()

    def run_guard(self, extra: list[str] | None = None) -> tuple[int, dict]:
        receipt = self.root / "receipt.json"
        code = GUARD.main(
            [
                "--repo",
                str(self.repo),
                "--base",
                self.base,
                "--head",
                "HEAD",
                "--input",
                "workstreams/po03/control/inputs/wave-a/wa-003.json",
                "--receipt",
                str(receipt),
                *(extra or []),
            ]
        )
        return code, json.loads(receipt.read_text(encoding="utf-8"))

    def test_owned_subtree_writes_are_allowed(self):
        self.write("workstreams/po03/wave-a/units/wa-003/result/result.json", "{}\n")
        self.write("workstreams/po03/wave-a/units/wa-003/harness/tool.py", "x = 1\n")
        self.commit("owned")
        code, report = self.run_guard()
        self.assertEqual(0, code)
        self.assertEqual("PASS", report["disposition"])
        self.assertEqual(2, report["changed_count"])
        self.assertEqual([], report["outside_allowlist"])
        self.assertEqual([], report["prohibited_hits"])

    def test_deliberate_out_of_allowlist_mutation_is_rejected(self):
        self.write("state/operator-system/pointer.json", '{"mutated": true}\n')
        self.commit("deliberate protected-state mutation fixture")
        code, report = self.run_guard()
        self.assertEqual(1, code)
        self.assertEqual("FAIL", report["disposition"])
        self.assertEqual(
            ["state/operator-system/pointer.json"],
            [item["path"] for item in report["outside_allowlist"]],
        )
        self.assertEqual(
            ["state/**"],
            report["prohibited_hits"][0]["patterns"],
        )

    def test_sibling_unit_write_is_outside_allowlist(self):
        self.write("workstreams/po03/wave-a/units/wa-004/result/result.json", "{}\n")
        self.commit("sibling unit collision fixture")
        code, report = self.run_guard()
        self.assertEqual(1, code)
        self.assertEqual(
            ["workstreams/po03/wave-a/units/wa-004/result/result.json"],
            [item["path"] for item in report["outside_allowlist"]],
        )
        self.assertEqual([], report["prohibited_hits"], "not prohibited, merely unowned")

    def test_po01_path_is_rejected_as_prohibited(self):
        self.write("workstreams/po01/producer.md", "touched\n")
        self.commit("po01 contact fixture")
        code, report = self.run_guard()
        self.assertEqual(1, code)
        self.assertEqual(["workstreams/po01/**"], report["prohibited_hits"][0]["patterns"])

    def test_controller_shared_path_is_outside_a_subordinate_allowlist(self):
        self.write("workstreams/po03/control/inputs/wave-a/wa-003.json", json.dumps(IMMUTABLE_INPUT) + "\n")
        self.commit("immutable input tamper fixture")
        code, report = self.run_guard()
        self.assertEqual(1, code)
        self.assertEqual(
            ["workstreams/po03/control/inputs/wave-a/wa-003.json"],
            [item["path"] for item in report["outside_allowlist"]],
        )

    def test_deletion_and_rename_out_of_the_owned_subtree_are_caught(self):
        self.write("workstreams/po03/wave-a/units/wa-003/harness/tool.py", "x = 1\n")
        self.commit("seed owned file")
        self.base = git(self.repo, "rev-parse", "HEAD").strip()
        (self.repo / "dispatch").mkdir(parents=True, exist_ok=True)
        git(self.repo, "mv", "workstreams/po03/wave-a/units/wa-003/harness/tool.py", "dispatch/tool.py")
        self.commit("rename out of the owned subtree")
        code, report = self.run_guard()
        self.assertEqual(1, code)
        paths = sorted(item["path"] for item in report["outside_allowlist"])
        self.assertEqual(["dispatch/tool.py"], paths)
        self.assertEqual(["dispatch/**"], report["prohibited_hits"][0]["patterns"])

    def test_no_changes_is_a_pass(self):
        code, report = self.run_guard()
        self.assertEqual(0, code)
        self.assertEqual(0, report["changed_count"])

    def test_guard_error_without_allowlist(self):
        code = GUARD.main(["--repo", str(self.repo), "--base", self.base])
        self.assertEqual(2, code)

    def test_guard_error_on_input_without_ownership_block(self):
        broken = self.root / "broken.json"
        broken.write_text(json.dumps({"task_id": "x"}) + "\n", encoding="utf-8")
        code = GUARD.main(["--repo", str(self.repo), "--base", self.base, "--input", str(broken)])
        self.assertEqual(2, code)

    def test_evaluate_is_pure_and_reports_both_categories(self):
        report = GUARD.evaluate(
            [
                {"status": "A", "path": "workstreams/po03/wave-a/units/wa-003/result/result.json"},
                {"status": "M", "path": "state/x.json"},
                {"status": "A", "path": "docs/readme.md"},
            ],
            [OWNED],
            ["state/**"],
        )
        self.assertEqual("FAIL", report["disposition"])
        self.assertEqual(1, len(report["inside_allowlist"]))
        self.assertEqual(
            ["docs/readme.md", "state/x.json"],
            sorted(item["path"] for item in report["outside_allowlist"]),
        )
        self.assertEqual(["state/x.json"], [item["path"] for item in report["prohibited_hits"]])


if __name__ == "__main__":
    unittest.main()
