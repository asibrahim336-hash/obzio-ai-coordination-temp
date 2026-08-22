import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "network_denied_runner.py"
SCRATCH = HERE / "_test_scratch"


def execute(*argv: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


class NetworkDeniedRunnerTests(unittest.TestCase):
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
            str(SCRATCH / "denied"),
            cwd=HERE,
        )

    def test_offline_standard_library_test_passes(self):
        commit = self.commit_test(
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            " def test_value(self): self.assertEqual(9, 3 * 3)\n"
            "if __name__ == '__main__': unittest.main()\n"
        )
        result = self.invoke(commit)
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("SUPPORTED", report["network_namespace_preflight"])
        self.assertEqual([], report["network_dependency_failures"])
        self.assertEqual([], report["unrelated_failures"])
        self.assertTrue(report["clean_after_run"])

    def test_network_attempt_is_classified_as_dependence(self):
        commit = self.commit_test(
            "import socket\n"
            "sock = socket.socket()\n"
            "sock.settimeout(0.2)\n"
            "sock.connect(('198.51.100.1', 443))\n"
        )
        result = self.invoke(commit)
        self.assertEqual(1, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(
            ["workstreams/po03/tests/test_fixture.py"],
            report["network_dependency_failures"],
        )
        self.assertEqual([], report["unrelated_failures"])

    def test_assertion_failure_is_classified_as_unrelated(self):
        commit = self.commit_test("raise AssertionError('fixture defect')\n")
        result = self.invoke(commit)
        self.assertEqual(1, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual([], report["network_dependency_failures"])
        self.assertEqual(
            ["workstreams/po03/tests/test_fixture.py"],
            report["unrelated_failures"],
        )


if __name__ == "__main__":
    unittest.main()
