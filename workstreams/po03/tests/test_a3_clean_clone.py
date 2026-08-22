"""Unit a3-u01: the clean-clone runner is exercised end to end.

The runner's real target is the GitHub remote, which is unavailable when the
suite runs offline (unit a3-u06) and must not be a hidden test dependency.  So
these tests build a synthetic bare repository on local disk and clone from it.
That exercises the same code path as a network clone -- ``git clone`` against a
remote URL -- while keeping the suite hermetic.

Both directions are proved: a repository whose suite passes yields ``PASS`` and
exit 0, and a repository whose suite fails yields ``FAIL`` and a non-zero exit.
A runner that can only report success is not a gate.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "workstreams" / "po03" / "runtime" / "clean_clone.sh"

PASSING_TEST = """import unittest


class Passing(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(2 + 2, 4)
"""

FAILING_TEST = """import unittest


class Failing(unittest.TestCase):
    def test_planted_defect(self):
        self.assertEqual(2 + 2, 5)
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def build_remote(root: Path, test_body: str) -> tuple[Path, str]:
    """Create a bare repository holding a minimal PO-03 test tree."""
    source = root / "source"
    tests = source / "workstreams" / "po03" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_fixture_case.py").write_text(test_body, encoding="utf-8")
    git(source, "init", "--quiet", "--initial-branch", "main", ".")
    git(source, "config", "user.email", "po03-worker-a3@example.invalid")
    git(source, "config", "user.name", "po03-worker-a3")
    git(source, "add", "--all")
    git(source, "commit", "--quiet", "--message", "fixture")
    commit = git(source, "rev-parse", "HEAD")
    bare = root / "remote.git"
    git(root, "clone", "--quiet", "--bare", str(source), str(bare))
    return bare, commit


def run_runner(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(RUNNER), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


@unittest.skipUnless(shutil.which("git"), "git is required")
class CleanCloneRunner(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="po03-a3-u01-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_runner_is_posix_shell_clean(self) -> None:
        check = subprocess.run(["sh", "-n", str(RUNNER)], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_passing_remote_produces_pass_transcript(self) -> None:
        bare, commit = build_remote(self.work, PASSING_TEST)
        out = self.work / "transcript.json"
        result = run_runner(
            "--remote",
            str(bare),
            "--ref",
            "main",
            "--expect-commit",
            commit,
            "--out",
            str(out),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        transcript = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(transcript["status"], "PASS")
        self.assertEqual(transcript["cloned_commit"], commit)
        self.assertEqual(transcript["tests_run"], 1)
        self.assertFalse(transcript["scratch_inside_repository"])
        self.assertEqual(transcript["environment"]["inherited_variables"], 0)
        self.assertEqual(transcript["leftovers"]["after_no_bytecode_run"], 0)
        self.assertEqual(transcript["leftovers"]["unexpected_after_canonical_run"], 0)
        names = [step["name"] for step in transcript["steps"]]
        self.assertEqual(
            names,
            [
                "clone",
                "tree_clean_before",
                "suite_no_bytecode",
                "tree_after_no_bytecode",
                "suite",
                "tree_clean_after",
            ],
        )
        self.assertTrue(all(step["exit_code"] == 0 for step in transcript["steps"]))

    def test_failing_remote_suite_fails_the_runner(self) -> None:
        """Planted defect: the runner must not report PASS for a red suite."""
        bare, _ = build_remote(self.work, FAILING_TEST)
        out = self.work / "transcript.json"
        result = run_runner("--remote", str(bare), "--ref", "main", "--out", str(out))
        self.assertNotEqual(result.returncode, 0, "a failing suite must fail the runner")
        transcript = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(transcript["status"], "FAIL")
        suite_steps = [s for s in transcript["steps"] if s["name"].startswith("suite")]
        self.assertTrue(suite_steps)
        self.assertTrue(any(step["exit_code"] != 0 for step in suite_steps))

    def test_wrong_expected_commit_is_rejected(self) -> None:
        bare, _ = build_remote(self.work, PASSING_TEST)
        result = run_runner(
            "--remote",
            str(bare),
            "--ref",
            "main",
            "--expect-commit",
            "0" * 40,
        )
        self.assertEqual(result.returncode, 71, result.stdout + result.stderr)
        self.assertIn("!= expected", result.stderr)

    def test_scratch_inside_repository_is_refused(self) -> None:
        bare, _ = build_remote(self.work, PASSING_TEST)
        inside = REPO_ROOT / "workstreams" / "po03" / "runtime"
        result = run_runner(
            "--remote",
            str(bare),
            "--ref",
            "main",
            "--scratch",
            str(inside),
        )
        self.assertEqual(result.returncode, 65, result.stdout + result.stderr)
        self.assertIn("refusing scratch directory inside the repository", result.stderr)
        leaked = sorted(p.name for p in inside.glob("po03-clean-clone.*"))
        for name in leaked:
            shutil.rmtree(inside / name, ignore_errors=True)
        self.assertEqual(leaked, [], f"scratch directories leaked into the repository: {leaked}")

    def test_credentials_are_redacted_from_the_transcript(self) -> None:
        bare, _ = build_remote(self.work, PASSING_TEST)
        out = self.work / "transcript.json"
        # A file:// URL carrying userinfo mirrors the token-bearing https remote.
        remote = f"file://x-access-token:s3cr3t-token-value@{bare}"
        result = run_runner("--remote", remote, "--ref", "main", "--out", str(out))
        text = out.read_text(encoding="utf-8") if out.exists() else ""
        combined = text + result.stdout + result.stderr
        self.assertNotIn("s3cr3t-token-value", combined)
        if text:
            self.assertIn("***@", json.loads(text)["remote"])

    def test_scratch_tree_is_removed_after_the_run(self) -> None:
        bare, _ = build_remote(self.work, PASSING_TEST)
        scratch_parent = self.work / "scratch"
        result = run_runner(
            "--remote",
            str(bare),
            "--ref",
            "main",
            "--scratch",
            str(scratch_parent),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            sorted(os.listdir(scratch_parent)),
            [],
            "the scratch clone must not survive the run",
        )


class CommittedTranscript(unittest.TestCase):
    """The recorded real-remote transcript must be present and internally sound."""

    TRANSCRIPT = REPO_ROOT / "workstreams" / "po03" / "runtime" / "transcripts" / "clean-clone.json"

    def test_transcript_is_committed_and_passing(self) -> None:
        self.assertTrue(self.TRANSCRIPT.is_file(), f"missing transcript: {self.TRANSCRIPT}")
        transcript = json.loads(self.TRANSCRIPT.read_text(encoding="utf-8"))
        self.assertEqual(transcript["schema"], "po03-clean-clone-transcript-v1")
        self.assertEqual(transcript["unit_id"], "a3-u01")
        self.assertEqual(transcript["status"], "PASS")
        self.assertGreater(transcript["tests_run"], 0)
        self.assertEqual(len(transcript["cloned_commit"]), 40)
        self.assertEqual(transcript["leftovers"]["unexpected_after_canonical_run"], 0)

    def test_transcript_contains_no_credentials(self) -> None:
        text = self.TRANSCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("x-access-token:", text)
        self.assertNotIn("ghp_", text)
        self.assertNotIn("github_pat_", text)


if __name__ == "__main__":
    unittest.main()
