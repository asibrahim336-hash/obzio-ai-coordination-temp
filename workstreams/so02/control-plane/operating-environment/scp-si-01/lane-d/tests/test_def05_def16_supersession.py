#!/usr/bin/env python3
"""EARNED (DEF-05, DEF-16): verify at commit, then compare to branch tip.

"DEF-05 and DEF-16 are two halves of one thing. Verify each artifact at its
own commit, then compare against branch tip to flag supersession. Neither
root alone is correct."

This is new lane-d capability, not a regression against a specific existing
function in a shared file (no shared module in this tree currently does
commit-scoped artifact verification at all — `write_admission` never checks
out a historical commit; `evidence_integrity.verify_readback_truth` compares
against a REMOTE, not a local commit-vs-tip pair). It is exercised here,
inside the lane's own namespace, against a real disposable git repository —
never a mock — per the same "recompute, do not trust" discipline the shared
modules already use.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
fix = _load("evidence_gate_wiring", HERE.parent / "fixes" / "evidence_gate_wiring.py")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def _new_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "tester")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


class SupersessionTests(unittest.TestCase):
    def test_a_commit_scoped_artifact_that_is_later_changed_is_flagged_superseded(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            repo = _new_repo(Path(d))
            (repo / "evidence.json").write_text('{"v":1}\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "v1")
            verified_commit = _git(repo, "rev-parse", "HEAD")

            (repo / "evidence.json").write_text('{"v":2}\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "v2 supersedes")

            result = fix.compare_to_branch_tip(repo, "evidence.json", verified_commit, "HEAD")
        self.assertEqual("SUPERSEDED_AT_TIP", result["verdict"])
        self.assertTrue(result["at_commit"]["present_at_commit"])
        self.assertTrue(result["at_tip"]["present_at_commit"])
        self.assertNotEqual(result["at_commit"]["sha256"], result["at_tip"]["sha256"])

    def test_an_artifact_unchanged_since_its_commit_is_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            repo = _new_repo(Path(d))
            (repo / "evidence.json").write_text('{"v":1}\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "v1")
            verified_commit = _git(repo, "rev-parse", "HEAD")

            (repo / "other.txt").write_text("unrelated\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "unrelated change, evidence.json untouched")

            result = fix.compare_to_branch_tip(repo, "evidence.json", verified_commit, "HEAD")
        self.assertEqual("UNCHANGED_AT_TIP", result["verdict"])

    def test_the_verified_commit_being_the_tip_reports_supersession_is_not_possible(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            repo = _new_repo(Path(d))
            (repo / "evidence.json").write_text('{"v":1}\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "v1")
            tip = _git(repo, "rev-parse", "HEAD")

            result = fix.compare_to_branch_tip(repo, "evidence.json", tip, "HEAD")
        self.assertEqual("COMMIT_IS_TIP_NO_SUPERSESSION_POSSIBLE", result["verdict"])

    def test_an_artifact_deleted_by_the_tip_is_flagged_absent_at_tip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            repo = _new_repo(Path(d))
            (repo / "evidence.json").write_text('{"v":1}\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "v1")
            verified_commit = _git(repo, "rev-parse", "HEAD")

            _git(repo, "rm", "-q", "evidence.json")
            _git(repo, "commit", "-q", "-m", "remove evidence.json")

            result = fix.compare_to_branch_tip(repo, "evidence.json", verified_commit, "HEAD")
        self.assertEqual("PATH_ABSENT_AT_TIP", result["verdict"])

    def test_verification_reads_the_commit_never_the_working_tree(self) -> None:
        """The working tree can be dirty or checked out elsewhere; the commit is not."""
        with tempfile.TemporaryDirectory() as d:
            repo = _new_repo(Path(d))
            (repo / "evidence.json").write_text('{"v":1}\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "v1")
            verified_commit = _git(repo, "rev-parse", "HEAD")

            # Dirty the working tree without committing.
            (repo / "evidence.json").write_text('{"v":"UNCOMMITTED TAMPERING"}\n', encoding="utf-8")

            result = fix.verify_artifact_at_commit(repo, "evidence.json", verified_commit)
        self.assertTrue(result["present_at_commit"])
        self.assertNotIn("UNCOMMITTED", str(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
