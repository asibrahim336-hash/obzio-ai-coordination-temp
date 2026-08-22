import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
HARNESS = HERE / "warm_checkout_adversarial.py"
FIXTURE = HERE / "warm_only_fixture.py"
CLEAN_RUNNER = (
    HERE.parent
    / "po03-wa-b2e7-001-clean-clone-runner"
    / "clean_clone_runner.py"
)
SCRATCH = HERE / "_test_scratch"


class WarmCheckoutAdversarialTests(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(SCRATCH, ignore_errors=True)
        SCRATCH.mkdir()
        self.addCleanup(shutil.rmtree, SCRATCH, True)

    def invoke(
        self,
        runner: Path = CLEAN_RUNNER,
        fixture: Path = FIXTURE,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(HARNESS),
                "--fixture",
                str(fixture),
                "--clean-runner",
                str(runner),
                "--workspace",
                str(SCRATCH / "exercise"),
            ],
            cwd=HERE,
            capture_output=True,
            text=True,
        )

    def test_real_clean_clone_runner_catches_warm_only_gate(self):
        result = self.invoke()
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["warm_checkout_dependence_caught"])
        self.assertFalse(report["warm_marker_tracked"])
        self.assertEqual(0, report["warm_returncode"])
        self.assertNotEqual(0, report["clean_runner_returncode"])
        self.assertEqual(
            ["workstreams/po03/tests/test_warm_only.py"],
            report["clean_runner_report"]["failed_tests"],
        )

    def test_vacuous_green_runner_is_rejected(self):
        fake = SCRATCH / "vacuous_runner.py"
        fake.write_text(
            "import json\nprint(json.dumps({'failed_tests': []}))\n",
            encoding="utf-8",
        )
        result = self.invoke(fake)
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertFalse(json.loads(result.stdout)["warm_checkout_dependence_caught"])

    def test_missing_required_fixture_fails_closed(self):
        result = self.invoke(fixture=SCRATCH / "absent.py")
        self.assertEqual(2, result.returncode)
        self.assertIn("must exist", result.stdout)


if __name__ == "__main__":
    unittest.main()
