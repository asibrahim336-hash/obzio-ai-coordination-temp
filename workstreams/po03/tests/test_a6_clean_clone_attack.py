import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "workstreams" / "po03" / "review" / "luna" / "clean_clone_attack.py"
SPEC = importlib.util.spec_from_file_location("clean_clone_attack", SCRIPT)
ATTACK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ATTACK)


class CleanCloneAttackTests(unittest.TestCase):
    def test_fetched_a3_commit_probe_records_missing_transcript(self):
        result = ATTACK.probe("FETCH_HEAD")
        self.assertEqual("ESCAPE_FOUND", result["status"])
        self.assertTrue(result["objects"]["runner"]["present"])
        self.assertTrue(result["objects"]["tests"]["present"])
        self.assertFalse(result["objects"]["transcript"]["present"])
        self.assertIn(
            "workstreams/po03/tests/__pycache__/test_validate_contracts.cpython-312.pyc",
            result["tracked_generated_files"],
        )
        self.assertTrue(result["runner_checks"]["runner_shell_syntax"])
        self.assertTrue(result["runner_checks"]["runner_clones_remote"])
        self.assertTrue(result["runner_checks"]["runner_strips_environment"])
        self.assertTrue(result["runner_checks"]["runner_rejects_inside_repo_scratch"])


if __name__ == "__main__":
    unittest.main()
