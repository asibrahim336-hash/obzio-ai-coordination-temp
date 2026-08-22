"""Falsification tests for the PO03-WA-055 three-candidate rubric ranking.

The hypothesis fails if the ranking depends on input order, if a modified rubric
still ranks, if fewer than three independent candidates yields a winner, or if a
missing score is silently scored as zero.
"""

from __future__ import annotations

import itertools
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from candidate_ranker import (  # noqa: E402
    MIN_INDEPENDENT_CANDIDATES,
    NOT_SUPPORTED,
    Candidate,
    Criterion,
    InsufficientCandidates,
    Rubric,
    RubricMismatch,
    independent_subset,
    pairwise_dominance,
    rank,
    score_candidate,
)

RUBRIC = Rubric(
    rubric_id="PO03-WA-055-CANDIDATE-RUBRIC-v1",
    criteria=(
        Criterion("critical_correctness", 0.40),
        Criterion("recovery_completeness", 0.25),
        Criterion("hidden_case_resistance", 0.20),
        Criterion("coordination_overhead", 0.15, higher_is_better=False),
    ),
)
DIGEST = RUBRIC.digest()

A = Candidate("cand-a", "principal-alpha", "claude-opus-5",
              {"critical_correctness": 1.0, "recovery_completeness": 0.9,
               "hidden_case_resistance": 0.8, "coordination_overhead": 0.2})
B = Candidate("cand-b", "principal-beta", "gpt-5.6-sol",
              {"critical_correctness": 0.7, "recovery_completeness": 0.8,
               "hidden_case_resistance": 0.9, "coordination_overhead": 0.1})
C = Candidate("cand-c", "principal-gamma", "gemini-3.1-pro",
              {"critical_correctness": 0.5, "recovery_completeness": 0.4,
               "hidden_case_resistance": 0.6, "coordination_overhead": 0.7})


class RubricIntegrityTests(unittest.TestCase):
    def test_digest_is_stable_for_the_same_rubric(self):
        clone = Rubric(RUBRIC.rubric_id, tuple(RUBRIC.criteria))
        self.assertEqual(RUBRIC.digest(), clone.digest())

    def test_changing_a_weight_changes_the_digest(self):
        tweaked = Rubric(
            RUBRIC.rubric_id,
            (Criterion("critical_correctness", 0.41),) + RUBRIC.criteria[1:],
        )
        self.assertNotEqual(RUBRIC.digest(), tweaked.digest())

    def test_a_rubric_that_moved_after_freezing_is_refused(self):
        tweaked = Rubric(
            RUBRIC.rubric_id,
            (Criterion("critical_correctness", 0.90),) + RUBRIC.criteria[1:],
        )
        with self.assertRaises(RubricMismatch):
            rank(tweaked, [A, B, C], DIGEST)

    def test_the_frozen_rubric_ranks(self):
        result = rank(RUBRIC, [A, B, C], DIGEST)
        self.assertEqual(DIGEST, result["rubric_digest"])
        self.assertEqual(3, len(result["ranking"]))


class DeterminismTests(unittest.TestCase):
    def test_ranking_is_invariant_under_every_input_permutation(self):
        baseline = rank(RUBRIC, [A, B, C], DIGEST)["ranking"]
        for permutation in itertools.permutations([A, B, C]):
            with self.subTest(order=[c.candidate_id for c in permutation]):
                self.assertEqual(baseline, rank(RUBRIC, list(permutation), DIGEST)["ranking"])

    def test_ranking_is_stable_across_repeated_runs(self):
        results = {tuple(rank(RUBRIC, [C, A, B], DIGEST)["ranking"]) for _ in range(10)}
        self.assertEqual(1, len(results))

    def test_shuffled_input_never_changes_the_winner(self):
        rng = random.Random(20260822)
        for _ in range(20):
            pool = [A, B, C]
            rng.shuffle(pool)
            self.assertEqual("cand-a", rank(RUBRIC, pool, DIGEST)["winner"])

    def test_ties_are_broken_by_the_declared_rule(self):
        """Distinct score vectors that weight to the same total must order by id."""
        tied_z = Candidate("cand-z", "principal-z", "gpt-5.6-sol",
                           {"critical_correctness": 0.50, "recovery_completeness": 0.50,
                            "hidden_case_resistance": 0.50, "coordination_overhead": 0.50})
        tied_y = Candidate("cand-y", "principal-y", "claude-opus-5",
                           {"critical_correctness": 0.55, "recovery_completeness": 0.42,
                            "hidden_case_resistance": 0.50, "coordination_overhead": 0.50})
        result = rank(RUBRIC, [tied_z, tied_y, C], DIGEST)
        self.assertIn(("cand-y", "cand-z"), result["ties"])
        self.assertLess(result["ranking"].index("cand-y"), result["ranking"].index("cand-z"))
        self.assertIn("candidate_id asc", result["tie_break_rule"])


class IndependenceTests(unittest.TestCase):
    def test_two_candidates_are_refused(self):
        with self.assertRaises(InsufficientCandidates):
            rank(RUBRIC, [A, B], DIGEST)

    def test_three_copies_of_one_candidate_are_refused(self):
        clones = [
            Candidate(f"clone-{i}", "principal-alpha", "claude-opus-5", dict(A.scores))
            for i in range(3)
        ]
        with self.assertRaises(InsufficientCandidates):
            rank(RUBRIC, clones, DIGEST)

    def test_identical_content_from_different_principals_collapses(self):
        twin = Candidate("cand-a2", "principal-delta", "gpt-5.6-sol", dict(A.scores))
        kept = independent_subset([A, twin, B, C])
        self.assertEqual(3, len(kept))
        self.assertNotIn("cand-a2", [c.candidate_id for c in kept])

    def test_a_single_model_family_is_refused_for_a_consequential_ranking(self):
        same_family = [
            Candidate("m-1", "p-1", "claude-opus-5", dict(A.scores)),
            Candidate("m-2", "p-2", "claude-opus-5", dict(B.scores)),
            Candidate("m-3", "p-3", "claude-opus-5", dict(C.scores)),
        ]
        with self.assertRaises(InsufficientCandidates):
            rank(RUBRIC, same_family, DIGEST)

    def test_dropped_dependents_are_reported(self):
        twin = Candidate("cand-a2", "principal-alpha", "claude-opus-5", dict(B.scores))
        result = rank(RUBRIC, [A, twin, B, C], DIGEST)
        self.assertIn("cand-a2", result["dropped_as_dependent"])

    def test_the_minimum_is_three(self):
        self.assertEqual(3, MIN_INDEPENDENT_CANDIDATES)


class ScoringTests(unittest.TestCase):
    def test_a_missing_score_lowers_coverage_and_is_not_zero(self):
        partial = Candidate("cand-p", "principal-p", "gpt-5.6-sol",
                            {"critical_correctness": 1.0, "recovery_completeness": 1.0})
        scored = score_candidate(RUBRIC, partial)
        self.assertEqual(1.0, scored.weighted_score)
        self.assertAlmostEqual(0.65, scored.coverage)
        self.assertEqual(
            ("coordination_overhead", "hidden_case_resistance"), scored.unsupported_criteria
        )

    def test_not_supported_is_honoured_explicitly(self):
        partial = Candidate("cand-q", "principal-q", "gpt-5.6-sol",
                            {"critical_correctness": 1.0, "recovery_completeness": NOT_SUPPORTED,
                             "hidden_case_resistance": NOT_SUPPORTED,
                             "coordination_overhead": NOT_SUPPORTED})
        scored = score_candidate(RUBRIC, partial)
        self.assertEqual(1, scored.scored_criteria)
        self.assertAlmostEqual(0.40, scored.coverage)

    def test_lower_is_better_criteria_are_inverted(self):
        cheap = Candidate("cheap", "p", "f", {"coordination_overhead": 0.0})
        dear = Candidate("dear", "p", "f", {"coordination_overhead": 1.0})
        self.assertGreater(
            score_candidate(RUBRIC, cheap).weighted_score,
            score_candidate(RUBRIC, dear).weighted_score,
        )

    def test_out_of_range_scores_are_refused(self):
        with self.assertRaises(ValueError):
            score_candidate(RUBRIC, Candidate("bad", "p", "f", {"critical_correctness": 1.5}))

    def test_non_numeric_scores_are_refused(self):
        with self.assertRaises(TypeError):
            score_candidate(RUBRIC, Candidate("bad", "p", "f", {"critical_correctness": "high"}))


class ConsistencyTests(unittest.TestCase):
    def test_pairwise_dominance_matches_the_total_order(self):
        result = rank(RUBRIC, [A, B, C], DIGEST)
        self.assertTrue(result["condorcet_consistent"], result)

    def test_dominance_table_covers_every_pair(self):
        scored = [score_candidate(RUBRIC, c) for c in (A, B, C)]
        table = pairwise_dominance(scored)
        self.assertEqual(3, len(table))

    def test_result_never_claims_a_terminal_decision(self):
        result = rank(RUBRIC, [A, B, C], DIGEST)
        self.assertEqual([], result["decision_changed"])
        self.assertNotIn("ACCEPTED", str(result))


if __name__ == "__main__":
    unittest.main()
