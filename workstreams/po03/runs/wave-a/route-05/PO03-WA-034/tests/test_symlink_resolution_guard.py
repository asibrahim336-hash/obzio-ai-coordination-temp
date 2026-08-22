"""Falsification tests for the PO03-WA-034 symlink resolution guard.

Each test builds a sanitized temporary filesystem: an ``owned`` root that
stands in for the route subtree and an ``outside`` tree that stands in for
the rest of the repository.  The controlling assertion in the adversarial
cases is not only that the guard says no, but that the file outside the
owned root is never created or modified.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SLOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SLOT / "src" / "symlink_resolution_guard.py"
SPEC = importlib.util.spec_from_file_location("symlink_resolution_guard", MODULE_PATH)
G = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)


class SymlinkFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="po03-wa-034-")
        self.root = Path(self._tmp.name)
        self.owned = self.root / "owned"
        self.outside = self.root / "outside"
        (self.owned / "nested").mkdir(parents=True)
        self.outside.mkdir()
        (self.outside / "victim.txt").write_text("ORIGINAL", encoding="utf-8")
        self.guard = G.SymlinkResolutionGuard(str(self.owned))

    def tearDown(self):
        self._tmp.cleanup()

    def assert_victim_untouched(self):
        self.assertEqual("ORIGINAL", (self.outside / "victim.txt").read_text(encoding="utf-8"))


class ContainmentTests(SymlinkFixture):
    def test_plain_owned_path_is_allowed(self):
        decision = self.guard.evaluate("nested/report.json")
        self.assertTrue(decision.allowed(), decision.reason)

    def test_nonexistent_deep_path_is_allowed(self):
        decision = self.guard.evaluate("a/b/c/not-created-yet.json")
        self.assertTrue(decision.allowed(), decision.reason)

    def test_lexical_escape_is_rejected_before_filesystem_access(self):
        decision = self.guard.evaluate("../outside/victim.txt")
        self.assertEqual(G.VERDICT_REJECTED_OUTSIDE_ROOT_LEXICAL, decision.verdict)
        self.assertIsNone(decision.resolved_path)

    def test_symlink_to_internal_directory_is_allowed(self):
        os.symlink(self.owned / "nested", self.owned / "inward")
        decision = self.guard.evaluate("inward/ok.json")
        self.assertTrue(decision.allowed(), decision.reason)
        self.assertTrue(decision.resolved_path.startswith(str(self.guard.root)))


class BypassAttemptTests(SymlinkFixture):
    def test_final_component_symlink_escape_is_rejected(self):
        os.symlink(self.outside / "victim.txt", self.owned / "escape.txt")
        decision = self.guard.evaluate("escape.txt")
        self.assertEqual(G.VERDICT_REJECTED_SYMLINK_ESCAPE, decision.verdict)
        self.assertIn("escape.txt", decision.symlink_components)

    def test_ancestor_directory_symlink_escape_is_rejected(self):
        os.symlink(self.outside, self.owned / "sneaky")
        decision = self.guard.evaluate("sneaky/victim.txt")
        self.assertEqual(G.VERDICT_REJECTED_ANCESTOR_SYMLINK_ESCAPE, decision.verdict)

    def test_deeply_nested_ancestor_symlink_escape_is_rejected(self):
        os.symlink(self.outside, self.owned / "nested" / "hop")
        decision = self.guard.evaluate("nested/hop/deep/new.json")
        self.assertEqual(G.VERDICT_REJECTED_ANCESTOR_SYMLINK_ESCAPE, decision.verdict)

    def test_chained_symlinks_are_followed_to_the_end(self):
        os.symlink(self.outside, self.root / "hop1")
        os.symlink(self.root / "hop1", self.owned / "hop2")
        decision = self.guard.evaluate("hop2/victim.txt")
        self.assertEqual(G.VERDICT_REJECTED_ANCESTOR_SYMLINK_ESCAPE, decision.verdict)

    def test_relative_symlink_escape_is_rejected(self):
        os.symlink("../outside", self.owned / "rel")
        decision = self.guard.evaluate("rel/victim.txt")
        self.assertEqual(G.VERDICT_REJECTED_ANCESTOR_SYMLINK_ESCAPE, decision.verdict)

    def test_dangling_symlink_is_rejected(self):
        os.symlink(self.outside / "does-not-exist.txt", self.owned / "dangling.txt")
        decision = self.guard.evaluate("dangling.txt")
        self.assertEqual(G.VERDICT_REJECTED_DANGLING_SYMLINK, decision.verdict)

    def test_symlink_loop_is_reported_as_a_loop(self):
        os.symlink(self.owned / "loop_b", self.owned / "loop_a")
        os.symlink(self.owned / "loop_a", self.owned / "loop_b")
        decision = self.guard.evaluate("loop_a")
        self.assertEqual(G.VERDICT_REJECTED_SYMLINK_LOOP, decision.verdict)


class WriteEnforcementTests(SymlinkFixture):
    """The guard must fail before the write, not report after it."""

    def test_write_through_escaping_symlink_never_touches_the_target(self):
        os.symlink(self.outside / "victim.txt", self.owned / "escape.txt")
        with self.assertRaises(PermissionError) as caught:
            self.guard.open_for_write("escape.txt", b"OVERWRITTEN")
        self.assertIn(G.VERDICT_REJECTED_SYMLINK_ESCAPE, str(caught.exception))
        self.assert_victim_untouched()

    def test_write_through_escaping_directory_symlink_creates_nothing_outside(self):
        os.symlink(self.outside, self.owned / "sneaky")
        before = sorted(p.name for p in self.outside.iterdir())
        with self.assertRaises(PermissionError):
            self.guard.open_for_write("sneaky/new-file.txt", b"payload")
        self.assertEqual(before, sorted(p.name for p in self.outside.iterdir()))

    def test_unguarded_write_would_have_escaped(self):
        """Control case: without the guard the same request corrupts the victim."""
        os.symlink(self.outside / "victim.txt", self.owned / "escape.txt")
        with open(self.owned / "escape.txt", "w", encoding="utf-8") as handle:
            handle.write("CORRUPTED")
        self.assertEqual("CORRUPTED", (self.outside / "victim.txt").read_text(encoding="utf-8"))

    def test_allowed_write_lands_inside_the_owned_root(self):
        written = self.guard.open_for_write("nested/ok.txt", b"payload")
        self.assertTrue(written.startswith(self.guard.root))
        self.assertEqual(b"payload", Path(written).read_bytes())


class CommandLineTests(SymlinkFixture):
    def _run(self, *paths: str):
        return subprocess.run(
            [sys.executable, str(MODULE_PATH), "--owned-root", str(self.owned), "--json", *paths],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_clean_paths_exit_zero(self):
        proc = self._run("nested/a.json", "b.json")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["admissible"])

    def test_symlink_bypass_exits_one(self):
        os.symlink(self.outside, self.owned / "sneaky")
        proc = self._run("nested/a.json", "sneaky/victim.txt")
        self.assertEqual(1, proc.returncode)
        report = json.loads(proc.stdout)
        self.assertEqual(1, report["rejected"])

    def test_missing_root_exits_two(self):
        proc = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--owned-root", str(self.root / "nope"), "x"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(2, proc.returncode)


if __name__ == "__main__":
    unittest.main(verbosity=2)
