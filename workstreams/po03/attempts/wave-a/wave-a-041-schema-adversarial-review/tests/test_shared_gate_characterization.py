#!/usr/bin/env python3
"""Characterisation tests for the shipped result-custody gate.

These tests assert what the shared control *currently does* with each adversarial
document, pinned by source hash.  They are deliberately characterisation rather
than specification tests: a failure here means the pinned control changed, and
the correct response is to re-run this review against the new source, not to
edit the expectations.  An exploit case that starts failing is good news, since
it means that hole was closed upstream.
"""

from __future__ import annotations

import copy
import unittest

import harness


class SourcePins(unittest.TestCase):
    def test_reviewed_sources_are_unmodified(self):
        self.assertEqual(harness.EXPECTED_GATE_SHA256, harness.sha256_file(harness.SHARED_GATE_PATH))
        self.assertEqual(harness.EXPECTED_SCHEMA_SHA256, harness.sha256_file(harness.SCHEMA_PATH))


class SharedGateBehaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = harness.run_all()
        cls.by_case = {result["case_id"]: result for result in cls.report["results"]}

    def test_every_case_behaves_as_recorded(self):
        for result in self.report["results"]:
            with self.subTest(case=result["case_id"]):
                self.assertEqual(result["predicted_gate"], result["observed_gate"])
                self.assertEqual(result["predicted_schema"], result["observed_schema"])
                self.assertEqual(result["predicted_classification"], result["observed_classification"])

    def test_hypothesis_is_refuted_by_at_least_one_exploit(self):
        self.assertTrue(
            self.report["exploit_case_ids"],
            "H-041 claims no path from provider completion to Obzio completion without durable "
            "evidence; refutation requires at least one accepted counterexample",
        )

    def test_negative_controls_are_still_refused(self):
        for case_id in ("B01-completed-without-commit-id", "B02-exact-string-self-accept", "B03-running-with-committed-artifacts"):
            self.assertEqual("BLOCKED", self.by_case[case_id]["observed_classification"])

    def test_honest_control_is_accepted(self):
        self.assertEqual("CONTROL_ACCEPT", self.by_case["C00-honest-control"]["observed_classification"])

    def test_self_acceptance_guard_is_defeated_only_by_aliasing(self):
        """The exact-match guard works; every alias of the same principal defeats it."""
        self.assertEqual("BLOCKED", self.by_case["B02-exact-string-self-accept"]["observed_classification"])
        for case_id in (
            "C08-self-accept-trailing-whitespace-alias",
            "C09-self-accept-zero-width-alias",
            "C10-self-accept-unicode-normalisation-alias",
        ):
            self.assertTrue(self.by_case[case_id]["observed_classification"].startswith("EXPLOIT"))

    def test_schema_is_not_the_enforced_gate(self):
        """C15 is refused by the schema and accepted by the executable control."""
        case = self.by_case["C15-unknown-property-injection"]
        self.assertEqual("ACCEPT", case["observed_gate"])
        self.assertEqual("INVALID", case["observed_schema"])

    def test_both_schema_implementations_agree(self):
        for result in self.report["results"]:
            for document in result["documents"]:
                agreement = document["reference_agrees_with_minischema"]
                if agreement is None:
                    self.skipTest("jsonschema is not importable in this runtime")
                self.assertTrue(agreement, f"{result['case_id']}: schema implementations disagree")


class HarnessIntegrity(unittest.TestCase):
    def test_gate_hash_mismatch_is_fatal(self):
        """The harness must refuse to report findings against a different source."""
        original = harness.EXPECTED_GATE_SHA256
        harness.EXPECTED_GATE_SHA256 = "0" * 64
        try:
            with self.assertRaises(AssertionError):
                harness.load_shared_gate()
        finally:
            harness.EXPECTED_GATE_SHA256 = original

    def test_documents_are_not_mutated_by_evaluation(self):
        cases = harness.load_cases()
        before = copy.deepcopy(cases["cases"])
        harness.run_all()
        self.assertEqual(before, harness.load_cases()["cases"])


if __name__ == "__main__":
    unittest.main()
