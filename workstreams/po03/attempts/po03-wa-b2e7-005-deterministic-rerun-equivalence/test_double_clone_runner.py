import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "double_clone_runner.py"
SCRATCH = HERE / "_test_scratch"
SPEC = importlib.util.spec_from_file_location("double_clone_runner", RUNNER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def execute(*argv: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


class DoubleCloneRunnerTests(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(SCRATCH, ignore_errors=True)
        SCRATCH.mkdir()
        self.addCleanup(shutil.rmtree, SCRATCH, True)
        self.repo = SCRATCH / "repo"
        execute("git", "init", "-q", str(self.repo), cwd=SCRATCH)
        execute("git", "config", "user.email", "fixture@example.invalid", cwd=self.repo)
        execute("git", "config", "user.name", "Fixture", cwd=self.repo)

    def commit_test(self, body: str) -> str:
        test = self.repo / "workstreams" / "po03" / "tests" / "test_fixture.py"
        test.parent.mkdir(parents=True)
        test.write_text(body, encoding="utf-8")
        execute("git", "add", ".", cwd=self.repo)
        committed = execute("git", "commit", "-qm", "fixture", cwd=self.repo)
        self.assertEqual(0, committed.returncode, committed.stderr)
        return execute("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip()

    def invoke(self, commit: str) -> subprocess.CompletedProcess[str]:
        return execute(
            sys.executable,
            "-I",
            "-B",
            str(RUNNER),
            "--source",
            str(self.repo),
            "--commit",
            commit,
            "--workspace",
            str(SCRATCH / "double-clone"),
            cwd=HERE,
        )

    def test_two_clean_clones_have_equal_canonical_output(self):
        commit = self.commit_test(
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            " def test_value(self): self.assertEqual(4, 2 + 2)\n"
            "if __name__ == '__main__': unittest.main()\n"
        )
        result = self.invoke(commit)
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["byte_equivalent"])
        self.assertEqual([True, True], report["clean_after_run"])
        self.assertEqual([], report["failed_tests"])
        self.assertEqual(
            {"unittest_elapsed_seconds": 1},
            report["normalized_fields"]["clone_a"],
        )

    def test_process_specific_output_is_not_equal(self):
        commit = self.commit_test("import os\nprint(os.getpid())\n")
        result = self.invoke(commit)
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertFalse(json.loads(result.stdout)["byte_equivalent"])

    def test_normalizer_reports_only_fields_it_changes(self):
        normalized, fields = MODULE.normalize(
            "2026-08-22T07:00:00Z\nRan 3 tests in 1.234s\n",
            Path("/unmentioned/clone"),
        )
        self.assertEqual("<TIMESTAMP>\nRan 3 tests in <ELAPSED>s\n", normalized)
        self.assertEqual(
            {"iso8601_timestamp": 1, "unittest_elapsed_seconds": 1},
            fields,
        )


if __name__ == "__main__":
    unittest.main()
