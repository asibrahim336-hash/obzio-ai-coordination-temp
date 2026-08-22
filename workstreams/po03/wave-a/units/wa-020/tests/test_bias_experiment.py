"""The experiment: cell coverage, identity swing, the freeze effect, determinism."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from harness.adjudicator import ProbingAdjudicator
from harness.bias_experiment import (
    ALTERNATIVE_WEIGHTINGS,
    identity_permutations,
    run_experiment,
    top_standing_target,
    weighted_draft,
)
from harness.candidates import build_pool, identity_pool, observed_prior_producer
from harness.canonical import digest
from harness.criteria import REVIEW_CRITERIA
from harness.logical_clock import LogicalClock
from harness.probes import RepositoryProbes, repository_root
from harness.reviewers import StandingSensitiveReviewer

ROOT = repository_root()
PROBES = RepositoryProbes(ROOT)
IDENTITIES = identity_pool(ROOT)
POOL = build_pool(IDENTITIES, observed_prior_producer(ROOT))
EXPERIMENT = run_experiment(POOL, PROBES, IDENTITIES)
CELLS = {cell["cell_id"]: cell for cell in EXPERIMENT["cells"]}


class DesignTests(unittest.TestCase):
    def test_the_design_is_fully_crossed(self) -> None:
        self.assertEqual(EXPERIMENT["cell_count"], 16)
        self.assertEqual(len(CELLS), 16)

    def test_every_submission_is_reviewed_under_every_standing_tier(self) -> None:
        permutations = identity_permutations(POOL, IDENTITIES)
        tiers = {envelope.standing_tier for envelope in IDENTITIES}
        for submission in POOL.submissions:
            seen = {item["tier_by_submission"][submission.submission_id] for item in permutations}
            self.assertEqual(seen, tiers, submission.submission_id)

    def test_the_permutations_change_only_the_attached_identity(self) -> None:
        permutations = identity_permutations(POOL, IDENTITIES)
        baseline = {
            submission.submission_id: submission.reviewable_content()["method"]
            for submission in POOL.submissions
        }
        for item in permutations:
            permuted = POOL.with_identities(item["assignment"])
            for submission in permuted.submissions:
                self.assertEqual(
                    submission.reviewable_content()["method"], baseline[submission.submission_id]
                )

    def test_the_alternative_weightings_leave_the_criterion_set_intact(self) -> None:
        for name in ALTERNATIVE_WEIGHTINGS:
            draft = weighted_draft(name)
            self.assertEqual(
                [criterion.criterion_id for criterion in draft.criteria],
                [criterion.criterion_id for criterion in REVIEW_CRITERIA],
            )

    def test_the_frozen_weighting_matches_the_preregistered_criteria(self) -> None:
        frozen = weighted_draft("frozen").seal(LogicalClock())
        for criterion in REVIEW_CRITERIA:
            self.assertEqual(frozen.by_id(criterion.criterion_id).weight, criterion.weight)

    def test_each_alternative_weighting_actually_differs_from_frozen(self) -> None:
        frozen = {criterion.criterion_id: criterion.weight for criterion in REVIEW_CRITERIA}
        for name, overrides in ALTERNATIVE_WEIGHTINGS.items():
            if name == "frozen":
                continue
            self.assertTrue(any(frozen[key] != value for key, value in overrides.items()), name)


class BlindingEffectTests(unittest.TestCase):
    def test_no_blind_cell_shows_any_identity_swing(self) -> None:
        for cell_id, cell in CELLS.items():
            if cell["blind"]:
                self.assertEqual(cell["max_identity_swing"], 0, cell_id)

    def test_no_blind_cell_shows_a_rank_inversion(self) -> None:
        for cell_id, cell in CELLS.items():
            if cell["blind"]:
                self.assertEqual(cell["rank_inversions"], 0, cell_id)

    def test_no_blind_cell_leaks(self) -> None:
        for cell_id, cell in CELLS.items():
            if cell["blind"]:
                self.assertEqual(cell["leak_count"], 0, cell_id)

    def test_the_biased_reviewer_swings_when_it_can_see_identity(self) -> None:
        self.assertGreater(CELLS["unblinded|gated|standing-sensitive|probing"]["max_identity_swing"], 0)

    def test_the_neutral_reviewer_does_not_swing_even_when_unblinded(self) -> None:
        """So the swing is the interaction of visibility and bias, not visibility alone."""
        self.assertEqual(CELLS["unblinded|gated|neutral|probing"]["max_identity_swing"], 0)

    def test_the_same_biased_reviewer_is_neutralised_by_blinding(self) -> None:
        blind = CELLS["blind|gated|standing-sensitive|probing"]["max_identity_swing"]
        unblinded = CELLS["unblinded|gated|standing-sensitive|probing"]["max_identity_swing"]
        self.assertEqual(blind, 0)
        self.assertGreater(unblinded, blind)

    def test_the_summary_agrees_with_the_cells(self) -> None:
        effect = EXPERIMENT["blinding_effect"]
        self.assertEqual(
            effect["max_identity_swing_in_blind_cells"],
            max(cell["max_identity_swing"] for cell in CELLS.values() if cell["blind"]),
        )
        self.assertEqual(
            effect["max_identity_swing_in_unblinded_cells"],
            max(cell["max_identity_swing"] for cell in CELLS.values() if not cell["blind"]),
        )


class SeededClaimTests(unittest.TestCase):
    def test_every_blind_probing_cell_catches_the_claim_in_every_permutation(self) -> None:
        for cell_id, cell in CELLS.items():
            if cell["blind"] and cell_id.endswith("probing"):
                self.assertEqual(cell["catch_rate"], "4/4", cell_id)

    def test_no_credulous_cell_catches_the_claim_at_all(self) -> None:
        for cell_id, cell in CELLS.items():
            if cell_id.endswith("credulous"):
                self.assertEqual(cell["catch_rate"], "0/4", cell_id)

    def test_unblinding_the_biased_reviewer_loses_the_catch_in_one_permutation(self) -> None:
        self.assertEqual(CELLS["unblinded|gated|standing-sensitive|probing"]["catch_rate"], "3/4")

    def test_the_lost_permutation_is_the_one_attributing_the_claim_to_the_top_tier(self) -> None:
        cell = CELLS["unblinded|gated|standing-sensitive|probing"]
        permutations = {item["permutation_id"]: item for item in identity_permutations(POOL, IDENTITIES)}
        top = max(envelope.standing_tier for envelope in IDENTITIES)
        missed = [key for key, caught in cell["caught_by_permutation"].items() if not caught]
        self.assertEqual(len(missed), 1)
        self.assertEqual(permutations[missed[0]]["tier_by_submission"]["SUB-2"], top)

    def test_the_summary_lists_the_catching_and_non_catching_cells(self) -> None:
        effect = EXPERIMENT["seeded_claim_effect"]
        self.assertEqual(len(effect["cells_never_catching"]), 8)
        self.assertEqual(len(effect["cells_catching_in_every_permutation"]), 6)


class GateEffectTests(unittest.TestCase):
    def test_the_gated_session_refuses_a_post_ingestion_seal(self) -> None:
        self.assertTrue(EXPERIMENT["gate_effect"]["gated_session_refused_post_hoc_seal"])

    def test_removing_the_gate_permits_the_ordering(self) -> None:
        self.assertTrue(EXPERIMENT["gate_effect"]["ungated_session_accepted_post_hoc_seal"])

    def test_shopping_gains_the_favoured_submission_weighted_points(self) -> None:
        self.assertGreater(EXPERIMENT["gate_effect"]["shopping_gain_for_target"], 0)

    def test_the_shopped_weighting_is_not_the_frozen_one(self) -> None:
        self.assertNotEqual(EXPERIMENT["gate_effect"]["shopped_weighting"], "frozen")

    def test_the_shopper_targets_the_highest_standing_submission(self) -> None:
        target = top_standing_target(POOL)
        self.assertEqual(EXPERIMENT["gate_effect"]["target_submission"], target)
        self.assertEqual(
            POOL.by_id(target).identity.standing_tier,
            max(submission.identity.standing_tier for submission in POOL.submissions),
        )

    def test_the_shopper_chooses_from_the_declared_menu_only(self) -> None:
        self.assertIn(EXPERIMENT["gate_effect"]["shopped_weighting"], ALTERNATIVE_WEIGHTINGS)


class FreezeEffectTests(unittest.TestCase):
    def test_the_preregistered_ranking_metric_is_reported_as_measured(self) -> None:
        """The recurrence test for M7.

        The preregistered metric for CM-H8 was a ranking change under blinding. It
        did not occur. The test asserts that the recorded value is the observation,
        so a later change that made the metric pass by redefining it would fail
        here rather than pass quietly.
        """
        freeze = EXPERIMENT["freeze_effect_under_blinding"]
        observed = any(item["permutations_with_changed_ranking"] for item in freeze["comparisons"])
        self.assertEqual(freeze["any_ranking_changed_under_blinding"], observed)
        self.assertIn("ranking", freeze["preregistered_metric"])

    def test_the_secondary_margin_reading_is_recorded_separately(self) -> None:
        freeze = EXPERIMENT["freeze_effect_under_blinding"]
        self.assertGreater(freeze["differential_gain"]["max_gain_spread"], 0)
        self.assertIn("differential_gain", freeze)

    def test_the_extra_gain_lands_on_the_candidate_with_a_refuted_claim(self) -> None:
        freeze = EXPERIMENT["freeze_effect_under_blinding"]
        probing = [
            item
            for item in freeze["differential_gain"]["per_permutation"]
            if item["adjudicator"] == "probing"
        ]
        self.assertTrue(probing)
        self.assertTrue(all("SUB-2" in item["largest_gain_submissions"] for item in probing))

    def test_the_comparison_covers_every_blind_reviewer_and_adjudicator(self) -> None:
        freeze = EXPERIMENT["freeze_effect_under_blinding"]
        self.assertEqual(len(freeze["comparisons"]), 4)


class DeterminismTests(unittest.TestCase):
    def test_the_summary_is_identical_across_runs(self) -> None:
        replay = run_experiment(POOL, PROBES, IDENTITIES)
        self.assertEqual(digest(EXPERIMENT["summary_by_cell"]), digest(replay["summary_by_cell"]))

    def test_every_review_digest_is_reproduced_on_replay(self) -> None:
        replay = {cell["cell_id"]: cell for cell in run_experiment(POOL, PROBES, IDENTITIES)["cells"]}
        for cell_id, cell in CELLS.items():
            self.assertEqual(cell["review_digests"], replay[cell_id]["review_digests"], cell_id)

    def test_probe_observations_are_recorded_for_the_experiment(self) -> None:
        self.assertGreater(len(EXPERIMENT["probe_observations"]), 0)
        for record in EXPERIMENT["probe_observations"].values():
            self.assertEqual(len(record["observation_sha256"]), 64)


class ShoppingTests(unittest.TestCase):
    def test_shopping_never_chooses_a_weighting_worse_than_frozen_for_its_target(self) -> None:
        from harness.bias_experiment import _shop_weighting

        reviewer = StandingSensitiveReviewer()
        adjudicator = ProbingAdjudicator(PROBES)
        chosen, scores = _shop_weighting(POOL, False, reviewer, adjudicator, top_standing_target)
        self.assertIn(chosen, ALTERNATIVE_WEIGHTINGS)
        self.assertGreaterEqual(scores[top_standing_target(POOL)], 0)


if __name__ == "__main__":
    unittest.main()
