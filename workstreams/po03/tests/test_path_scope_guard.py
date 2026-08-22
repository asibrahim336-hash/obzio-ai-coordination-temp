import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "path_scope_guard.py"
SPEC = importlib.util.spec_from_file_location("path_scope_guard", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

GIT = shutil.which("git")


class AllowlistTests(unittest.TestCase):
    def assert_in_scope(self, path):
        normalized, reason = MODULE.normalize(path)
        self.assertIsNotNone(normalized, f"{path} was unusable: {reason}")
        self.assertTrue(MODULE.is_allowed(normalized), f"{path} should be in scope")

    def assert_out_of_scope(self, path):
        normalized, _ = MODULE.normalize(path)
        if normalized is None:
            return
        self.assertFalse(MODULE.is_allowed(normalized), f"{path} should be rejected")

    def test_workstream_paths_in_scope(self):
        for path in (
            "workstreams/po03/tools/path_scope_guard.py",
            "workstreams/po03/evidence/source-lock.json",
            "workstreams/po03/.gitignore",
            "workstreams/po03/a/b/c/d.json",
        ):
            self.assert_in_scope(path)

    def test_receipt_paths_in_scope(self):
        self.assert_in_scope("receipts/po03/2026-08-22/producer-execution.json")

    def test_po03_workflow_in_scope(self):
        self.assert_in_scope(".github/workflows/po03-contracts.yml")

    def test_governance_paths_out_of_scope(self):
        for path in (
            "AGENTS.md",
            "README.md",
            "state/operator-system/ACTIVE_INSTRUCTION_STACK.json",
            "dispatch/anything.md",
            "commissions/anything.md",
            "operations/README.md",
            "scripts/check_operator_taxonomy.py",
            ".cursor/environment.json",
            ".gitignore",
        ):
            self.assert_out_of_scope(path)

    def test_other_workstreams_out_of_scope(self):
        for path in (
            "workstreams/po01/thing.json",
            "workstreams/README.md",
            "receipts/po01/thing.json",
        ):
            self.assert_out_of_scope(path)

    def test_prefix_boundary_is_a_path_segment(self):
        for path in (
            "workstreams/po03x/thing.json",
            "workstreams/po030/thing.json",
            "receipts/po03-old/thing.json",
        ):
            self.assert_out_of_scope(path)

    def test_bare_allowlisted_directory_is_not_a_file(self):
        for path in ("workstreams/po03", "receipts/po03", "workstreams/po03/"):
            self.assert_out_of_scope(path)

    def test_non_po03_workflows_out_of_scope(self):
        for path in (
            ".github/workflows/ci.yml",
            ".github/workflows/po03-contracts.yaml",
            ".github/workflows/po03.yml",
            ".github/workflows/nested/po03-contracts.yml",
            ".github/workflows/po03-.yml",
            ".github/dependabot.yml",
        ):
            self.assert_out_of_scope(path)

    def test_traversal_out_of_allowlist_is_rejected(self):
        normalized, reason = MODULE.normalize("workstreams/po03/../../state/leak.json")
        self.assertIsNotNone(normalized)
        self.assertEqual("state/leak.json", normalized)
        self.assertFalse(MODULE.is_allowed(normalized))

    def test_traversal_escaping_the_repository_is_unusable(self):
        normalized, reason = MODULE.normalize("../outside/leak.json")
        self.assertIsNone(normalized)
        self.assertIn("outside the repository root", reason)

    def test_absolute_paths_are_unusable(self):
        for path in ("/etc/passwd", "/workspace/state/leak.json", "C:/state/leak.json"):
            normalized, reason = MODULE.normalize(path)
            self.assertIsNone(normalized, path)

    def test_backslash_paths_are_unusable(self):
        normalized, reason = MODULE.normalize("workstreams\\po03\\thing.json")
        self.assertIsNone(normalized)
        self.assertIn("backslash", reason)

    def test_git_quoted_path_is_unusable(self):
        normalized, reason = MODULE.normalize('"workstreams/po03/caf\\303\\251.json"')
        self.assertIsNone(normalized)
        self.assertIn("git-quoted", reason)

    def test_case_variants_are_rejected(self):
        for path in ("Workstreams/po03/thing.json", "workstreams/PO03/thing.json"):
            self.assert_out_of_scope(path)

    def test_redundant_separators_are_normalized_then_allowed(self):
        normalized, _ = MODULE.normalize("./workstreams/po03//tools/x.py")
        self.assertEqual("workstreams/po03/tools/x.py", normalized)
        self.assertTrue(MODULE.is_allowed(normalized))


class CheckTests(unittest.TestCase):
    def test_blank_lines_are_skipped(self):
        accepted, rejected = MODULE.check(["", "  ", "workstreams/po03/a.json", ""])
        self.assertEqual(["workstreams/po03/a.json"], accepted)
        self.assertEqual([], rejected)

    def test_every_offending_path_is_reported(self):
        accepted, rejected = MODULE.check(
            [
                "workstreams/po03/a.json",
                "state/leak.json",
                "receipts/po03/b.json",
                "AGENTS.md",
                "modules/operators/x.py",
            ]
        )
        self.assertEqual(2, len(accepted))
        self.assertEqual(
            ["state/leak.json", "AGENTS.md", "modules/operators/x.py"],
            [item.raw for item in rejected],
        )


class CliTests(unittest.TestCase):
    def run_main(self, argv, stdin_text=""):
        buffer = io.StringIO()
        original = sys.stdout
        sys.stdout = buffer
        try:
            code = MODULE.main(argv, stdin=io.StringIO(stdin_text))
        finally:
            sys.stdout = original
        return code, buffer.getvalue()

    def test_argv_clean_set_exits_zero(self):
        code, output = self.run_main(
            ["workstreams/po03/a.json", ".github/workflows/po03-contracts.yml"]
        )
        self.assertEqual(0, code)
        self.assertIn("PASS 2 paths in scope", output)

    def test_argv_offending_path_exits_nonzero(self):
        code, output = self.run_main(["workstreams/po03/a.json", "state/leak.json"])
        self.assertEqual(1, code)
        self.assertIn("OUT-OF-ALLOWLIST: state/leak.json", output)
        self.assertIn("FAIL 1 rejected", output)

    def test_stdin_newline_separated(self):
        code, output = self.run_main([], "workstreams/po03/a.json\nstate/leak.json\n")
        self.assertEqual(1, code)
        self.assertIn("OUT-OF-ALLOWLIST: state/leak.json", output)

    def test_stdin_null_separated(self):
        code, output = self.run_main(
            ["--null"], "workstreams/po03/a.json\x00receipts/po03/b.json\x00"
        )
        self.assertEqual(0, code)
        self.assertIn("PASS 2 paths in scope", output)

    def test_empty_diff_passes(self):
        code, output = self.run_main([], "")
        self.assertEqual(0, code)
        self.assertIn("PASS 0 paths in scope", output)


@unittest.skipUnless(GIT, "git is required for the changed-path fixture")
class DeliberateOutOfAllowlistFixtureTests(unittest.TestCase):
    """Proves rejection against a real `git diff --name-only` in a throwaway repo.

    The out-of-allowlist mutation happens only inside a temporary repository so
    that no path outside the allowlist is ever written in this repository.
    """

    def git(self, cwd, *args):
        return subprocess.run(
            [
                GIT,
                "-c",
                "user.email=po03@obzio.invalid",
                "-c",
                "user.name=PO-03 fixture",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )

    def guard(self, diff_output, extra_args=()):
        return subprocess.run(
            [sys.executable, "-I", str(MODULE_PATH), *extra_args],
            input=diff_output,
            capture_output=True,
            text=True,
        )

    def build_repo(self, root, paths):
        self.git(root, "init", "-q", "-b", "main")
        base_file = root / "workstreams" / "po03" / "seed.json"
        base_file.parent.mkdir(parents=True)
        base_file.write_text("{}\n", encoding="utf-8")
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "-m", "seed")
        base = self.git(root, "rev-parse", "HEAD").stdout.strip()
        for relative in paths:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}\n", encoding="utf-8")
        self.git(root, "add", "-A")
        self.git(root, "commit", "-q", "-m", "wave")
        return base

    def test_out_of_allowlist_mutation_fails_the_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self.build_repo(
                root,
                [
                    "workstreams/po03/tools/new_tool.py",
                    "receipts/po03/2026-08-22/receipt.json",
                    ".github/workflows/po03-contracts.yml",
                    "state/operator-system/LEAK.json",
                ],
            )
            diff = self.git(root, "diff", "--name-only", f"{base}...HEAD").stdout
            self.assertIn("state/operator-system/LEAK.json", diff)
            result = self.guard(diff)
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("OUT-OF-ALLOWLIST: state/operator-system/LEAK.json", result.stdout)
            self.assertNotIn("workstreams/po03/tools/new_tool.py", result.stdout)

    def test_in_allowlist_mutation_passes_the_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self.build_repo(
                root,
                [
                    "workstreams/po03/tools/new_tool.py",
                    "workstreams/po03/evidence/new_evidence.json",
                    "receipts/po03/2026-08-22/receipt.json",
                    ".github/workflows/po03-contracts.yml",
                ],
            )
            diff = self.git(root, "diff", "--name-only", f"{base}...HEAD").stdout
            result = self.guard(diff)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("PASS 4 paths in scope", result.stdout)

    def test_null_separated_diff_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self.build_repo(root, ["workstreams/po03/evidence/x.json", "AGENTS.md"])
            diff = self.git(root, "diff", "--name-only", "-z", f"{base}...HEAD").stdout
            result = self.guard(diff, extra_args=("--null",))
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("OUT-OF-ALLOWLIST: AGENTS.md", result.stdout)

    def test_rename_out_of_the_allowlist_is_caught_without_rename_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q", "-b", "main")
            governed = root / "state" / "governed.json"
            governed.parent.mkdir(parents=True)
            governed.write_text("{}\n", encoding="utf-8")
            seed = root / "workstreams" / "po03" / "seed.json"
            seed.parent.mkdir(parents=True)
            seed.write_text("{}\n", encoding="utf-8")
            self.git(root, "add", "-A")
            self.git(root, "commit", "-q", "-m", "seed")
            base = self.git(root, "rev-parse", "HEAD").stdout.strip()
            self.git(root, "mv", "state/governed.json", "workstreams/po03/governed.json")
            self.git(root, "commit", "-q", "-m", "rename into the allowlist")

            with_detection = self.git(
                root, "diff", "--name-only", f"{base}...HEAD"
            ).stdout
            self.assertNotIn("state/governed.json", with_detection)
            self.assertEqual(0, self.guard(with_detection).returncode)

            without_detection = self.git(
                root, "diff", "--name-only", "--no-renames", f"{base}...HEAD"
            ).stdout
            self.assertIn("state/governed.json", without_detection)
            result = self.guard(without_detection)
            self.assertEqual(1, result.returncode, result.stdout)
            self.assertIn("OUT-OF-ALLOWLIST: state/governed.json", result.stdout)

    def test_wrong_diff_base_charges_the_wave_for_pre_existing_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q", "-b", "main")
            seed = root / "workstreams" / "po03" / "seed.json"
            seed.parent.mkdir(parents=True)
            seed.write_text("{}\n", encoding="utf-8")
            self.git(root, "add", "-A")
            self.git(root, "commit", "-q", "-m", "main")
            main = self.git(root, "rev-parse", "HEAD").stdout.strip()

            self.git(root, "checkout", "-q", "-b", "po03/base")
            inherited = root / ".cursor" / "environment.json"
            inherited.parent.mkdir(parents=True)
            inherited.write_text("{}\n", encoding="utf-8")
            self.git(root, "add", "-A")
            self.git(root, "commit", "-q", "-m", "base branch content")
            po03_base = self.git(root, "rev-parse", "HEAD").stdout.strip()

            self.git(root, "checkout", "-q", "-b", "cursor/po03-wave")
            wave = root / "workstreams" / "po03" / "evidence" / "wave.json"
            wave.parent.mkdir(parents=True, exist_ok=True)
            wave.write_text("{}\n", encoding="utf-8")
            self.git(root, "add", "-A")
            self.git(root, "commit", "-q", "-m", "wave")

            against_main = self.git(
                root, "diff", "--name-only", "--no-renames", f"{main}...HEAD"
            ).stdout
            self.assertIn(".cursor/environment.json", against_main)
            self.assertEqual(1, self.guard(against_main).returncode)

            against_po03_base = self.git(
                root, "diff", "--name-only", "--no-renames", f"{po03_base}...HEAD"
            ).stdout
            self.assertNotIn(".cursor/environment.json", against_po03_base)
            result = self.guard(against_po03_base)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_ci_workflow_prefers_the_po03_base_ref_over_main(self):
        workflow = Path(__file__).parents[3] / ".github" / "workflows" / "po03-contracts.yml"
        text = workflow.read_text(encoding="utf-8")
        candidates = [
            line for line in text.splitlines() if 'first_existing_ref' in line and '\\' in line
        ]
        self.assertTrue(candidates, "no fallback ref list found in the workflow")
        fallbacks = text.split("first_existing_ref")[-1]
        base_ref_at = fallbacks.find("origin/${PO03_BASE_REF}")
        main_at = fallbacks.find("origin/main")
        self.assertNotEqual(-1, base_ref_at, fallbacks)
        self.assertNotEqual(-1, main_at, fallbacks)
        self.assertLess(base_ref_at, main_at, fallbacks)

    def test_ci_workflow_disables_rename_detection(self):
        workflow = Path(__file__).parents[3] / ".github" / "workflows" / "po03-contracts.yml"
        text = workflow.read_text(encoding="utf-8")
        diff_lines = [line for line in text.splitlines() if "git diff --name-only" in line]
        self.assertTrue(diff_lines)
        for line in diff_lines:
            self.assertIn("--no-renames", line, line)

    def test_guard_runs_without_third_party_imports(self):
        result = subprocess.run(
            [sys.executable, "-I", str(MODULE_PATH), "workstreams/po03/a.json"],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": ""},
        )
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
