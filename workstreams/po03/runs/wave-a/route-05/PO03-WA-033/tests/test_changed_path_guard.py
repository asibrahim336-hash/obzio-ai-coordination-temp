"""Falsification tests for the PO03-WA-033 changed-path guard.

Every fixture is created inside a throwaway temporary directory; the tests
never read or write repository state outside this task slot.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SLOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SLOT / "src" / "changed_path_guard.py"
SPEC = importlib.util.spec_from_file_location("changed_path_guard", MODULE_PATH)
G = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
# Registering before execution keeps dataclass field resolution working for a
# module loaded straight from a path.
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)


OWNED = "workstreams/po03/runs/wave-a/route-05/PO03-WA-033/"


class NormalisationTests(unittest.TestCase):
    def test_dot_slash_prefix_is_collapsed(self):
        normalised, verdict, _ = G.normalise_repo_path("./a/b.txt")
        self.assertEqual("a/b.txt", normalised)
        self.assertEqual(G.VERDICT_ALLOWED, verdict)

    def test_redundant_separators_collapse(self):
        normalised, _, _ = G.normalise_repo_path("a//b/./c.txt")
        self.assertEqual("a/b/c.txt", normalised)

    def test_absolute_path_is_rejected_not_normalised(self):
        _, verdict, _ = G.normalise_repo_path("/etc/passwd")
        self.assertEqual(G.VERDICT_REJECTED_ABSOLUTE, verdict)

    def test_drive_qualified_path_is_rejected(self):
        _, verdict, _ = G.normalise_repo_path("C:/windows/system32")
        self.assertEqual(G.VERDICT_REJECTED_ABSOLUTE, verdict)

    def test_nul_byte_is_rejected(self):
        _, verdict, _ = G.normalise_repo_path("a/b\x00c")
        self.assertEqual(G.VERDICT_REJECTED_MALFORMED, verdict)

    def test_root_relative_dot_is_rejected(self):
        _, verdict, _ = G.normalise_repo_path(".")
        self.assertEqual(G.VERDICT_REJECTED_MALFORMED, verdict)


class ContainmentTests(unittest.TestCase):
    def setUp(self):
        self.guard = G.ChangedPathGuard([OWNED])

    def test_owned_path_is_allowed(self):
        decision = self.guard.evaluate(OWNED + "src/changed_path_guard.py")
        self.assertTrue(decision.allowed())
        self.assertEqual(OWNED, decision.matched_rule)

    def test_deliberate_out_of_allowlist_mutation_is_rejected(self):
        decision = self.guard.evaluate("docs/roadmap.md")
        self.assertEqual(G.VERDICT_REJECTED_NOT_IN_ALLOWLIST, decision.verdict)
        self.assertIsNone(decision.matched_rule)

    def test_sibling_route_is_rejected(self):
        decision = self.guard.evaluate("workstreams/po03/runs/wave-a/route-04/PO03-WA-025/x.json")
        self.assertEqual(G.VERDICT_REJECTED_NOT_IN_ALLOWLIST, decision.verdict)

    def test_shared_control_path_is_rejected(self):
        decision = self.guard.evaluate("workstreams/po03/control/leases/route-05.json")
        self.assertEqual(G.VERDICT_REJECTED_NOT_IN_ALLOWLIST, decision.verdict)

    def test_prefix_match_respects_component_boundary(self):
        """`route-05/PO03-WA-033` must not admit `route-05/PO03-WA-0330`."""
        guard = G.ChangedPathGuard(["workstreams/po03/runs/wave-a/route-05/PO03-WA-033/"])
        decision = guard.evaluate("workstreams/po03/runs/wave-a/route-05/PO03-WA-0330/x")
        self.assertEqual(G.VERDICT_REJECTED_NOT_IN_ALLOWLIST, decision.verdict)

    def test_dot_dot_traversal_out_of_owned_subtree_is_rejected(self):
        decision = self.guard.evaluate(OWNED + "../../route-04/stolen.json")
        self.assertEqual(G.VERDICT_REJECTED_NOT_IN_ALLOWLIST, decision.verdict)
        self.assertEqual("workstreams/po03/runs/wave-a/route-04/stolen.json", decision.normalised_path)

    def test_traversal_above_repository_root_is_a_distinct_verdict(self):
        decision = self.guard.evaluate("../../../etc/hosts")
        self.assertEqual(G.VERDICT_REJECTED_ESCAPES_ROOT, decision.verdict)

    def test_cosmetic_spelling_cannot_smuggle_a_write(self):
        decision = self.guard.evaluate("./workstreams/po03//control/./outbox.jsonl")
        self.assertEqual(G.VERDICT_REJECTED_NOT_IN_ALLOWLIST, decision.verdict)

    def test_double_star_suffix_is_accepted_as_a_subtree_rule(self):
        guard = G.ChangedPathGuard([OWNED.rstrip("/") + "/**"])
        self.assertTrue(guard.evaluate(OWNED + "tests/t.py").allowed())

    def test_exact_file_rule_does_not_admit_siblings(self):
        guard = G.ChangedPathGuard(["a/b/exact.json"])
        self.assertTrue(guard.evaluate("a/b/exact.json").allowed())
        self.assertFalse(guard.evaluate("a/b/exact.json.bak").allowed())

    def test_empty_allowlist_rejects_everything(self):
        guard = G.ChangedPathGuard([])
        self.assertFalse(guard.evaluate(OWNED + "x").allowed())

    def test_allowlist_entry_escaping_root_is_refused(self):
        with self.assertRaises(G.AllowlistError):
            G.ChangedPathGuard(["../outside/"])

    def test_absolute_allowlist_entry_is_refused(self):
        with self.assertRaises(G.AllowlistError):
            G.ChangedPathGuard(["/workspace/workstreams/"])


class ReportTests(unittest.TestCase):
    def test_report_counts_reconcile(self):
        guard = G.ChangedPathGuard([OWNED])
        report = G.build_report(guard, [OWNED + "a", "docs/b", OWNED + "c"])
        self.assertEqual(3, report["evaluated"])
        self.assertEqual(2, report["allowed"])
        self.assertEqual(1, report["rejected"])
        self.assertFalse(report["admissible"])
        self.assertEqual(report["evaluated"], report["allowed"] + report["rejected"])


class CommandLineTests(unittest.TestCase):
    """The adversarial fixture: a real changeset containing one deliberate escape."""

    def _run(self, allowlist: list[str], changed: list[str]):
        with tempfile.TemporaryDirectory(prefix="po03-wa-033-") as tmp:
            root = Path(tmp)
            (root / "allowlist.txt").write_text("\n".join(allowlist) + "\n", encoding="utf-8")
            (root / "changed.txt").write_text("\n".join(changed) + "\n", encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--allowlist-file",
                    str(root / "allowlist.txt"),
                    "--changed-paths-file",
                    str(root / "changed.txt"),
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_clean_changeset_exits_zero(self):
        proc = self._run([OWNED], [OWNED + "src/changed_path_guard.py", OWNED + "result.json"])
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["admissible"])

    def test_deliberate_out_of_allowlist_mutation_exits_one(self):
        proc = self._run(
            [OWNED],
            [OWNED + "src/changed_path_guard.py", "workstreams/po03/control/leases/route-05.json"],
        )
        self.assertEqual(1, proc.returncode)
        report = json.loads(proc.stdout)
        self.assertEqual(1, report["rejected"])
        rejected = [d for d in report["decisions"] if d["verdict"] != G.VERDICT_ALLOWED]
        self.assertEqual("workstreams/po03/control/leases/route-05.json", rejected[0]["raw_path"])

    def test_unusable_allowlist_exits_two(self):
        proc = self._run(["/absolute/"], [OWNED + "x"])
        self.assertEqual(2, proc.returncode)
        self.assertIn("USAGE_ERROR", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
