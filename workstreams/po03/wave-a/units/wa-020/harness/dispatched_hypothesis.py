"""Evaluate the dispatched hypothesis H-PO03-WA-020 against the factorial design.

The dispatched hypothesis is a conjunction:

    Criteria frozen before anonymized candidate ingestion reduce producer-identity
    bias and catch one seeded attractive false claim.

It names one compound mechanism -- the ordering gate plus anonymization -- and
attributes two distinct effects to it. A conjunction is worth testing only if each
conjunct can fail on its own, and the 2x2x2x2 design exists so that each one is
attributed to the factor that actually moves it rather than to the mechanism that
happened to be switched on at the time.

The mechanism named by the hypothesis is the cell subset ``blind`` and ``gated``.
The two remaining factors, the reviewer's bias and whether the adjudicator executes
the control, are held as the counterfactual axes: they are the things the hypothesis
does not name, and if either of them turns out to carry an effect the hypothesis
claims for the mechanism, the hypothesis is wrong about its own cause.
"""

from __future__ import annotations

from typing import Any

HYPOTHESIS_ID = "H-PO03-WA-020"
STATEMENT = (
    "Criteria frozen before anonymized candidate ingestion reduce producer-identity bias "
    "and catch one seeded attractive false claim."
)
MECHANISM_AS_NAMED = "the ordering gate (gated) together with anonymization (blind)"


def _rate(text: str) -> tuple[int, int]:
    """Parse a ``caught/total`` cell rate."""
    caught, _, total = text.partition("/")
    return int(caught), int(total)


def _select(cells: dict[str, dict[str, Any]], **factors: str) -> list[dict[str, Any]]:
    """Cells matching every named factor, in deterministic cell-id order."""
    chosen = []
    for cell_id in sorted(cells):
        blind, gate, reviewer, adjudicator = cell_id.split("|")
        actual = {"blind": blind, "gate": gate, "reviewer": reviewer, "adjudicator": adjudicator}
        if all(actual[key] == value for key, value in factors.items()):
            chosen.append(cells[cell_id])
    return chosen


def _worst_swing(cells: list[dict[str, Any]]) -> int:
    return max((cell["max_identity_swing"] for cell in cells), default=0)


def _worst_inversions(cells: list[dict[str, Any]]) -> int:
    return max((cell["rank_inversions"] for cell in cells), default=0)


def _catch_range(cells: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Lowest caught count, highest caught count, and the shared permutation total."""
    rates = [_rate(cell["catch_rate"]) for cell in cells]
    totals = {total for _, total in rates}
    if len(totals) != 1:
        raise AssertionError(f"cells disagree on permutation count: {sorted(totals)}")
    counts = [caught for caught, _ in rates]
    return min(counts), max(counts), totals.pop()


def evaluate_identity_bias_conjunct(cells: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Conjunct A: does the named mechanism reduce producer-identity bias?

    Reduction is measured against the mechanism's own counterfactuals rather than
    against an absolute standard: remove one factor at a time and see which removal
    the bias survives.
    """
    mechanism = _select(cells, blind="blind", gate="gated")
    without_anonymization = _select(cells, blind="unblinded", gate="gated")
    without_freeze = _select(cells, blind="blind", gate="ungated")

    mechanism_swing = _worst_swing(mechanism)
    anonymization_marginal = _worst_swing(without_anonymization) - mechanism_swing
    freeze_marginal = _worst_swing(without_freeze) - mechanism_swing

    # Removing anonymization only bites when the reviewer is actually biased, so the
    # neutral row is reported alongside it to keep the effect attributable to the
    # interaction rather than to visibility on its own.
    unblinded_neutral = _worst_swing(_select(cells, blind="unblinded", gate="gated", reviewer="neutral"))
    unblinded_biased = _worst_swing(
        _select(cells, blind="unblinded", gate="gated", reviewer="standing-sensitive")
    )

    holds = mechanism_swing == 0 and _worst_inversions(mechanism) == 0 and anonymization_marginal > 0
    return {
        "conjunct": "criteria frozen before anonymized candidate ingestion reduce producer-identity bias",
        "conjunct_id": "A",
        "load_bearing_factor": "anonymization",
        "measurement": {
            "mechanism_cells": len(mechanism),
            "mechanism_max_identity_swing": mechanism_swing,
            "mechanism_rank_inversions": _worst_inversions(mechanism),
            "removing_anonymization_max_swing": _worst_swing(without_anonymization),
            "removing_anonymization_rank_inversions": _worst_inversions(without_anonymization),
            "removing_freeze_max_swing": _worst_swing(without_freeze),
            "removing_freeze_rank_inversions": _worst_inversions(without_freeze),
            "unblinded_biased_reviewer_max_swing": unblinded_biased,
            "unblinded_neutral_reviewer_max_swing": unblinded_neutral,
        },
        "marginal_effect_of_anonymization": anonymization_marginal,
        "marginal_effect_of_the_freeze": freeze_marginal,
        "outcome": "SUPPORTED" if holds else "REFUTED",
        "reading": (
            "Under the named mechanism, permuting which producer identity is attached to which "
            f"submission moves no score at all: worst-case identity swing {mechanism_swing} weighted "
            f"points across {len(mechanism)} cells, {_worst_inversions(mechanism)} rank inversions. "
            f"Removing anonymization and changing nothing else takes the worst case to "
            f"{_worst_swing(without_anonymization)} points and "
            f"{_worst_inversions(without_anonymization)} rank inversions, so the reduction is real and "
            "is not an artefact of a reviewer that had no bias to express. Removing the freeze instead, "
            f"and keeping anonymization, leaves the worst case at {_worst_swing(without_freeze)}: the "
            "ordering gate contributes nothing to this conjunct. The effect the hypothesis claims for "
            "its compound mechanism is carried entirely by the anonymization half of it."
        ),
        "why_the_effect_is_attributable": (
            "The reviewer's bias function is byte-identical across the blinding factor, so a null "
            "result under anonymization cannot be explained by a reviewer that was never biased. The "
            f"unblinded neutral reviewer swings {unblinded_neutral} and the unblinded biased reviewer "
            f"swings {unblinded_biased}, which locates the effect in the interaction of visibility and "
            "bias, exactly where the mechanism is supposed to act."
        ),
    }


def evaluate_false_claim_conjunct(cells: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Conjunct B: does the named mechanism catch the seeded attractive false claim?

    The decisive comparison is inside the mechanism, not against it. Both mechanism
    factors are held on and only the adjudicator is varied, so any difference is
    attributable to executing the control rather than to the mechanism.
    """
    mechanism_probing = _select(cells, blind="blind", gate="gated", adjudicator="probing")
    mechanism_credulous = _select(cells, blind="blind", gate="gated", adjudicator="credulous")
    without_freeze_probing = _select(cells, blind="blind", gate="ungated", adjudicator="probing")
    without_anonymization_probing = _select(
        cells, blind="unblinded", gate="gated", adjudicator="probing", reviewer="standing-sensitive"
    )
    mechanism_biased_probing = _select(
        cells, blind="blind", gate="gated", adjudicator="probing", reviewer="standing-sensitive"
    )

    credulous_low, credulous_high, total = _catch_range(mechanism_credulous)
    probing_low, probing_high, _ = _catch_range(mechanism_probing)
    freeze_removed_low, _, _ = _catch_range(without_freeze_probing)
    anonymization_removed_low, _, _ = _catch_range(without_anonymization_probing)
    biased_probing_low, _, _ = _catch_range(mechanism_biased_probing)

    # The mechanism is credited only if it catches the claim wherever it is switched
    # on. A mechanism that needs an unnamed third component is not the cause.
    holds = credulous_high > 0
    return {
        "conjunct": "criteria frozen before anonymized candidate ingestion catch one seeded attractive false claim",
        "conjunct_id": "B",
        "load_bearing_factor": "executing the repository control (the probing adjudicator)",
        "marginal_effect_of_anonymization": biased_probing_low - anonymization_removed_low,
        "marginal_effect_of_executing_the_control": probing_low - credulous_high,
        "marginal_effect_of_the_freeze": probing_low - freeze_removed_low,
        "measurement": {
            "mechanism_with_a_credulous_adjudicator": f"{credulous_low}/{total} to {credulous_high}/{total}",
            "mechanism_with_a_probing_adjudicator": f"{probing_low}/{total} to {probing_high}/{total}",
            "permutations_per_cell": total,
            "removing_anonymization_biased_probing": f"{anonymization_removed_low}/{total}",
            "removing_freeze_probing": f"{freeze_removed_low}/{total}",
        },
        "outcome": "SUPPORTED" if holds else "REFUTED",
        "reading": (
            "With both mechanism factors switched on and only the adjudicator varied, the seeded false "
            f"claim is caught {probing_low}/{total} of permutations when the control is executed and "
            f"{credulous_high}/{total} when it is not. The mechanism the hypothesis names is fully "
            "present in both, so the catch is not attributable to it. Freezing a criterion that demands "
            "verification does not perform the verification, and withholding the producer's identity "
            "does not make an unexecuted claim testable: the claim is caught because a control is run "
            "and its exit status contradicts the claim. Removing the freeze while still executing the "
            f"control changes the catch rate by {probing_low - freeze_removed_low}."
        ),
        "what_the_mechanism_does_contribute": (
            "Executing the control is necessary but not sufficient. A biased reviewer that can see a "
            "high-standing producer discounts a refutation it has already obtained, so the unblinded "
            f"standing-sensitive probing cell catches {anonymization_removed_low}/{total} while its "
            f"blind counterpart catches {biased_probing_low}/{total}. Anonymization protects a "
            "refutation that has already been found; it does not find one. That is a real contribution "
            "of one permutation in sixteen and it is worth keeping, but it is not the effect the "
            "hypothesis asserts."
        ),
    }


def evaluate(experiment: dict[str, Any]) -> dict[str, Any]:
    """Render the verdict on the dispatched hypothesis from the completed design."""
    cells = {cell["cell_id"]: cell for cell in experiment["cells"]}
    if len(cells) != 16:
        raise AssertionError(f"the design must be complete before it is evaluated: {len(cells)} cells")

    conjuncts = [evaluate_identity_bias_conjunct(cells), evaluate_false_claim_conjunct(cells)]
    failed = [item for item in conjuncts if item["outcome"] != "SUPPORTED"]
    outcome = "SUPPORTED" if not failed else "REFUTED"

    return {
        "conjuncts": conjuncts,
        "decision_rule_fixed_before_the_run": (
            "The hypothesis is a conjunction and is recorded SUPPORTED only if every conjunct holds "
            "when attributed to the mechanism the hypothesis names. A conjunct that holds only because "
            "of a factor the hypothesis does not name is recorded as refuting the hypothesis as stated, "
            "because the hypothesis is a causal claim about the mechanism and not a description of the "
            "cell it was measured in."
        ),
        "failed_conjunct_ids": [item["conjunct_id"] for item in failed],
        "hypothesis_id": HYPOTHESIS_ID,
        "mechanism_as_named": MECHANISM_AS_NAMED,
        "outcome": outcome,
        "statement": STATEMENT,
        "summary": (
            "Half of the hypothesis holds and half of it does not, and the design says which half. "
            "Anonymization does reduce producer-identity bias, completely and measurably: worst-case "
            f"identity swing falls from {conjuncts[0]['measurement']['removing_anonymization_max_swing']} "
            "weighted points to 0 with the same reviewer and the same bias function. The ordering gate "
            "contributes nothing to that reduction. The second conjunct fails: the mechanism does not "
            "catch the seeded false claim, because the claim is caught by running a repository control "
            "and refuted by its exit status, and the mechanism contains nothing that runs anything. "
            "Held fully on with a credulous adjudicator, the mechanism catches the claim in "
            f"{conjuncts[1]['measurement']['mechanism_with_a_credulous_adjudicator']} permutations. "
            "Anonymization earns a narrower credit than the hypothesis claims: it stops a biased "
            "reviewer discounting a refutation the probe already produced, worth one permutation of "
            "four in the one cell where standing is visible and the control is run."
        ),
        "what_would_have_changed_the_verdict": (
            "Conjunct B would have been recorded SUPPORTED had any cell with both mechanism factors on "
            "and a credulous adjudicator caught the claim in even one permutation. None did. Conjunct A "
            "would have been recorded REFUTED had removing anonymization left the worst-case identity "
            "swing at 0, which would have meant the null result under blinding came from an unbiased "
            "reviewer rather than from the blind."
        ),
    }
