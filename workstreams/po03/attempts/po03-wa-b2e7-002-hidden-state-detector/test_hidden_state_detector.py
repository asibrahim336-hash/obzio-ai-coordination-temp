import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
DETECTOR = HERE / "hidden_state_detector.py"
SCRATCH = HERE / "_test_scratch"


def execute(*argv: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


class HiddenStateDetectorTests(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(SCRATCH, ignore_errors=True)
        SCRATCH.mkdir()
        self.addCleanup(shutil.rmtree, SCRATCH, True)
        self.repo = SCRATCH / "repo"
        execute("git", "init", "-q", str(self.repo), cwd=SCRATCH)
        execute("git", "config", "user.email", "fixture@example.invalid", cwd=self.repo)
        execute("git", "config", "user.name", "Fixture", cwd=self.repo)
        (self.repo / "probe.py").write_text(
            "from pathlib import Path\nprint('warm' if Path('.warm-state').exists() else 'pristine')\n",
            encoding="utf-8",
        )
        execute("git", "add", "probe.py", cwd=self.repo)
        committed = execute("git", "commit", "-qm", "fixture", cwd=self.repo)
        self.assertEqual(0, committed.returncode, committed.stderr)
        self.commit = execute("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip()

    def invoke(self, commit: str | None = None) -> subprocess.CompletedProcess[str]:
        return execute(
            sys.executable,
            "-I",
            str(DETECTOR),
            "--repo",
            str(self.repo),
            "--commit",
            commit or self.commit,
            "--scratch",
            str(SCRATCH / "export"),
            "--",
            sys.executable,
            "-I",
            "-B",
            "probe.py",
            cwd=HERE,
        )

    def test_reports_uncommitted_behavioral_divergence(self):
        (self.repo / ".warm-state").write_text("uncommitted\n", encoding="utf-8")
        result = self.invoke()
        self.assertEqual(1, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["hidden_state_dependence"])
        self.assertEqual("warm\n", report["warm"]["stdout"])
        self.assertEqual("pristine\n", report["pristine"]["stdout"])

    def test_equivalent_behavior_is_not_misclassified(self):
        result = self.invoke()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(json.loads(result.stdout)["hidden_state_dependence"])

    def test_rejects_commit_other_than_working_head(self):
        result = self.invoke("0" * 40)
        self.assertEqual(2, result.returncode)
        self.assertIn("HEAD does not equal requested commit", result.stdout)


if __name__ == "__main__":
    unittest.main()
