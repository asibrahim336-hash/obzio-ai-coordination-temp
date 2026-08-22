#!/usr/bin/env python3
"""Tests for the generation comparison, the decision rule and the wave receipt.

The comparison's job is to reach a verdict that the evidence forces.  So the
tests that matter are the ones that make the evidence say NOT_YET: a sub-threshold
lift, a regression, a saturated suite, generations measured on different suite
bytes.  A comparator that cannot return NOT_YET is not measuring anything, and a
verdict from one that can is worth something.

The receipt is checked against the real contract validator rather than against a
transcription of the schema.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

UNIT = Path(__file__).resolve().parent
PO03 = UNIT.parents[1]
REPO = PO03.parents[1]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


comparator = load(UNIT / "compare_generations.py", "po03_compare_generations_under_test")
validator = load(PO03 / "tools/validate_contracts.py", "po03_validate_contracts_for_receipt")

PREREGISTRATION = json.loads((UNIT / "preregistration.json").read_text(encoding="utf-8"))
CLEAN_REGRESSION = {
    "suite": {"origin": "workstreams/po03/tests", "authored_by": "not this cohort"},
    "g1": {"totals": {"ok": 58, "ran": 58}},
    "g2": {"totals": {"ok": 58, "ran": 58}},
    "comparison": {"no_quality_regression": True, "regressed_tests": [], "disappeared_tests": [],
                   "regression_count": 0},
}
CLEAN_IDENTITY = {
    "all_generations_measured_on_one_suite": True,
    "identical_case_sets": True,
    "holdout_seal_matches_file": True,
}


def synthetic(outcomes: dict[str, str], *, false_green_rate: float = 0.0) -> dict:
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
            "failed": sum(1 for record in subset if record["outcome"] == "FAIL"),
            "unsupported": sum(1 for record in subset if record["outcome"] == "UNSUPPORTED"),
            "pass_rate": passed / total if total else None,
            "false_green_rate": false_green_rate,
            "false_green_count": 0,
            "reported_success_count": sum(1 for record in subset if record["reports_success"]),
        }

    return {
        "suite_freeze": {
            "public_suite_sha256": "a" * 64,
            "holdout_sha256": "b" * 64,
            "holdout_seal_combined_sha256": "c" * 64,
            "holdout_seal_matches_file": True,
        },
        "generation": {"source_sha256": "d" * 64, "source_bytes": 1},
        "public": scored([r for r in records if r["suite"] == "public"]),
        "holdout": scored([r for r in records if r["suite"] == "holdout"]),
        "combined": scored(records),
        "records": records,
    }


class TheDecisionRuleCanReturnNotYet(unittest.TestCase):
    def decide(self, before, after, *, regression=None, identity=None):
        measured = {"G0": before, "G1": before, "G2": after}
        return comparator.decide(
            PREREGISTRATION, measured, regression or CLEAN_REGRESSION, identity or CLEAN_IDENTITY
        )

    def test_a_genuine_lift_with_no_regression_is_pass(self) -> None:
        before = synthetic({"P1": "PASS", "H1": "FAIL", "H2": "FAIL"})
        after = synthetic({"P1": "PASS", "H1": "PASS", "H2": "PASS"})
        decision = self.decide(before, after)
        self.assertEqual(decision["compounding_verdict"], "PASS")
        self.assertEqual(decision["unmet_conjuncts"], [])

    def test_a_lift_below_the_preregistered_threshold_is_not_yet(self) -> None:
        base = {f"P{index}": "PASS" for index in range(40)}
        before = synthetic(dict(base, H1="FAIL"))
        after = synthetic(dict(base, H1="PASS"))
        decision = self.decide(before, after)
        self.assertEqual(decision["compounding_verdict"], "NOT_YET")
        self.assertIn("successor_lift >= 0.05 in combined_pass_rate", decision["unmet_conjuncts"])

    def test_no_change_at_all_is_not_yet(self) -> None:
        same = synthetic({"P1": "PASS", "H1": "FAIL"})
        decision = self.decide(same, copy.deepcopy(same))
        self.assertEqual(decision["compounding_verdict"], "NOT_YET")

    def test_a_regression_defeats_any_lift(self) -> None:
        before = synthetic({"P1": "PASS", "H1": "FAIL", "H2": "FAIL", "H3": "FAIL"})
        after = synthetic({"P1": "FAIL", "H1": "PASS", "H2": "PASS", "H3": "PASS"})
        decision = self.decide(before, after)
        self.assertEqual(decision["compounding_verdict"], "NOT_YET")
        self.assertIn("quality_regression_count == 0", decision["unmet_conjuncts"])

    def test_an_unsupported_case_counts_as_not_passed(self) -> None:
        before = synthetic({"P1": "PASS", "H1": "FAIL", "H2": "FAIL", "H3": "FAIL"})
        after = synthetic({"P1": "UNSUPPORTED", "H1": "PASS", "H2": "PASS", "H3": "PASS"})
        decision = self.decide(before, after)
        self.assertEqual(decision["compounding_verdict"], "NOT_YET")

    def test_a_worse_false_green_rate_is_not_yet(self) -> None:
        before = synthetic({"P1": "PASS", "H1": "FAIL", "H2": "FAIL"}, false_green_rate=0.2)
        after = synthetic({"P1": "PASS", "H1": "PASS", "H2": "PASS"}, false_green_rate=0.9)
        decision = self.decide(before, after)
        self.assertEqual(decision["compounding_verdict"], "NOT_YET")

    def test_generations_measured_on_different_suites_is_not_yet(self) -> None:
        before = synthetic({"P1": "PASS", "H1": "FAIL", "H2": "FAIL"})
        after = synthetic({"P1": "PASS", "H1": "PASS", "H2": "PASS"})
        identity = dict(CLEAN_IDENTITY, all_generations_measured_on_one_suite=False)
        decision = self.decide(before, after, identity=identity)
        self.assertEqual(decision["compounding_verdict"], "NOT_YET")
        self.assertIn("all generations measured on one frozen suite", decision["unmet_conjuncts"])

    def test_a_broken_holdout_seal_is_not_yet(self) -> None:
        before = synthetic({"P1": "PASS", "H1": "FAIL", "H2": "FAIL"})
        after = synthetic({"P1": "PASS", "H1": "PASS", "H2": "PASS"})
        identity = dict(CLEAN_IDENTITY, holdout_seal_matches_file=False)
        decision = self.decide(before, after, identity=identity)
        self.assertEqual(decision["compounding_verdict"], "NOT_YET")

    def test_a_failure_in_the_independent_suite_is_not_yet(self) -> None:
        before = synthetic({"P1": "PASS", "H1": "FAIL", "H2": "FAIL"})
        after = synthetic({"P1": "PASS", "H1": "PASS", "H2": "PASS"})
        regression = copy.deepcopy(CLEAN_REGRESSION)
        regression["comparison"] = {
            "no_quality_regression": False,
            "regressed_tests": ["CompletionTests.test_coordinator_completion_passes_the_seeded_contract"],
            "disappeared_tests": [],
            "regression_count": 1,
        }
        decision = self.decide(before, after, regression=regression)
        self.assertEqual(decision["compounding_verdict"], "NOT_YET")
        self.assertIn(
            "no regression in the independently authored baseline suite", decision["unmet_conjuncts"]
        )

    def test_the_threshold_and_rule_come_from_the_preregistration(self) -> None:
        before = synthetic({"P1": "PASS", "H1": "FAIL", "H2": "FAIL"})
        after = synthetic({"P1": "PASS", "H1": "PASS", "H2": "PASS"})
        decision = self.decide(before, after)
        self.assertEqual(decision["lift_threshold"], PREREGISTRATION["lift_threshold"]["successor_lift_minimum"])
        self.assertEqual(decision["decision_rule"], PREREGISTRATION["decision_rule"]["PASS"])


class TheComparisonRefusesUncomparableRuns(unittest.TestCase):
    def test_differing_suite_bytes_are_reported_not_averaged(self) -> None:
        first = synthetic({"P1": "PASS"})
        second = synthetic({"P1": "PASS"})
        second["suite_freeze"]["public_suite_sha256"] = "e" * 64
        identity = comparator.one_suite_for_all({"G1": first, "G2": second})
        self.assertFalse(identity["all_generations_measured_on_one_suite"])
        self.assertEqual(len(identity["public_suite_sha256"]), 2)

    def test_differing_case_sets_are_detected(self) -> None:
        identity = comparator.one_suite_for_all(
            {"G1": synthetic({"P1": "PASS"}), "G2": synthetic({"P1": "PASS", "P2": "PASS"})}
        )
        self.assertFalse(identity["identical_case_sets"])

    def test_a_fresh_run_that_disagrees_with_the_committed_one_is_flagged(self) -> None:
        committed = synthetic({"P1": "PASS", "H1": "FAIL"})
        fresh = synthetic({"P1": "PASS", "H1": "PASS"})
        record = comparator.agreement(fresh, committed)
        self.assertFalse(record["reproduces_the_committed_measurement"])
        self.assertTrue(record["outcome_disagreements"])

    def test_an_identical_rerun_reproduces_the_committed_measurement(self) -> None:
        committed = synthetic({"P1": "PASS", "H1": "FAIL"})
        record = comparator.agreement(copy.deepcopy(committed), committed)
        self.assertTrue(record["reproduces_the_committed_measurement"])
        self.assertEqual(record["outcome_disagreements"], [])


class TheRecordedComparisonIsSound(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = UNIT / "generation-comparison.json"
        if not path.is_file():
            raise unittest.SkipTest("generation-comparison.json is produced by compare_generations.py")
        cls.comparison = json.loads(path.read_text(encoding="utf-8"))

    def test_all_three_generations_were_measured_on_one_frozen_suite(self) -> None:
        identity = self.comparison["suite_identity"]
        self.assertTrue(identity["all_generations_measured_on_one_suite"])
        self.assertTrue(identity["identical_case_sets"])
        self.assertTrue(identity["holdout_seal_matches_file"])
        self.assertEqual(len(identity["public_suite_sha256"]), 1)
        self.assertEqual(len(identity["holdout_sha256"]), 1)

    def test_each_fresh_run_reproduced_the_measurement_its_unit_committed(self) -> None:
        reproducibility = self.comparison["reproducibility"]
        self.assertTrue(reproducibility["all_generations_reproduced_their_committed_measurement"])
        for name, record in reproducibility["fresh_run_agreement"].items():
            self.assertTrue(record["source_identical"], name)
            self.assertTrue(record["suite_bytes_identical"], name)
            self.assertEqual(record["outcome_disagreements"], [], name)

    def test_the_preregistration_predates_the_measurements_in_git_history(self) -> None:
        prereg = "workstreams/po03/attempts/po03-wa-b2e7-064-generation-comparison/preregistration.json"
        measurements = (
            "workstreams/po03/attempts/po03-wa-b2e7-061-g0-reconstruction/g0-measurement.json",
            "workstreams/po03/attempts/po03-wa-b2e7-062-g1-packaging/g1-measurement.json",
            "workstreams/po03/attempts/po03-wa-b2e7-063-g2-successor/g2-measurement.json",
        )

        def first_commit_time(relative: str) -> int:
            output = subprocess.run(
                ("git", "log", "--diff-filter=A", "--format=%ct", "--", relative),
                cwd=REPO, check=True, capture_output=True, text=True,
            ).stdout.split()
            self.assertTrue(output, f"{relative} has no add commit")
            return int(output[-1])

        registered = first_commit_time(prereg)
        for relative in measurements:
            self.assertLessEqual(
                registered,
                first_commit_time(relative),
                f"the preregistration must be committed no later than {relative}",
            )

    def test_the_g2_source_did_not_exist_when_the_suite_was_committed(self) -> None:
        def first_commit(relative: str) -> str:
            return subprocess.run(
                ("git", "log", "--diff-filter=A", "--format=%H", "--", relative),
                cwd=REPO, check=True, capture_output=True, text=True,
            ).stdout.split()[-1]

        suite = first_commit(
            "workstreams/po03/attempts/po03-wa-b2e7-061-g0-reconstruction/generation_suite.py"
        )
        successor = first_commit(
            "workstreams/po03/attempts/po03-wa-b2e7-063-g2-successor/g2/transactional_factory_g2.py"
        )
        ancestor = subprocess.run(
            ("git", "merge-base", "--is-ancestor", suite, successor), cwd=REPO, capture_output=True
        )
        self.assertEqual(ancestor.returncode, 0, "the suite commit must be an ancestor of the successor commit")

    def test_every_measured_g1_failure_has_a_disposition_with_lineage(self) -> None:
        superseded = {
            record["lineage"]["measured_failure"]
            for record in self.comparison["dispositions"]
            if record["decision"] == "SUPERSEDE"
        }
        failing = {
            case_id
            for case_id, outcome in self.comparison["per_case"]["G1"].items()
            if outcome != "PASS"
        }
        self.assertEqual(superseded, failing)

    def test_every_disposition_carries_a_decision_and_evidence(self) -> None:
        for record in self.comparison["dispositions"]:
            self.assertIn(record["decision"], {"RETAIN", "DELETE", "SUPERSEDE", "RETEST", "REJECT"})
            self.assertTrue(record["subject"])
            self.assertTrue(record["evidence_uri"].startswith("git:"))
            self.assertIn("lineage", record)

    def test_unmotivated_candidate_repairs_were_rejected_rather_than_shipped(self) -> None:
        rejected = [r for r in self.comparison["dispositions"] if r["decision"] == "REJECT"]
        self.assertTrue(rejected, "a change without measured lineage must be recorded as REJECT")
        for record in rejected:
            self.assertIn("reason", record["lineage"])

    def test_the_verdict_matches_the_recorded_conjuncts(self) -> None:
        decision = self.comparison["decision"]
        unmet = [entry["conjunct"] for entry in decision["conjuncts"] if not entry["met"]]
        self.assertEqual(unmet, decision["unmet_conjuncts"])
        self.assertEqual(
            decision["compounding_verdict"], "PASS" if not unmet else "NOT_YET"
        )


class TheReceiptValidatesAgainstTheRealContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = UNIT / "compounding-results.json"
        if not cls.path.is_file():
            raise unittest.SkipTest("compounding-results.json is produced by compare_generations.py")
        cls.receipt = json.loads(cls.path.read_text(encoding="utf-8"))

    def test_the_contract_validator_accepts_the_receipt(self) -> None:
        self.assertEqual([], validator.validate_wave(self.receipt))

    def test_the_validation_command_from_the_preregistration_exits_clean(self) -> None:
        completed = subprocess.run(
            ("python3", "-I", "workstreams/po03/tools/validate_contracts.py", "wave",
             self.path.relative_to(REPO).as_posix()),
            cwd=REPO, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("VALID wave", completed.stdout)

    def test_decision_changed_is_empty(self) -> None:
        self.assertEqual(self.receipt["decision_changed"], [])

    def test_every_locator_names_an_immutable_object(self) -> None:
        locators = [self.receipt["baseline"]["metrics_uri"], self.receipt["successor_manifest_uri"]]
        locators.extend(record["evidence_uri"] for record in self.receipt["dispositions"])
        for value in locators:
            self.assertTrue(value.startswith("git:"), value)
            revision = value.split(":")[1]
            self.assertEqual(len(revision), 40, value)
            self.assertNotIn(revision, {"HEAD", "main"}, value)
            shown = subprocess.run(
                ("git", "cat-file", "-e", f"{revision}^{{commit}}"), cwd=REPO, capture_output=True
            )
            self.assertEqual(shown.returncode, 0, f"{value} does not name a commit that exists")

    def test_the_baseline_digest_matches_the_bytes_it_names(self) -> None:
        revision, path = self.receipt["baseline"]["metrics_uri"][len("git:"):].split(":", 1)
        shown = subprocess.run(
            ("git", "cat-file", "blob", f"{revision}:{path}"), cwd=REPO, check=True, capture_output=True
        )
        self.assertEqual(
            self.receipt["baseline"]["sha256"], comparator.sha256_bytes(shown.stdout)
        )

    def test_external_hypotheses_are_labelled_as_producer_claims_not_citations(self) -> None:
        for claim in self.receipt["external_hypotheses"]:
            self.assertIn("NOT A CITATION", claim)

    def test_the_receipt_makes_no_acceptance_or_completion_claim(self) -> None:
        text = json.dumps(self.receipt)
        self.assertNotIn('"COMPLETED"', text)
        self.assertNotIn('"ACCEPTED"', text)
        self.assertIn("READY_TO_COMMIT", self.receipt["subordinate_claim"])

    def test_a_receipt_with_a_founder_correction_is_refused(self) -> None:
        broken = copy.deepcopy(self.receipt)
        broken["decision_changed"] = ["a correction"]
        self.assertTrue(validator.validate_wave(broken))

    def test_a_receipt_missing_independent_tests_is_refused(self) -> None:
        broken = copy.deepcopy(self.receipt)
        broken["independent_tests"] = []
        self.assertTrue(validator.validate_wave(broken))


if __name__ == "__main__":
    unittest.main(verbosity=2)
