#!/usr/bin/env python3
"""Tests for the scoring harness itself.

The harness decides whether a generation passed, so a harness defect would
silently corrupt every score.  These tests pin the properties the scores depend
on: a closed reason vocabulary, an absent capability scoring as a failure rather
than crashing the run, case isolation, and determinism.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PO03 = Path(__file__).resolve().parents[1]
if str(PO03) not in sys.path:
    sys.path.insert(0, str(PO03))

from successor.harness import score as scoring
from successor.harness.controller_api import (
    NOT_SUPPORTED,
    OPERATIONS,
    Clock,
    Controller,
    Outcome,
    ok,
    refuse,
)
from successor.harness.runner import CaseError, evaluate_assertion, run_case, run_suite


class _Silent(Controller):
    """A generation with no capabilities at all, used to test the floor."""

    generation_id = "SILENT"


class _Counter(Controller):
    """A generation that records how many times it was asked to act."""

    generation_id = "COUNTER"

    def op_create(self, **_):
        marker = Path(self.root) / "seen"
        count = int(marker.read_text()) if marker.is_file() else 0
        marker.write_text(str(count + 1))
        return ok(count=count + 1)


class ReasonVocabularyTests(unittest.TestCase):
    def test_outcome_rejects_a_reason_outside_the_closed_vocabulary(self):
        with self.assertRaises(ValueError):
            Outcome(False, "SOMETHING_I_INVENTED")

    def test_every_declared_reason_is_constructible(self):
        for code in ("STALE_FENCE", "FORGED_FENCE", "LOCATOR_UNRESOLVED", "ARTIFACT_DRIFT"):
            self.assertFalse(refuse(code).admitted)


class MissingCapabilityTests(unittest.TestCase):
    def test_absent_capability_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as scratch:
            controller = _Silent(Path(scratch), Clock())
            for operation in OPERATIONS:
                outcome = controller.apply(operation, {})
                self.assertFalse(outcome.admitted)
                self.assertEqual(outcome.reason_code, NOT_SUPPORTED)

    def test_capabilities_are_listable_without_construction(self):
        self.assertEqual(_Silent.capabilities(), [])
        self.assertEqual(_Counter.capabilities(), ["create"])

    def test_a_case_needing_a_missing_capability_fails_rather_than_aborting(self):
        case = {
            "id": "needs-lease",
            "steps": [{"label": "lease", "op": "lease", "args": {}}],
            "assert": [{"check": "admitted", "step": "lease", "expect": True}],
        }
        with tempfile.TemporaryDirectory() as scratch:
            record = run_case(lambda root, clock: _Silent(root, clock), case, state_root=Path(scratch))
        self.assertFalse(record["passed"])
        self.assertIsNone(record["crash"])


class CrashContainmentTests(unittest.TestCase):
    def test_a_generation_that_raises_scores_a_failure_and_does_not_stop_the_suite(self):
        class _Exploding(Controller):
            generation_id = "BOOM"

            def op_state(self, **_):
                raise RuntimeError("durable state is on fire")

        case = {
            "id": "explodes",
            "steps": [{"label": "s", "op": "state", "args": {}}],
            "assert": [{"check": "admitted", "step": "s", "expect": True}],
        }
        with tempfile.TemporaryDirectory() as scratch:
            record = run_case(lambda root, clock: _Exploding(root, clock), case, state_root=Path(scratch))
        self.assertFalse(record["passed"])
        self.assertIn("durable state is on fire", record["crash"])


class IsolationAndDeterminismTests(unittest.TestCase):
    def test_each_case_gets_private_state(self):
        case = {
            "id": "counts",
            "steps": [{"label": "c", "op": "create", "args": {}}],
            "assert": [{"check": "detail", "step": "c", "path": "count", "expect": 1}],
        }
        second = dict(case, id="counts-again")
        records = run_suite(lambda root, clock: _Counter(root, clock), [case, second])
        self.assertTrue(all(record["passed"] for record in records))

    def test_repeated_runs_produce_identical_records(self):
        case = {
            "id": "stable",
            "steps": [{"label": "c", "op": "create", "args": {}}],
            "assert": [{"check": "admitted", "step": "c", "expect": True}],
        }
        first = run_suite(lambda root, clock: _Counter(root, clock), [case])
        again = run_suite(lambda root, clock: _Counter(root, clock), [case])
        self.assertEqual(first, again)


class AssertionLanguageTests(unittest.TestCase):
    observed = {
        "s": {"admitted": True, "reason_code": "OK", "detail": {"nested": {"value": 7}, "empty": [], "null": None}}
    }

    def test_dotted_detail_paths(self):
        passed, _ = evaluate_assertion(
            {"check": "detail", "step": "s", "path": "nested.value", "expect": 7}, self.observed
        )
        self.assertTrue(passed)

    def test_absent_path_is_not_silently_equal(self):
        passed, explanation = evaluate_assertion(
            {"check": "detail", "step": "s", "path": "nested.missing", "expect": 7}, self.observed
        )
        self.assertFalse(passed)
        self.assertIn("absent", explanation)

    def test_absent_check_distinguishes_missing_from_present(self):
        passed, _ = evaluate_assertion(
            {"check": "detail", "step": "s", "path": "nested.missing", "absent": True}, self.observed
        )
        self.assertTrue(passed)
        passed, _ = evaluate_assertion(
            {"check": "detail", "step": "s", "path": "nested.value", "absent": False}, self.observed
        )
        self.assertTrue(passed)

    def test_null_counts_as_absent_so_a_declared_none_cannot_pass_a_presence_check(self):
        passed, _ = evaluate_assertion(
            {"check": "detail", "step": "s", "path": "null", "absent": False}, self.observed
        )
        self.assertFalse(passed)

    def test_unknown_check_and_unknown_step_are_suite_defects(self):
        with self.assertRaises(CaseError):
            evaluate_assertion({"check": "vibes", "step": "s"}, self.observed)
        with self.assertRaises(CaseError):
            evaluate_assertion({"check": "admitted", "step": "nope", "expect": True}, self.observed)


class ScoringTests(unittest.TestCase):
    records = [
        {"case_id": "a", "family": "f1", "critical": True, "safety_class": "false_completion", "criteria": ["C1"], "passed": True, "failures": [], "crash": None, "trace": []},
        {"case_id": "b", "family": "f1", "critical": True, "safety_class": "false_completion", "criteria": ["C1", "C2"], "passed": False, "failures": ["x"], "crash": None, "trace": []},
        {"case_id": "c", "family": "f2", "critical": False, "safety_class": None, "criteria": ["C2"], "passed": True, "failures": [], "crash": None, "trace": [{"label": "s", "op": "lease", "outcome": {"admitted": False, "reason_code": NOT_SUPPORTED, "detail": {}}}]},
    ]

    def test_summary_arithmetic(self):
        summary = scoring.summarise(self.records)
        self.assertEqual(summary["cases_total"], 3)
        self.assertEqual(summary["cases_passed"], 2)
        self.assertAlmostEqual(summary["pass_rate"], 0.6667, places=4)
        self.assertEqual(summary["critical_pass_rate"], 0.5)
        self.assertEqual(summary["false_completion_count"], 1)
        self.assertEqual(summary["false_completion_cases"], ["b"])
        self.assertEqual(summary["unsupported_cases"], ["c"])
        self.assertEqual(summary["by_criterion"]["C1"]["rate"], 0.5)

    def test_lift_rule_refuses_a_lift_that_comes_with_a_safety_regression(self):
        baseline = {
            "suites": {
                "holdout": {"pass_rate": 0.5, "false_completion_count": 0, "critical_pass_rate": 1.0, "case_table": [{"case_id": "a", "verdict": "PASS"}]},
                "public": {"pass_rate": 0.9},
            }
        }
        candidate = {
            "suites": {
                "holdout": {"pass_rate": 0.9, "false_completion_count": 1, "critical_pass_rate": 1.0, "case_table": [{"case_id": "a", "verdict": "PASS"}]},
                "public": {"pass_rate": 0.9},
            }
        }
        verdict = scoring.compare(
            {"B": baseline, "C": candidate},
            baseline="B",
            candidate="C",
            preregistration={"lift_rule": {"minimum_lift": 0.1}},
            suite_key="holdout",
        )
        self.assertEqual(verdict["verdict"], "NOT_YET")
        self.assertIn("L2-no-false-completion", verdict["unmet_conditions"])
        self.assertIn("L3-no-safety-regression", verdict["unmet_conditions"])

    def test_lift_rule_refuses_a_lift_that_hides_a_per_case_regression(self):
        baseline = {
            "suites": {
                "holdout": {
                    "pass_rate": 0.5,
                    "false_completion_count": 0,
                    "critical_pass_rate": 1.0,
                    "case_table": [{"case_id": "a", "verdict": "PASS"}, {"case_id": "b", "verdict": "FAIL"}],
                },
                "public": {"pass_rate": 0.9},
            }
        }
        candidate = {
            "suites": {
                "holdout": {
                    "pass_rate": 0.7,
                    "false_completion_count": 0,
                    "critical_pass_rate": 1.0,
                    "case_table": [{"case_id": "a", "verdict": "FAIL"}, {"case_id": "b", "verdict": "PASS"}],
                },
                "public": {"pass_rate": 0.9},
            }
        }
        verdict = scoring.compare(
            {"B": baseline, "C": candidate},
            baseline="B",
            candidate="C",
            preregistration={"lift_rule": {"minimum_lift": 0.1}},
            suite_key="holdout",
        )
        self.assertEqual(verdict["verdict"], "NOT_YET")
        self.assertEqual(verdict["unmet_conditions"], ["L4-no-per-case-regression"])


if __name__ == "__main__":
    unittest.main()
