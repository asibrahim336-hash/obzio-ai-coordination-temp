"""Tests for the PO-03 changed-path rejection fixture.

The hypothesis under test is that the path-scope guard has real rejection power,
demonstrated by a deliberate out-of-allowlist mutation fixture.  The fixture
itself is the deliverable, so these tests check two things: that the fixture
reports the guard's real behaviour, and that the fixture would notice if the
guard stopped rejecting.
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent
MODULE_PATH = UNIT_ROOT / "rejection_fixture.py"
SPEC = importlib.util.spec_from_file_location("po03_rejection_fixture", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
FIXTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURE)

REPO_ROOT = UNIT_ROOT.parents[3]
LIVE_GUARD = REPO_ROOT / "workstreams/po03/tools/check_path_scope.py"

VACUOUS_GUARD = """#!/usr/bin/env python3
import sys
print("PO03_PATH_SCOPE_PASS changed_paths=0")
sys.exit(0)
"""


class LiveGuardTests(unittest.TestCase):
    """Run every scenario against the guard that is actually in the repository."""

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.scenarios = FIXTURE.run_all(LIVE_GUARD, Path(cls.temporary.name))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def scenario(self, name):
        matches = [item for item in self.scenarios if item.name == name]
        self.assertEqual(1, len(matches), f"{name} not found in {[i.name for i in self.scenarios]}")
        return matches[0]

    def test_the_guard_exists_where_the_fixture_expects_it(self):
        self.assertTrue(LIVE_GUARD.is_file(), LIVE_GUARD)

    def test_every_scenario_behaved_as_expected(self):
        deviations = [item.as_dict() for item in self.scenarios if not item.passed]
        self.assertEqual([], deviations)

    def test_the_fixture_contains_both_rejecting_and_passing_scenarios(self):
        rejecting = [item for item in self.scenarios if item.expected_exit != 0]
        passing = [item for item in self.scenarios if item.expected_exit == 0]
        self.assertGreaterEqual(len(rejecting), 10)
        self.assertGreaterEqual(len(passing), 2)

    def test_deliberate_out_of_allowlist_commit_is_rejected_with_non_zero_exit(self):
        scenario = self.scenario("scratch-repo-out-of-allowlist-mutation")
        self.assertEqual(1, scenario.actual_exit)
        self.assertIn("PO03_PATH_SCOPE_VIOLATION: state/PO03-SHOULD-NOT-WRITE.json", scenario.output)

    def test_in_allowlist_control_commit_passes(self):
        scenario = self.scenario("scratch-repo-in-allowlist-control")
        self.assertEqual(0, scenario.actual_exit)
        self.assertIn("PO03_PATH_SCOPE_PASS", scenario.output)

    def test_out_of_allowlist_deletion_is_rejected(self):
        scenario = self.scenario("scratch-repo-out-of-allowlist-deletion")
        self.assertEqual(1, scenario.actual_exit)

    def test_unresolvable_base_is_an_error_and_not_a_pass(self):
        scenario = self.scenario("unresolvable-base-fails-closed")
        self.assertEqual(2, scenario.actual_exit)
        self.assertIn("PO03_PATH_SCOPE_ERROR", scenario.output)

    def test_protected_surfaces_are_each_individually_rejected(self):
        for path in (".cursor/environment.json", "workstreams/po01/producer-result.json",
                     "packs/pack-a/manifest.json", "dispatch/queue.json", "_transport/spool/message.json"):
            scenario = self.scenario(f"synthetic-rejected:{path}")
            self.assertEqual(1, scenario.actual_exit, path)

    def test_one_bad_path_taints_an_otherwise_clean_change_set(self):
        scenario = self.scenario("synthetic-one-bad-path-among-many-good")
        self.assertEqual(1, scenario.actual_exit)


class FixtureDetectsAVacuousGuardTests(unittest.TestCase):
    """A fixture that cannot fail is worthless, so prove this one fails."""

    def test_a_guard_that_always_passes_is_reported_as_deviating(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            vacuous = root / "vacuous_guard.py"
            vacuous.write_text(VACUOUS_GUARD, encoding="utf-8")
            scenarios = FIXTURE.run_all(vacuous, root)
            deviations = [item for item in scenarios if not item.passed]
            self.assertGreaterEqual(len(deviations), 10)
            self.assertTrue(
                any(item.name == "scratch-repo-out-of-allowlist-mutation" for item in deviations)
            )
            controls = [item for item in scenarios if item.expected_exit == 0 and item.passed]
            self.assertGreaterEqual(len(controls), 2, "a vacuous guard still passes the controls")

    def test_a_guard_that_always_fails_is_also_reported_as_deviating(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            paranoid = root / "paranoid_guard.py"
            paranoid.write_text(
                "#!/usr/bin/env python3\nimport sys\nsys.exit(1)\n", encoding="utf-8"
            )
            scenarios = FIXTURE.run_all(paranoid, root)
            failing_controls = [
                item for item in scenarios if item.expected_exit == 0 and not item.passed
            ]
            self.assertGreaterEqual(len(failing_controls), 2)


class NoBoundaryViolationTests(unittest.TestCase):
    """The fixture must not commit out-of-allowlist paths to the repository under test."""

    def test_fixture_leaves_the_real_repository_untouched(self):
        before = subprocess.run(
            ("git", "status", "--porcelain"), cwd=REPO_ROOT, check=True, capture_output=True, text=True
        ).stdout
        head_before = subprocess.run(
            ("git", "rev-parse", "HEAD"), cwd=REPO_ROOT, check=True, capture_output=True, text=True
        ).stdout
        with tempfile.TemporaryDirectory() as scratch:
            FIXTURE.run_all(LIVE_GUARD, Path(scratch))
        after = subprocess.run(
            ("git", "status", "--porcelain"), cwd=REPO_ROOT, check=True, capture_output=True, text=True
        ).stdout
        head_after = subprocess.run(
            ("git", "rev-parse", "HEAD"), cwd=REPO_ROOT, check=True, capture_output=True, text=True
        ).stdout
        self.assertEqual(before, after)
        self.assertEqual(head_before, head_after)

    def test_scratch_repository_is_a_distinct_repository(self):
        with tempfile.TemporaryDirectory() as scratch:
            repo, base = FIXTURE.build_scratch_repository(Path(scratch))
            self.assertTrue((repo / ".git").exists())
            self.assertNotEqual(repo.resolve(), REPO_ROOT.resolve())
            self.assertEqual(40, len(base))

    def test_scratch_directory_is_removed_after_a_command_line_run(self):
        with tempfile.TemporaryDirectory() as scratch:
            result = subprocess.run(
                (sys.executable, "-I", str(MODULE_PATH), "--scratch-root", scratch),
                capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual([], list(Path(scratch).iterdir()))


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            (sys.executable, "-I", str(MODULE_PATH), *arguments), capture_output=True, text=True
        )

    def test_default_invocation_exits_zero_against_the_live_guard(self):
        result = self.run_cli()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("PO03_FIXTURE_PASS", result.stdout)

    def test_json_mode_is_machine_readable(self):
        result = self.run_cli("--json")
        self.assertEqual(0, result.returncode, result.stderr)
        document = json.loads(result.stdout)
        self.assertTrue(all(entry["passed"] for entry in document["scenarios"]))
        self.assertGreaterEqual(len(document["scenarios"]), 15)

    def test_missing_guard_exits_two(self):
        result = self.run_cli("--guard", "/nonexistent/check_path_scope.py")
        self.assertEqual(2, result.returncode)
        self.assertIn("PO03_FIXTURE_ERROR", result.stderr)

    def test_repo_scope_option_reports_this_branch(self):
        base = "5ef49cb148f5186397acf1303f325f726bb58543"
        reachable = subprocess.run(
            ("git", "cat-file", "-e", f"{base}^{{commit}}"), cwd=REPO_ROOT, capture_output=True
        ).returncode == 0
        if not reachable:
            self.skipTest("cohort base commit is not reachable in this checkout")
        result = self.run_cli("--include-repo-scope", base)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn(f"real-repository-scope:{base}..HEAD", result.stdout)


if __name__ == "__main__":
    unittest.main()
