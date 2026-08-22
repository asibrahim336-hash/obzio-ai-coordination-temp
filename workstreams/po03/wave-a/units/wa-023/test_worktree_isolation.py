import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


UNIT = Path(__file__).resolve().parent
MODULE_PATH = UNIT / "probe_worktree_isolation.py"
SPEC = importlib.util.spec_from_file_location("probe_worktree_isolation", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class WorktreeIsolationProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = UNIT / ".test-scratch"
        cls.scratch.mkdir(exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.rmdir()

    def make_repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        MODULE._run(("git", "init", "-b", "controller"), cwd=repo)
        MODULE._run(("git", "config", "user.name", "Probe Test"), cwd=repo)
        MODULE._run(
            ("git", "config", "user.email", "probe-test@invalid.example"),
            cwd=repo,
        )
        (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
        MODULE._run(("git", "add", "tracked.txt"), cwd=repo)
        MODULE._run(("git", "commit", "-m", "baseline"), cwd=repo)
        return repo

    def test_sanitized_reproduction_passes_every_assertion(self):
        result = MODULE.reproduce(self.scratch)
        self.assertEqual("PASS", result["result"])
        self.assertTrue(all(result["assertions"].values()), result)
        self.assertFalse(result["sanitization"]["real_repository_content_used"])
        self.assertFalse(result["sanitization"]["external_mutation"])

    def test_guard_passes_for_stable_checkout(self):
        with tempfile.TemporaryDirectory(dir=self.scratch) as temporary:
            repo = self.make_repo(Path(temporary))
            identity = MODULE.capture_identity(repo)
            result = MODULE.guard_checkout(
                repo,
                expected_toplevel=identity.toplevel,
                expected_branch=identity.branch,
                expected_head=identity.head,
            )
            self.assertEqual("PASS", result["decision"])
            self.assertEqual([], result["mismatches"])

    def test_guard_fails_closed_after_branch_switch(self):
        with tempfile.TemporaryDirectory(dir=self.scratch) as temporary:
            repo = self.make_repo(Path(temporary))
            identity = MODULE.capture_identity(repo)
            MODULE._run(("git", "switch", "-c", "intruding-worker"), cwd=repo)
            result = MODULE.guard_checkout(
                repo,
                expected_toplevel=identity.toplevel,
                expected_branch=identity.branch,
                expected_head=identity.head,
            )
            self.assertEqual("FAIL_CLOSED", result["decision"])
            self.assertEqual(
                [
                    {
                        "field": "branch",
                        "expected": "controller",
                        "actual": "intruding-worker",
                    }
                ],
                result["mismatches"],
            )

    def test_guard_cli_uses_nonzero_exit_for_checkout_drift(self):
        with tempfile.TemporaryDirectory(dir=self.scratch) as temporary:
            repo = self.make_repo(Path(temporary))
            identity = MODULE.capture_identity(repo)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "guard",
                    "--repo",
                    str(repo),
                    "--expected-toplevel",
                    identity.toplevel,
                    "--expected-branch",
                    "wrong-branch",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(3, completed.returncode)
            self.assertEqual(
                "FAIL_CLOSED", json.loads(completed.stdout)["decision"]
            )

    def test_git_rejects_same_branch_in_second_worktree(self):
        with tempfile.TemporaryDirectory(dir=self.scratch) as temporary:
            root = Path(temporary)
            repo = self.make_repo(root)
            first = root / "first"
            second = root / "second"
            MODULE._run(
                ("git", "worktree", "add", "-b", "worker", str(first)),
                cwd=repo,
            )
            blocked = MODULE._run(
                ("git", "worktree", "add", str(second), "worker"),
                cwd=repo,
                check=False,
            )
            self.assertNotEqual(0, blocked.returncode)
            self.assertIn("already checked out", blocked.stderr)
            self.assertFalse(second.exists())


if __name__ == "__main__":
    unittest.main()
