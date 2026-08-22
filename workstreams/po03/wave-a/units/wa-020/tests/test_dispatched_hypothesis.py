"""Tests for the verdict on the dispatched hypothesis H-PO03-WA-020.

These tests do most of their work on synthetic cell tables rather than on the real
experiment. The point of the evaluator is that it reaches the opposite verdict when
the evidence is the opposite, and that is only demonstrable by feeding it evidence
the real run does not produce. A test that only ever sees the real numbers cannot
distinguish an evaluator from a constant.

The final class does check the evaluator against the real design, so the recorded
verdict is tied to the committed harness and not only to fixtures.
"""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from harness import dispatched_hypothesis
from harness.bias_experiment import run_experiment
from harness.candidates import build_pool, identity_pool, observed_prior_producer
from harness.probes import RepositoryProbes, repository_root

FACTORS = [
    (blind, gate, reviewer, adjudicator)
    for blind in ("blind", "unblinded")
    for gate in ("gated", "ungated")
    for reviewer in ("neutral", "standing-sensitive")
    for adjudicator in ("probing", "credulous")
]


def cell_table(**overrides: dict[str, object]) -> dict[str, object]:
    """A complete 16-cell table with benign defaults, plus any per-cell overrides.

    Defaults describe a world in which nothing has any effect: no identity swing
    anywhere and no catch anywhere. Each test switches on only what it is about.
    """
    cells = []
    for blind, gate, reviewer, adjudicator in FACTORS:
        cell_id = f"{blind}|{gate}|{reviewer}|{adjudicator}"
        cell = {
            "catch_rate": "0/4",
            "cell_id": cell_id,
            "max_identity_swing": 0,
            "rank_inversions": 0,
        }
        cell.update(overrides.get(cell_id, {}))
        cells.append(cell)
    return {"cells": cells}


def realistic_table() -> dict[str, object]:
    """The shape the real run produces, written out explicitly.

    Anonymization removes an identity swing that only a biased reviewer expresses,
    the probe does all the catching, and a biased unblinded reviewer discards one
    refutation it already has.
    """
    overrides: dict[str, dict[str, object]] = {}
    for blind, gate, reviewer, adjudicator in FACTORS:
        cell_id = f"{blind}|{gate}|{reviewer}|{adjudicator}"
        override: dict[str, object] = {}
        if blind == "unblinded" and reviewer == "standing-sensitive":
            override["max_identity_swing"] = 49
            override["rank_inversions"] = 1
        if adjudicator == "probing":
            missed = blind == "unblinded" and reviewer == "standing-sensitive"
            override["catch_rate"] = "3/4" if missed else "4/4"
        if override:
            overrides[cell_id] = override
    return cell_table(**overrides)


class DesignCompletenessTests(unittest.TestCase):
    def test_an_incomplete_design_is_refused_rather_than_scored(self) -> None:
        table = realistic_table()
        table["cells"] = table["cells"][:8]
        with self.assertRaises(AssertionError):
            dispatched_hypothesis.evaluate(table)

    def test_cells_disagreeing_on_permutation_count_are_refused(self) -> None:
        """A rate parsed against a different denominator would silently mislead."""
        table = realistic_table()
        for cell in table["cells"]:
            if cell["cell_id"] == "blind|gated|neutral|probing":
                cell["catch_rate"] = "4/6"
        with self.assertRaises(AssertionError):
            dispatched_hypothesis.evaluate(table)


class ConjunctATests(unittest.TestCase):
    def test_the_bias_conjunct_holds_when_removing_anonymization_restores_the_swing(self) -> None:
        result = dispatched_hypothesis.evaluate_identity_bias_conjunct(
            {cell["cell_id"]: cell for cell in realistic_table()["cells"]}
        )
        self.assertEqual(result["outcome"], "SUPPORTED")
        self.assertEqual(result["measurement"]["mechanism_max_identity_swing"], 0)
        self.assertGreater(result["marginal_effect_of_anonymization"], 0)

    def test_the_freeze_is_credited_with_nothing_when_removing_it_changes_no_swing(self) -> None:
        result = dispatched_hypothesis.evaluate_identity_bias_conjunct(
            {cell["cell_id"]: cell for cell in realistic_table()["cells"]}
        )
        self.assertEqual(result["marginal_effect_of_the_freeze"], 0)
        self.assertEqual(result["load_bearing_factor"], "anonymization")

    def test_a_null_swing_everywhere_refutes_the_bias_conjunct(self) -> None:
        """If the unblinded reviewer never swings, the blind result proves nothing."""
        result = dispatched_hypothesis.evaluate_identity_bias_conjunct(
            {cell["cell_id"]: cell for cell in cell_table()["cells"]}
        )
        self.assertEqual(result["outcome"], "REFUTED")
        self.assertEqual(result["marginal_effect_of_anonymization"], 0)

    def test_a_swing_inside_the_mechanism_refutes_the_bias_conjunct(self) -> None:
        table = realistic_table()
        for cell in table["cells"]:
            if cell["cell_id"] == "blind|gated|standing-sensitive|probing":
                cell["max_identity_swing"] = 12
        result = dispatched_hypothesis.evaluate_identity_bias_conjunct(
            {cell["cell_id"]: cell for cell in table["cells"]}
        )
        self.assertEqual(result["outcome"], "REFUTED")

    def test_a_rank_inversion_inside_the_mechanism_refutes_the_bias_conjunct(self) -> None:
        """Scores can survive a permutation while the ordering does not."""
        table = realistic_table()
        for cell in table["cells"]:
            if cell["cell_id"] == "blind|gated|neutral|credulous":
                cell["rank_inversions"] = 1
        result = dispatched_hypothesis.evaluate_identity_bias_conjunct(
            {cell["cell_id"]: cell for cell in table["cells"]}
        )
        self.assertEqual(result["outcome"], "REFUTED")

    def test_a_rank_inversion_outside_the_mechanism_does_not_refute_it(self) -> None:
        """An ungated cell is the counterfactual, not the mechanism under test."""
        table = realistic_table()
        for cell in table["cells"]:
            if cell["cell_id"] == "blind|ungated|neutral|credulous":
                cell["rank_inversions"] = 1
        result = dispatched_hypothesis.evaluate_identity_bias_conjunct(
            {cell["cell_id"]: cell for cell in table["cells"]}
        )
        self.assertEqual(result["outcome"], "SUPPORTED")
        self.assertEqual(result["measurement"]["removing_freeze_rank_inversions"], 1)

    def test_the_neutral_and_biased_unblinded_rows_are_both_reported(self) -> None:
        """Without both rows the effect cannot be attributed to the interaction."""
        result = dispatched_hypothesis.evaluate_identity_bias_conjunct(
            {cell["cell_id"]: cell for cell in realistic_table()["cells"]}
        )
        self.assertEqual(result["measurement"]["unblinded_neutral_reviewer_max_swing"], 0)
        self.assertEqual(result["measurement"]["unblinded_biased_reviewer_max_swing"], 49)


class ConjunctBTests(unittest.TestCase):
    def test_the_mechanism_alone_catches_nothing_without_execution(self) -> None:
        """The recurrence test for M8."""
        result = dispatched_hypothesis.evaluate_false_claim_conjunct(
            {cell["cell_id"]: cell for cell in realistic_table()["cells"]}
        )
        self.assertEqual(result["outcome"], "REFUTED")
        self.assertEqual(result["measurement"]["mechanism_with_a_credulous_adjudicator"], "0/4 to 0/4")

    def test_execution_carries_the_whole_catch(self) -> None:
        result = dispatched_hypothesis.evaluate_false_claim_conjunct(
            {cell["cell_id"]: cell for cell in realistic_table()["cells"]}
        )
        self.assertEqual(result["marginal_effect_of_executing_the_control"], 4)
        self.assertEqual(result["marginal_effect_of_the_freeze"], 0)

    def test_anonymization_is_credited_only_with_the_discount_it_prevents(self) -> None:
        result = dispatched_hypothesis.evaluate_false_claim_conjunct(
            {cell["cell_id"]: cell for cell in realistic_table()["cells"]}
        )
        self.assertEqual(result["marginal_effect_of_anonymization"], 1)

    def test_the_catch_conjunct_holds_if_the_mechanism_ever_catches_unaided(self) -> None:
        """The evaluator must be able to return SUPPORTED, or it decides nothing."""
        table = realistic_table()
        for cell in table["cells"]:
            if cell["cell_id"] == "blind|gated|neutral|credulous":
                cell["catch_rate"] = "1/4"
        result = dispatched_hypothesis.evaluate_false_claim_conjunct(
            {cell["cell_id"]: cell for cell in table["cells"]}
        )
        self.assertEqual(result["outcome"], "SUPPORTED")

    def test_one_permutation_is_enough_to_credit_the_mechanism(self) -> None:
        """The bar is deliberately low: the mechanism gets the benefit of any doubt."""
        table = realistic_table()
        for cell in table["cells"]:
            if cell["cell_id"] == "blind|gated|standing-sensitive|credulous":
                cell["catch_rate"] = "1/4"
        result = dispatched_hypothesis.evaluate_false_claim_conjunct(
            {cell["cell_id"]: cell for cell in table["cells"]}
        )
        self.assertEqual(result["outcome"], "SUPPORTED")


class ConjunctionTests(unittest.TestCase):
    def test_one_failed_conjunct_refutes_the_conjunction(self) -> None:
        verdict = dispatched_hypothesis.evaluate(realistic_table())
        self.assertEqual(verdict["outcome"], "REFUTED")
        self.assertEqual(verdict["failed_conjunct_ids"], ["B"])

    def test_both_conjuncts_holding_yields_support(self) -> None:
        table = realistic_table()
        for cell in table["cells"]:
            if cell["cell_id"].endswith("credulous") and cell["cell_id"].startswith("blind|gated"):
                cell["catch_rate"] = "4/4"
        verdict = dispatched_hypothesis.evaluate(table)
        self.assertEqual(verdict["outcome"], "SUPPORTED")
        self.assertEqual(verdict["failed_conjunct_ids"], [])

    def test_both_conjuncts_failing_is_reported_as_both(self) -> None:
        verdict = dispatched_hypothesis.evaluate(cell_table())
        self.assertEqual(verdict["outcome"], "REFUTED")
        self.assertEqual(verdict["failed_conjunct_ids"], ["A", "B"])

    def test_the_verdict_names_the_hypothesis_it_was_dispatched_to_test(self) -> None:
        verdict = dispatched_hypothesis.evaluate(realistic_table())
        self.assertEqual(verdict["hypothesis_id"], "H-PO03-WA-020")
        self.assertIn("reduce producer-identity bias", verdict["statement"])
        self.assertIn("seeded attractive false claim", verdict["statement"])

    def test_the_decision_rule_and_the_falsifier_are_both_recorded(self) -> None:
        """A verdict without a stated falsifier is not a falsifiable test."""
        verdict = dispatched_hypothesis.evaluate(realistic_table())
        self.assertIn("conjunction", verdict["decision_rule_fixed_before_the_run"])
        self.assertIn("credulous", verdict["what_would_have_changed_the_verdict"])


class AgainstTheRealDesignTests(unittest.TestCase):
    """The committed verdict must follow from the committed harness."""

    @classmethod
    def setUpClass(cls) -> None:
        root = repository_root()
        probes = RepositoryProbes(root)
        identities = identity_pool(root)
        pool = build_pool(identities, observed_prior_producer(root))
        cls.experiment = run_experiment(pool, probes, identities)
        cls.verdict = dispatched_hypothesis.evaluate(cls.experiment)

    def test_the_real_design_refutes_the_dispatched_hypothesis_on_conjunct_b(self) -> None:
        self.assertEqual(self.verdict["outcome"], "REFUTED")
        self.assertEqual(self.verdict["failed_conjunct_ids"], ["B"])

    def test_the_real_design_supports_the_bias_conjunct(self) -> None:
        conjunct = self.verdict["conjuncts"][0]
        self.assertEqual(conjunct["conjunct_id"], "A")
        self.assertEqual(conjunct["outcome"], "SUPPORTED")
        self.assertEqual(conjunct["measurement"]["mechanism_max_identity_swing"], 0)
        self.assertGreater(conjunct["measurement"]["removing_anonymization_max_swing"], 0)

    def test_the_real_design_credits_execution_not_the_freeze_for_the_catch(self) -> None:
        conjunct = self.verdict["conjuncts"][1]
        self.assertEqual(conjunct["conjunct_id"], "B")
        self.assertEqual(conjunct["marginal_effect_of_the_freeze"], 0)
        self.assertGreater(conjunct["marginal_effect_of_executing_the_control"], 0)

    def test_the_real_design_shows_the_mechanism_catching_nothing_unaided(self) -> None:
        conjunct = self.verdict["conjuncts"][1]
        low, _, high = conjunct["measurement"]["mechanism_with_a_credulous_adjudicator"].partition(" to ")
        self.assertEqual(low, "0/4")
        self.assertEqual(high, "0/4")


if __name__ == "__main__":
    unittest.main()
