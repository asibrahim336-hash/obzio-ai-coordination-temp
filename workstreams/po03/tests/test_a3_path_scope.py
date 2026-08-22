"""Unit a3-u03: the path-scope guard rejects out-of-allowlist writes.

The load-bearing assertion is that a deliberate out-of-allowlist mutation is
rejected by the same code path CI runs.  The mutation is data -- a synthetic
changed-path list and a synthetic unified diff -- because proving the guard by
actually committing outside the allowlist would perform the act the guard
exists to prevent.

The guard binds to ``control_plane``'s allowlist functions rather than copying
them, and one test asserts that binding by object identity.  A second copy of an
allowlist is a second thing to drift, and a drifted guard reports PASS with
authority it no longer has.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PO03_ROOT = REPO_ROOT / "workstreams" / "po03"
GUARD_PATH = PO03_ROOT / "runtime" / "path_scope.py"
CONTROL_PLANE_PATH = PO03_ROOT / "tools" / "control_plane.py"
FIXTURE_DIR = PO03_ROOT / "runtime" / "fixtures" / "path_scope"
EXPECTATIONS_PATH = FIXTURE_DIR / "expected-verdicts.json"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "po03-path-scope.yml"
REPAIR_DIR = PO03_ROOT / "runtime" / "repair-candidates"
REPAIR_PATCH = REPAIR_DIR / "control-plane-dot-directory-allowlist.patch"
REPAIR_RECORD = REPAIR_DIR / "control-plane-dot-directory-allowlist.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


path_scope = load_module(GUARD_PATH, "po03_path_scope")
control_plane = load_module(CONTROL_PLANE_PATH, "po03_control_plane_under_test")


class GuardUsesTheCoordinatorsLogic(unittest.TestCase):
    def test_allowlist_functions_are_the_control_planes_own(self) -> None:
        self.assertIs(path_scope.path_in_allowlist, path_scope.control_plane.path_in_allowlist)
        self.assertIs(path_scope.check_allowlist, path_scope.control_plane.check_allowlist)
        self.assertIs(path_scope.check_ownership, path_scope.control_plane.check_ownership)

    def test_the_control_plane_module_it_loaded_is_the_committed_one(self) -> None:
        self.assertEqual(
            Path(path_scope.CONTROL_PLANE_PATH).resolve(),
            CONTROL_PLANE_PATH.resolve(),
        )

    def test_workflow_pattern_constants_come_from_the_control_plane(self) -> None:
        self.assertEqual(path_scope.WORKFLOW_DIR, control_plane.ALLOWLIST_WORKFLOW_DIR)
        self.assertEqual(path_scope.WORKFLOW_PREFIX, control_plane.ALLOWLIST_WORKFLOW_PREFIX)
        self.assertEqual(path_scope.WORKFLOW_SUFFIX, control_plane.ALLOWLIST_WORKFLOW_SUFFIX)


class MutationFixtureIsRejected(unittest.TestCase):
    def setUp(self) -> None:
        self.expectations = json.loads(EXPECTATIONS_PATH.read_text(encoding="utf-8"))
        self.cases = {case["fixture"]: case for case in self.expectations["cases"]}

    def test_selftest_reproduces_every_recorded_verdict(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            code, outcomes = path_scope.run_selftest()
        self.assertEqual(code, 0, json.dumps(outcomes, indent=2))
        self.assertEqual(len(outcomes), len(self.expectations["cases"]))
        for outcome in outcomes:
            self.assertEqual(outcome["outcome"], "PASS", outcome)

    def test_the_out_of_allowlist_path_list_is_rejected(self) -> None:
        fixture = "workstreams/po03/runtime/fixtures/path_scope/out-of-allowlist-changed-paths.txt"
        case = self.cases[fixture]
        paths = path_scope.parse_path_list((REPO_ROOT / fixture).read_text(encoding="utf-8"))
        report = path_scope.evaluate(paths, source=fixture)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(
            sorted(report["allowlist_violations"]),
            sorted(case["expected_allowlist_violations"]),
        )

    def test_the_out_of_allowlist_diff_is_rejected(self) -> None:
        fixture = "workstreams/po03/runtime/fixtures/path_scope/out-of-allowlist.diff"
        case = self.cases[fixture]
        paths = path_scope.parse_unified_diff((REPO_ROOT / fixture).read_text(encoding="utf-8"))
        report = path_scope.evaluate(paths, source=fixture)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(
            sorted(report["allowlist_violations"]),
            sorted(case["expected_allowlist_violations"]),
        )

    def test_rename_only_sides_are_both_collected_from_the_diff(self) -> None:
        """A rename names its paths only in the diff header, never in a hunk."""
        fixture = FIXTURE_DIR / "out-of-allowlist.diff"
        paths = path_scope.parse_unified_diff(fixture.read_text(encoding="utf-8"))
        self.assertIn("modules/operators/directory.md", paths)
        self.assertIn("modules/operators/renamed-directory.md", paths)

    def test_the_guard_is_selective_not_blanket(self) -> None:
        fixture = "workstreams/po03/runtime/fixtures/path_scope/in-allowlist-changed-paths.txt"
        paths = path_scope.parse_path_list((REPO_ROOT / fixture).read_text(encoding="utf-8"))
        report = path_scope.evaluate(paths, source=fixture, owner="po03-worker-a3")
        self.assertEqual(report["verdict"], "PASS", report)

    def test_foreign_owned_paths_inside_the_allowlist_are_rejected(self) -> None:
        fixture = "workstreams/po03/runtime/fixtures/path_scope/foreign-owned-changed-paths.txt"
        case = self.cases[fixture]
        paths = path_scope.parse_path_list((REPO_ROOT / fixture).read_text(encoding="utf-8"))
        report = path_scope.evaluate(paths, source=fixture, owner="po03-worker-a3")
        self.assertEqual(report["allowlist_violations"], [])
        self.assertEqual(
            sorted(report["ownership_violations"]),
            sorted(case["expected_ownership_violations"]),
        )

    def test_no_fixture_is_an_actual_out_of_allowlist_commit(self) -> None:
        """The mutation must exist only as data, never as a tracked write."""
        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        offending = [
            path
            for path in tracked
            if not path_scope.path_in_allowlist(path)
            and path.startswith(("workstreams/po03/", "receipts/po03/", ".github/workflows/po03-"))
        ]
        self.assertEqual(offending, [])


class NormalisationIsGuardedNotCompensated(unittest.TestCase):
    """What replaced the compensation, and why it is stronger than what it replaced.

    This module once carried a narrow compensation for the upstream ``lstrip
    ("./")`` normaliser, which stripped characters rather than a leading ``./``
    segment and so judged every dot-directory path outside an allowlist that
    named it.  That was fixed at ``6f5e386``.  A compensation whose defect has
    been fixed is worse than none: it is unreachable code that would silently
    admit a path if the defect returned.  The tests below therefore assert the
    contract the normaliser must keep, so a regression fails the build instead
    of being absorbed.

    None of them asserts that a defect exists.  Each states an invariant.
    """

    def test_the_allowlist_admits_the_paths_the_commission_grants(self) -> None:
        """The invariant the compensation used to stand in for.

        The commission's written allowlist contains ``.github/workflows/po03-*
        .yml``.  A normaliser that damages the leading dot cannot admit it, so
        this single assertion is the whole of what the compensation was for.
        """
        self.assertTrue(path_scope.path_in_allowlist(path_scope.WORKFLOW_PROBE))
        self.assertEqual(path_scope.normalisation_guard(), [])

    def test_the_guard_fires_when_the_normaliser_breaks_its_contract(self) -> None:
        """Proved against a stand-in, since the real normaliser is correct now.

        A guard that has never fired is not evidence, and the only honest way to
        fire this one is to substitute a normaliser that fails the way the
        original did.  ``lstrip("./")`` is reproduced exactly, so what fires the
        guard is the real defect's behaviour and not an invented one.
        """
        real = path_scope.path_in_allowlist
        prefixes = path_scope.control_plane.ALLOWLIST_PREFIXES

        def damaged(path: str) -> bool:
            return path.lstrip("./").startswith(tuple(prefixes))

        path_scope.path_in_allowlist = damaged
        try:
            failures = path_scope.normalisation_guard()
        finally:
            path_scope.path_in_allowlist = real

        probes = {failure["probe"] for failure in failures}
        self.assertIn("dot_directory_workflow_is_admitted", probes)
        self.assertIn("absolute_path_is_refused", probes)
        self.assertIn("traversal_is_refused", probes)
        # Not the equivalence probe. lstrip("./") happens to damage "./x" and
        # "x" into the same string, so it passes that check while failing three
        # others -- which is why the guard needs more than one probe.
        self.assertNotIn("leading_dot_segment_is_equivalent", probes)

    def test_the_equivalence_probe_fires_on_its_own_failure_mode(self) -> None:
        """A probe that has never fired is not evidence either.

        The equivalence probe is untouched by the historical defect, so it needs
        its own stand-in: a normaliser that does not normalise at all, and so
        decides two spellings of one path differently.
        """
        real = path_scope.path_in_allowlist
        prefixes = tuple(path_scope.control_plane.ALLOWLIST_PREFIXES)
        path_scope.path_in_allowlist = lambda path: path.startswith(prefixes)
        try:
            failures = path_scope.normalisation_guard()
        finally:
            path_scope.path_in_allowlist = real

        equivalence = [
            failure
            for failure in failures
            if failure["probe"] == "leading_dot_segment_is_equivalent"
        ]
        self.assertEqual(len(equivalence), 1, failures)
        self.assertEqual(equivalence[0]["equivalent_to"], path_scope.RELATIVE_PROBE)

    def test_a_guard_failure_fails_the_whole_report(self) -> None:
        """A normalisation regression must not pass merely because no path moved."""
        real = path_scope.path_in_allowlist
        path_scope.path_in_allowlist = lambda path: False
        try:
            report = path_scope.evaluate([], source="probe")
        finally:
            path_scope.path_in_allowlist = real
        self.assertEqual(report["verdict"], "FAIL")
        self.assertTrue(report["normalisation_guard_failures"])

    def test_the_retirement_is_recorded_rather_than_silent(self) -> None:
        record = json.loads(REPAIR_RECORD.read_text(encoding="utf-8"))
        retired = path_scope.RETIRED_COMPENSATION
        self.assertEqual(record["defect_id"], retired["defect_id"])
        self.assertFalse(record["applied_by_this_writer"])
        self.assertEqual(retired["fixed_upstream_at"], "6f5e386")
        # Three independent discoveries are why the fix is trusted rather than
        # believed, so the record names all three.
        self.assertIn("po03-worker-a3", retired["independently_rediscovered_by"])
        self.assertGreaterEqual(len(retired["independently_rediscovered_by"]), 3)
        report = path_scope.evaluate([], source="probe")
        self.assertEqual(report["retired_compensation"]["defect_id"], retired["defect_id"])
        self.assertNotIn("compensated_allowlist_paths", report)
        self.assertNotIn("compensated_ownership_paths", report)

    def test_absolute_paths_fail_closed_whatever_upstream_returns(self) -> None:
        """Kept independent of the authority, because this is the granting direction.

        A normaliser that loses a leading slash *admits* an absolute path, and a
        guard that deferred to it there would widen access rather than deny it.
        The check therefore does not consult upstream at all.
        """
        probe = path_scope.ABSOLUTE_PROBE
        self.assertTrue(probe.startswith("/"))
        real = path_scope.path_in_allowlist
        path_scope.path_in_allowlist = lambda path: True
        try:
            report = path_scope.evaluate([probe], source="probe")
        finally:
            path_scope.path_in_allowlist = real
        self.assertEqual(report["allowlist_violations"], [probe])
        self.assertEqual(report["verdict"], "FAIL")

    def test_diff_sentinel_is_dropped_without_becoming_a_violation(self) -> None:
        diff = "diff --git a/workstreams/po03/x b/workstreams/po03/x\n--- /dev/null\n+++ b/workstreams/po03/x\n"
        paths = path_scope.parse_unified_diff(diff)
        self.assertEqual(paths, ["workstreams/po03/x"])
        self.assertEqual(path_scope.evaluate(paths, source="probe")["verdict"], "PASS")


class CommandLineBehaviour(unittest.TestCase):
    """CI invokes the guard as a command, so the command is what is tested."""

    def run_guard(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", "-B", str(GUARD_PATH), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

    def test_selftest_command_exits_zero(self) -> None:
        result = self.run_guard("selftest")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("produced their recorded verdicts", result.stdout)

    def test_mutation_path_list_exits_nonzero(self) -> None:
        result = self.run_guard(
            "paths", str(FIXTURE_DIR / "out-of-allowlist-changed-paths.txt")
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("OUT_OF_ALLOWLIST: packs/operator/pack-manifest.json", result.stdout)

    def test_mutation_diff_exits_nonzero(self) -> None:
        result = self.run_guard("diff", str(FIXTURE_DIR / "out-of-allowlist.diff"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "OUT_OF_ALLOWLIST: state/operator-system/ACTIVE_INSTRUCTION_STACK.json",
            result.stdout,
        )

    def test_in_allowlist_path_list_exits_zero(self) -> None:
        result = self.run_guard(
            "paths", str(FIXTURE_DIR / "in-allowlist-changed-paths.txt"), "--owner", "po03-worker-a3"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unreadable_input_fails_closed(self) -> None:
        result = self.run_guard("paths", str(FIXTURE_DIR / "does-not-exist.txt"))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("PATH_SCOPE_ERROR", result.stderr)

    def test_git_mode_reports_this_branch(self) -> None:
        result = self.run_guard("--json", "git", "--base", "HEAD~1", "--head", "HEAD")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "po03-path-scope-report-v1")
        self.assertEqual(report["verdict"], "PASS")
        self.assertIn("merge-base", report["source"])
        self.assertEqual(report["attribution"], {})


class ViolationsAreAttributedToCommits(unittest.TestCase):
    """A guard that cannot say which commit wrote the path is hard to act on."""

    def test_attribution_names_the_commit_that_touched_a_path(self) -> None:
        commits = path_scope.attribute(
            "workstreams/po03/runtime/path_scope.py", "HEAD~1", "HEAD"
        )
        for commit in commits:
            self.assertRegex(commit["commit"], r"^[0-9a-f]{40}$")
            self.assertTrue(commit["subject"])

    def test_attribution_of_an_untouched_path_is_empty(self) -> None:
        self.assertEqual(path_scope.attribute("packs/nothing-here", "HEAD~1", "HEAD"), [])

    def test_attribution_of_an_unresolvable_range_is_empty_not_an_error(self) -> None:
        self.assertEqual(path_scope.attribute("anything", "not-a-ref", "HEAD"), [])


class WorkflowSurface(unittest.TestCase):
    """The workflow must actually run, and must run within its permissions."""

    def setUp(self) -> None:
        self.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_workflow_is_committed_and_named_in_scope(self) -> None:
        self.assertTrue(WORKFLOW_PATH.is_file())
        self.assertTrue(WORKFLOW_PATH.name.startswith("po03-"))
        self.assertTrue(WORKFLOW_PATH.name.endswith(".yml"))

    def test_workflow_is_read_only_and_secretless(self) -> None:
        self.assertIn("permissions:\n  contents: read\n", self.text)
        self.assertNotIn("secrets.", self.text)
        runners = [
            line.split(":", 1)[1].strip()
            for line in self.text.splitlines()
            if line.strip().startswith("runs-on:")
        ]
        self.assertEqual(runners, ["ubuntu-latest"])

    def test_workflow_runs_on_pull_request_and_on_this_branch_class(self) -> None:
        self.assertIn("pull_request:", self.text)
        self.assertIn('"cursor/po03-**"', self.text)
        self.assertIn('"po03/**"', self.text)

    def test_workflow_runs_the_rejection_selftest_before_judging_real_paths(self) -> None:
        selftest_at = self.text.index("path_scope.py selftest")
        enforce_at = self.text.index("Enforce the allowlist on the real changed paths")
        self.assertLess(selftest_at, enforce_at)


if __name__ == "__main__":
    unittest.main()
