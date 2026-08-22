"""Unit tests for the a5-u11 registered-vs-unregistered conversion model."""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from lib.conversion_rate_simulation_u11 import (  # noqa: E402
    Candidate,
    generate_candidates,
    is_correct,
    is_decisive,
    registered_pipeline,
    run_pipeline_over_pool,
    unregistered_pipeline,
)


class TestGenerateCandidates(unittest.TestCase):
    def test_same_seed_reproduces_identical_pool(self) -> None:
        a = generate_candidates(seed=1, n=100)
        b = generate_candidates(seed=1, n=100)
        self.assertEqual([c.ground_truth for c in a], [c.ground_truth for c in b])

    def test_produces_all_three_ground_truth_kinds_at_reasonable_scale(self) -> None:
        pool = generate_candidates(seed=5, n=500)
        kinds = {c.ground_truth for c in pool}
        self.assertEqual(kinds, {"TRUE", "FALSE", "AMBIGUOUS"})


class TestRegisteredPipeline(unittest.TestCase):
    def test_never_forces_a_decisive_verdict_on_an_ambiguous_candidate(self) -> None:
        rng = random.Random(0)
        for _ in range(200):
            candidate = Candidate(0, "AMBIGUOUS")
            outcome = registered_pipeline(candidate, rng)
            self.assertEqual(outcome, "NOT_YET")

    def test_mostly_resolves_true_candidates_as_supported(self) -> None:
        rng = random.Random(42)
        outcomes = [registered_pipeline(Candidate(i, "TRUE"), rng) for i in range(500)]
        supported = sum(1 for o in outcomes if o == "SUPPORTED")
        self.assertGreater(supported / len(outcomes), 0.8)

    def test_mostly_resolves_false_candidates_as_rejected(self) -> None:
        rng = random.Random(43)
        outcomes = [registered_pipeline(Candidate(i, "FALSE"), rng) for i in range(500)]
        rejected = sum(1 for o in outcomes if o == "REJECTED")
        self.assertGreater(rejected / len(outcomes), 0.8)


class TestUnregisteredPipeline(unittest.TestCase):
    def test_sometimes_forces_a_decisive_verdict_on_ambiguous_candidates(self) -> None:
        rng = random.Random(7)
        outcomes = [unregistered_pipeline(Candidate(i, "AMBIGUOUS"), rng) for i in range(500)]
        decisive = sum(1 for o in outcomes if is_decisive(o))
        self.assertGreater(decisive, 0)  # spurious decisiveness actually occurs, not just theoretically possible

    def test_lower_decisive_rate_than_registered_on_true_candidates(self) -> None:
        rng_r = random.Random(1)
        rng_u = random.Random(2)
        true_candidates = [Candidate(i, "TRUE") for i in range(500)]
        registered_decisive = sum(is_decisive(registered_pipeline(c, rng_r)) for c in true_candidates)
        unregistered_decisive = sum(is_decisive(unregistered_pipeline(c, rng_u)) for c in true_candidates)
        self.assertGreater(registered_decisive, unregistered_decisive)


class TestIsCorrect(unittest.TestCase):
    def test_supported_is_correct_for_true(self) -> None:
        self.assertTrue(is_correct("SUPPORTED", Candidate(0, "TRUE")))

    def test_supported_is_incorrect_for_false(self) -> None:
        self.assertFalse(is_correct("SUPPORTED", Candidate(0, "FALSE")))

    def test_not_yet_is_never_correct(self) -> None:
        self.assertFalse(is_correct("NOT_YET", Candidate(0, "TRUE")))

    def test_no_decisive_verdict_on_ambiguous_can_ever_be_correct(self) -> None:
        self.assertFalse(is_correct("SUPPORTED", Candidate(0, "AMBIGUOUS")))
        self.assertFalse(is_correct("REJECTED", Candidate(0, "AMBIGUOUS")))


class TestRunPipelineOverPool(unittest.TestCase):
    def test_same_pool_and_seed_reproduces_identical_summary(self) -> None:
        pool = generate_candidates(seed=9, n=200)
        a = run_pipeline_over_pool(pool, registered_pipeline, seed=11)
        b = run_pipeline_over_pool(pool, registered_pipeline, seed=11)
        self.assertEqual(a, b)

    def test_registered_conversion_rate_exceeds_unregistered_on_the_same_pool(self) -> None:
        pool = generate_candidates(seed=20260822, n=1000)
        registered = run_pipeline_over_pool(pool, registered_pipeline, seed=1)
        unregistered = run_pipeline_over_pool(pool, unregistered_pipeline, seed=2)
        self.assertGreater(registered["conversion_rate"], unregistered["conversion_rate"])

    def test_registered_correct_rate_given_decisive_exceeds_unregistered(self) -> None:
        pool = generate_candidates(seed=20260822, n=1000)
        registered = run_pipeline_over_pool(pool, registered_pipeline, seed=1)
        unregistered = run_pipeline_over_pool(pool, unregistered_pipeline, seed=2)
        self.assertGreater(registered["correct_rate_given_decisive"], unregistered["correct_rate_given_decisive"])

    def test_registered_has_zero_spurious_decisive_on_ambiguous(self) -> None:
        pool = generate_candidates(seed=20260822, n=1000)
        registered = run_pipeline_over_pool(pool, registered_pipeline, seed=1)
        self.assertEqual(registered["spurious_decisive_on_ambiguous_count"], 0)

    def test_unregistered_has_nonzero_spurious_decisive_on_ambiguous(self) -> None:
        pool = generate_candidates(seed=20260822, n=1000)
        unregistered = run_pipeline_over_pool(pool, unregistered_pipeline, seed=2)
        self.assertGreater(unregistered["spurious_decisive_on_ambiguous_count"], 0)

    def test_denominator_n_is_always_reported(self) -> None:
        pool = generate_candidates(seed=1, n=37)
        summary = run_pipeline_over_pool(pool, registered_pipeline, seed=1)
        self.assertEqual(summary["n"], 37)


if __name__ == "__main__":
    unittest.main()
