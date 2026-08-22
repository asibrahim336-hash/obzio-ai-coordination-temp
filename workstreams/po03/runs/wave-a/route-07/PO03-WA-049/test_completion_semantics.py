"""Falsification tests for the PO03-WA-049 three-axis completion separation.

The hypothesis fails if any provider observation can be read as Obzio completion,
if a durable-state assertion survives without a result commit, or if acceptance
can go terminal without a distinct reviewer.
"""

from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from completion_semantics import (  # noqa: E402
    ACCEPTANCE_STATES,
    Axis,
    AxisConfusion,
    Classification,
    CompletionTriple,
    CustodyViolation,
    DURABLE_OBZIO_STATES,
    OBZIO_STATES,
    PROVIDER_STATES,
    classify,
    independent_axes_report,
    is_complete,
    provider_completion_implies_obzio_completion,
)


class AxisSeparationTests(unittest.TestCase):
    def test_provider_completion_never_implies_obzio_completion(self):
        triple = CompletionTriple("COMPLETED", "RUNNING", "NOT_TESTED")
        with self.assertRaises(AxisConfusion):
            provider_completion_implies_obzio_completion(triple)

    def test_axis_query_requires_an_axis_member(self):
        triple = CompletionTriple("COMPLETED", "RUNNING", "NOT_TESTED")
        with self.assertRaises(AxisConfusion):
            is_complete(triple, "provider")

    def test_the_three_axes_are_independently_addressable(self):
        triple = CompletionTriple(
            "COMPLETED",
            "COMPLETED",
            "ACCEPTED",
            durable_result_commit_id="deadbeef",
            parent_ingested_at="2026-08-22T07:00:00Z",
            completion_actor="coordinator",
            reviewer_id="reviewer-a",
            producer_id="producer-b",
        )
        self.assertTrue(is_complete(triple, Axis.PROVIDER))
        self.assertTrue(is_complete(triple, Axis.OBZIO))
        self.assertTrue(is_complete(triple, Axis.ACCEPTANCE))
        report = independent_axes_report(triple)
        self.assertEqual({"provider", "obzio", "acceptance"}, set(report))
        self.assertNotEqual(report["provider"]["meaning"], report["obzio"]["meaning"])

    def test_provider_completion_alone_leaves_the_other_axes_incomplete(self):
        triple = CompletionTriple("COMPLETED", "RUNNING", "NOT_TESTED")
        self.assertTrue(is_complete(triple, Axis.PROVIDER))
        self.assertFalse(is_complete(triple, Axis.OBZIO))
        self.assertFalse(is_complete(triple, Axis.ACCEPTANCE))


class ReclassificationTests(unittest.TestCase):
    def test_provider_completed_without_commit_is_reclassified(self):
        triple = CompletionTriple("COMPLETED", "RESULT_COMMITTED", "NOT_TESTED")
        result = classify(triple)
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", result.effective_obzio_state)
        self.assertTrue(result.reclassified)

    def test_durable_state_without_commit_demands_recovery(self):
        triple = CompletionTriple("RUNNING", "PARENT_INGESTED", "NOT_TESTED")
        result = classify(triple)
        self.assertEqual("RECOVERY_REQUIRED", result.effective_obzio_state)

    def test_lost_po02_code2_fixture_never_reads_as_completed(self):
        """The frozen fault fixture: provider COMPLETED, nothing durable."""
        triple = CompletionTriple("COMPLETED", "RUNNING", "NOT_TESTED")
        result = classify(triple)
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", result.effective_obzio_state)
        self.assertNotEqual("COMPLETED", result.effective_obzio_state)

    def test_no_uncommitted_triple_can_reach_completed(self):
        """Exhaustive sweep of the provider x obzio grid without a commit id."""
        for provider, obzio in itertools.product(PROVIDER_STATES, OBZIO_STATES):
            triple = CompletionTriple(
                provider,
                obzio,
                "NOT_TESTED",
                completion_actor="coordinator" if obzio == "COMPLETED" else None,
                parent_ingested_at="2026-08-22T07:00:00Z" if obzio == "COMPLETED" else None,
            )
            with self.subTest(provider=provider, obzio=obzio):
                self.assertNotEqual("COMPLETED", classify(triple).effective_obzio_state)

    def test_committed_state_is_preserved_when_evidence_exists(self):
        triple = CompletionTriple(
            "COMPLETED", "RESULT_COMMITTED", "NOT_TESTED", durable_result_commit_id="c0ffee"
        )
        result = classify(triple)
        self.assertEqual("RESULT_COMMITTED", result.effective_obzio_state)
        self.assertFalse(result.reclassified)


class AuthorityTests(unittest.TestCase):
    def test_only_the_coordinator_may_set_completed(self):
        triple = CompletionTriple(
            "COMPLETED",
            "COMPLETED",
            "NOT_TESTED",
            durable_result_commit_id="abc123",
            parent_ingested_at="2026-08-22T07:00:00Z",
            completion_actor="route-07-worker",
        )
        with self.assertRaises(CustodyViolation):
            classify(triple)

    def test_completed_requires_recorded_parent_ingestion(self):
        triple = CompletionTriple(
            "COMPLETED",
            "COMPLETED",
            "NOT_TESTED",
            durable_result_commit_id="abc123",
            completion_actor="coordinator",
        )
        self.assertEqual("RESULT_COMMITTED", classify(triple).effective_obzio_state)

    def test_acceptance_cannot_be_terminal_before_obzio_completion(self):
        for state in ("ACCEPTED", "REJECTED"):
            triple = CompletionTriple(
                "COMPLETED",
                "RESULT_COMMITTED",
                state,
                durable_result_commit_id="abc123",
                reviewer_id="reviewer-a",
                producer_id="producer-b",
            )
            with self.subTest(acceptance=state):
                with self.assertRaises(CustodyViolation):
                    classify(triple)

    def test_producer_cannot_be_its_own_reviewer(self):
        triple = CompletionTriple(
            "COMPLETED",
            "COMPLETED",
            "ACCEPTED",
            durable_result_commit_id="abc123",
            parent_ingested_at="2026-08-22T07:00:00Z",
            completion_actor="coordinator",
            reviewer_id="same-actor",
            producer_id="same-actor",
        )
        with self.assertRaises(CustodyViolation):
            classify(triple)


class EnumHygieneTests(unittest.TestCase):
    def test_the_shared_state_names_are_exactly_the_conflation_hazard(self):
        """Provider and Obzio share three spellings; that ambiguity is the bug.

        The contract enum reuses RUNNING, COMPLETED and CANCELLED on both axes,
        so a bare string can never identify which axis is being asserted. The
        component therefore refuses string axis selectors and answers only
        through an explicit Axis member.
        """
        self.assertEqual(
            {"RUNNING", "COMPLETED", "CANCELLED"}, set(PROVIDER_STATES) & set(OBZIO_STATES)
        )
        self.assertEqual(set(), set(PROVIDER_STATES) & set(ACCEPTANCE_STATES))
        self.assertEqual(set(), set(ACCEPTANCE_STATES) & set(OBZIO_STATES))
        triple = CompletionTriple("COMPLETED", "RUNNING", "NOT_TESTED")
        with self.assertRaises(AxisConfusion):
            is_complete(triple, "COMPLETED")

    def test_unknown_states_are_rejected_on_construction(self):
        with self.assertRaises(ValueError):
            CompletionTriple("DONE", "RUNNING", "NOT_TESTED")
        with self.assertRaises(ValueError):
            CompletionTriple("RUNNING", "FINISHED", "NOT_TESTED")
        with self.assertRaises(ValueError):
            CompletionTriple("RUNNING", "RUNNING", "APPROVED")

    def test_durable_states_are_a_strict_subset_of_obzio_states(self):
        self.assertTrue(DURABLE_OBZIO_STATES.issubset(set(OBZIO_STATES)))
        self.assertNotIn("RESULT_STAGED", DURABLE_OBZIO_STATES)

    def test_classification_is_a_value_object(self):
        triple = CompletionTriple("RUNNING", "RUNNING", "NOT_TESTED")
        self.assertIsInstance(classify(triple), Classification)


if __name__ == "__main__":
    unittest.main()
