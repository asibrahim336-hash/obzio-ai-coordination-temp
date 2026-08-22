import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "clean_clone_runner.py"
SCRATCH = HERE / "_test_scratch"


def execute(*argv: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


class CleanCloneRunnerTests(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(SCRATCH, ignore_errors=True)
        SCRATCH.mkdir()
        self.addCleanup(shutil.rmtree, SCRATCH, True)

    def repository(self, test_bodies: dict[str, str]) -> tuple[Path, str]:
        repository = SCRATCH / "source"
        execute("git", "init", "-q", str(repository), cwd=SCRATCH)
        execute("git", "config", "user.email", "fixture@example.invalid", cwd=repository)
        execute("git", "config", "user.name", "Fixture", cwd=repository)
        for relative, body in test_bodies.items():
            path = repository / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        execute("git", "add", ".", cwd=repository)
        committed = execute("git", "commit", "-qm", "fixture", cwd=repository)
        self.assertEqual(0, committed.returncode, committed.stderr)
        commit = execute("git", "rev-parse", "HEAD", cwd=repository).stdout.strip()
        return repository, commit

    def invoke(self, repository: Path, commit: str) -> subprocess.CompletedProcess[str]:
        return execute(
            sys.executable,
            "-I",
            str(RUNNER),
            "--source",
            str(repository),
            "--commit",
            commit,
            "--destination",
            str(SCRATCH / "clone"),
            cwd=HERE,
        )

    def test_discovers_nested_committed_tests_by_file_path(self):
        passing = "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\nif __name__ == '__main__': unittest.main()\n"
        repository, commit = self.repository(
            {
                "workstreams/po03/tests/test_base.py": passing,
                "workstreams/po03/attempts/unit/test_nested.py": passing,
            }
        )
        result = self.invoke(repository, commit)
        self.assertEqual(0, result.returncode, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(2, summary["test_count"])
        self.assertEqual([], summary["failed_tests"])
        self.assertFalse(summary["dirty_after_run"])

    def test_rejects_nonimmutable_commit_name(self):
        repository, _ = self.repository(
            {"workstreams/po03/tests/test_base.py": "raise AssertionError('not executed')\n"}
        )
        result = self.invoke(repository, "HEAD")
        self.assertEqual(2, result.returncode)
        self.assertIn("full lowercase Git object ID", result.stdout)

    def test_fails_closed_when_test_dirties_clone(self):
        body = (
            "from pathlib import Path\n"
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            " def test_writes(self): Path('generated.txt').write_text('state')\n"
            "if __name__ == '__main__': unittest.main()\n"
        )
        repository, commit = self.repository({"workstreams/po03/tests/test_dirty.py": body})
        result = self.invoke(repository, commit)
        self.assertEqual(3, result.returncode)
        summary = json.loads(result.stdout)
        self.assertTrue(summary["dirty_after_run"])
        self.assertIn("generated.txt", summary["working_tree_status"])


if __name__ == "__main__":
    unittest.main()
