"""The review session: the ordering gate, the leak stop, and what counts as a catch."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from harness.adjudicator import CredulousAdjudicator, ProbingAdjudicator
from harness.bias_experiment import weighted_draft
from harness.blinding import Blinder, IdentityLeak, LeakyBlinder
from harness.candidates import build_pool, identity_pool, observed_prior_producer
from harness.claims import REFUTED
from harness.criteria import CriteriaFreezeOrderError, frozen_criteria
from harness.logical_clock import LogicalClock
from harness.probes import RepositoryProbes, repository_root
from harness.review import (
    CriteriaNotSealed,
    ReviewSession,
    SessionStateError,
    UngatedReviewSession,
    ordering_evidence,
)
from harness.reviewers import NeutralReviewer, StandingSensitiveReviewer
from harness.seeded_case import SEEDED_FALSE_CLAIM_ID, claims_for

ROOT = repository_root()
PROBES = RepositoryProbes(ROOT)
IDENTITIES = identity_pool(ROOT)
POOL = build_pool(IDENTITIES, observed_prior_producer(ROOT))


def _session(blind: bool = True, gated: bool = True, blinder=None) -> ReviewSession:
    factory = ReviewSession if gated else UngatedReviewSession
    return factory(LogicalClock(), blinder or Blinder(), blind=blind, session_id="test")


class OrderingGateTests(unittest.TestCase):
    def test_a_candidate_offered_before_sealing_is_refused(self) -> None:
        session = _session()
        with self.assertRaises(CriteriaNotSealed):
            session.admit(POOL.submissions[0])

    def test_sealing_after_a_candidate_has_been_admitted_is_refused(self) -> None:
        session = _session()
        session.seal(weighted_draft("frozen"))
        session.admit(POOL.submissions[0])
        with self.assertRaises(CriteriaFreezeOrderError):
            session.seal(weighted_draft("novelty-forward"))

    def test_the_seal_tick_strictly_precedes_every_admission(self) -> None:
        session = _session()
        sealed = session.seal(weighted_draft("frozen"))
        for submission in POOL.submissions:
            session.admit(submission)
        self.assertTrue(
            all(sealed.sealed_at_tick < admission.admitted_at_tick for admission in session.admissions)
        )

    def test_the_ungated_session_permits_the_ordering_the_gate_refuses(self) -> None:
        """The control that makes the gate's effect measurable rather than assumed."""
        session = _session(gated=False)
        session.seal(weighted_draft("frozen"))
        session.admit(POOL.submissions[0])
        session.seal(weighted_draft("novelty-forward"))
        self.assertFalse(session.gate_enforced)

    def test_review_before_sealing_is_refused(self) -> None:
        with self.assertRaises(CriteriaNotSealed):
            _session().review(NeutralReviewer(), ProbingAdjudicator(PROBES), claims_for)

    def test_review_with_no_candidates_is_refused(self) -> None:
        session = _session()
        session.seal(weighted_draft("frozen"))
        with self.assertRaises(SessionStateError):
            session.review(NeutralReviewer(), ProbingAdjudicator(PROBES), claims_for)

    def test_a_criteria_edit_between_ingestion_and_scoring_is_detected(self) -> None:
        session = _session()
        session.seal(weighted_draft("frozen"))
        for submission in POOL.submissions:
            session.admit(submission)
        session.criteria = type(session.criteria)(
            criteria=session.criteria.criteria,
            sealed_at_tick=session.criteria.sealed_at_tick,
            seal_sha256="0" * 64,
        )
        with self.assertRaises(Exception) as caught:
            session.review(NeutralReviewer(), ProbingAdjudicator(PROBES), claims_for)
        self.assertIn("seal", str(caught.exception).lower())

    def test_admitting_after_the_review_is_refused(self) -> None:
        session = _session()
        session.seal(weighted_draft("frozen"))
        for submission in POOL.submissions:
            session.admit(submission)
        session.review(NeutralReviewer(), ProbingAdjudicator(PROBES), claims_for)
        with self.assertRaises(SessionStateError):
            session.admit(POOL.submissions[0])

    def test_ordering_evidence_reports_every_session(self) -> None:
        record = self._reviewed()
        evidence = ordering_evidence([record])
        self.assertEqual(evidence["sessions"], 1)
        self.assertEqual(evidence["sessions_sealed_before_first_admission"], 1)

    def _reviewed(self):
        session = _session()
        session.seal(weighted_draft("frozen"))
        for submission in POOL.submissions:
            session.admit(submission)
        return session.review(NeutralReviewer(), ProbingAdjudicator(PROBES), claims_for)


class BlindingIntegrationTests(unittest.TestCase):
    def test_a_leak_stops_the_session_instead_of_being_reported_afterwards(self) -> None:
        session = _session(blinder=LeakyBlinder())
        session.seal(weighted_draft("frozen"))
        for submission in POOL.submissions:
            session.admit(submission)
        with self.assertRaises(IdentityLeak):
            session.review(NeutralReviewer(), ProbingAdjudicator(PROBES), claims_for)

    def test_the_blind_record_reports_no_leak(self) -> None:
        record = self._review(blind=True)
        self.assertEqual(record.leaks, [])
        self.assertTrue(record.blind)

    def test_the_blind_record_labels_candidates_by_pseudonym(self) -> None:
        record = self._review(blind=True)
        for pseudonym in record.pseudonym_by_submission.values():
            self.assertTrue(pseudonym.startswith("CANDIDATE-"))

    def test_the_unblinded_record_labels_candidates_by_submission_id(self) -> None:
        record = self._review(blind=False)
        self.assertEqual(
            sorted(record.pseudonym_by_submission.values()),
            sorted(record.pseudonym_by_submission),
        )

    def test_no_identity_string_reaches_a_blind_score(self) -> None:
        record = self._review(blind=True)
        text = repr(record.as_record()["scores"])
        for envelope in IDENTITIES:
            self.assertNotIn(envelope.runner_id, text)
            self.assertNotIn(envelope.model_slug, text)

    def _review(self, blind: bool, reviewer=None, adjudicator=None):
        session = _session(blind=blind)
        session.seal(weighted_draft("frozen"))
        for submission in POOL.submissions:
            session.admit(submission)
        return session.review(
            reviewer or NeutralReviewer(), adjudicator or ProbingAdjudicator(PROBES), claims_for
        )


class CatchDefinitionTests(unittest.TestCase):
    def test_the_seeded_claim_is_caught_under_blinding(self) -> None:
        record = self._review(blind=True, reviewer=StandingSensitiveReviewer())
        self.assertTrue(record.caught(SEEDED_FALSE_CLAIM_ID))

    def test_a_refutation_the_reviewer_discounts_is_not_a_catch(self) -> None:
        """The recurrence test for M4.

        The top-tier permutation is the one where the standing-sensitive reviewer
        discounts a refutation it already obtained. Under a weaker definition that
        counted refutation alone, this would have been recorded as a catch.
        """
        top = max(IDENTITIES, key=lambda envelope: envelope.standing_tier)
        assignment = {
            submission.submission_id: (
                top if submission.submission_id == "SUB-2" else submission.identity
            )
            for submission in POOL.submissions
        }
        permuted = POOL.with_identities(assignment)
        session = _session(blind=False)
        session.seal(weighted_draft("frozen"))
        for submission in permuted.submissions:
            session.admit(submission)
        record = session.review(StandingSensitiveReviewer(), ProbingAdjudicator(PROBES), claims_for)
        self.assertNotIn(SEEDED_FALSE_CLAIM_ID, record.refuted_claim_ids())
        self.assertFalse(record.caught(SEEDED_FALSE_CLAIM_ID))

    def test_the_probe_still_refuted_the_claim_before_the_reviewer_discounted_it(self) -> None:
        """The failure is the discount, not a failure to notice."""
        top = max(IDENTITIES, key=lambda envelope: envelope.standing_tier)
        assignment = {
            submission.submission_id: (
                top if submission.submission_id == "SUB-2" else submission.identity
            )
            for submission in POOL.submissions
        }
        permuted = POOL.with_identities(assignment)
        session = _session(blind=False)
        session.seal(weighted_draft("frozen"))
        for submission in permuted.submissions:
            session.admit(submission)
        record = session.review(StandingSensitiveReviewer(), ProbingAdjudicator(PROBES), claims_for)
        raw = record.adjudications["SUB-2"]
        self.assertIn(
            SEEDED_FALSE_CLAIM_ID,
            [item.claim_id for item in raw if item.verdict == REFUTED],
        )

    def test_a_credulous_adjudicator_never_catches_the_claim(self) -> None:
        session = _session(blind=True)
        session.seal(weighted_draft("frozen"))
        for submission in POOL.submissions:
            session.admit(submission)
        record = session.review(NeutralReviewer(), CredulousAdjudicator(), claims_for)
        self.assertFalse(record.caught(SEEDED_FALSE_CLAIM_ID))

    def test_the_gate_criterion_scores_zero_for_the_carrying_candidate(self) -> None:
        record = self._review(blind=True, reviewer=NeutralReviewer())
        carrier = record.pseudonym_by_submission["SUB-2"]
        score = next(item for item in record.scores if item.label == carrier)
        self.assertEqual(score.raw["C2-NO-REFUTED-CLAIM"], 0)

    def test_a_candidate_with_no_refuted_claim_scores_full_on_the_gate(self) -> None:
        record = self._review(blind=True, reviewer=NeutralReviewer())
        clean = record.pseudonym_by_submission["SUB-3"]
        score = next(item for item in record.scores if item.label == clean)
        self.assertEqual(score.raw["C2-NO-REFUTED-CLAIM"], 10)

    def _review(self, blind: bool, reviewer=None):
        session = _session(blind=blind)
        session.seal(weighted_draft("frozen"))
        for submission in POOL.submissions:
            session.admit(submission)
        return session.review(reviewer or NeutralReviewer(), ProbingAdjudicator(PROBES), claims_for)


class ReviewerTests(unittest.TestCase):
    def test_the_biased_reviewer_cannot_act_without_an_identity_view(self) -> None:
        reviewer = StandingSensitiveReviewer()
        adjudications = ProbingAdjudicator(PROBES).adjudicate_all(claims_for("SUB-2"))
        blind = reviewer.adjust_adjudications(adjudications, None)
        self.assertEqual([item.verdict for item in blind], [item.verdict for item in adjudications])

    def test_the_biased_reviewer_discounts_a_refutation_at_the_top_tier(self) -> None:
        reviewer = StandingSensitiveReviewer()
        adjudications = ProbingAdjudicator(PROBES).adjudicate_all(claims_for("SUB-2"))
        lenient = reviewer.adjust_adjudications(adjudications, {"standing_tier": 4})
        self.assertNotIn(REFUTED, [item.verdict for item in lenient])

    def test_the_biased_reviewer_does_not_discount_below_the_leniency_tier(self) -> None:
        reviewer = StandingSensitiveReviewer()
        adjudications = ProbingAdjudicator(PROBES).adjudicate_all(claims_for("SUB-2"))
        strict = reviewer.adjust_adjudications(adjudications, {"standing_tier": 3})
        self.assertIn(REFUTED, [item.verdict for item in strict])

    def test_the_neutral_reviewer_ignores_an_identity_view_entirely(self) -> None:
        reviewer = NeutralReviewer()
        adjudications = ProbingAdjudicator(PROBES).adjudicate_all(claims_for("SUB-2"))
        self.assertEqual(
            [item.verdict for item in reviewer.adjust_adjudications(adjudications, {"standing_tier": 4})],
            [item.verdict for item in adjudications],
        )

    def test_the_presentation_bonus_only_touches_identity_sensitive_criteria(self) -> None:
        reviewer = StandingSensitiveReviewer()
        criteria = frozen_criteria(LogicalClock())
        for criterion in criteria.criteria:
            bonus = reviewer.bonus(criterion, {"standing_tier": 4})
            self.assertEqual(bonus > 0, criterion.identity_sensitive)

    def test_a_score_never_exceeds_the_criterion_scale(self) -> None:
        session = _session(blind=False)
        session.seal(weighted_draft("frozen"))
        for submission in POOL.submissions:
            session.admit(submission)
        record = session.review(StandingSensitiveReviewer(), ProbingAdjudicator(PROBES), claims_for)
        criteria = session.criteria
        for score in record.scores:
            for criterion_id, value in score.raw.items():
                self.assertLessEqual(value, criteria.by_id(criterion_id).scale)
                self.assertGreaterEqual(value, 0)


if __name__ == "__main__":
    unittest.main()
