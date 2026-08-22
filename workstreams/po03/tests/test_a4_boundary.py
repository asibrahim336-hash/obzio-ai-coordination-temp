import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workstreams.po03.packverify.boundary_run import (
    run_process,
    sanitized_environment,
)


SCRATCH = ROOT / "workstreams/po03/control/units/a4/test-scratch"


class ProcessBoundaryFixtureTests(unittest.TestCase):
    def test_entrypoint_runs_in_distinct_sanitized_process(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as temporary:
            workspace = Path(temporary)
            environment = sanitized_environment(workspace)
            result = run_process(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    "import os; print(os.getpid()); print(os.environ['HOME'])",
                ],
                cwd=workspace,
                environment=environment,
                timeout_seconds=10,
            )
            lines = result["stdout"].splitlines()
            self.assertEqual(result["exit_code"], 0)
            self.assertNotEqual(int(lines[0]), os.getpid())
            self.assertEqual(lines[1], str(workspace / "home"))
            self.assertFalse(result["timed_out"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(SCRATCH, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
