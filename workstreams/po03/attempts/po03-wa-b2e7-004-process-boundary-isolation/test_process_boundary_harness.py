import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
HARNESS = HERE / "process_boundary_harness.py"
SCRATCH = HERE / "_test_scratch"


class ProcessBoundaryHarnessTests(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(SCRATCH, ignore_errors=True)
        SCRATCH.mkdir()
        self.addCleanup(shutil.rmtree, SCRATCH, True)

    def invoke(self, script_body: str) -> subprocess.CompletedProcess[str]:
        script = SCRATCH / "mechanism.py"
        script.write_text(script_body, encoding="utf-8")
        spec = SCRATCH / "mechanisms.json"
        spec.write_text(
            json.dumps(
                [
                    {
                        "name": "fixture-mechanism",
                        "script": "_test_scratch/mechanism.py",
                        "args": [],
                    }
                ]
            ),
            encoding="utf-8",
        )
        return subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(HARNESS),
                "--repo-root",
                str(HERE),
                "--spec",
                str(spec),
            ],
            cwd=HERE,
            capture_output=True,
            text=True,
        )

    def test_identical_canonical_output_passes(self):
        result = self.invoke("import json\nprint(json.dumps({'answer': 42}, sort_keys=True))\n")
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["all_process_boundaries_equivalent"])
        self.assertEqual([], report["mismatches"])
        self.assertEqual(
            report["mechanisms"][0]["first"],
            report["mechanisms"][0]["second"],
        )

    def test_process_specific_state_is_detected(self):
        result = self.invoke("import os\nprint(os.getpid())\n")
        self.assertEqual(1, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["all_process_boundaries_equivalent"])
        first = report["mechanisms"][0]["first"]["stdout"]
        second = report["mechanisms"][0]["second"]["stdout"]
        self.assertNotEqual(first, second)

    def test_missing_mechanism_fails_closed(self):
        spec = SCRATCH / "mechanisms.json"
        spec.write_text(
            '[{"name":"missing","script":"_test_scratch/absent.py","args":[]}]\n',
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(HARNESS),
                "--repo-root",
                str(HERE),
                "--spec",
                str(spec),
            ],
            cwd=HERE,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("absent or outside repository", result.stdout)


if __name__ == "__main__":
    unittest.main()
