"""Tests for PO-03 path-guard hardening.

The hypothesis under test is that the path-scope guard resists traversal,
symlink, unicode and case-variation evasion.  It is refuted on the symlink
clause: the guard in `workstreams/po03/tools/check_path_scope.py` admits an
in-allowlist name whose blob is a symlink pointing out of the allowlist, and
admits a rename that deletes a file outside the allowlist.  Traversal, unicode
and case variation are genuinely resisted and the tests say so.

Each evasion class is asserted twice: once against the legacy guard to record
what it really does, and once against the hardened guard to prove the class is
now refused.
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = UNIT_ROOT.parents[3]
HARDENED_PATH = UNIT_ROOT / "hardened_path_scope.py"
MATRIX_PATH = UNIT_ROOT / "evasion_matrix.py"
LEGACY_PATH = REPO_ROOT / "workstreams/po03/tools/check_path_scope.py"


def load(module_path, name):
    specification = importlib.util.spec_from_file_location(name, module_path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


HARDENED = load(HARDENED_PATH, "po03_hardened_under_test")
MATRIX = load(MATRIX_PATH, "po03_matrix_under_test")
LEGACY = load(LEGACY_PATH, "po03_legacy_under_test")


def refuses_by_name(module, path):
    """True when a guard module refuses a path judged by name alone."""
    if module is LEGACY:
        return bool(module.violations([path]))
    return bool(module.evaluate([module.ChangedEntry(status="A", path=path)]))


class NormalizeTests(unittest.TestCase):
    def assertRefused(self, path):
        with self.assertRaises(HARDENED.ScopeError, msg=path):
            HARDENED.normalize(path)

    def test_canonical_paths_are_returned_unchanged(self):
        for path in ("workstreams/po03/a.py", "receipts/po03/x.json", ".github/workflows/po03-a.yml"):
            self.assertEqual(path, HARDENED.normalize(path))

    def test_traversal_spellings_are_refused(self):
        for path in ("..", "../x", "workstreams/po03/../state/x", "workstreams/po03/./x"):
            self.assertRefused(path)

    def test_absolute_and_separator_abuse_is_refused(self):
        for path in ("/workstreams/po03/x", "workstreams\\po03\\x", "workstreams/po03//x",
                     "workstreams/po03/x/", ""):
            self.assertRefused(path)

    def test_nul_and_control_characters_are_refused(self):
        for path in ("workstreams/po03/x\x00.py", "workstreams/po03/x\ny", "workstreams/po03/x\ty"):
            self.assertRefused(path)

    def test_bidi_and_zero_width_characters_are_refused(self):
        for character in ("\u202e", "\u200b", "\u200f", "\ufeff", "\u00ad", "\u2066"):
            self.assertRefused(f"workstreams/po03/{character}name.txt")

    def test_non_ascii_is_refused_as_a_deliberate_narrowing(self):
        for path in ("workstreams/po03/caf\u00e9.txt", "workstreams/p\u043e03/x", "\uff57orkstreams/po03/x"):
            self.assertRefused(path)

    def test_trailing_dot_or_space_components_are_refused(self):
        for path in ("workstreams/po03/x.", "workstreams/po03/x ", " workstreams/po03/x",
                     "workstreams/po03./x"):
            self.assertRefused(path)


class GlobMatchingTests(unittest.TestCase):
    def test_wildcard_does_not_cross_a_directory_boundary(self):
        pattern = ".github/workflows/po03-*.yml"
        self.assertTrue(HARDENED.matches_glob(".github/workflows/po03-suite.yml", pattern))
        self.assertTrue(HARDENED.matches_glob(".github/workflows/po03-.yml", pattern))
        self.assertFalse(HARDENED.matches_glob(".github/workflows/po03-a/b.yml", pattern))
        self.assertFalse(HARDENED.matches_glob(".github/workflows/po03-a.yaml", pattern))
        self.assertFalse(HARDENED.matches_glob(".github/workflows/not-po03.yml", pattern))

    def test_glob_matching_is_case_sensitive(self):
        self.assertFalse(HARDENED.matches_glob(".github/workflows/PO03-a.yml", ALLOW_GLOB()))

    def test_nested_workflow_path_is_reported_as_a_glob_mismatch(self):
        finding = HARDENED.classify(".github/workflows/po03-a/b.yml")
        self.assertIsNotNone(finding)
        self.assertTrue(finding.startswith("WORKFLOW_GLOB_MISMATCH"), finding)


def ALLOW_GLOB():
    return HARDENED.ALLOW_GLOBS[0]


class LegacyGuardBehaviourTests(unittest.TestCase):
    """Record what the live guard really does, in both directions."""

    def test_legacy_guard_already_resists_traversal_absolute_backslash_and_nul(self):
        for path in ("workstreams/po03/../state/x", "/workstreams/po03/x",
                     "workstreams\\po03\\x", "workstreams/po03/x\x00.py"):
            self.assertTrue(refuses_by_name(LEGACY, path), f"legacy admitted {path!r}")

    def test_legacy_guard_already_resists_unicode_confusables_and_case_variants(self):
        for path in ("workstreams/p\u043e03/x", "\uff57orkstreams/po03/x",
                     "WORKSTREAMS/PO03/x", ".github/workflows/PO03-a.yml"):
            self.assertTrue(refuses_by_name(LEGACY, path), f"legacy admitted {path!r}")

    def test_legacy_guard_admits_a_nested_workflow_path_the_allowlist_glob_excludes(self):
        self.assertFalse(refuses_by_name(LEGACY, ".github/workflows/po03-a/b.yml"))
        self.assertTrue(refuses_by_name(HARDENED, ".github/workflows/po03-a/b.yml"))

    def test_legacy_guard_admits_trailing_dot_and_bidi_names_inside_the_allowlist(self):
        for path in ("workstreams/po03/x.", "workstreams/po03/x ", "workstreams/po03/\u202egnp.txt"):
            self.assertFalse(refuses_by_name(LEGACY, path), path)
            self.assertTrue(refuses_by_name(HARDENED, path), path)


class RawParsingTests(unittest.TestCase):
    def test_rename_record_carries_both_images(self):
        payload = (
            b":100644 100644 " + b"a" * 40 + b" " + b"b" * 40 + b" R100\x00"
            b"state/OUT.json\x00workstreams/po03/imported.json\x00"
        )
        entries = HARDENED.parse_raw(payload)
        self.assertEqual(1, len(entries))
        self.assertEqual("state/OUT.json", entries[0].source_path)
        self.assertEqual("workstreams/po03/imported.json", entries[0].path)
        self.assertEqual(
            [("pre", "state/OUT.json"), ("post", "workstreams/po03/imported.json")],
            entries[0].paths,
        )

    def test_copy_record_does_not_treat_its_source_as_a_mutation(self):
        payload = (
            b":100644 100644 " + b"a" * 40 + b" " + b"b" * 40 + b" C100\x00"
            b"state/OUT.json\x00workstreams/po03/copy.json\x00"
        )
        entries = HARDENED.parse_raw(payload)
        self.assertEqual([("post", "workstreams/po03/copy.json")], entries[0].paths)
        self.assertEqual([], HARDENED.evaluate(entries, lambda _: b""))

    def test_malformed_raw_output_is_an_error_not_a_pass(self):
        for payload in (b"workstreams/po03/x\x00", b":100644 M\x00x\x00", b":100644 100644 a b R100\x00only\x00"):
            with self.assertRaises(HARDENED.ScopeError):
                HARDENED.parse_raw(payload)

    def test_parse_of_real_git_output_round_trips(self):
        with tempfile.TemporaryDirectory() as scratch:
            repo, base = MATRIX.new_repository(Path(scratch), "parse")
            (repo / "workstreams/po03/attempts/scratch/new.txt").write_text("n\n", encoding="utf-8")
            MATRIX.git(repo, "add", "-A")
            MATRIX.git(repo, "commit", "-qm", "add")
            entries = HARDENED.changed_entries(str(repo), base, "HEAD")
            self.assertEqual(["workstreams/po03/attempts/scratch/new.txt"], [e.path for e in entries])
            self.assertEqual("100644", entries[0].dst_mode)


class SymlinkAndModeTests(unittest.TestCase):
    def test_symlink_target_leaving_the_allowlist_is_refused(self):
        entry = HARDENED.ChangedEntry(
            status="A", path="workstreams/po03/link", dst_mode="120000", dst_sha="deadbeef"
        )
        findings = HARDENED.evaluate([entry], lambda _: b"../../state")
        self.assertTrue(any(item.startswith("SYMLINK_TARGET_OUT_OF_SCOPE") for item in findings), findings)

    def test_symlink_target_staying_inside_the_allowlist_is_allowed(self):
        entry = HARDENED.ChangedEntry(
            status="A", path="workstreams/po03/attempts/x/alias", dst_mode="120000", dst_sha="cafe"
        )
        self.assertEqual([], HARDENED.evaluate([entry], lambda _: b"real.txt"))

    def test_absolute_symlink_target_is_refused(self):
        entry = HARDENED.ChangedEntry(
            status="A", path="workstreams/po03/passwd", dst_mode="120000", dst_sha="cafe"
        )
        findings = HARDENED.evaluate([entry], lambda _: b"/etc/passwd")
        self.assertTrue(any(item.startswith("SYMLINK_TARGET_REFUSED") for item in findings), findings)

    def test_symlink_escaping_the_repository_is_refused(self):
        entry = HARDENED.ChangedEntry(
            status="A", path="workstreams/po03/up", dst_mode="120000", dst_sha="cafe"
        )
        findings = HARDENED.evaluate([entry], lambda _: b"../../../../../etc")
        self.assertTrue(any(item.startswith("SYMLINK_TARGET_REFUSED") for item in findings), findings)

    def test_unreadable_symlink_is_refused_rather_than_cleared(self):
        entry = HARDENED.ChangedEntry(
            status="A", path="workstreams/po03/link", dst_mode="120000", dst_sha="cafe"
        )
        findings = HARDENED.evaluate([entry], None)
        self.assertTrue(any(item.startswith("SYMLINK_UNVERIFIABLE") for item in findings), findings)

    def test_gitlink_inside_the_allowlist_is_refused(self):
        entry = HARDENED.ChangedEntry(
            status="A", path="workstreams/po03/sub", dst_mode="160000", dst_sha="cafe"
        )
        findings = HARDENED.evaluate([entry], lambda _: b"")
        self.assertTrue(any(item.startswith("GITLINK_NOT_ALLOWED") for item in findings), findings)

    def test_unexpected_mode_is_refused(self):
        entry = HARDENED.ChangedEntry(
            status="A", path="workstreams/po03/odd", dst_mode="100755x", dst_sha="cafe"
        )
        findings = HARDENED.evaluate([entry], lambda _: b"")
        self.assertTrue(any(item.startswith("UNEXPECTED_MODE") for item in findings), findings)

    def test_executable_regular_file_is_allowed(self):
        entry = HARDENED.ChangedEntry(
            status="A", path="workstreams/po03/tool.sh", dst_mode="100755", dst_sha="cafe"
        )
        self.assertEqual([], HARDENED.evaluate([entry], lambda _: b""))


class EndToEndScratchRepositoryTests(unittest.TestCase):
    """Reproduce each real escape against both guards in a throwaway repository."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.scratch = Path(self.temporary.name)

    def guards(self, repo, base):
        legacy = subprocess.run(
            (sys.executable, "-I", str(LEGACY_PATH), "--base", base, "--head", "HEAD"),
            cwd=repo, capture_output=True, text=True,
        )
        hardened = subprocess.run(
            (sys.executable, "-I", str(HARDENED_PATH), "--repo", ".", "--base", base, "--head", "HEAD"),
            cwd=repo, capture_output=True, text=True,
        )
        return legacy, hardened

    def test_rename_out_of_allowlist_into_allowlist_escapes_the_legacy_guard(self):
        repo, base = MATRIX.new_repository(self.scratch, "rename")
        MATRIX.git(repo, "mv", "state/PROTECTED.json", "workstreams/po03/attempts/scratch/i.json")
        MATRIX.git(repo, "commit", "-qm", "rename in")
        legacy, hardened = self.guards(repo, base)
        self.assertEqual(0, legacy.returncode, "legacy guard was expected to admit this rename")
        self.assertIn("PO03_PATH_SCOPE_PASS", legacy.stdout)
        self.assertEqual(1, hardened.returncode, hardened.stdout + hardened.stderr)
        self.assertIn("RENAME_SOURCE_OUT_OF_SCOPE", hardened.stderr)
        self.assertIn("state/PROTECTED.json", hardened.stderr)

    def test_symlink_out_of_allowlist_escapes_the_legacy_guard(self):
        repo, base = MATRIX.new_repository(self.scratch, "symlink")
        (repo / "workstreams/po03/attempts/scratch/link").symlink_to("../../../../state")
        MATRIX.git(repo, "add", "-A")
        MATRIX.git(repo, "commit", "-qm", "symlink out")
        legacy, hardened = self.guards(repo, base)
        self.assertEqual(0, legacy.returncode, "legacy guard was expected to admit this symlink")
        self.assertEqual(1, hardened.returncode, hardened.stdout + hardened.stderr)
        self.assertIn("SYMLINK_TARGET_OUT_OF_SCOPE", hardened.stderr)

    def test_typechange_to_an_escaping_symlink_escapes_the_legacy_guard(self):
        repo, base = MATRIX.new_repository(self.scratch, "typechange")
        target = repo / "workstreams/po03/attempts/scratch/a.txt"
        target.unlink()
        target.symlink_to("../../../../state/PROTECTED.json")
        MATRIX.git(repo, "add", "-A")
        MATRIX.git(repo, "commit", "-qm", "typechange")
        legacy, hardened = self.guards(repo, base)
        self.assertEqual(0, legacy.returncode)
        self.assertEqual(1, hardened.returncode)
        self.assertIn("SYMLINK_TARGET_OUT_OF_SCOPE", hardened.stderr)

    def test_in_allowlist_change_still_passes_both_guards(self):
        repo, base = MATRIX.new_repository(self.scratch, "control")
        (repo / "workstreams/po03/attempts/scratch/b.txt").write_text("b\n", encoding="utf-8")
        MATRIX.git(repo, "add", "-A")
        MATRIX.git(repo, "commit", "-qm", "in allowlist")
        legacy, hardened = self.guards(repo, base)
        self.assertEqual(0, legacy.returncode, legacy.stderr)
        self.assertEqual(0, hardened.returncode, hardened.stderr)
        self.assertIn("PO03_HARDENED_SCOPE_PASS", hardened.stdout)

    def test_out_of_allowlist_addition_is_refused_by_both_guards(self):
        repo, base = MATRIX.new_repository(self.scratch, "out")
        (repo / "state/NEW.json").write_text("{}\n", encoding="utf-8")
        MATRIX.git(repo, "add", "-A")
        MATRIX.git(repo, "commit", "-qm", "out of allowlist")
        legacy, hardened = self.guards(repo, base)
        self.assertEqual(1, legacy.returncode)
        self.assertEqual(1, hardened.returncode)
        self.assertIn("OUT_OF_SCOPE state/NEW.json", hardened.stderr)

    def test_rename_detection_disabled_still_judges_both_paths(self):
        repo, base = MATRIX.new_repository(self.scratch, "norenames")
        MATRIX.git(repo, "config", "diff.renames", "false")
        MATRIX.git(repo, "mv", "state/PROTECTED.json", "workstreams/po03/attempts/scratch/i.json")
        MATRIX.git(repo, "commit", "-qm", "rename with detection off")
        hardened = subprocess.run(
            (sys.executable, "-I", str(HARDENED_PATH), "--repo", ".", "--base", base, "--head", "HEAD"),
            cwd=repo, capture_output=True, text=True,
        )
        self.assertEqual(1, hardened.returncode, hardened.stdout + hardened.stderr)
        self.assertIn("state/PROTECTED.json", hardened.stderr)


class CommandLineTests(unittest.TestCase):
    def run_hardened(self, *arguments):
        return subprocess.run(
            (sys.executable, "-I", str(HARDENED_PATH), *arguments), capture_output=True, text=True
        )

    def test_in_allowlist_paths_exit_zero(self):
        result = self.run_hardened("--path", "workstreams/po03/a.py", "--path", "receipts/po03/b.json")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("PO03_HARDENED_SCOPE_PASS images=2", result.stdout)

    def test_out_of_allowlist_path_exits_one(self):
        result = self.run_hardened("--path", "state/x.json")
        self.assertEqual(1, result.returncode)
        self.assertIn("PO03_HARDENED_SCOPE_VIOLATION: OUT_OF_SCOPE state/x.json", result.stderr)

    def test_missing_base_exits_two(self):
        result = self.run_hardened()
        self.assertEqual(2, result.returncode)
        self.assertIn("PO03_HARDENED_SCOPE_ERROR", result.stderr)

    def test_unresolvable_base_exits_two(self):
        result = self.run_hardened("--repo", str(REPO_ROOT), "--base", "f" * 40)
        self.assertEqual(2, result.returncode)
        self.assertIn("PO03_HARDENED_SCOPE_ERROR", result.stderr)

    def test_this_branch_passes_the_hardened_guard(self):
        base = "5ef49cb148f5186397acf1303f325f726bb58543"
        reachable = subprocess.run(
            ("git", "cat-file", "-e", f"{base}^{{commit}}"), cwd=REPO_ROOT, capture_output=True
        ).returncode == 0
        if not reachable:
            self.skipTest("cohort base commit is not reachable in this checkout")
        result = self.run_hardened("--repo", str(REPO_ROOT), "--base", base, "--head", "HEAD")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


class MatrixTests(unittest.TestCase):
    """The matrix is the reproduction, so assert its shape and its conclusions."""

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.rows = MATRIX.build(Path(cls.temporary.name))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def row(self, case):
        matches = [item for item in self.rows if item["case"] == case]
        self.assertEqual(1, len(matches), case)
        return matches[0]

    def test_hardened_guard_satisfies_every_stated_requirement(self):
        unsatisfied = [row["case"] for row in self.rows if not row["hardened_satisfies_requirement"]]
        self.assertEqual([], unsatisfied)

    def test_corpus_covers_every_evasion_class_named_in_the_hypothesis(self):
        cases = {row["case"] for row in self.rows}
        for required in ("dotdot-traversal", "absolute-path", "backslash-separator", "nul-byte",
                         "cyrillic-o-confusable", "case-variant-prefix", "trailing-dot-file",
                         "repo-symlink-target-out-of-allowlist"):
            self.assertIn(required, cases)

    def test_the_symlink_clause_of_the_hypothesis_is_refuted_for_the_legacy_guard(self):
        row = self.row("repo-symlink-target-out-of-allowlist")
        self.assertEqual("ADMITS", row["legacy"])
        self.assertEqual("REFUSES", row["hardened"])

    def test_the_traversal_unicode_and_case_clauses_hold_for_the_legacy_guard(self):
        for case in ("dotdot-traversal", "cyrillic-o-confusable", "fullwidth-w-confusable",
                     "case-variant-prefix", "case-variant-workflow"):
            self.assertEqual("REFUSES", self.row(case)["legacy"], case)

    def test_nul_case_is_recorded_as_judged_in_process(self):
        row = self.row("nul-byte")
        self.assertIn("in-process", row["channel"])
        self.assertEqual("REFUSES", row["legacy"])
        self.assertEqual("REFUSES", row["hardened"])

    def test_legitimate_in_allowlist_changes_are_not_broken_by_hardening(self):
        for case in ("in-allowlist-workstreams", "in-allowlist-receipts", "in-allowlist-workflow",
                     "repo-in-allowlist-control", "repo-symlink-target-in-allowlist"):
            self.assertEqual("ADMITS", self.row(case)["hardened"], case)


if __name__ == "__main__":
    unittest.main()
