"""Unit a3-u06: the suite passes with outbound network disabled.

The claim under test is not "the suite passed on a machine with no route out".
That is produced equally by a suite with a hidden remote dependency running on a
disconnected host, and it is worth nothing. What is tested here is that
``offline_check.sh`` distinguishes the cases:

* a sandbox that removes egress, proved by probes that succeed outside it and
  fail inside it;
* a planted unmarked network dependence, which the offline run must fail on;
* a declared and guarded network dependence, which it must separate and skip;
* a sandbox that removes nothing, which must be reported as
  ``OFFLINE_NOT_ENFORCED`` rather than quietly passing.

Every test that needs the network to be reachable states so and skips when it is
not, following the same marker convention the runner enforces.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_DIR = REPO_ROOT / "workstreams" / "po03" / "runtime"
RUNNER = RUNTIME_DIR / "offline_check.sh"
POLICY_PATH = RUNTIME_DIR / "offline-policy.json"
TRANSCRIPT_PATH = RUNTIME_DIR / "transcripts" / "offline-suite.json"
FIXTURE_DIR = "workstreams/po03/runtime/fixtures/offline"

POLICY = json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def run_runner(*args: str) -> tuple[int, dict, str]:
    """Invoke the runner as a command and parse the transcript it prints."""
    completed = subprocess.run(
        ["sh", str(RUNNER), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    document = completed.stdout[completed.stdout.index("{") :] if "{" in completed.stdout else "{}"
    return completed.returncode, json.loads(document), completed.stderr


def sandbox_works() -> bool:
    command = POLICY["sandbox"]["command"]
    try:
        return subprocess.run([*command, "true"], capture_output=True).returncode == 0
    except OSError:
        return False


def baseline_reachable() -> bool:
    """Whether the host can reach the remote at all, using the runner's own probes."""
    code, transcript, _ = run_runner("--probe-only")
    return code == 0 and transcript.get("baseline_probe_failures") == 0


SANDBOX_WORKS = sandbox_works()
requires_sandbox = unittest.skipUnless(
    SANDBOX_WORKS, "no unprivileged network namespace available on this host"
)


class PolicyIsWellFormed(unittest.TestCase):
    def test_schema_and_required_sections(self) -> None:
        self.assertEqual(POLICY["schema"], "po03-offline-policy-v1")
        for section in ("preconditions", "sandbox", "probes", "marker"):
            self.assertIn(section, POLICY)
        self.assertTrue(POLICY["probes"])

    def test_every_probe_must_fail_inside_the_sandbox(self) -> None:
        """A probe that is allowed to succeed offline would prove nothing."""
        for probe in POLICY["probes"]:
            self.assertTrue(probe["must_fail_inside_sandbox"], probe["id"])

    def test_runner_rejects_a_foreign_policy_schema(self) -> None:
        code, _, stderr = run_runner("--policy", str(POLICY_PATH.parent / "entry-points.json"))
        self.assertEqual(code, 66)
        self.assertIn("unexpected policy schema", stderr)


class MarkerRegistryMatchesTheTree(unittest.TestCase):
    """The separated set is recomputed from the tree so it cannot drift silently."""

    def marked_modules(self, directory: Path) -> list[str]:
        constant = POLICY["marker"]["constant"]
        found = []
        for path in sorted(directory.rglob("*.py")):
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith(constant) and stripped.endswith("True"):
                    found.append(path.name)
                    break
        return found

    def test_no_committed_test_module_claims_to_need_the_network(self) -> None:
        actual = self.marked_modules(REPO_ROOT / "workstreams" / "po03" / "tests")
        self.assertEqual(actual, POLICY["expected_marked_test_modules"])

    def test_the_marker_is_detectable_where_it_is_used(self) -> None:
        """Guards against a scan that reports an empty set because it is broken."""
        actual = self.marked_modules(REPO_ROOT / FIXTURE_DIR)
        self.assertEqual(actual, ["test_marked_network_dependence.py"])

    def test_declared_network_requiring_components_exist_and_are_not_tests(self) -> None:
        for component in POLICY["network_requiring_components"]:
            path = REPO_ROOT / component["path"]
            self.assertTrue(path.is_file(), component["path"])
            self.assertNotIn("tests", Path(component["path"]).parts)


class SandboxEnforcementIsObserved(unittest.TestCase):
    @requires_sandbox
    def test_probes_succeed_outside_and_fail_inside(self) -> None:
        code, transcript, _ = run_runner("--probe-only")
        if transcript["baseline_probe_failures"]:
            self.skipTest("remote unreachable from this host; enforcement is unattributable")
        self.assertEqual(code, 0)
        self.assertEqual(transcript["status"], "PROBES_ONLY")
        self.assertEqual(transcript["sandboxed_probe_successes"], 0)
        phases = {(p["probe_id"], p["phase"]): p["exit_code"] for p in transcript["probes"]}
        for probe in POLICY["probes"]:
            self.assertEqual(phases[(probe["id"], "baseline")], 0, probe["id"])
            self.assertNotEqual(phases[(probe["id"], "sandboxed")], 0, probe["id"])

    def test_a_sandbox_that_removes_nothing_is_reported_not_enforced(self) -> None:
        """The planted defect for this detector: env is a no-op wrapper."""
        if not baseline_reachable():
            self.skipTest("remote unreachable from this host; a no-op sandbox cannot be caught")
        code, transcript, _ = run_runner("--probe-only", "--sandbox", "env")
        self.assertEqual(code, 5)
        self.assertEqual(transcript["status"], "OFFLINE_NOT_ENFORCED")
        self.assertEqual(transcript["sandboxed_probe_successes"], len(POLICY["probes"]))

    def test_a_missing_sandbox_is_not_supported_rather_than_a_pass(self) -> None:
        code, transcript, _ = run_runner("--probe-only", "--sandbox", "po03-no-such-sandbox")
        self.assertEqual(code, 3)
        self.assertEqual(transcript["status"], "NOT_SUPPORTED")
        self.assertFalse(transcript["sandbox_available"])


class PlantedDependenceIsCaught(unittest.TestCase):
    @requires_sandbox
    def test_unmarked_network_dependence_fails_offline(self) -> None:
        code, transcript, _ = run_runner(
            "--suite-dir", FIXTURE_DIR, "--suite-pattern", "test_unmarked_*.py"
        )
        self.assertEqual(code, 1)
        self.assertEqual(transcript["status"], "FAIL")
        self.assertEqual(transcript["suite"]["tests_run"], 1)
        self.assertIn("getaddrinfo", transcript["suite"]["tail"])
        # The separated list describes the directory, not the discovery pattern,
        # so the marked sibling appears even though it was not run. Being marked
        # is what does not rescue the unmarked module from failing.
        self.assertNotIn("test_unmarked_network_dependence.py", transcript["separated_modules"])

    @requires_sandbox
    def test_marked_network_dependence_is_separated_and_skipped(self) -> None:
        code, transcript, _ = run_runner(
            "--suite-dir", FIXTURE_DIR, "--suite-pattern", "test_marked_*.py"
        )
        self.assertEqual(code, 0)
        self.assertEqual(transcript["status"], "PASS")
        self.assertEqual(transcript["separated_modules"], ["test_marked_network_dependence.py"])
        self.assertEqual(transcript["suite"]["tests_skipped"], 1)


class CommittedTranscript(unittest.TestCase):
    """The recorded offline run, so the evidence survives without the sandbox."""

    def setUp(self) -> None:
        if not TRANSCRIPT_PATH.is_file():
            self.skipTest(f"no recorded transcript at {TRANSCRIPT_PATH}")
        self.transcript = json.loads(TRANSCRIPT_PATH.read_text(encoding="utf-8"))

    def test_recorded_run_passed_with_the_network_disabled(self) -> None:
        self.assertEqual(self.transcript["schema"], "po03-offline-transcript-v1")
        self.assertEqual(self.transcript["unit_id"], "a3-u06")
        self.assertEqual(self.transcript["status"], "PASS")
        self.assertEqual(self.transcript["suite"]["exit_code"], 0)
        self.assertEqual(self.transcript["suite"]["start_directory"], "workstreams/po03/tests")
        self.assertEqual(self.transcript["suite"]["pattern"], "test_*.py")

    def test_recorded_run_proved_the_sandbox_changed_something(self) -> None:
        self.assertTrue(self.transcript["sandbox_available"])
        self.assertEqual(self.transcript["baseline_probe_failures"], 0)
        self.assertEqual(self.transcript["sandboxed_probe_successes"], 0)
        phases = {(p["probe_id"], p["phase"]): p["exit_code"] for p in self.transcript["probes"]}
        for probe in POLICY["probes"]:
            self.assertEqual(phases[(probe["id"], "baseline")], 0, probe["id"])
            self.assertNotEqual(phases[(probe["id"], "sandboxed")], 0, probe["id"])

    def test_recorded_run_covered_the_whole_suite(self) -> None:
        """A transcript of three tests would not support the unit's claim.

        The count cannot be re-derived by running the suite here: this module is
        part of that suite, so a subprocess re-run would recurse without bound.
        Instead the transcript names the commit it describes and the count is
        compared against the modules committed at that commit.
        """
        commit = self.transcript["repository_commit"]
        self.assertRegex(commit, r"^[0-9a-f]{40}$")
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=REPO_ROOT
        )
        self.assertEqual(ancestor.returncode, 0, f"{commit} is not an ancestor of HEAD")
        modules = subprocess.run(
            ["git", "ls-tree", "--name-only", f"{commit}:workstreams/po03/tests"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        recorded_modules = [name for name in modules if name.startswith("test_")]
        self.assertGreaterEqual(len(recorded_modules), 8)
        self.assertGreater(self.transcript["suite"]["tests_run"], 100)

    def test_recorded_run_separated_nothing_because_nothing_needs_the_remote(self) -> None:
        self.assertEqual(self.transcript["separated_modules"], [])
        self.assertEqual(self.transcript["environment"]["inherited_variables"], 0)


if __name__ == "__main__":
    unittest.main()
