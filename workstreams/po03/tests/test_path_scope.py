import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "check_path_scope.py"
SPEC = importlib.util.spec_from_file_location("check_path_scope", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PathScopeTests(unittest.TestCase):
    def test_allowlist_accepts_only_po03_owned_paths(self):
        self.assertTrue(MODULE.is_allowed("workstreams/po03/control/work-unit-registry.jsonl"))
        self.assertTrue(MODULE.is_allowed("receipts/po03/2026-08-22/activation.json"))
        self.assertTrue(MODULE.is_allowed(".github/workflows/po03-contracts.yml"))
        self.assertFalse(MODULE.is_allowed("workstreams/po01/COMMISSION.md"))
        self.assertFalse(MODULE.is_allowed("state/ACTIVE_CONTROL_POINTER_CURRENT.json"))

    def test_deliberate_out_of_allowlist_mutation_fixture_is_rejected(self):
        escaped = MODULE.violations(
            [
                "workstreams/po03/control/legitimate.json",
                "state/must-not-change.json",
                "modules/operators/must-not-change.py",
            ]
        )
        self.assertEqual(
            ["modules/operators/must-not-change.py", "state/must-not-change.json"],
            escaped,
        )


class WorkflowScopeTests(unittest.TestCase):
    def test_po03_guard_runs_for_out_of_scope_changes_on_po03_branches(self):
        workflow = Path(__file__).parents[3] / ".github" / "workflows" / "po03-contracts.yml"
        content = workflow.read_text(encoding="utf-8")
        self.assertNotIn("  paths:", content)
        self.assertEqual(
            2,
            content.count("if: github.event_name == 'push' || startsWith(github.head_ref, 'po03/')"),
        )


if __name__ == "__main__":
    unittest.main()
