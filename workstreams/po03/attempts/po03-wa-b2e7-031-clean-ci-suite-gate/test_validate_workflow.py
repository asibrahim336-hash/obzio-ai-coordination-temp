#!/usr/bin/env python3
"""Tests for the staged PO-03 suite workflow and its validator.

Three separate claims are under test and they are not the same claim.

That the validator can read the staged file.  A YAML subset parser that silently
skipped a step would let an unchecked step through, so the parser is required to
raise on anything it cannot read, and the real staged workflow is required to
parse into the steps it visibly contains.

That the structural checks have teeth.  A checker that returns no findings for
every input is worthless, so each check is driven with a workflow mutated to
violate exactly that check and is required to report it.  This is the same
non-vacuity discipline the rejection fixture applies to the path-scope guard.

That the staged file is installable where it claims.  The declared install path
is fed to the live path-scope guard, so the claim "this path is inside the
commissioned allowlist" is measured against the guard that will judge it rather
than asserted in a comment.

Full-suite execution in a clean clone is deliberately not driven from here.  It
is minutes of work and its evidence is captured by running the validator with
--execute directly; these tests cover the execution machinery with a synthetic
step instead.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = UNIT_ROOT.parents[3]
LEGACY_GUARD = REPO_ROOT / "workstreams" / "po03" / "tools" / "check_path_scope.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load(UNIT_ROOT / "validate_workflow.py", "po03_validate_workflow")
WORKFLOW_TEXT = (UNIT_ROOT / "po03-suite.yml").read_text(encoding="utf-8")


class ParseTests(unittest.TestCase):
    """The parser must read the real file and refuse what it cannot read."""

    def test_the_staged_workflow_parses_into_its_visible_steps(self):
        top_level, steps = validator.parse(WORKFLOW_TEXT)
        for key in ("name", "on", "permissions", "concurrency", "jobs"):
            self.assertIn(key, top_level, f"top-level key {key} was not parsed")
        # Every `- uses:` and `- name:` in the file must become exactly one step.
        expected = sum(
            1 for line in WORKFLOW_TEXT.splitlines()
            if line.strip().startswith("- uses:") or line.strip().startswith("- name:")
        )
        self.assertEqual(len(steps), expected, "parsed step count disagrees with the file")
        self.assertTrue(all(step.uses or step.run for step in steps))

    def test_every_named_step_keeps_its_run_block(self):
        _, steps = validator.parse(WORKFLOW_TEXT)
        named = [step for step in steps if step.name]
        self.assertTrue(named, "no named steps parsed")
        for step in named:
            self.assertIsNotNone(step.run, f"step {step.name!r} lost its run block")
            self.assertTrue(step.run.strip(), f"step {step.name!r} has an empty run block")

    def test_a_multi_line_run_block_survives_intact(self):
        _, steps = validator.parse(WORKFLOW_TEXT)
        loop = next(s for s in steps if s.name == "Run every counted unit's own tests")
        # The loop body is what makes the aggregate step aggregate; if the parser
        # kept only the first line the forbidden-content checks would inspect
        # almost nothing.
        self.assertIn("for unit in workstreams/po03/attempts/*/", loop.run)
        self.assertIn("PO03_SUITE_ERROR", loop.run)
        self.assertGreater(len(loop.run.splitlines()), 8)

    def test_an_unreadable_step_line_raises_instead_of_being_skipped(self):
        broken = WORKFLOW_TEXT.replace(
            "      - name: Record the runtime that produced this result",
            "      - name: Record the runtime that produced this result\n        !!! unreadable",
        )
        with self.assertRaises(validator.WorkflowError):
            validator.parse(broken)

    def test_an_unreadable_top_level_line_raises(self):
        with self.assertRaises(validator.WorkflowError):
            validator.parse("name: x\n!!! junk\n")

    def test_a_file_with_no_steps_raises(self):
        with self.assertRaises(validator.WorkflowError):
            validator.parse("name: x\npermissions:\n  contents: read\n")


class StructuralCheckTests(unittest.TestCase):
    """Each check is proved non-vacuous by a workflow that violates only it."""

    def findings_for(self, text: str) -> list[str]:
        top_level, steps = validator.parse(text)
        return validator.structural_findings(top_level, steps)

    def test_the_staged_workflow_has_no_structural_findings(self):
        self.assertEqual(self.findings_for(WORKFLOW_TEXT), [])

    def test_a_write_permission_is_reported(self):
        findings = self.findings_for(WORKFLOW_TEXT.replace("contents: read", "contents: write"))
        self.assertIn("PERMISSIONS_NOT_READ_ONLY", findings)

    def test_a_trigger_path_outside_the_allowlist_is_reported(self):
        findings = self.findings_for(
            WORKFLOW_TEXT.replace('- "receipts/po03/**"', '- "state/**"', 1)
        )
        self.assertTrue(
            any(f.startswith("TRIGGER_PATH_OUTSIDE_ALLOWLIST state/**") for f in findings),
            findings,
        )

    def test_an_unpinned_action_is_reported(self):
        findings = self.findings_for(
            WORKFLOW_TEXT.replace("actions/checkout@v4", "actions/checkout@main")
        )
        self.assertIn("MISSING_PINNED_ACTION actions/checkout@v4", findings)

    def test_a_package_install_is_reported(self):
        findings = self.findings_for(
            WORKFLOW_TEXT.replace("          git --version", "          pip install pyyaml")
        )
        self.assertTrue(
            any("FORBIDDEN_RUN_CONTENT" in f and "third-party" in f for f in findings), findings
        )

    def test_a_network_fetch_is_reported(self):
        findings = self.findings_for(
            WORKFLOW_TEXT.replace("          git --version", "          curl http://example.invalid")
        )
        self.assertTrue(
            any("FORBIDDEN_RUN_CONTENT" in f and "network" in f for f in findings), findings
        )

    def test_a_github_expression_in_a_run_block_is_reported(self):
        # Expressions are fine in `concurrency:` but a run block carrying one is
        # not locally executable, so the execution evidence would be a fiction.
        findings = self.findings_for(
            WORKFLOW_TEXT.replace("          git --version", "          echo ${{ github.sha }}")
        )
        self.assertTrue(
            any("FORBIDDEN_RUN_CONTENT" in f and "GitHub expression" in f for f in findings),
            findings,
        )

    def test_python_without_the_isolated_flag_is_reported(self):
        findings = self.findings_for(
            WORKFLOW_TEXT.replace(
                "python -I workstreams/po03/tools/check_path_scope.py",
                "python workstreams/po03/tools/check_path_scope.py",
            )
        )
        self.assertTrue(
            any(f.startswith("PYTHON_WITHOUT_ISOLATED_FLAG") for f in findings), findings
        )

    def test_an_unnamed_run_step_is_reported(self):
        findings = self.findings_for(
            WORKFLOW_TEXT.replace(
                "      - name: Enforce the immutable PO-03 path boundary\n        run: |",
                "      - run: |",
            )
        )
        self.assertIn("UNNAMED_RUN_STEP", findings)

    def test_dropping_the_path_scope_guard_step_is_reported(self):
        findings = self.findings_for(
            WORKFLOW_TEXT.replace(
                "          python -I workstreams/po03/tools/check_path_scope.py",
                "          true",
            )
        )
        self.assertIn("NO_PATH_SCOPE_GUARD_STEP", findings)

    def test_dropping_the_contract_suite_step_is_reported(self):
        findings = self.findings_for(
            WORKFLOW_TEXT.replace("unittest discover -s workstreams/po03/tests", "true #", 1)
        )
        self.assertIn("NO_CONTRACT_SUITE_STEP", findings)

    def test_dropping_the_rejection_fixture_step_is_reported(self):
        findings = self.findings_for(WORKFLOW_TEXT.replace("rejection_fixture.py", "true"))
        self.assertIn("NO_REJECTION_FIXTURE_STEP", findings)

    def test_dropping_the_aggregate_unit_test_step_is_reported(self):
        findings = self.findings_for(
            WORKFLOW_TEXT.replace("workstreams/po03/attempts/*/", "IGNORED")
        )
        self.assertIn("NO_AGGREGATE_UNIT_TEST_STEP", findings)

    def test_a_missing_top_level_key_is_reported(self):
        findings = self.findings_for(WORKFLOW_TEXT.replace("permissions:\n  contents: read\n", ""))
        self.assertIn("MISSING_TOP_LEVEL_KEY permissions", findings)

    def test_a_missing_trigger_is_reported(self):
        findings = self.findings_for(WORKFLOW_TEXT.replace("  pull_request:\n", "", 1))
        self.assertIn("NO_PULL_REQUEST_TRIGGER", findings)


class DeliverableTests(unittest.TestCase):
    """The staged file must actually contain the commissioned deliverable."""

    def setUp(self):
        _, self.steps = validator.parse(WORKFLOW_TEXT)
        self.blocks = "\n".join(step.run for step in self.steps if step.run)

    def test_the_required_deliverable_elements_are_all_present(self):
        # The capsule names three things the runner must exercise.
        for required in (
            "unittest discover -s workstreams/po03/tests",
            "check_path_scope.py",
            "rejection_fixture.py",
        ):
            self.assertIn(required, self.blocks, f"workflow never runs {required}")

    def test_every_c4_mechanism_is_exercised_by_some_step(self):
        for mechanism in (
            "hardened_path_scope.py",
            "coverage_assert.py",
            "provenance_walker.py",
            "tamper_harness.py",
        ):
            self.assertIn(mechanism, self.blocks, f"workflow never runs {mechanism}")

    def test_the_runner_checks_out_full_history(self):
        # The pinned base commit is unreachable at the default shallow depth, so
        # without this the guard steps would error rather than judge.
        self.assertIn("fetch-depth: 0", WORKFLOW_TEXT)

    def test_the_hardened_guard_uses_the_same_pinned_base_as_the_legacy_guard(self):
        legacy = load(LEGACY_GUARD, "po03_legacy_guard_for_031")
        self.assertIn(legacy.PINNED_BASE_SHA, WORKFLOW_TEXT)

    def test_every_aggregate_loop_fails_closed_when_it_finds_nothing(self):
        # A `for` loop over an empty glob exits 0 and would report a green gate
        # having verified nothing at all.
        loops = [step for step in self.steps if step.run and "for " in step.run]
        self.assertGreaterEqual(len(loops), 3)
        for step in loops:
            self.assertIn("PO03_SUITE_ERROR", step.run, f"{step.name!r} cannot fail closed")
            self.assertIn("exit 1", step.run, f"{step.name!r} does not exit non-zero when empty")


class InstallPathTests(unittest.TestCase):
    """The declared install path is judged by the guard, not by assertion."""

    def test_the_live_guard_admits_the_declared_install_path(self):
        completed = subprocess.run(
            (sys.executable, "-I", str(LEGACY_GUARD), "--path", validator.INSTALL_PATH),
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_the_install_path_is_declared_in_the_file_itself(self):
        # A controller reading only the staged bytes must learn where they go.
        self.assertIn(f"INSTALL AS: {validator.INSTALL_PATH}", WORKFLOW_TEXT)

    def test_the_staged_file_is_not_itself_inside_dot_github(self):
        staged = (UNIT_ROOT / "po03-suite.yml").resolve()
        self.assertNotIn(".github", staged.parts)
        self.assertTrue(staged.is_relative_to(UNIT_ROOT))


class CleanCloneTests(unittest.TestCase):
    """The execution substrate must hold committed bytes only."""

    @classmethod
    def setUpClass(cls):
        cls.holder = Path(tempfile.mkdtemp(prefix="po03-031-clone-"))
        head = subprocess.run(
            ("git", "rev-parse", "HEAD"), cwd=REPO_ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        cls.checkout = validator.clean_clone(head, cls.holder)
        cls.head = head

    @classmethod
    def tearDownClass(cls):
        subprocess.run(("rm", "-rf", str(cls.holder)), check=False)

    def test_the_clone_is_detached_at_the_requested_commit(self):
        resolved = subprocess.run(
            ("git", "rev-parse", "HEAD"), cwd=self.checkout, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(resolved, self.head)

    def test_the_clone_carries_no_untracked_or_modified_state(self):
        # This is the operative evidence for "no repository-local state": an
        # untracked helper or a stray __pycache__ in the producer's worktree
        # cannot travel into the clone.
        status = subprocess.run(
            ("git", "status", "--porcelain"), cwd=self.checkout, check=True,
            capture_output=True, text=True,
        ).stdout
        self.assertEqual(status, "", f"clean clone was not clean: {status!r}")

    def test_the_producer_worktree_untracked_files_are_absent_from_the_clone(self):
        untracked = [
            line[3:] for line in subprocess.run(
                ("git", "status", "--porcelain"), cwd=REPO_ROOT, check=True,
                capture_output=True, text=True,
            ).stdout.splitlines() if line.startswith("??")
        ]
        for path in untracked:
            self.assertFalse(
                (self.checkout / path).exists(),
                f"untracked producer path {path} leaked into the clean clone",
            )

    def test_a_step_runs_in_the_clone_with_a_scrubbed_environment(self):
        home = self.holder / "probe-home"
        home.mkdir(exist_ok=True)
        environment = validator.scrubbed_environment(home)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertEqual(environment["HOME"], str(home))
        completed = subprocess.run(
            ("bash", "-euo", "pipefail", "-c", "python3 -I -c 'import sys; print(sys.prefix)'"),
            cwd=self.checkout, env=environment, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_a_failing_step_is_reported_as_failing(self):
        # Guards against an execute() that swallows non-zero exits.
        failing = [validator.Step("deliberate failure", None, "exit 3\n")]
        outcomes = validator.execute(failing, self.head, self.holder / "fail-probe")

        self.assertEqual(len(outcomes), 1)
        self.assertFalse(outcomes[0]["passed"])
        self.assertEqual(outcomes[0]["exit_code"], 3)

    def test_a_step_that_reads_an_untracked_file_fails_in_the_clone(self):
        # Direct refutation attempt against the clean-environment claim: a step
        # depending on repository-local state must not pass in the clone.
        probe = REPO_ROOT / "po03-031-local-state-probe.txt"
        self.addCleanup(lambda: probe.unlink(missing_ok=True))
        probe.write_text("local state\n", encoding="utf-8")
        step = [validator.Step("read local state", None, f"cat {probe.name}\n")]
        outcomes = validator.execute(step, self.head, self.holder / "state-probe")
        self.assertFalse(
            outcomes[0]["passed"],
            "a step reading an untracked worktree file passed inside the clean clone",
        )


class CommandLineTests(unittest.TestCase):
    """The validator is CI-callable and signals through its exit code."""

    def run_validator(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            (sys.executable, "-I", str(UNIT_ROOT / "validate_workflow.py"), *extra),
            cwd=REPO_ROOT, capture_output=True, text=True,
        )

    def test_the_staged_workflow_passes_the_structural_gate(self):
        completed = self.run_validator()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("PO03_WORKFLOW_PASS", completed.stdout)

    def test_json_mode_emits_one_parseable_document_on_stdout(self):
        import json

        completed = self.run_validator("--json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["install_path"], validator.INSTALL_PATH)
        self.assertEqual(report["findings"], [])
        self.assertTrue(report["steps"])

    def test_a_violating_workflow_exits_non_zero(self):
        with tempfile.TemporaryDirectory() as scratch:
            bad = Path(scratch) / "bad.yml"
            bad.write_text(WORKFLOW_TEXT.replace("contents: read", "contents: write"), encoding="utf-8")
            completed = self.run_validator("--workflow", str(bad))
        self.assertEqual(completed.returncode, 1)
        self.assertIn("PERMISSIONS_NOT_READ_ONLY", completed.stderr)

    def test_an_unreadable_workflow_exits_two(self):
        with tempfile.TemporaryDirectory() as scratch:
            junk = Path(scratch) / "junk.yml"
            junk.write_text("!!! not a workflow\n", encoding="utf-8")
            completed = self.run_validator("--workflow", str(junk))
        self.assertEqual(completed.returncode, 2)
        self.assertIn("PO03_WORKFLOW_ERROR", completed.stderr)

    def test_a_missing_workflow_exits_two(self):
        completed = self.run_validator("--workflow", str(UNIT_ROOT / "absent.yml"))
        self.assertEqual(completed.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
