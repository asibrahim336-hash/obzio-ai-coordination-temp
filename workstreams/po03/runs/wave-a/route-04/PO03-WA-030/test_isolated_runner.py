import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("isolated_runner.py")
SPEC = importlib.util.spec_from_file_location("wa030_isolated", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class IsolatedRunnerTests(unittest.TestCase):
    def test_empty_home_and_ambient_secret_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "probe.py").write_text(
                "import json, os\n"
                "assert os.environ.get('HOME') == ''\n"
                "assert 'AMBIENT_SECRET' not in os.environ\n"
                "print(json.dumps({'home': os.environ['HOME'], "
                "'secret': os.environ.get('AMBIENT_SECRET')}))\n",
                encoding="utf-8",
            )
            report = MODULE.run_isolated(
                root,
                "probe.py",
                [],
                ambient={"AMBIENT_SECRET": "must-not-leak"},
            )
            self.assertEqual("PASS", report["disposition"])
            self.assertEqual({"home": "", "secret": None}, json.loads(report["stdout"]))
            self.assertEqual([], report["ambient_keys_inherited"])

    def test_hidden_pythonpath_cannot_supply_missing_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root / "ambient"
            helper.mkdir()
            (helper / "undeclared_helper.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "probe.py").write_text("import undeclared_helper\n", encoding="utf-8")
            report = MODULE.run_isolated(
                root,
                "probe.py",
                [],
                ambient={"PYTHONPATH": str(helper)},
            )
            self.assertEqual("FAIL", report["disposition"])
            self.assertIn("ModuleNotFoundError", report["stderr"])

    def test_only_explicit_namespaced_values_survive(self):
        environment = MODULE.sanitized_environment(
            {"PO03_DECLARED_MODE": "portable", "UNDECLARED": "drop"}
        )
        self.assertEqual("portable", environment["PO03_DECLARED_MODE"])
        self.assertNotIn("UNDECLARED", environment)


if __name__ == "__main__":
    unittest.main()
