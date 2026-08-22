#!/usr/bin/env python3
"""Falsification suite for PO03-WA-006.

The hypothesis is falsified if recovery after a process loss causes any external
effect key to execute more than once.  Every assertion is made against
``ExternalSystem.executions``, the count taken at the effect itself, so a
component that merely updates a status field cannot pass.

The crash matrix covers all five protocol points, and each recovery is run in a
*fresh workflow object* over the same durable directory, so nothing carried in
the crashed object's memory can contribute.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("effect_journal", Path(__file__).with_name("effect_journal.py"))
assert SPEC is not None and SPEC.loader is not None
EJ = importlib.util.module_from_spec(SPEC)
sys.modules["effect_journal"] = EJ
SPEC.loader.exec_module(EJ)


class TempCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.directory = Path(self._directory.name)


class HappyPathTests(TempCase):
    def test_uninterrupted_run_applies_the_effect_once(self):
        external = EJ.ExternalSystem()
        workflow = EJ.CommitWorkflow(self.directory, external)
        workflow.run("T1", {"v": 1})
        self.assertEqual(1, external.executions["effect:T1"])
        self.assertEqual("APPLIED", workflow.journal.phase_of("effect:T1"))

    def test_recovery_after_a_complete_run_does_nothing(self):
        external = EJ.ExternalSystem()
        EJ.CommitWorkflow(self.directory, external).run("T1", {"v": 1})
        for _ in range(5):
            report = EJ.CommitWorkflow(self.directory, external).recover("T1")
            self.assertEqual("ALREADY_COMPLETE_NO_ACTION", report["action"])
        self.assertEqual(1, external.executions["effect:T1"], "repeated recovery must not re-execute")
        self.assertEqual(0, external.probes, "a confirmed effect needs no probe")

    def test_rerunning_run_after_completion_is_not_a_second_commit(self):
        external = EJ.ExternalSystem()
        workflow = EJ.CommitWorkflow(self.directory, external)
        first = workflow.run("T1", {"v": 1})
        committed_at = workflow.committed()["committed_at"]
        self.assertEqual("RESULT_COMMITTED", first["state"])
        self.assertEqual(committed_at, workflow.committed()["committed_at"])


class CrashMatrixTests(TempCase):
    def test_no_crash_point_causes_a_duplicate_effect(self):
        report = EJ.reproduce_crash_matrix(self.directory)
        self.assertEqual(1, report["max_executions_for_any_key"], report)
        for outcome in report["outcomes"]:
            self.assertLessEqual(
                outcome["executions_after_recovery"],
                1,
                f"{outcome['crash_point']} produced a duplicate effect",
            )

    def test_each_crash_point_recovers_to_the_expected_action(self):
        report = EJ.reproduce_crash_matrix(self.directory)
        actions = {item["crash_point"]: item["recovery_action"] for item in report["outcomes"]}
        self.assertEqual("RESTART_FROM_SCRATCH", actions["before_commit"])
        self.assertEqual("EFFECT_APPLIED_FIRST_TIME", actions["after_commit_before_intent"])
        self.assertEqual("PROBE_SHOWED_NOT_APPLIED_SO_APPLIED", actions["after_intent_before_effect"])
        self.assertEqual("CONFIRMED_BY_PROBE_JOURNAL_REPAIRED", actions["after_effect_before_applied"])
        self.assertEqual("ALREADY_COMPLETE_NO_ACTION", actions["after_applied"])

    def test_the_dangerous_window_is_recovered_without_reapplying(self):
        """Crash between the effect and its APPLIED record -- the real hazard."""
        external = EJ.ExternalSystem()
        workflow = EJ.CommitWorkflow(self.directory, external)
        with self.assertRaises(EJ.ProcessLost):
            workflow.run("T1", {"v": 1}, crash_at="after_effect_before_applied")

        self.assertEqual(1, external.executions["effect:T1"], "the effect really did happen")
        self.assertEqual("INTENT", workflow.journal.phase_of("effect:T1"), "but was never recorded")

        report = EJ.CommitWorkflow(self.directory, external).recover("T1")
        self.assertEqual("CONFIRMED_BY_PROBE_JOURNAL_REPAIRED", report["action"])
        self.assertFalse(report["effect_reapplied"])
        self.assertEqual(1, external.executions["effect:T1"], "recovery must not repeat it")
        self.assertEqual(1, external.probes)
        self.assertEqual("APPLIED", EJ.CommitWorkflow(self.directory, external).journal.phase_of("effect:T1"))

    def test_crash_before_the_effect_still_applies_it_exactly_once(self):
        external = EJ.ExternalSystem()
        workflow = EJ.CommitWorkflow(self.directory, external)
        with self.assertRaises(EJ.ProcessLost):
            workflow.run("T1", {"v": 1}, crash_at="after_intent_before_effect")
        self.assertEqual(0, external.total_executions(), "the effect had not happened yet")
        report = EJ.CommitWorkflow(self.directory, external).recover("T1")
        self.assertEqual("PROBE_SHOWED_NOT_APPLIED_SO_APPLIED", report["action"])
        self.assertEqual(1, external.executions["effect:T1"], "the work must not be lost either")

    def test_crash_before_commit_leaves_no_effect_and_no_commit(self):
        external = EJ.ExternalSystem()
        workflow = EJ.CommitWorkflow(self.directory, external)
        with self.assertRaises(EJ.ProcessLost):
            workflow.run("T1", {"v": 1}, crash_at="before_commit")
        self.assertIsNone(workflow.committed())
        self.assertEqual(0, external.total_executions())
        report = EJ.CommitWorkflow(self.directory, external).recover("T1")
        self.assertEqual("RESTART_FROM_SCRATCH", report["action"])
        self.assertEqual("RETRY_SCHEDULED", report["obzio_state"])
        self.assertEqual(0, external.total_executions())

    def test_repeated_recovery_at_every_crash_point_is_idempotent(self):
        for point in EJ.CommitWorkflow.CRASH_POINTS:
            external = EJ.ExternalSystem()
            slot = self.directory / f"repeat-{point}"
            workflow = EJ.CommitWorkflow(slot, external)
            try:
                workflow.run("T1", {"v": 1}, crash_at=point)
            except EJ.ProcessLost:
                pass
            for _ in range(4):
                EJ.CommitWorkflow(slot, external).recover("T1")
            self.assertLessEqual(
                external.total_executions(), 1, f"repeated recovery at {point} duplicated the effect"
            )


class UnprobeableSystemTests(TempCase):
    """Without an observable key, recovery reports rather than guesses."""

    def test_unknown_outcome_is_not_supported_rather_than_assumed(self):
        external = EJ.ExternalSystem(probeable=False)
        workflow = EJ.CommitWorkflow(self.directory, external)
        with self.assertRaises(EJ.ProcessLost):
            workflow.run("T1", {"v": 1}, crash_at="after_effect_before_applied")
        self.assertEqual(1, external.total_executions())

        report = EJ.CommitWorkflow(self.directory, external).recover("T1")
        self.assertEqual("RECONCILIATION_NOT_SUPPORTED", report["action"])
        self.assertEqual("RECOVERY_REQUIRED", report["obzio_state"])
        self.assertFalse(report["effect_reapplied"])
        self.assertEqual(1, external.total_executions(), "refusing to guess must not re-execute")

    def test_blind_matrix_never_duplicates_an_effect(self):
        report = EJ.reproduce_crash_matrix(self.directory, probeable=False)
        self.assertEqual(1, report["max_executions_for_any_key"], report)
        actions = {item["crash_point"]: item["recovery_action"] for item in report["outcomes"]}
        self.assertEqual("RECONCILIATION_NOT_SUPPORTED", actions["after_intent_before_effect"])
        self.assertEqual("RECONCILIATION_NOT_SUPPORTED", actions["after_effect_before_applied"])


class JournalTests(TempCase):
    def test_intent_is_journalled_before_the_effect_runs(self):
        external = EJ.ExternalSystem()
        workflow = EJ.CommitWorkflow(self.directory, external)
        with self.assertRaises(EJ.ProcessLost):
            workflow.run("T1", {"v": 1}, crash_at="after_intent_before_effect")
        phases = [entry["phase"] for entry in workflow.journal.entries()]
        self.assertEqual(["INTENT"], phases, "intent must be durable before the effect is attempted")

    def test_journal_is_append_only_and_survives_a_new_object(self):
        external = EJ.ExternalSystem()
        EJ.CommitWorkflow(self.directory, external).run("T1", {"v": 1})
        entries = EJ.CommitWorkflow(self.directory, external).journal.entries()
        self.assertEqual(["INTENT", "APPLIED"], [entry["phase"] for entry in entries])

    def test_distinct_tasks_have_distinct_effect_keys(self):
        external = EJ.ExternalSystem()
        for task in ("T1", "T2", "T3"):
            EJ.CommitWorkflow(self.directory / task, external).run(task, {"v": task})
        self.assertEqual({"effect:T1", "effect:T2", "effect:T3"}, set(external.executions))
        self.assertEqual([1, 1, 1], sorted(external.executions.values()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
