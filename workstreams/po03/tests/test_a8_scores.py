#!/usr/bin/env python3
"""Tests for the generation comparison document.

A score document is only evidence if it can be regenerated and if its verdict is
forced by a rule written down before the result was seen.  These tests attack
both halves: the committed document must be reproducible byte for byte from the
committed tree, and the verdict rule must refuse a lift when any preregistered
guard is violated, including guards that no observed comparison happens to trip.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

PO03 = Path(__file__).resolve().parents[1]
REPO_ROOT = PO03.parents[1]
if str(PO03) not in sys.path:
    sys.path.insert(0, str(PO03))

from successor.harness import score as scoring

SCORES = PO03 / "successor" / "scores" / "generation-comparison.json"
PREREGISTRATION = PO03 / "successor" / "suite" / "lift-preregistration.json"
SCORER = "workstreams/po03/successor/score_generations.py"


def _document() -> dict:
    return json.loads(SCORES.read_text(encoding="utf-8"))


def _preregistration() -> dict:
    return json.loads(PREREGISTRATION.read_text(encoding="utf-8"))


class ReproducibilityTests(unittest.TestCase):
    def test_committed_scores_are_regenerated_byte_for_byte(self):
        """The recorded score must still be the score this tree produces."""
        result = subprocess.run(
            [sys.executable, "-I", SCORER, "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("REPRODUCED", result.stdout)

    def test_no_field_carries_a_timestamp_or_an_absolute_path(self):
        """A clock reading or a machine path would break byte identity elsewhere."""
        forbidden_keys = {"generated_at", "recorded_at", "timestamp", "run_id", "hostname"}
        offenders: list[str] = []

        def walk(node, trail: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in forbidden_keys:
                        offenders.append(f"{trail}.{key}")
                    walk(value, f"{trail}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{trail}[{index}]")
            elif isinstance(node, str) and (node.startswith("/") or "/tmp/" in node):
                offenders.append(f"{trail}={node}")

        walk(_document(), "$")
        self.assertEqual(offenders, [], f"unreproducible values: {offenders}")


class IdenticalInputTests(unittest.TestCase):
    def test_every_generation_is_scored_on_every_frozen_suite(self):
        document = _document()
        suite_keys = {suite["key"] for suite in document["suites"]}
        self.assertEqual(suite_keys, {"public", "holdout"})
        self.assertEqual(set(document["generations"]), {"G0", "G1", "G2"})
        for generation_id, score in document["generations"].items():
            self.assertEqual(set(score["suites"]), suite_keys, generation_id)

    def test_case_totals_are_identical_across_generations(self):
        """"Identical inputs" is only true if every generation saw the same cases."""
        document = _document()
        for suite in document["suites"]:
            totals = {
                generation_id: score["suites"][suite["key"]]["cases_total"]
                for generation_id, score in document["generations"].items()
            }
            self.assertEqual(
                set(totals.values()),
                {suite["case_count"]},
                f"{suite['key']} case counts diverged: {totals}",
            )

    def test_holdout_is_not_authored_by_the_generation_owner(self):
        document = _document()
        holdout = next(suite for suite in document["suites"] if suite["role"] == "holdout")
        self.assertNotEqual(holdout["authored_by"], document["produced_by"])


class PreregistrationBindingTests(unittest.TestCase):
    def test_recorded_preregistration_hash_matches_the_committed_file(self):
        import hashlib

        document = _document()
        digest = hashlib.sha256(PREREGISTRATION.read_bytes()).hexdigest()
        self.assertEqual(document["preregistration"]["sha256"], digest)

    def test_headline_is_the_preregistered_primary_comparison(self):
        document = _document()
        prereg = _preregistration()
        headline = document["headline"]
        self.assertEqual(headline["metric_id"], prereg["primary_metric"]["metric_id"])
        self.assertEqual(headline["baseline"], prereg["primary_comparison"]["baseline"])
        self.assertEqual(headline["candidate"], prereg["primary_comparison"]["candidate"])
        self.assertEqual(headline["suite"], prereg["primary_comparison"]["suite"])

    def test_headline_suite_is_the_holdout_not_the_self_authored_suite(self):
        """Compounding may not be claimed from the suite this cohort wrote."""
        document = _document()
        headline_suite = next(
            suite for suite in document["suites"] if suite["key"] == document["headline"]["suite"]
        )
        self.assertEqual(headline_suite["role"], "holdout")

    def test_every_preregistered_comparison_appears_exactly_once(self):
        document = _document()
        prereg = _preregistration()
        declared = [
            (pair["baseline"], pair["candidate"], pair["suite"]) for pair in prereg["comparisons"]
        ]
        observed = [
            (row["baseline"], row["candidate"], row["suite"]) for row in document["comparisons"]
        ]
        self.assertEqual(sorted(declared), sorted(observed))

    def test_no_comparison_was_added_after_the_fact(self):
        """A comparison absent from the preregistration could be a chosen result."""
        document = _document()
        declared = {
            (pair["baseline"], pair["candidate"], pair["suite"])
            for pair in _preregistration()["comparisons"]
        }
        for row in document["comparisons"]:
            self.assertIn((row["baseline"], row["candidate"], row["suite"]), declared)


class VerdictRuleTests(unittest.TestCase):
    def test_pass_requires_every_condition_and_not_yet_names_its_clause(self):
        for row in _document()["comparisons"]:
            unmet = [item["id"] for item in row["conditions"] if not item["held"]]
            self.assertEqual(sorted(unmet), sorted(row["unmet_conditions"]), row)
            if row["verdict"] == "PASS":
                self.assertEqual(unmet, [], f"{row['baseline']}->{row['candidate']} claims PASS with {unmet}")
            else:
                self.assertEqual(row["verdict"], "NOT_YET")
                self.assertTrue(unmet, "a NOT_YET must name the clause it failed")
                for clause in unmet:
                    self.assertIn(clause, row["reason"])

    def test_measured_lift_matches_the_recorded_pass_rates(self):
        for row in _document()["comparisons"]:
            self.assertAlmostEqual(
                row["lift"],
                round(row["candidate_pass_rate"] - row["baseline_pass_rate"], 4),
                places=4,
            )

    def test_recorded_pass_rates_match_the_generation_scores(self):
        document = _document()
        for row in document["comparisons"]:
            suites = document["generations"]
            self.assertEqual(
                row["baseline_pass_rate"],
                suites[row["baseline"]]["suites"][row["suite"]]["pass_rate"],
            )
            self.assertEqual(
                row["candidate_pass_rate"],
                suites[row["candidate"]]["suites"][row["suite"]]["pass_rate"],
            )


def _synthetic(pass_rate, *, critical=1.0, false_completions=0, table=None, public=None):
    suite = {
        "pass_rate": pass_rate,
        "critical_pass_rate": critical,
        "false_completion_count": false_completions,
        "case_table": table if table is not None else [],
    }
    return {
        "suites": {
            "holdout": suite,
            "public": suite if public is None else public,
        }
    }


class GuardFalsificationTests(unittest.TestCase):
    """Each guard must be able to refuse a lift, or it is decoration."""

    def setUp(self):
        self.prereg = _preregistration()

    def _compare(self, baseline, candidate):
        return scoring.compare(
            {"B": baseline, "C": candidate},
            baseline="B",
            candidate="C",
            preregistration=self.prereg,
            suite_key="holdout",
        )

    def test_clean_improvement_passes(self):
        row = self._compare(_synthetic(0.5), _synthetic(0.9))
        self.assertEqual(row["verdict"], "PASS", row["unmet_conditions"])

    def test_lift_below_threshold_is_refused(self):
        row = self._compare(_synthetic(0.9), _synthetic(0.95))
        self.assertEqual(row["verdict"], "NOT_YET")
        self.assertIn("L1-minimum-lift", row["unmet_conditions"])

    def test_a_false_completion_refuses_an_otherwise_large_lift(self):
        row = self._compare(_synthetic(0.1), _synthetic(1.0, false_completions=1))
        self.assertEqual(row["verdict"], "NOT_YET")
        self.assertIn("L2-no-false-completion", row["unmet_conditions"])

    def test_per_case_regression_refuses_a_lift(self):
        baseline = _synthetic(
            0.5,
            table=[
                {"case_id": "H01", "verdict": "PASS"},
                {"case_id": "H02", "verdict": "FAIL"},
            ],
        )
        candidate = _synthetic(
            0.9,
            table=[
                {"case_id": "H01", "verdict": "FAIL"},
                {"case_id": "H02", "verdict": "PASS"},
            ],
        )
        row = self._compare(baseline, candidate)
        self.assertEqual(row["verdict"], "NOT_YET")
        self.assertIn("L4-no-per-case-regression", row["unmet_conditions"])
        self.assertEqual(
            [item["observed"] for item in row["conditions"] if item["id"] == "L4-no-per-case-regression"],
            [["H01"]],
        )

    def test_public_suite_regression_refuses_a_holdout_lift(self):
        baseline = _synthetic(0.5, public={"pass_rate": 0.9, "critical_pass_rate": 1.0, "false_completion_count": 0, "case_table": []})
        candidate = _synthetic(1.0, public={"pass_rate": 0.4, "critical_pass_rate": 1.0, "false_completion_count": 0, "case_table": []})
        row = self._compare(baseline, candidate)
        self.assertEqual(row["verdict"], "NOT_YET")
        self.assertIn("L5-public-suite-not-worse", row["unmet_conditions"])

    def test_incomplete_critical_correctness_refuses_a_lift(self):
        row = self._compare(_synthetic(0.2), _synthetic(0.9, critical=0.99))
        self.assertEqual(row["verdict"], "NOT_YET")
        self.assertIn("L6-critical-correctness-complete", row["unmet_conditions"])

    def test_every_declared_condition_id_is_evaluated(self):
        declared = {clause.split(":")[0] for clause in self.prereg["lift_rule"]["conditions"]}
        evaluated = {item["id"] for item in self._compare(_synthetic(0.5), _synthetic(0.9))["conditions"]}
        self.assertEqual(declared, evaluated)


class TranscriptTests(unittest.TestCase):
    def test_recorded_transcripts_reproduce(self):
        result = subprocess.run(
            [sys.executable, "-I", "workstreams/po03/successor/record_transcripts.py", "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_transcript_exists_for_every_generation_and_suite(self):
        directory = PO03 / "successor" / "transcripts"
        for generation_id in ("g0", "g1", "g2"):
            for suite_key in ("public", "holdout"):
                self.assertTrue(
                    (directory / f"{generation_id}-{suite_key}.txt").is_file(),
                    f"missing transcript for {generation_id} on {suite_key}",
                )


if __name__ == "__main__":
    unittest.main()
