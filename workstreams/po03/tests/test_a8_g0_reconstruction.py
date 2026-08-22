#!/usr/bin/env python3
"""Tests that G0 is faithful to the pinned pre-amendment source, and executable.

The claim "the pre-amendment controller had no durable result custody" is only
worth anything if it is checked against the immutable commit rather than
remembered.  The first test does that with read-only git access, so if the
reconstruction basis were ever wrong the suite would say so.

The remaining tests pin G0's behaviour in both directions: the capabilities it
genuinely had, and the defects that make it the baseline.  Asserting the defects
matters as much as asserting the capabilities - a G0 that quietly improved would
understate every later generation's lift.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PO03 = Path(__file__).resolve().parents[1]
REPO_ROOT = PO03.parents[1]
if str(PO03) not in sys.path:
    sys.path.insert(0, str(PO03))

from successor.g0.controller import G0Controller, build
from successor.harness.controller_api import NOT_SUPPORTED, Clock
from successor.harness.runner import load_cases, run_suite
from successor.harness.score import summarise

PRIOR_OBSERVED_HEAD = "d627119351a6dc0e90158705abf6aab96e26b3dd"
PRIOR_COMMISSION_COMMIT = "887b3c1ac2dec49d5f36d31593e416f651486aee"
PINNED_BASE_SHA = "5db7affeb7f00763e148e6d98a33ee6b751f2def"


def git(*args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:  # pragma: no cover - git absent
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


class ReconstructionBasisTests(unittest.TestCase):
    """Verify against the immutable commits, not against a memory of them."""

    def setUp(self) -> None:
        if git("cat-file", "-e", f"{PRIOR_OBSERVED_HEAD}^{{commit}}") is None:
            self.skipTest("pinned pre-amendment commit not reachable in this clone")

    def test_pre_amendment_tree_holds_exactly_two_po03_files(self):
        listing = git("ls-tree", "-r", "--name-only", PRIOR_OBSERVED_HEAD, "--", "workstreams/po03", "receipts/po03")
        self.assertIsNotNone(listing)
        files = sorted(line for line in listing.splitlines() if line.strip())
        self.assertEqual(
            files,
            ["receipts/po03/2026-08-22/appointment-seed.json", "workstreams/po03/COMMISSION.md"],
        )

    def test_pre_amendment_tree_contains_no_executable_controller(self):
        listing = git("ls-tree", "-r", "--name-only", PRIOR_OBSERVED_HEAD)
        self.assertIsNotNone(listing)
        po03_python = [
            line
            for line in listing.splitlines()
            if line.startswith(("workstreams/po03/", "receipts/po03/")) and line.endswith(".py")
        ]
        self.assertEqual(po03_python, [], "a controller implementation would change G0's reconstruction")

    def test_pre_amendment_commission_never_separates_provider_from_obzio_completion(self):
        text = git("show", f"{PRIOR_COMMISSION_COMMIT}:workstreams/po03/COMMISSION.md")
        self.assertIsNotNone(text)
        self.assertNotIn("PROVIDER_COMPLETED_UNCOMMITTED", text)
        self.assertNotIn("fence", text.lower())
        self.assertNotIn("idempotency", text.lower())
        # The capability G0 genuinely had, quoted from the same immutable text.
        self.assertIn("pinned by repository and SHA", text)

    def test_pinned_base_predates_any_po03_content(self):
        listing = git("ls-tree", "-r", "--name-only", PINNED_BASE_SHA, "--", "workstreams/po03")
        self.assertEqual((listing or "").strip(), "")


class CapabilityBoundaryTests(unittest.TestCase):
    def test_g0_lacks_leases_ingestion_and_recovery(self):
        absent = {"lease", "ingest", "recover"}
        self.assertEqual(absent & set(G0Controller.capabilities()), set())

    def test_absent_capabilities_report_not_supported(self):
        with tempfile.TemporaryDirectory() as scratch:
            controller = build(root=Path(scratch), clock=Clock())
            for operation in ("lease", "ingest", "recover"):
                self.assertEqual(controller.apply(operation, {}).reason_code, NOT_SUPPORTED)


class BaselineDefectTests(unittest.TestCase):
    """The defects that define the baseline, asserted so they cannot drift."""

    def _controller(self, scratch: str) -> G0Controller:
        return build(root=Path(scratch), clock=Clock())

    def test_provider_completion_becomes_recorded_completion(self):
        with tempfile.TemporaryDirectory() as scratch:
            controller = self._controller(scratch)
            controller.apply("create", {"unit_id": "u1", "spec": {}})
            outcome = controller.apply(
                "submit",
                {
                    "unit_id": "u1",
                    "worker": "w1",
                    "provider_state": "COMPLETED",
                    "claimed_state": "COMPLETED",
                    "artifacts": [],
                    "result_commit_id": None,
                },
            )
            self.assertTrue(outcome.admitted)
            state = controller.apply("state", {"unit_id": "u1"})
            self.assertEqual(state.detail["obzio_state"], "COMPLETED")
            self.assertIsNone(state.detail["result_commit_id"])

    def test_any_actor_may_complete(self):
        with tempfile.TemporaryDirectory() as scratch:
            controller = self._controller(scratch)
            controller.apply("create", {"unit_id": "u1", "spec": {}})
            outcome = controller.apply("complete", {"unit_id": "u1", "actor": "some-worker"})
            self.assertTrue(outcome.admitted)
            self.assertEqual(outcome.detail["completion_actor"], "some-worker")

    def test_no_artifact_is_ever_read_back(self):
        with tempfile.TemporaryDirectory() as scratch:
            controller = self._controller(scratch)
            controller.apply("create", {"unit_id": "u1", "spec": {}})
            outcome = controller.apply(
                "submit",
                {
                    "unit_id": "u1",
                    "worker": "w1",
                    "artifacts": [{"artifact_id": "a1", "path": "nowhere.json", "sha256": "0" * 64, "bytes": 99}],
                    "result_commit_id": "deadbeef",
                },
            )
            self.assertTrue(outcome.admitted)
            self.assertEqual(outcome.detail["verified_artifacts"], 0)
            self.assertFalse(outcome.detail["artifacts_read_back"])

    def test_history_is_overwritten_in_place(self):
        with tempfile.TemporaryDirectory() as scratch:
            controller = self._controller(scratch)
            controller.apply("create", {"unit_id": "u1", "spec": {}})
            controller.apply("complete", {"unit_id": "u1"})
            receipts = sorted((Path(scratch) / "receipts").glob("*.json"))
            self.assertEqual(len(receipts), 1, "a mutable receipt file, with no immutable history behind it")


class RetainedCapabilityTests(unittest.TestCase):
    """What G0 did have. G1 lost one of these, which the comparison must show."""

    def test_pinned_input_drift_is_detected(self):
        with tempfile.TemporaryDirectory() as scratch:
            controller = build(root=Path(scratch), clock=Clock())
            controller.apply("create", {"unit_id": "u1", "spec": {"pinned_inputs": {"a": "0" * 64}}})
            controller.apply(
                "tamper",
                {"target": "record", "kind": "edit", "unit_id": "u1", "fields": {"pinned_inputs": {"a": "1" * 64}}},
            )
            outcome = controller.apply("verify", {})
            self.assertEqual(outcome.detail["input_drift"], ["u1"])

    def test_restart_recovers_the_last_report_from_disk(self):
        with tempfile.TemporaryDirectory() as scratch:
            first = build(root=Path(scratch), clock=Clock())
            first.apply("create", {"unit_id": "u1", "spec": {}})
            second = build(root=Path(scratch), clock=Clock())
            outcome = second.apply("restart", {})
            self.assertEqual(outcome.detail["units_recovered"], 1)


class ExecutableGenerationTests(unittest.TestCase):
    """G0 is code that runs the frozen suite, not a description of code."""

    def test_g0_runs_the_frozen_public_suite_and_scores_measurably(self):
        _, cases = load_cases(PO03 / "successor" / "suite" / "public" / "cases.json")
        summary = summarise(run_suite(build, cases))
        self.assertGreater(summary["cases_total"], 0)
        self.assertGreater(
            summary["unsupported_case_count"], 0, "absent custody must show up as unsupported cases"
        )
        self.assertGreater(
            summary["false_completion_count"], 0, "the baseline permits false completion; that is the finding"
        )
        self.assertLess(summary["pass_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
