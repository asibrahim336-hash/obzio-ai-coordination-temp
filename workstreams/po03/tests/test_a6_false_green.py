import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "workstreams" / "po03" / "review" / "luna" / "false_green.py"
SPEC = importlib.util.spec_from_file_location("false_green", SCRIPT)
FALSE_GREEN = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(FALSE_GREEN)


class FalseGreenDetectorTests(unittest.TestCase):
    def test_mutates_fixture_and_reports_under_asserting_test(self):
        with tempfile.TemporaryDirectory(prefix="po03-fg-test-") as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            (root / "impl.py").write_text(
                "def is_even(value):\n    return value % 2 == 0\n",
                encoding="utf-8",
            )
            (root / "tests" / "test_impl.py").write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "import unittest\n"
                "sys.path.insert(0, str(Path(__file__).parents[1]))\n"
                "from impl import is_even\n\n"
                "class EvenTests(unittest.TestCase):\n"
                "    def test_even_only(self):\n"
                "        self.assertTrue(is_even(2))\n",
                encoding="utf-8",
            )
            mutations = [
                {
                    "id": "weak-test-accepts-always-true",
                    "path": "impl.py",
                    "old": "return value % 2 == 0",
                    "new": "return True",
                },
                {
                    "id": "real-behavior-break",
                    "path": "impl.py",
                    "old": "return value % 2 == 0",
                    "new": "return value % 2 == 1",
                },
            ]
            mutations_path = root / "mutations.json"
            mutations_path.write_text(json.dumps(mutations), encoding="utf-8")
            report = FALSE_GREEN.run_mutations(
                root,
                mutations_path,
                "python3 -I -m unittest discover -s tests -p test_*.py",
            )
            self.assertEqual(2, report["mutation_count"])
            self.assertEqual(1, report["false_green_count"])
            by_id = {item["id"]: item for item in report["results"]}
            self.assertTrue(by_id["weak-test-accepts-always-true"]["false_green"])
            self.assertFalse(by_id["real-behavior-break"]["false_green"])


if __name__ == "__main__":
    unittest.main()
