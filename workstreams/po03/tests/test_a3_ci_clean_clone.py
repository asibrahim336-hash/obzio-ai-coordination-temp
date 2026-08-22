"""Unit a3-u04: the clean-runner workflow, and the receipt for its real run.

The acceptance is falsified if the workflow needs a preinstalled dependency or a
warm cache, so both are checked here against the committed workflow rather than
described in it. Every rule in ``ci-surface-rules.json`` is proved to fire, on a
planted fixture for the text rules and on synthetic trees for the rest: a rule
that has never fired is not evidence.

The receipt is the one artifact this runtime cannot manufacture. A GitHub
Actions run URL, conclusion and duration are only observable after the workflow
runs on GitHub, so the receipt is checked for shape and for internal consistency
with what was actually observed, and the tests skip while it is absent rather
than asserting against a placeholder.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_DIR = REPO_ROOT / "workstreams" / "po03" / "runtime"
RULES_PATH = RUNTIME_DIR / "ci-surface-rules.json"
FIXTURE_DIR = RUNTIME_DIR / "fixtures" / "ci_surface"
EXPECTED_PATH = FIXTURE_DIR / "expected-findings.json"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "po03-clean-clone.yml"
SEEDED_PATH = REPO_ROOT / ".github" / "workflows" / "po03-contracts.yml"
RECEIPT_PATH = REPO_ROOT / "receipts" / "po03" / "2026-08-22" / "ci-clean-clone.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ci_surface = load_module(RUNTIME_DIR / "ci_surface.py", "po03_ci_surface")
RULES = ci_surface.load_rules(RULES_PATH)
EXPECTED = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


class WorkflowSurface(unittest.TestCase):
    def setUp(self) -> None:
        self.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_workflow_is_committed_and_named_in_scope(self) -> None:
        self.assertTrue(WORKFLOW_PATH.is_file())
        self.assertTrue(WORKFLOW_PATH.name.startswith("po03-"))
        self.assertTrue(WORKFLOW_PATH.name.endswith(".yml"))

    def test_real_surface_passes_its_own_check(self) -> None:
        """Workflow text only: running this suite is itself what writes bytecode."""
        report = ci_surface.run(RULES, REPO_ROOT, skip_bytecode=True)
        self.assertEqual(report["verdict"], "PASS", json.dumps(report["findings"], indent=2))

    def test_the_bytecode_check_runs_before_anything_imports(self) -> None:
        """Ordering is load-bearing: after the first suite pass the tree has caches."""
        surface = self.text.index("ci_surface.py")
        first_suite = self.text.index("-m unittest discover")
        self.assertLess(surface, first_suite)

    def test_workflow_uses_only_the_two_approved_actions(self) -> None:
        used = set(ci_surface.ACTION_PATTERN.findall(self.text))
        self.assertTrue(used)
        self.assertEqual(used - set(RULES["allowed_actions"]), set())

    def test_workflow_runs_the_canonical_gate_command(self) -> None:
        self.assertIn(
            "python3 -I -m unittest discover -s workstreams/po03/tests -p 'test_*.py'", self.text
        )

    def test_workflow_runs_the_suite_without_site_packages(self) -> None:
        """-S is what turns 'no third-party dependency' into an observation."""
        self.assertIn(
            "python3 -I -S -m unittest discover -s workstreams/po03/tests -p 'test_*.py'", self.text
        )

    def test_no_site_packages_pass_precedes_the_canonical_pass(self) -> None:
        stripped = self.text.index("-I -S -m unittest")
        canonical = self.text.index("Run the canonical gate command")
        self.assertLess(stripped, canonical)

    def test_workflow_runs_on_pull_request_and_on_this_branch_class(self) -> None:
        self.assertIn("pull_request:", self.text)
        self.assertIn('"cursor/po03-**"', self.text)
        self.assertIn('"po03/**"', self.text)

    def test_workflow_exercises_every_owned_portability_gate(self) -> None:
        for entry_point in (
            "hermeticity.py",
            "determinism.py",
            "committed_only.py",
            "process_boundary.py",
            "path_scope.py selftest",
            "clean_clone.sh",
            "offline_check.sh",
            "ci_surface.py",
        ):
            self.assertIn(entry_point, self.text, entry_point)


class SeededControlIsNotWeakened(unittest.TestCase):
    """po03-contracts.yml is an active control; this unit strengthens around it."""

    def test_seeded_gate_is_present_and_intact(self) -> None:
        self.assertTrue(SEEDED_PATH.is_file())
        self.assertEqual(ci_surface.check_seeded_control(RULES, REPO_ROOT), [])

    def test_removal_of_the_seeded_gate_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            (root / ".github" / "workflows").mkdir(parents=True)
            findings = ci_surface.check_seeded_control(RULES, root)
            self.assertEqual([finding.rule for finding in findings], ["SEEDED_CONTROL_REMOVED"])

    def test_weakening_the_seeded_gate_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            target = root / RULES["seeded_control"]["path"]
            target.parent.mkdir(parents=True)
            weakened = SEEDED_PATH.read_text(encoding="utf-8").replace(
                "unittest discover -s workstreams/po03/tests -p 'test_*.py'",
                "unittest discover -s workstreams/po03/tests -p 'test_validate_contracts.py'",
            )
            target.write_text(weakened, encoding="utf-8")
            findings = ci_surface.check_seeded_control(RULES, root)
            self.assertEqual([finding.rule for finding in findings], ["SEEDED_CONTROL_WEAKENED"])


class PlantedWorkflowDefectsAreCaught(unittest.TestCase):
    def test_each_fixture_fires_exactly_its_recorded_rules(self) -> None:
        for relative, expected in EXPECTED["expected"].items():
            with self.subTest(fixture=relative):
                findings = ci_surface.check_workflow(RULES, REPO_ROOT, relative)
                self.assertEqual(sorted({finding.rule for finding in findings}), sorted(expected))

    def test_every_text_rule_is_covered_by_a_fixture(self) -> None:
        """Otherwise a rule could be silently broken and nothing would notice."""
        fired = {rule for rules in EXPECTED["expected"].values() for rule in rules}
        for name in RULES["forbidden_patterns"]:
            self.assertIn(name, fired, name)

    def test_fixtures_are_inert(self) -> None:
        """A planted broken workflow inside .github/workflows would really run."""
        for relative in EXPECTED["expected"]:
            self.assertNotIn(".github", Path(relative).parts)


class BytecodePolicy(unittest.TestCase):
    def test_the_real_checkout_carries_only_registered_bytecode(self) -> None:
        findings = [
            finding
            for finding in ci_surface.check_bytecode(RULES, REPO_ROOT)
            if finding.rule != "WARM_BYTECODE_CACHE"
        ]
        self.assertEqual([finding.as_dict() for finding in findings], [])

    def test_registered_exceptions_are_the_paths_actually_committed(self) -> None:
        self.assertEqual(
            sorted(RULES["bytecode_policy"]["tracked_exceptions"]),
            ci_surface.tracked_bytecode(REPO_ROOT),
        )

    def test_a_warm_cache_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            cache = root / "pkg" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "warm.cpython-312.pyc").write_bytes(b"\x00")
            rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
            rules["bytecode_policy"]["tracked_exceptions"] = []
            findings = ci_surface.check_bytecode(rules, root)
            self.assertEqual([finding.rule for finding in findings], ["WARM_BYTECODE_CACHE"])

    def test_a_stale_exception_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            findings = ci_surface.check_bytecode(RULES, root)
            self.assertEqual(
                sorted({finding.rule for finding in findings}), ["STALE_BYTECODE_EXCEPTION"]
            )

    def test_the_repair_candidate_records_the_inherited_bytecode(self) -> None:
        record = json.loads(
            (RUNTIME_DIR / "repair-candidates" / "tracked-bytecode.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(record["disposition"], "PROPOSED_TO_COORDINATOR")
        self.assertFalse(record["applied_by_this_writer"])
        self.assertEqual(
            RULES["bytecode_policy"]["repair_candidate"],
            "workstreams/po03/runtime/repair-candidates/tracked-bytecode.json",
        )


class CommandLineBehaviour(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", "-B", str(RUNTIME_DIR / "ci_surface.py"), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

    def test_exits_zero_on_the_real_surface(self) -> None:
        result = self.run_cli("--skip-bytecode")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no cache, no install and no secret", result.stdout)

    def test_json_report_shape(self) -> None:
        result = self.run_cli("--skip-bytecode", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "po03-ci-surface-report-v1")
        self.assertEqual(report["unit_id"], "a3-u04")
        self.assertEqual(report["findings"], [])

    def test_bad_rules_schema_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            bad = Path(scratch) / "rules.json"
            bad.write_text(json.dumps({"schema": "nope"}), encoding="utf-8")
            result = self.run_cli("--rules", str(bad))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("CI_SURFACE_ERROR", result.stderr)


class Receipt(unittest.TestCase):
    """The receipt records a run this runtime observed, or it does not exist."""

    def setUp(self) -> None:
        if not RECEIPT_PATH.is_file():
            self.skipTest(f"no CI receipt at {RECEIPT_PATH}; the workflow has not been observed")
        self.receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))

    def test_receipt_records_url_conclusion_and_duration(self) -> None:
        self.assertEqual(self.receipt["schema"], "po03-ci-receipt-v1")
        self.assertEqual(self.receipt["unit_id"], "a3-u04")
        run = self.receipt["run"]
        self.assertRegex(run["url"], r"^https://github\.com/[^/]+/[^/]+/actions/runs/\d+$")
        self.assertIn(run["conclusion"], {"success", "failure", "cancelled", "skipped"})
        self.assertIsInstance(run["duration_seconds"], int)
        self.assertGreater(run["duration_seconds"], 0)

    def test_receipt_url_and_identifiers_agree(self) -> None:
        run = self.receipt["run"]
        self.assertTrue(run["url"].endswith(f"/{run['id']}"))
        self.assertEqual(run["workflow_file"], "po03-clean-clone.yml")

    def test_recorded_commit_is_on_this_branch(self) -> None:
        commit = self.receipt["run"]["head_sha"]
        self.assertRegex(commit, r"^[0-9a-f]{40}$")
        reachable = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=REPO_ROOT
        )
        self.assertEqual(reachable.returncode, 0, f"{commit} is not an ancestor of HEAD")

    def test_observation_method_is_stated(self) -> None:
        """A receipt that does not say how it was obtained cannot be checked."""
        self.assertIn("gh run view", self.receipt["observation"]["command"])
        self.assertTrue(self.receipt["observation"]["observed_by"].strip())

    def test_step_conclusions_are_recorded_not_summarised(self) -> None:
        steps = self.receipt["run"]["steps"]
        self.assertTrue(steps)
        for step in steps:
            self.assertTrue(step["name"].strip())
            self.assertIn(step["conclusion"], {"success", "failure", "skipped", "cancelled", None})

    def test_boundaries_are_named_rather_than_smoothed_over(self) -> None:
        for boundary in self.receipt.get("boundaries", []):
            self.assertTrue(boundary["statement"].strip())
            self.assertTrue(boundary["observed_in"].strip())


if __name__ == "__main__":
    unittest.main()
