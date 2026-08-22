"""Evasion cover for the changed-path allowlist guard.

A prefix-and-suffix test over `.github/workflows/po03-` admitted nested paths
such as `.github/workflows/po03-a/b.yml`, which is an allowlist bypass rather
than a cosmetic issue: the commissioned glob permits one file directly in that
directory, not a subtree.
"""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "check_path_scope.py"
SPEC = importlib.util.spec_from_file_location("check_path_scope_hardening", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class WorkflowAllowlistTests(unittest.TestCase):
    def test_a_nested_path_under_the_workflow_prefix_is_refused(self):
        for path in (
            ".github/workflows/po03-a/b.yml",
            ".github/workflows/po03-x/y/z.yml",
            ".github/workflows/po03-dir/nested/deep.yml",
        ):
            self.assertFalse(MODULE.is_allowed(path), path)

    def test_a_single_workflow_file_is_allowed(self):
        for path in (
            ".github/workflows/po03-suite.yml",
            ".github/workflows/po03-contracts.yml",
            ".github/workflows/po03-path-scope.yml",
        ):
            self.assertTrue(MODULE.is_allowed(path), path)

    def test_unrelated_workflows_are_refused(self):
        for path in (
            ".github/workflows/ci.yml",
            ".github/workflows/operator-taxonomy-currentness.yml",
            ".github/workflows/po04-suite.yml",
            ".github/workflows/po03-suite.yaml",
            ".github/workflows/po03-suite.yml.bak",
        ):
            self.assertFalse(MODULE.is_allowed(path), path)

    def test_traversal_and_non_canonical_paths_are_refused(self):
        # A non-canonical path raises from the predicate; violations() is the
        # entry point that must classify it as a violation rather than crash.
        candidates = [
            "../escape.json",
            "/absolute/escape.json",
            "workstreams/po03/../../state/escape.json",
            ".github/workflows/po03-x/../../../evil.yml",
            "workstreams\\po03\\windows.json",
        ]
        self.assertEqual(sorted(candidates), MODULE.violations(candidates))

    def test_in_scope_prefixes_are_allowed(self):
        for path in (
            "workstreams/po03/control/work-unit-registry.jsonl",
            "receipts/po03/2026-08-22/dispatch-authorization.json",
        ):
            self.assertTrue(MODULE.is_allowed(path), path)

    def test_out_of_scope_prefixes_are_refused(self):
        for path in (
            "state/ACTIVE_CONTROL_POINTER_CURRENT.json",
            "packs/operator-packs-v1/manifest.json",
            "modules/operators/thing.py",
            "_transport/debris.tar",
            ".cursor/environment.json",
            "workstreams/po04/other.json",
            "receipts/po01/thing.json",
        ):
            self.assertFalse(MODULE.is_allowed(path), path)


class RenameAndModeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repository"
        self.repo.mkdir()
        self._git("init", "--quiet")
        self._git("config", "user.email", "po03@obzio.invalid")
        self._git("config", "user.name", "PO-03 Test")
        inside = self.repo / "workstreams" / "po03" / "attempts" / "unit"
        inside.mkdir(parents=True)
        (inside / "payload.txt").write_text("payload\n" * 8, encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "--quiet", "-m", "base")
        self.base = self._git("rev-parse", "HEAD")

    def _git(self, *arguments):
        return subprocess.run(
            ("git", *arguments), cwd=self.repo, check=True, capture_output=True, text=True
        ).stdout.strip()

    def _with_module_cwd(self, function, *arguments):
        import os

        previous = os.getcwd()
        os.chdir(self.repo)
        try:
            return function(*arguments)
        finally:
            os.chdir(previous)

    def test_a_rename_out_of_scope_exposes_both_images(self):
        outside = self.repo / "state"
        outside.mkdir()
        self._git("mv", "workstreams/po03/attempts/unit/payload.txt", "state/payload.txt")
        self._git("commit", "--quiet", "-m", "move out of scope")
        head = self._git("rev-parse", "HEAD")
        paths = self._with_module_cwd(MODULE.changed_paths, self.base, head)
        self.assertIn("state/payload.txt", paths)
        self.assertTrue(MODULE.violations(paths), "a move out of the allowlist must be a violation")

    def test_a_symlink_is_reported_rather_than_trusted_by_name(self):
        import os

        link = self.repo / "workstreams" / "po03" / "attempts" / "unit" / "link.txt"
        os.symlink("../../../../../state/secret.txt", link)
        self._git("add", "-A")
        self._git("commit", "--quiet", "-m", "add symlink with an in-scope name")
        head = self._git("rev-parse", "HEAD")
        paths = self._with_module_cwd(MODULE.changed_paths, self.base, head)
        self.assertIn("workstreams/po03/attempts/unit/link.txt", paths)
        self.assertEqual([], MODULE.violations(paths), "the name itself is in scope")
        flagged = self._with_module_cwd(MODULE.non_plain_entries, self.base, head)
        self.assertTrue(any("symlink" in entry for entry in flagged), flagged)

    def test_an_ordinary_in_scope_change_is_clean(self):
        target = self.repo / "workstreams" / "po03" / "attempts" / "unit" / "payload.txt"
        target.write_text("changed\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "--quiet", "-m", "in-scope edit")
        head = self._git("rev-parse", "HEAD")
        paths = self._with_module_cwd(MODULE.changed_paths, self.base, head)
        self.assertEqual(["workstreams/po03/attempts/unit/payload.txt"], paths)
        self.assertEqual([], MODULE.violations(paths))
        self.assertEqual([], self._with_module_cwd(MODULE.non_plain_entries, self.base, head))


if __name__ == "__main__":
    unittest.main()
