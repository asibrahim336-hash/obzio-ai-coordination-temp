import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "check_path_scope.py"
SPEC = importlib.util.spec_from_file_location("check_path_scope", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PathScopeTests(unittest.TestCase):
    def test_all_commissioned_prefixes_are_allowed(self):
        paths = [
            "workstreams/po03/tools/controller.py",
            "receipts/po03/2026-08-22/result.json",
            ".github/workflows/po03-clean-runtime.yml",
        ]
        self.assertEqual([], MODULE.violations(paths))

    def test_deliberate_out_of_allowlist_mutation_fixture_is_rejected(self):
        fixture = "state/PO03-SHOULD-NOT-WRITE.json"
        self.assertEqual([fixture], MODULE.violations([fixture]))

    def test_po01_path_is_rejected(self):
        fixture = "workstreams/po01/producer-result.json"
        self.assertEqual([fixture], MODULE.violations([fixture]))

    def test_pr8_environment_path_is_rejected(self):
        fixture = ".cursor/environment.json"
        self.assertEqual([fixture], MODULE.violations([fixture]))

    def test_similar_workflow_name_is_rejected(self):
        fixture = ".github/workflows/not-po03.yml"
        self.assertEqual([fixture], MODULE.violations([fixture]))

    def test_non_yml_po03_workflow_is_rejected(self):
        fixture = ".github/workflows/po03-guard.yaml"
        self.assertEqual([fixture], MODULE.violations([fixture]))

    def test_traversal_and_backslash_are_rejected(self):
        paths = ["workstreams/po03/../po01/x", "workstreams\\po03\\x"]
        self.assertEqual(sorted(paths), MODULE.violations(paths))


if __name__ == "__main__":
    unittest.main()
