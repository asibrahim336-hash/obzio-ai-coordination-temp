"""The criteria seal and what it is able to detect."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from harness.criteria import (
    REVIEW_CRITERIA,
    Criterion,
    CriteriaDraft,
    CriteriaSealBroken,
    frozen_criteria,
    seal_digest,
)
from harness.logical_clock import LogicalClock


def _draft() -> CriteriaDraft:
    return CriteriaDraft(criteria=list(REVIEW_CRITERIA))


class SealTests(unittest.TestCase):
    def test_the_seal_records_the_tick_it_was_taken_at(self) -> None:
        clock = LogicalClock()
        sealed = _draft().seal(clock)
        self.assertEqual(sealed.sealed_at_tick, 1)
        self.assertEqual(clock.now, 1)

    def test_the_seal_digest_is_reproducible_from_the_specification(self) -> None:
        sealed = _draft().seal(LogicalClock())
        self.assertEqual(sealed.recompute_seal(), sealed.seal_sha256)
        sealed.verify()

    def test_the_digest_is_independent_of_criterion_order(self) -> None:
        forward = seal_digest(tuple(REVIEW_CRITERIA))
        backward = seal_digest(tuple(reversed(REVIEW_CRITERIA)))
        self.assertEqual(forward, backward)

    def test_a_changed_weight_breaks_the_seal(self) -> None:
        sealed = _draft().seal(LogicalClock())
        tampered = list(sealed.criteria)
        target = tampered[0]
        tampered[0] = Criterion(
            criterion_id=target.criterion_id,
            question=target.question,
            evaluator=target.evaluator,
            scale=target.scale,
            weight=target.weight + 5,
            identity_sensitive=target.identity_sensitive,
        )
        self.assertNotEqual(seal_digest(tuple(tampered)), sealed.seal_sha256)

    def test_a_changed_question_breaks_the_seal(self) -> None:
        sealed = _draft().seal(LogicalClock())
        tampered = list(sealed.criteria)
        target = tampered[1]
        tampered[1] = Criterion(
            criterion_id=target.criterion_id,
            question=target.question + " And is it well presented?",
            evaluator=target.evaluator,
            scale=target.scale,
            weight=target.weight,
            identity_sensitive=target.identity_sensitive,
        )
        self.assertNotEqual(seal_digest(tuple(tampered)), sealed.seal_sha256)

    def test_verify_raises_when_the_recorded_digest_does_not_match(self) -> None:
        sealed = _draft().seal(LogicalClock())
        broken = type(sealed)(
            criteria=sealed.criteria,
            sealed_at_tick=sealed.sealed_at_tick,
            seal_sha256="0" * 64,
        )
        with self.assertRaises(CriteriaSealBroken):
            broken.verify()

    def test_a_rationale_change_alone_does_not_break_the_seal(self) -> None:
        """The seal covers what decides outcomes, not the prose explaining it."""
        sealed = _draft().seal(LogicalClock())
        restated = list(sealed.criteria)
        target = restated[0]
        restated[0] = Criterion(
            criterion_id=target.criterion_id,
            question=target.question,
            evaluator=target.evaluator,
            scale=target.scale,
            weight=target.weight,
            identity_sensitive=target.identity_sensitive,
            rationale="restated for clarity",
        )
        self.assertEqual(seal_digest(tuple(restated)), sealed.seal_sha256)

    def test_an_empty_criteria_set_cannot_be_sealed(self) -> None:
        with self.assertRaises(ValueError):
            CriteriaDraft().seal(LogicalClock())

    def test_duplicate_criterion_identifiers_are_refused(self) -> None:
        draft = CriteriaDraft()
        draft.add(REVIEW_CRITERIA[0])
        with self.assertRaises(ValueError):
            draft.add(REVIEW_CRITERIA[0])


class PreregisteredCriteriaTests(unittest.TestCase):
    def test_evidence_outweighs_presentation(self) -> None:
        """The two evidence criteria must together outweigh every other question."""
        sealed = frozen_criteria(LogicalClock())
        evidence = sum(
            criterion.scale * criterion.weight
            for criterion in sealed.criteria
            if criterion.criterion_id in ("C1-CLAIMS-UPHELD-BY-PROBE", "C2-NO-REFUTED-CLAIM")
        )
        self.assertGreater(evidence, sealed.maximum_weighted_score - evidence)

    def test_the_refuted_claim_gate_carries_the_highest_weight(self) -> None:
        sealed = frozen_criteria(LogicalClock())
        gate = sealed.by_id("C2-NO-REFUTED-CLAIM")
        self.assertEqual(gate.weight, max(criterion.weight for criterion in sealed.criteria))

    def test_exactly_one_criterion_is_marked_identity_sensitive(self) -> None:
        sealed = frozen_criteria(LogicalClock())
        sensitive = [criterion for criterion in sealed.criteria if criterion.identity_sensitive]
        self.assertEqual([criterion.criterion_id for criterion in sensitive], ["C6-NOVELTY-ASSERTED"])

    def test_the_identity_sensitive_criterion_carries_the_lowest_weight(self) -> None:
        sealed = frozen_criteria(LogicalClock())
        sensitive = sealed.by_id("C6-NOVELTY-ASSERTED")
        self.assertEqual(sensitive.weight, min(criterion.weight for criterion in sealed.criteria))

    def test_every_evaluator_name_resolves(self) -> None:
        from harness.reviewers import EVALUATORS

        for criterion in frozen_criteria(LogicalClock()).criteria:
            self.assertIn(criterion.evaluator, EVALUATORS)


class ClockTests(unittest.TestCase):
    def test_ticks_are_strictly_monotonic(self) -> None:
        clock = LogicalClock()
        observed = [clock.tick() for _ in range(5)]
        self.assertEqual(observed, [1, 2, 3, 4, 5])

    def test_now_is_zero_before_the_first_tick(self) -> None:
        self.assertEqual(LogicalClock().now, 0)


if __name__ == "__main__":
    unittest.main()
