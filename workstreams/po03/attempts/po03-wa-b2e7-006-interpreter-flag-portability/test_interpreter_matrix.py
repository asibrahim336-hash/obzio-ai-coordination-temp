import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "interpreter_matrix.py"
SCRATCH = HERE / "_test_scratch"


def execute(*argv: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


class InterpreterMatrixTests(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(SCRATCH, ignore_errors=True)
        SCRATCH.mkdir()
        self.addCleanup(shutil.rmtree, SCRATCH, True)
        self.repo = SCRATCH / "repo"
        execute("git", "init", "-q", str(self.repo), cwd=SCRATCH)
        execute("git", "config", "user.email", "fixture@example.invalid", cwd=self.repo)
        execute("git", "config", "user.name", "Fixture", cwd=self.repo)

    def commit_test(self, body: str) -> str:
        path = self.repo / "workstreams" / "po03" / "tests" / "test_fixture.py"
        path.parent.mkdir(parents=True)
        path.write_text(body, encoding="utf-8")
        execute("git", "add", ".", cwd=self.repo)
        result = execute("git", "commit", "-qm", "fixture", cwd=self.repo)
        self.assertEqual(0, result.returncode, result.stderr)
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
            str(SCRATCH / "matrix"),
            cwd=HERE,
        )

    def test_standard_library_test_passes_both_matrices(self):
        commit = self.commit_test(
            "import json\nimport unittest\n"
            "class T(unittest.TestCase):\n"
            " def test_json(self): self.assertEqual('1', json.dumps(1))\n"
            "if __name__ == '__main__': unittest.main()\n"
        )
        result = self.invoke(commit)
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual([["-I"], ["-I", "-S"]], report["matrices"])
        self.assertEqual(2, report["matrix_case_count"])
        self.assertEqual([], report["failed_cases"])
        self.assertEqual([], report["imports_escaping_standard_environment"])
        self.assertTrue(report["clean_after_run"])

    def test_missing_external_import_is_recorded(self):
        commit = self.commit_test("import definitely_missing_vendor_package\n")
        result = self.invoke(commit)
        self.assertEqual(1, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(2, len(report["failed_cases"]))
        self.assertEqual(
            {"definitely_missing_vendor_package"},
            {
                item["module"]
                for item in report["imports_escaping_standard_environment"]
            },
        )

    def test_nonimmutable_commit_is_rejected(self):
        result = self.invoke("HEAD")
        self.assertEqual(2, result.returncode)
        self.assertIn("full object ID", result.stdout)


if __name__ == "__main__":
    unittest.main()
