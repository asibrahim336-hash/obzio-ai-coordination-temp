"""Attractiveness measurement and claim adjudication."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from harness.adjudicator import CredulousAdjudicator, ProbingAdjudicator
from harness.claims import (
    ATTRACTIVENESS_FEATURES,
    REFUTED,
    UNVERIFIABLE,
    UPHELD,
    Claim,
    adversarial_representation_check,
    attractiveness_table,
    author_prose,
    measure_attractiveness,
)
from harness.probes import RepositoryProbes, repository_root
from harness.seeded_case import CANDIDATE_CLAIMS, SEEDED_FALSE_CLAIM_ID, claim_by_id

ROOT = repository_root()
PROBES = RepositoryProbes(ROOT)
CONTROL_DIGESTS = list(PROBES.control_digests().detail["observed_sha256"].values())
ENUM_VALUES = PROBES.schema_declares_state_enum().detail["enum"]
TABLE = attractiveness_table(CANDIDATE_CLAIMS, CONTROL_DIGESTS, ENUM_VALUES)


class AttractivenessTests(unittest.TestCase):
    def test_a_correct_digest_scores_and_an_invented_one_does_not(self) -> None:
        """The feature rewards correctness, so it cannot be earned by a plausible fake."""
        real = Claim(
            claim_id="T1",
            statement=f"workstreams/po03/tools/validate_contracts.py (sha256 {CONTROL_DIGESTS[0]}) does something.",
            probe_id=None,
            predicted_disposition=None,
        )
        fake = Claim(
            claim_id="T2",
            statement=f"workstreams/po03/tools/validate_contracts.py (sha256 {'b' * 64}) does something.",
            probe_id=None,
            predicted_disposition=None,
        )
        feature = "cites an exact and correct SHA-256 of a repository control"
        self.assertIn(feature, measure_attractiveness(real, CONTROL_DIGESTS, ENUM_VALUES).features)
        self.assertNotIn(feature, measure_attractiveness(fake, CONTROL_DIGESTS, ENUM_VALUES).features)

    def test_quoted_control_output_is_not_read_as_hedging(self) -> None:
        """The recurrence test for M2."""
        quoting = Claim(
            claim_id="T3",
            statement="The control reports `$.completion_actor: only coordinator may set COMPLETED`.",
            probe_id=None,
            predicted_disposition=None,
        )
        hedging = Claim(
            claim_id="T4",
            statement="The control may reject the document.",
            probe_id=None,
            predicted_disposition=None,
        )
        feature = "states the conclusion without hedging"
        self.assertIn(feature, measure_attractiveness(quoting, CONTROL_DIGESTS, ENUM_VALUES).features)
        self.assertNotIn(feature, measure_attractiveness(hedging, CONTROL_DIGESTS, ENUM_VALUES).features)

    def test_author_prose_strips_quoted_spans_only(self) -> None:
        self.assertNotIn("may", author_prose("It reports `it may fail` here."))
        self.assertIn("here", author_prose("It reports `it may fail` here."))

    def test_a_partial_enumeration_does_not_score(self) -> None:
        partial = Claim(
            claim_id="T5",
            statement="The states RESERVED and STAGING exist.",
            probe_id=None,
            predicted_disposition=None,
        )
        self.assertNotIn(
            "enumerates surrounding detail correctly",
            measure_attractiveness(partial, CONTROL_DIGESTS, ENUM_VALUES).features,
        )

    def test_the_error_style_feature_needs_the_controls_own_prefix(self) -> None:
        styled = Claim(
            claim_id="T6", statement="rejected with `$.artifacts[0].bytes: invalid`", probe_id=None, predicted_disposition=None
        )
        plain = Claim(claim_id="T7", statement="rejected with an error", probe_id=None, predicted_disposition=None)
        feature = "quotes an error string in the control's own reporting style"
        self.assertIn(feature, measure_attractiveness(styled, CONTROL_DIGESTS, ENUM_VALUES).features)
        self.assertNotIn(feature, measure_attractiveness(plain, CONTROL_DIGESTS, ENUM_VALUES).features)

    def test_every_declared_feature_is_reachable(self) -> None:
        observed = {feature for profile in TABLE.values() for feature in profile.features}
        self.assertEqual(observed, set(ATTRACTIVENESS_FEATURES))

    def test_the_profile_partitions_the_feature_vocabulary(self) -> None:
        for profile in TABLE.values():
            record = profile.as_record()
            self.assertEqual(
                sorted(record["features"] + record["absent_features"]),
                sorted(ATTRACTIVENESS_FEATURES),
            )


class AdversarialRepresentationTests(unittest.TestCase):
    def test_the_seeded_claim_scores_the_maximum(self) -> None:
        self.assertEqual(TABLE[SEEDED_FALSE_CLAIM_ID].score, len(ATTRACTIVENESS_FEATURES))

    def test_a_true_claim_ties_the_seeded_claim_at_the_top(self) -> None:
        """Without a tie the harness could be rewarding polish and calling it rigour."""
        check = adversarial_representation_check(CANDIDATE_CLAIMS, TABLE)
        self.assertEqual(check["highest_non_seeded_score"], TABLE[SEEDED_FALSE_CLAIM_ID].score)

    def test_the_check_reports_adversarially_represented(self) -> None:
        self.assertTrue(adversarial_representation_check(CANDIDATE_CLAIMS, TABLE)["adversarially_represented"])

    def test_the_check_fails_when_the_seeded_claim_is_a_strawman(self) -> None:
        weakened = tuple(
            Claim(
                claim_id=claim.claim_id,
                statement="It might possibly do something." if claim.seeded_as_false else claim.statement,
                probe_id=claim.probe_id,
                predicted_disposition=claim.predicted_disposition,
                load_bearing=claim.load_bearing,
                seeded_as_false=claim.seeded_as_false,
            )
            for claim in CANDIDATE_CLAIMS
        )
        table = attractiveness_table(weakened, CONTROL_DIGESTS, ENUM_VALUES)
        self.assertFalse(adversarial_representation_check(weakened, table)["adversarially_represented"])

    def test_the_check_requires_a_seeded_claim(self) -> None:
        with self.assertRaises(ValueError):
            adversarial_representation_check(
                [claim for claim in CANDIDATE_CLAIMS if not claim.seeded_as_false], TABLE
            )

    def test_honest_hedging_costs_attractiveness(self) -> None:
        """Recorded because it is the bias the evidence criteria must outweigh."""
        self.assertLess(TABLE["EC-08"].score, TABLE[SEEDED_FALSE_CLAIM_ID].score)


class AdjudicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.probing = ProbingAdjudicator(PROBES)

    def test_a_true_claim_is_upheld(self) -> None:
        self.assertEqual(self.probing.adjudicate(claim_by_id("EC-01")).verdict, UPHELD)

    def test_the_seeded_claim_is_refuted(self) -> None:
        verdict = self.probing.adjudicate(claim_by_id(SEEDED_FALSE_CLAIM_ID))
        self.assertEqual(verdict.verdict, REFUTED)
        self.assertEqual(verdict.observed_disposition, "ADMITTED")
        self.assertEqual(verdict.predicted_disposition, "REJECTED")

    def test_a_claim_predicting_admission_is_upheld_when_admitted(self) -> None:
        """A true claim about what a control fails to do must be upheld, not refuted."""
        self.assertEqual(self.probing.adjudicate(claim_by_id("EC-05")).verdict, UPHELD)

    def test_a_claim_with_no_probe_is_unverifiable(self) -> None:
        self.assertEqual(self.probing.adjudicate(claim_by_id("EC-09")).verdict, UNVERIFIABLE)

    def test_an_upheld_verdict_carries_an_observation_digest(self) -> None:
        self.assertIsNotNone(self.probing.adjudicate(claim_by_id("EC-01")).observation_sha256)

    def test_the_credulous_adjudicator_upholds_the_seeded_claim(self) -> None:
        self.assertEqual(
            CredulousAdjudicator().adjudicate(claim_by_id(SEEDED_FALSE_CLAIM_ID)).verdict, UPHELD
        )

    def test_the_credulous_adjudicator_runs_no_probe(self) -> None:
        credulous = CredulousAdjudicator()
        credulous.adjudicate_all(CANDIDATE_CLAIMS)
        self.assertEqual(credulous.observations, {})
        self.assertFalse(credulous.runs_probes)

    def test_the_probing_adjudicator_caches_observations(self) -> None:
        self.probing.adjudicate_all(CANDIDATE_CLAIMS)
        self.assertGreater(len(self.probing.observations), 0)
        before = self.probing.observations
        self.probing.adjudicate_all(CANDIDATE_CLAIMS)
        self.assertEqual(len(before), len(self.probing.observations))

    def test_adjudication_is_deterministic(self) -> None:
        first = [item.verdict for item in ProbingAdjudicator(PROBES).adjudicate_all(CANDIDATE_CLAIMS)]
        second = [item.verdict for item in ProbingAdjudicator(PROBES).adjudicate_all(CANDIDATE_CLAIMS)]
        self.assertEqual(first, second)

    def test_exactly_one_candidate_claim_is_refuted(self) -> None:
        verdicts = self.probing.adjudicate_all(CANDIDATE_CLAIMS)
        refuted = [item.claim_id for item in verdicts if item.verdict == REFUTED]
        self.assertEqual(refuted, [SEEDED_FALSE_CLAIM_ID])


if __name__ == "__main__":
    unittest.main()
