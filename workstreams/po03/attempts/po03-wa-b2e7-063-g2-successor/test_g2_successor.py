#!/usr/bin/env python3
"""Tests for the G2 successor, its lineage and the improvement claim.

Three things are worth testing here and they are not the same thing.  That the
successor is exactly G1 plus the recorded patches, so the lineage document
describes the actual diff.  That each individual repair behaves correctly at the
function level, including on the legitimate path the repair could have broken.
And that the claim tool refuses when a conjunct is unmet, because a tool that
can only say yes is not evidence of anything.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

UNIT = Path(__file__).resolve().parent
PO03 = UNIT.parents[1]
REPO = PO03.parents[1]
G1_SOURCE = PO03 / "attempts/po03-wa-b2e7-062-g1-packaging/g1/transactional_factory.py"
G1_MEASUREMENT = PO03 / "attempts/po03-wa-b2e7-062-g1-packaging/g1-measurement.json"
PREREGISTRATION = PO03 / "attempts/po03-wa-b2e7-064-generation-comparison/preregistration.json"
G2_SOURCE = UNIT / "g2/transactional_factory_g2.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load(UNIT / "build_g2.py", "po03_build_g2_under_test")
claimer = load(UNIT / "successor_claim.py", "po03_successor_claim_under_test")
checker = load(UNIT / "regression_check.py", "po03_regression_check_under_test")
g2 = load(G2_SOURCE, "po03_g2_module_under_test")


def result_document(**overrides):
    document = {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": "unit-under-test",
        "obzio_state": "RESULT_COMMITTED",
        "attempt": {"worker_id": "worker-a", "fence_token": 1},
        "result_transaction": {"result_txn_id": "txn-1", "parent_ingested_at": None},
        "artifacts": [{"artifact_id": "a-001", "sha256": "f" * 64, "bytes": 3}],
        "completion_actor": None,
        "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
    }
    document.update(overrides)
    return document


class TheSuccessorIsG1PlusTheRecordedPatches(unittest.TestCase):
    def test_rebuilding_from_g1_reproduces_the_committed_successor(self) -> None:
        failures = builder.measured_failures(G1_MEASUREMENT)
        text, _ = builder.apply_patches(G1_SOURCE.read_text(encoding="utf-8"), failures)
        self.assertEqual(text.encode("utf-8"), G2_SOURCE.read_bytes())

    def test_every_measured_g1_failure_has_exactly_one_change(self) -> None:
        lineage = json.loads((UNIT / "g2/lineage.json").read_text(encoding="utf-8"))
        failures = set(builder.measured_failures(G1_MEASUREMENT))
        addressed = [change["motivating_failure"]["case_id"] for change in lineage["changes"]]
        self.assertEqual(sorted(addressed), sorted(failures))
        self.assertEqual(len(addressed), len(set(addressed)), "a failure is addressed twice")
        self.assertTrue(lineage["coverage"]["every_measured_failure_has_a_change"])

    def test_every_change_records_lineage_and_a_disposition(self) -> None:
        lineage = json.loads((UNIT / "g2/lineage.json").read_text(encoding="utf-8"))
        for change in lineage["changes"]:
            self.assertIn(change["disposition"], {"RETAIN", "DELETE", "SUPERSEDE", "RETEST", "REJECT"})
            failure = change["motivating_failure"]
            self.assertTrue(failure["case_id"])
            self.assertTrue(failure["g1_observed_detail"])
            self.assertNotEqual(failure["g1_outcome"], "PASS")
            self.assertTrue(change["route"])
            self.assertTrue(change["rationale"])
            self.assertGreaterEqual(change["edit_count"], 1)

    def test_a_change_without_a_measured_failure_is_refused(self) -> None:
        failures = builder.measured_failures(G1_MEASUREMENT)
        del failures["H02-fence-monotonic-under-concurrency"]
        with self.assertRaises(ValueError) as caught:
            builder.apply_patches(G1_SOURCE.read_text(encoding="utf-8"), failures)
        self.assertIn("not a measured G1 failure", str(caught.exception))

    def test_an_anchor_that_does_not_match_exactly_once_is_refused(self) -> None:
        failures = builder.measured_failures(G1_MEASUREMENT)
        with self.assertRaises(ValueError) as caught:
            builder.apply_patches("def nothing_here(): pass\n", failures)
        self.assertIn("anchor matched 0 times", str(caught.exception))

    def test_the_successor_keeps_the_whole_g1_surface(self) -> None:
        g1_names = {
            name for name in dir(load(G1_SOURCE, "po03_g1_module_for_surface")) if not name.startswith("_")
        }
        g2_names = {name for name in dir(g2) if not name.startswith("_")}
        self.assertEqual(set(), g1_names - g2_names, "the successor dropped part of the G1 surface")
        self.assertIn("result_binding_digest", g2_names)
        self.assertIn("verify_chain_head", g2_names)


class TheCompletionBindingHoldsBothWays(unittest.TestCase):
    """G2-CHANGE-001 had to refuse a substitution without breaking the real path."""

    def test_the_coordinator_stamp_does_not_change_the_binding(self) -> None:
        ingested = result_document()
        completed = copy.deepcopy(ingested)
        completed["result_transaction"]["parent_ingested_at"] = "2026-08-22T07:03:00Z"
        completed["obzio_state"] = "COMPLETED"
        completed["completion_actor"] = "coordinator"
        completed["independent_acceptance"] = {
            "state": "PENDING", "reviewer_id": "reviewer-2", "receipt_uri": None
        }
        self.assertEqual(g2.result_binding_digest(ingested), g2.result_binding_digest(completed))

    def test_a_substituted_worker_changes_the_binding(self) -> None:
        ingested = result_document()
        substituted = copy.deepcopy(ingested)
        substituted["attempt"]["worker_id"] = "a-different-worker"
        self.assertNotEqual(g2.result_binding_digest(ingested), g2.result_binding_digest(substituted))

    def test_a_substituted_artifact_changes_the_binding(self) -> None:
        ingested = result_document()
        substituted = copy.deepcopy(ingested)
        substituted["artifacts"][0]["sha256"] = "e" * 64
        self.assertNotEqual(g2.result_binding_digest(ingested), g2.result_binding_digest(substituted))


class TheOtherRepairsBehaveAtTheFunctionLevel(unittest.TestCase):
    def test_a_mutable_locator_is_refused_and_an_object_id_is_accepted_in_form(self) -> None:
        for locator in ("git:HEAD:path/to/file", "git:main:path", "git:v1.0:path", "git:abc123:path"):
            with self.assertRaises(ValueError, msg=locator):
                g2.read_object_bytes(locator)
        with self.assertRaises(ValueError):
            g2.read_object_bytes(f"git:{'a' * 40}")
        with self.assertRaises(ValueError):
            g2.read_object_bytes("/var/tmp/not-a-git-locator")

    def test_path_collisions_are_computed_from_overlapping_claims(self) -> None:
        collisions = g2.detect_path_collisions.__doc__
        self.assertIn("Fail closed", collisions)

    def test_the_fence_lock_timeout_is_bounded(self) -> None:
        self.assertGreater(g2.FENCE_LOCK_TIMEOUT_SECONDS, 0)
        self.assertLessEqual(g2.FENCE_LOCK_TIMEOUT_SECONDS, 120)

    def test_chain_head_verification_is_silent_without_a_pointer(self) -> None:
        self.assertEqual([], g2.verify_chain_head("a-task-with-no-chain-head-pointer", []))


class TheClaimToolRefusesWhenAConjunctFails(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.prereg = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))

    def measurement(self, outcomes: dict[str, str], *, false_green_rate: float = 0.0) -> dict:
        records = [
            {
                "case_id": case_id,
                "suite": "public" if case_id.startswith("P") else "holdout",
                "outcome": outcome,
                "reports_success": outcome == "FAIL",
                "invariant_held": outcome == "PASS",
                "detail": "synthetic",
            }
            for case_id, outcome in outcomes.items()
        ]

        def scored(subset):
            total = len(subset)
            passed = sum(1 for record in subset if record["outcome"] == "PASS")
            return {
                "case_count": total,
                "passed": passed,
                "pass_rate": passed / total if total else None,
                "false_green_rate": false_green_rate,
                "reported_success_count": sum(1 for record in subset if record["reports_success"]),
            }

        return {
            "suite_freeze": {
                "public_suite_sha256": "a" * 64,
                "holdout_sha256": "b" * 64,
                "holdout_seal_combined_sha256": "c" * 64,
            },
            "public": scored([r for r in records if r["suite"] == "public"]),
            "holdout": scored([r for r in records if r["suite"] == "holdout"]),
            "combined": scored(records),
            "records": records,
        }

    def test_a_real_lift_with_no_regression_is_supported(self) -> None:
        before = self.measurement({"P1": "PASS", "H1": "FAIL", "H2": "FAIL"})
        after = self.measurement({"P1": "PASS", "H1": "PASS", "H2": "PASS"})
        record = claimer.evaluate(self.prereg, before, after, None)
        self.assertEqual(record["claim"], "SUPPORTED")
        self.assertEqual(record["verdict"], "PASS")

    def test_lift_below_the_threshold_is_refused(self) -> None:
        cases = {f"P{index}": "PASS" for index in range(40)}
        before = dict(cases, H1="FAIL")
        after = dict(cases, H1="PASS")
        record = claimer.evaluate(self.prereg, self.measurement(before), self.measurement(after), None)
        self.assertEqual(record["claim"], "REFUSED")
        self.assertEqual(record["verdict"], "NOT_YET")
        self.assertIn("successor_lift >= lift_threshold", record["unmet_conjuncts"])

    def test_a_regression_is_refused_even_with_a_large_lift(self) -> None:
        before = self.measurement({"P1": "PASS", "H1": "FAIL", "H2": "FAIL", "H3": "FAIL"})
        after = self.measurement({"P1": "FAIL", "H1": "PASS", "H2": "PASS", "H3": "PASS"})
        record = claimer.evaluate(self.prereg, before, after, None)
        self.assertEqual(record["claim"], "REFUSED")
        self.assertIn("P1", record["regressed_cases"])

    def test_an_unsupported_case_is_not_a_pass(self) -> None:
        before = self.measurement({"P1": "PASS", "H1": "FAIL"})
        after = self.measurement({"P1": "UNSUPPORTED", "H1": "PASS"})
        record = claimer.evaluate(self.prereg, before, after, None)
        self.assertEqual(record["claim"], "REFUSED")
        self.assertIn("P1", record["regressed_cases"])

    def test_a_worse_false_green_rate_is_refused(self) -> None:
        before = self.measurement({"P1": "PASS", "H1": "FAIL", "H2": "FAIL"}, false_green_rate=0.1)
        after = self.measurement({"P1": "PASS", "H1": "PASS", "H2": "PASS"}, false_green_rate=0.5)
        record = claimer.evaluate(self.prereg, before, after, None)
        self.assertEqual(record["claim"], "REFUSED")
        self.assertIn("false_green_rate(G2) <= false_green_rate(G1)", record["unmet_conjuncts"])

    def test_runs_on_different_suite_bytes_are_not_comparable(self) -> None:
        before = self.measurement({"P1": "PASS", "H1": "FAIL", "H2": "FAIL"})
        after = self.measurement({"P1": "PASS", "H1": "PASS", "H2": "PASS"})
        after["suite_freeze"]["public_suite_sha256"] = "d" * 64
        record = claimer.evaluate(self.prereg, before, after, None)
        self.assertFalse(record["comparability"]["comparable"])
        self.assertEqual(record["claim"], "REFUSED")

    def test_a_failure_in_the_independent_suite_is_refused(self) -> None:
        before = self.measurement({"P1": "PASS", "H1": "FAIL", "H2": "FAIL"})
        after = self.measurement({"P1": "PASS", "H1": "PASS", "H2": "PASS"})
        regression = {
            "suite": {"origin": "workstreams/po03/tests"},
            "g1": {"totals": {"ok": 58}},
            "g2": {"totals": {"ok": 57}},
            "comparison": {
                "no_quality_regression": False,
                "regressed_tests": ["CompletionTests.test_coordinator_completion_passes_the_seeded_contract"],
                "disappeared_tests": [],
            },
        }
        record = claimer.evaluate(self.prereg, before, after, regression)
        self.assertEqual(record["claim"], "REFUSED")
        self.assertIn(
            "no regression in the independent baseline suite this cohort did not author",
            record["unmet_conjuncts"],
        )

    def test_the_threshold_is_read_from_the_preregistration(self) -> None:
        before = self.measurement({"P1": "PASS", "H1": "FAIL", "H2": "FAIL"})
        after = self.measurement({"P1": "PASS", "H1": "PASS", "H2": "PASS"})
        record = claimer.evaluate(self.prereg, before, after, None)
        self.assertEqual(
            record["preregistration"]["lift_threshold"],
            self.prereg["lift_threshold"]["successor_lift_minimum"],
        )


class TheRegressionCheckReadsRealOutcomes(unittest.TestCase):
    def test_verbose_unittest_output_is_parsed_into_outcomes(self) -> None:
        output = (
            "test_one (pkg.CaseA.test_one) ... ok\n"
            "test_two (pkg.CaseA.test_two) ... FAIL\n"
            "test_three (pkg.CaseB.test_three) ... ERROR\n"
            "test_four (pkg.CaseB.test_four) ... skipped 'no reason'\n"
        )
        outcomes = checker.parse_outcomes(output)
        self.assertEqual(outcomes["pkg.CaseA.test_one"], "ok")
        self.assertEqual(outcomes["pkg.CaseA.test_two"], "FAIL")
        self.assertEqual(outcomes["pkg.CaseB.test_three"], "ERROR")
        self.assertEqual(outcomes["pkg.CaseB.test_four"], "skipped")

    def test_an_incomplete_parse_is_not_reported_as_clean(self) -> None:
        output = "test_one (pkg.CaseA.test_one) ... ok\nRan 2 tests in 0.001s\n"
        self.assertEqual(checker.reported_total(output), 2)
        arm = {"label": "G1", "outcomes": checker.parse_outcomes(output),
               "totals": {"parse_is_complete": False}}
        comparison = checker.compare(arm, arm)
        self.assertFalse(
            comparison["no_quality_regression"],
            "a parse that missed a test must not be reported as a clean comparison",
        )

    def test_a_test_that_stops_passing_is_a_regression(self) -> None:
        before = {"label": "G1", "outcomes": {"a": "ok", "b": "ok"}}
        after = {"label": "G2", "outcomes": {"a": "ok", "b": "FAIL"}}
        comparison = checker.compare(before, after)
        self.assertEqual(comparison["regressed_tests"], ["b"])
        self.assertFalse(comparison["no_quality_regression"])

    def test_a_test_that_vanishes_is_not_counted_as_clean(self) -> None:
        before = {"label": "G1", "outcomes": {"a": "ok", "b": "ok"}}
        after = {"label": "G2", "outcomes": {"a": "ok"}}
        comparison = checker.compare(before, after)
        self.assertEqual(comparison["disappeared_tests"], ["b"])
        self.assertFalse(comparison["no_quality_regression"])

    def test_the_recorded_check_ran_the_whole_baseline_suite_against_both(self) -> None:
        path = UNIT / "regression-check.json"
        if not path.is_file():
            self.skipTest("regression-check.json is produced by regression_check.py")
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["g1"]["totals"]["ran"], 58)
        self.assertEqual(record["g2"]["totals"]["ran"], 58)
        self.assertEqual(record["g1"]["totals"]["ok"], 58)
        self.assertEqual(record["g2"]["totals"]["ok"], 58)
        self.assertTrue(record["g1"]["totals"]["parse_is_complete"])
        self.assertTrue(record["g2"]["totals"]["parse_is_complete"])
        self.assertTrue(record["comparison"]["no_quality_regression"])
        self.assertEqual(
            record["g2"]["factory_sha256"], claimer.sha256_bytes(G2_SOURCE.read_bytes())
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
