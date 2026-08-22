"""The sanitized Obzio reproductions, and the separation of research states.

The commission requires source claim, frozen hypothesis, reproduction, result and
mechanism disposition to stay distinct.  These tests assert both the separation
and each reproduction's verdict, so a reproduction that stops reproducing is
visible rather than absorbed into a summary.
"""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from harness import fixtures, reproductions, research
from harness.reproductions import (
    ALL_REPRODUCTIONS,
    RECOVERY_STATE_REL,
    reproduce_deterministic_replay,
    reproduce_frozen_input_resolvability,
    reproduce_idempotent_replay_conflict,
    reproduce_po02_code2_loss,
    reproduce_seeded_validator_gaps,
)
from harness.seeded import repository_root

VERDICTS = {"REPRODUCED", "NOT_REPRODUCED", "DEFECT_REPRODUCED", "NO_DEFECT_OBSERVED", "NOT_SUPPORTED", "ERROR"}


class R1Po02Code2Tests(unittest.TestCase):
    """The lost PO-02 Code-2 packaging return, replayed on a sanitized workload."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = reproduce_po02_code2_loss(repository_root())

    def test_it_reproduces(self):
        self.assertEqual("REPRODUCED", self.result["verdict"])

    def test_it_compares_against_the_recorded_fixture_rather_than_a_retyped_one(self):
        import json

        recorded = json.loads((repository_root() / RECOVERY_STATE_REL).read_text(encoding="utf-8"))
        self.assertEqual(recorded["po02_code2_fixture"], self.result["recorded_fixture"])

    def test_four_routes_reported_completion_and_left_nothing_durable(self):
        self.assertEqual(4, len(self.result["routes"]))
        self.assertTrue(self.result["four_routes_left_no_durable_result"])
        self.assertTrue(self.result["never_reported_completed_without_commit"])
        self.assertTrue(self.result["classification_matches_recorded_fixture"])
        for route in self.result["routes"]:
            self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", route["classified_as"])
            self.assertIsNone(route["durable_commit"])
            self.assertIn("SCHEDULE_RETRY_FROM_IMMUTABLE_INPUT", route["recovery_actions"])

    def test_the_fifth_route_commits_loses_its_callback_and_still_completes(self):
        self.assertTrue(self.result["route_five_commit_id"])
        self.assertEqual(["LOST_IN_TRANSIT"], [o["outcome"] for o in self.result["route_five_callback_outcome"]])
        self.assertIn("REPLAY_LOST_CALLBACK", self.result["route_five_recovery_actions"])
        self.assertEqual("COMPLETED", self.result["route_five_completion"])
        self.assertEqual("COMPLETED", self.result["final_state"])


class R2ResolvabilityTests(unittest.TestCase):
    def test_the_defect_reproduces_across_the_frozen_inputs(self):
        result = reproduce_frozen_input_resolvability(repository_root())
        self.assertEqual("DEFECT_REPRODUCED", result["verdict"])
        self.assertEqual(64, result["input_count"])
        self.assertEqual(["minimum_protocol_ancestor"], result["unresolvable_pointers"])
        self.assertEqual("UNRESOLVABLE", result["this_unit_example"]["disposition"])


class R4DeterminismTests(unittest.TestCase):
    def test_a_seeded_cell_replays_byte_identically(self):
        result = reproduce_deterministic_replay()
        self.assertEqual("REPRODUCED", result["verdict"])
        self.assertTrue(result["trace_digests_equal"])
        self.assertTrue(result["rows_equal"])
        self.assertEqual(result["trace_digest_first"], result["trace_digest_second"])


class R5ValidatorGapTests(unittest.TestCase):
    def test_the_seeded_validator_admits_documents_the_layer_rejects(self):
        result = reproduce_seeded_validator_gaps()
        self.assertEqual("DEFECT_REPRODUCED", result["verdict"])
        self.assertGreater(result["admitted_by_seeded_validator"], 0)
        self.assertEqual(result["gap_count"], result["closed_by_strengthened_layer"])


class R7IdempotencyTests(unittest.TestCase):
    def test_a_divergent_replay_under_one_key_is_refused(self):
        result = reproduce_idempotent_replay_conflict()
        self.assertEqual("REPRODUCED", result["verdict"])
        self.assertTrue(result["same_parameter_replay_returns_same_commit"])
        self.assertEqual("IdempotencyConflict", result["divergent_replay_outcome"])
        self.assertEqual(1, result["distinct_external_effects"])


class LedgerTests(unittest.TestCase):
    def test_the_wave_quota_of_sanitized_reproductions_is_exceeded(self):
        self.assertGreaterEqual(len(ALL_REPRODUCTIONS), 1)
        self.assertEqual(7, len(ALL_REPRODUCTIONS))

    def test_every_reproduction_returns_a_declared_verdict(self):
        for row in reproductions.run_all(repository_root()):
            with self.subTest(reproduction=row["reproduction_id"]):
                self.assertIn(row["verdict"], VERDICTS)
                self.assertNotEqual("ERROR", row["verdict"], row.get("error"))
                self.assertNotIn(row["verdict"], {"NOT_REPRODUCED"})

    def test_every_reproduction_documents_what_it_reproduces(self):
        for function in ALL_REPRODUCTIONS:
            with self.subTest(reproduction=function.__name__):
                self.assertTrue(function.__doc__, function.__name__)

    def test_a_failing_reproduction_is_recorded_as_data_not_a_crash(self):
        original = reproductions.ALL_REPRODUCTIONS

        def exploding() -> dict:
            """A reproduction that raises."""
            raise RuntimeError("deliberate")

        reproductions.ALL_REPRODUCTIONS = (exploding,)
        try:
            rows = reproductions.run_all()
        finally:
            reproductions.ALL_REPRODUCTIONS = original
        self.assertEqual("ERROR", rows[0]["verdict"])
        self.assertEqual("RuntimeError", rows[0]["error_type"])

    def test_no_reproduction_contains_a_credential_or_owner_identifier(self):
        """Sanitized means sanitized: only repository-native, public content."""
        forbidden = ("ghp_", "github_pat_", "Authorization:", "BEGIN PRIVATE KEY", "@gmail.", "password")
        from pathlib import Path

        for module in (reproductions, fixtures):
            source = Path(module.__file__).read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, source, f"{module.__name__}: {token}")


class ResearchStateSeparationTests(unittest.TestCase):
    def test_source_claims_hypotheses_and_mechanisms_are_separate_records(self):
        claim_ids = {c["claim_id"] for c in research.EXTERNAL_SOURCE_CLAIMS}
        repo_ids = {c["claim_id"] for c in research.REPOSITORY_SOURCE_CLAIMS}
        hypothesis_ids = {h["hypothesis_id"] for h in research.HYPOTHESES}
        mechanism_ids = {m["mechanism_id"] for m in research.MECHANISM_CHANGES}
        self.assertEqual(set(), claim_ids & repo_ids)
        self.assertEqual(set(), claim_ids & hypothesis_ids)
        self.assertEqual(set(), hypothesis_ids & mechanism_ids)

    def test_the_wave_quota_of_current_method_hypotheses_is_exceeded(self):
        self.assertGreaterEqual(len(research.HYPOTHESES), 2)

    def test_no_hypothesis_asserts_a_source_it_does_not_cite(self):
        known = {c["claim_id"] for c in research.EXTERNAL_SOURCE_CLAIMS}
        for hypothesis in research.HYPOTHESES:
            self.assertTrue(hypothesis["source_claim_ids"], hypothesis["hypothesis_id"])
            self.assertTrue(set(hypothesis["source_claim_ids"]) <= known, hypothesis["hypothesis_id"])

    def test_no_hypothesis_rests_on_a_source_that_could_not_be_read(self):
        unsupported = {
            c["claim_id"] for c in research.EXTERNAL_SOURCE_CLAIMS if not c["readable_in_runtime"]
        }
        self.assertTrue(unsupported, "the NOT_SUPPORTED cases must still be declared")
        for hypothesis in research.HYPOTHESES:
            self.assertEqual(
                set(),
                set(hypothesis["source_claim_ids"]) & unsupported,
                hypothesis["hypothesis_id"],
            )

    def test_unreadable_sources_claim_nothing_and_state_why(self):
        for claim in research.EXTERNAL_SOURCE_CLAIMS:
            if claim["readable_in_runtime"]:
                self.assertNotEqual("NOT_SUPPORTED", claim["claim"], claim["claim_id"])
                continue
            self.assertEqual("NOT_SUPPORTED", claim["claim"], claim["claim_id"])
            self.assertTrue(claim["limitation"].strip(), claim["claim_id"])

    def test_every_external_claim_records_the_bytes_actually_retrieved(self):
        for claim in research.EXTERNAL_SOURCE_CLAIMS:
            with self.subTest(claim=claim["claim_id"]):
                self.assertTrue(claim["url"].startswith("https://"))
                self.assertIsInstance(claim["http_status"], int)
                self.assertEqual(64, len(claim["sha256"]))
                self.assertGreater(claim["bytes"], 0)

    def test_every_hypothesis_names_the_reproduction_that_tests_it(self):
        for hypothesis in research.HYPOTHESES:
            self.assertTrue(hypothesis["reproduction_ids"], hypothesis["hypothesis_id"])
            self.assertTrue(hypothesis["prediction"].strip())
            self.assertTrue(hypothesis["evaluator"].strip())

    def test_every_mechanism_names_a_recurrence_test_that_exists(self):
        from pathlib import Path

        tests_dir = Path(__file__).resolve().parent
        for mechanism in research.MECHANISM_CHANGES:
            with self.subTest(mechanism=mechanism["mechanism_id"]):
                relative = mechanism["recurrence_test"].split("::")[0]
                self.assertTrue((tests_dir.parent / relative).exists(), relative)
                self.assertTrue(mechanism["rationale"].strip())
                self.assertIn(
                    mechanism["disposition"],
                    {"PROPOSED_TO_COORDINATOR", "RETAIN", "EVIDENCE_BACKED_REJECTION"},
                )

    def test_at_least_one_mechanism_is_live_and_one_is_an_evidence_backed_rejection(self):
        dispositions = [m["disposition"] for m in research.MECHANISM_CHANGES]
        self.assertIn("RETAIN", dispositions)
        self.assertIn("EVIDENCE_BACKED_REJECTION", dispositions)

    def test_a_proposal_never_claims_to_have_edited_a_read_only_control(self):
        for mechanism in research.MECHANISM_CHANGES:
            if mechanism["scope"] == "PROPOSAL_TO_COORDINATOR":
                self.assertIn("not modified by this unit", mechanism["target"])

    def test_every_live_mechanism_targets_this_units_own_subtree(self):
        for mechanism in research.MECHANISM_CHANGES:
            if mechanism["scope"] == "LIVE_IN_THIS_UNIT":
                self.assertTrue(mechanism["target"].startswith("harness/"), mechanism["mechanism_id"])

    def test_a_prediction_corrected_after_the_fact_says_so(self):
        corrected = [h for h in research.HYPOTHESES if "prediction_correction" in h]
        self.assertTrue(corrected)
        for hypothesis in corrected:
            self.assertIn("after seeing the result", hypothesis["prediction_correction"])


if __name__ == "__main__":
    unittest.main()
