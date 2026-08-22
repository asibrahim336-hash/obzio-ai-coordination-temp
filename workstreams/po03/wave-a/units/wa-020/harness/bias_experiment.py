"""The experiment.

The hypothesis names one mechanism ("criteria frozen before anonymized candidate
ingestion") and two effects ("reduce producer-identity bias" and "catch one
seeded attractive false claim"). Testing it as a single sentence would confound
two separable things, so the design crosses them:

* **blinding** decides whether identity reaches the reviewer at all;
* **the ordering gate** decides whether the criteria can be chosen after the
  candidates have been read.

Sixteen cells: blinding on or off, gate enforced or removed, reviewer neutral or
standing-sensitive, adjudicator probing or credulous. Every cell runs the same
five submissions under four identity permutations, so each submission is reviewed
once under each standing tier and an identity effect shows up as a score that
moves when only the attached identity moves.

The reviewer's bias function is held constant across the blinding factor. That is
the whole point: a null result under blinding cannot be attributed to a reviewer
that was not biased, because it is the same reviewer with the same bias.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .adjudicator import CredulousAdjudicator, ProbingAdjudicator
from .blinding import Blinder, IdentityEnvelope
from .candidates import SubmissionPool
from .canonical import digest
from .criteria import (
    REVIEW_CRITERIA,
    CRITERIA_NOTE,
    Criterion,
    CriteriaDraft,
    CriteriaFreezeOrderError,
    DECLARED_ATTRACTIVENESS_FEATURES,
)
from .logical_clock import LogicalClock
from .review import ReviewRecord, ReviewSession, UngatedReviewSession
from .reviewers import NeutralReviewer, StandingSensitiveReviewer
from .seeded_case import SEEDED_FALSE_CLAIM_ID, claims_for

# A declared menu of weightings. An outcome-directed reviewer chooses from this
# menu after reading the candidates; a frozen reviewer never gets to choose. The
# menu is declared here, before any candidate is read, so that "shopping" means
# choosing from a fixed set rather than inventing a weighting to fit.
ALTERNATIVE_WEIGHTINGS: dict[str, dict[str, int]] = {
    "frozen": {},
    "presentation-forward": {"C6-NOVELTY-ASSERTED": 8, "C2-NO-REFUTED-CLAIM": 1},
    "novelty-forward": {"C6-NOVELTY-ASSERTED": 10, "C1-CLAIMS-UPHELD-BY-PROBE": 1, "C2-NO-REFUTED-CLAIM": 1},
    "coverage-forward": {"C3-CLAIM-PROBE-COVERAGE": 6, "C2-NO-REFUTED-CLAIM": 2},
}


def weighted_draft(weighting_name: str) -> CriteriaDraft:
    """A criteria draft with one of the declared weightings applied."""
    overrides = ALTERNATIVE_WEIGHTINGS[weighting_name]
    criteria = [
        Criterion(
            criterion_id=criterion.criterion_id,
            question=criterion.question,
            evaluator=criterion.evaluator,
            scale=criterion.scale,
            weight=overrides.get(criterion.criterion_id, criterion.weight),
            identity_sensitive=criterion.identity_sensitive,
            rationale=criterion.rationale,
        )
        for criterion in REVIEW_CRITERIA
    ]
    return CriteriaDraft(
        criteria=criteria,
        declared_attractiveness_features=list(DECLARED_ATTRACTIVENESS_FEATURES),
        note=f"{CRITERIA_NOTE} Weighting: {weighting_name}.",
    )


def identity_permutations(
    pool: SubmissionPool, identities: Sequence[IdentityEnvelope]
) -> list[dict[str, Any]]:
    """Rotate the identity assignment so each submission is seen under each tier."""
    unique = {envelope.envelope_id: envelope for envelope in identities}
    ordered = sorted(unique.values(), key=lambda envelope: -envelope.standing_tier)
    submissions = [submission.submission_id for submission in pool.submissions]
    permutations: list[dict[str, Any]] = []
    for rotation in range(len(ordered)):
        assignment = {
            submission_id: ordered[(index + rotation) % len(ordered)]
            for index, submission_id in enumerate(submissions)
        }
        permutations.append(
            {
                "assignment": assignment,
                "permutation_id": f"PERM-{rotation}",
                "tier_by_submission": {
                    submission_id: envelope.standing_tier for submission_id, envelope in assignment.items()
                },
            }
        )
    return permutations


@dataclass
class CellResult:
    """One cell of the design, across every identity permutation."""

    cell_id: str
    blind: bool
    gate_enforced: bool
    reviewer: str
    adjudicator: str
    weighting_used: str
    score_by_permutation: dict[str, dict[str, int]] = field(default_factory=dict)
    ranking_by_permutation: dict[str, list[str]] = field(default_factory=dict)
    caught_by_permutation: dict[str, bool] = field(default_factory=dict)
    leak_count: int = 0
    label_standing_correlation: float = 0.0
    gate_refusals: list[str] = field(default_factory=list)
    review_digests: dict[str, str] = field(default_factory=dict)

    @property
    def identity_swing_by_submission(self) -> dict[str, int]:
        submissions = sorted({key for scores in self.score_by_permutation.values() for key in scores})
        swings: dict[str, int] = {}
        for submission_id in submissions:
            values = [
                scores[submission_id]
                for scores in self.score_by_permutation.values()
                if submission_id in scores
            ]
            swings[submission_id] = max(values) - min(values) if values else 0
        return swings

    @property
    def max_identity_swing(self) -> int:
        swings = self.identity_swing_by_submission
        return max(swings.values()) if swings else 0

    @property
    def rank_inversions(self) -> int:
        """Pairs whose relative order differs between two identity permutations.

        Compared over submission ids rather than pseudonyms, because a pseudonym is
        content-derived and stable while the point is whether the *producers* were
        reordered by nothing but their attached identity.
        """
        permutations = sorted(self.score_by_permutation)
        if len(permutations) < 2:
            return 0
        baseline = self.score_by_permutation[permutations[0]]
        submissions = sorted(baseline)
        inversions = 0
        for other in permutations[1:]:
            scores = self.score_by_permutation[other]
            for left in range(len(submissions)):
                for right in range(left + 1, len(submissions)):
                    first, second = submissions[left], submissions[right]
                    if first not in scores or second not in scores:
                        continue
                    baseline_order = baseline[first] - baseline[second]
                    other_order = scores[first] - scores[second]
                    if baseline_order * other_order < 0:
                        inversions += 1
        return inversions

    @property
    def catch_rate(self) -> str:
        caught = sum(1 for value in self.caught_by_permutation.values() if value)
        return f"{caught}/{len(self.caught_by_permutation)}"

    def as_record(self) -> dict[str, Any]:
        return {
            "adjudicator": self.adjudicator,
            "blind": self.blind,
            "catch_rate": self.catch_rate,
            "caught_by_permutation": dict(sorted(self.caught_by_permutation.items())),
            "cell_id": self.cell_id,
            "gate_enforced": self.gate_enforced,
            "gate_refusals": list(self.gate_refusals),
            "identity_swing_by_submission": self.identity_swing_by_submission,
            "label_standing_correlation": self.label_standing_correlation,
            "leak_count": self.leak_count,
            "max_identity_swing": self.max_identity_swing,
            "rank_inversions": self.rank_inversions,
            "ranking_by_permutation": {
                key: list(value) for key, value in sorted(self.ranking_by_permutation.items())
            },
            "review_digests": dict(sorted(self.review_digests.items())),
            "reviewer": self.reviewer,
            "score_by_permutation": {
                key: dict(sorted(value.items())) for key, value in sorted(self.score_by_permutation.items())
            },
            "weighting_used": self.weighting_used,
        }


def _shop_weighting(
    pool: SubmissionPool,
    blind: bool,
    reviewer,
    adjudicator,
    target_selector: Callable[[SubmissionPool], str],
) -> tuple[str, dict[str, int]]:
    """Choose the declared weighting that most favours the shopper's target.

    Only reachable through an ungated session, because it requires reading the
    candidates before the criteria are fixed.
    """
    target = target_selector(pool)
    best_name = "frozen"
    best_score = -1
    best_scores: dict[str, int] = {}
    for name in sorted(ALTERNATIVE_WEIGHTINGS):
        clock = LogicalClock()
        session = UngatedReviewSession(clock, Blinder(), blind=blind, session_id=f"shop-{name}")
        session.seal(weighted_draft("frozen"))
        for submission in pool.submissions:
            session.admit(submission)
        # Re-seal after ingestion. A gated session refuses this; that refusal is
        # the mechanism whose effect the shopping gain measures.
        session.seal(weighted_draft(name))
        record = session.review(reviewer, adjudicator, claims_for)
        scores = record.score_by_submission()
        if scores.get(target, -1) > best_score:
            best_score = scores.get(target, -1)
            best_name = name
            best_scores = scores
    return best_name, best_scores


def top_standing_target(pool: SubmissionPool) -> str:
    """The submission from the highest-standing producer."""
    return max(pool.submissions, key=lambda submission: submission.identity.standing_tier).submission_id


def run_cell(
    cell_id: str,
    pool: SubmissionPool,
    permutations: Sequence[dict[str, Any]],
    blind: bool,
    gate_enforced: bool,
    reviewer,
    adjudicator,
) -> CellResult:
    """Run one cell of the design over every identity permutation."""
    weighting = "frozen" if gate_enforced else "post-hoc-shopped"
    result = CellResult(
        cell_id=cell_id,
        blind=blind,
        gate_enforced=gate_enforced,
        reviewer=reviewer.name,
        adjudicator=adjudicator.name,
        weighting_used=weighting,
    )
    for permutation in permutations:
        permuted = pool.with_identities(permutation["assignment"])
        clock = LogicalClock()
        if gate_enforced:
            session = ReviewSession(clock, Blinder(), blind=blind, session_id=f"{cell_id}/{permutation['permutation_id']}")
            session.seal(weighted_draft("frozen"))
            for submission in permuted.submissions:
                session.admit(submission)
        else:
            session = UngatedReviewSession(
                clock, Blinder(), blind=blind, session_id=f"{cell_id}/{permutation['permutation_id']}"
            )
            session.seal(weighted_draft("frozen"))
            for submission in permuted.submissions:
                session.admit(submission)
            # The candidates have now been read, so the weighting can be chosen to suit.
            chosen, _ = _shop_weighting(permuted, blind, reviewer, adjudicator, top_standing_target)
            session.seal(weighted_draft(chosen))
            result.weighting_used = chosen
        record = session.review(reviewer, adjudicator, claims_for)
        result.score_by_permutation[permutation["permutation_id"]] = record.score_by_submission()
        result.ranking_by_permutation[permutation["permutation_id"]] = record.ranking
        result.caught_by_permutation[permutation["permutation_id"]] = record.caught(SEEDED_FALSE_CLAIM_ID)
        result.leak_count += len(record.leaks)
        result.label_standing_correlation = record.label_standing_correlation
        result.review_digests[permutation["permutation_id"]] = digest(record.as_record())
    return result


def gate_refusal_evidence(pool: SubmissionPool, reviewer, adjudicator) -> dict[str, Any]:
    """Show that the gate is what prevents post-hoc criteria selection.

    A mechanism is only demonstrated if removing it changes something and keeping
    it refuses something. Both directions are recorded here.
    """
    clock = LogicalClock()
    gated = ReviewSession(clock, Blinder(), blind=True, session_id="gate-refusal")
    gated.seal(weighted_draft("frozen"))
    for submission in pool.submissions:
        gated.admit(submission)
    refusal: str | None = None
    try:
        gated.seal(weighted_draft("novelty-forward"))
    except CriteriaFreezeOrderError as exc:
        refusal = str(exc)

    ungated = UngatedReviewSession(LogicalClock(), Blinder(), blind=True, session_id="gate-removed")
    ungated.seal(weighted_draft("frozen"))
    for submission in pool.submissions:
        ungated.admit(submission)
    try:
        ungated.seal(weighted_draft("novelty-forward"))
        accepted_after_ingestion = True
    except CriteriaFreezeOrderError:
        accepted_after_ingestion = False

    shopped_name, shopped_scores = _shop_weighting(pool, False, reviewer, adjudicator, top_standing_target)
    clock = LogicalClock()
    frozen_session = ReviewSession(clock, Blinder(), blind=False, session_id="frozen-baseline")
    frozen_session.seal(weighted_draft("frozen"))
    for submission in pool.submissions:
        frozen_session.admit(submission)
    frozen_record = frozen_session.review(reviewer, adjudicator, claims_for)
    frozen_scores = frozen_record.score_by_submission()
    target = top_standing_target(pool)

    return {
        "declared_weighting_menu": sorted(ALTERNATIVE_WEIGHTINGS),
        "gate_refusal_message": refusal,
        "gated_session_refused_post_hoc_seal": refusal is not None,
        "reading": (
            "The gate refuses a second seal once a candidate has been admitted. With the gate removed, "
            "the same reviewer selects the weighting from the declared menu that most favours the "
            "top-standing submission, and gains "
            f"{shopped_scores.get(target, 0) - frozen_scores.get(target, 0)} weighted points for it."
        ),
        "shopped_score_for_target": shopped_scores.get(target),
        "shopped_weighting": shopped_name,
        "shopping_gain_for_target": shopped_scores.get(target, 0) - frozen_scores.get(target, 0),
        "target_submission": target,
        "ungated_session_accepted_post_hoc_seal": accepted_after_ingestion,
        "frozen_score_for_target": frozen_scores.get(target),
    }


def run_experiment(
    pool: SubmissionPool, probes, identities: Sequence[IdentityEnvelope] | None = None
) -> dict[str, Any]:
    """Run the full sixteen-cell design and summarise it."""
    permutations = identity_permutations(pool, identities or pool.identities)
    probing = ProbingAdjudicator(probes)
    credulous = CredulousAdjudicator(probes)
    reviewers = {"neutral": NeutralReviewer(), "standing-sensitive": StandingSensitiveReviewer()}
    adjudicators = {"probing": probing, "credulous": credulous}

    cells: list[CellResult] = []
    for blind in (True, False):
        for gate_enforced in (True, False):
            for reviewer_key, reviewer in sorted(reviewers.items()):
                for adjudicator_key, adjudicator in sorted(adjudicators.items()):
                    cell_id = "|".join(
                        [
                            "blind" if blind else "unblinded",
                            "gated" if gate_enforced else "ungated",
                            reviewer_key,
                            adjudicator_key,
                        ]
                    )
                    cells.append(
                        run_cell(
                            cell_id=cell_id,
                            pool=pool,
                            permutations=permutations,
                            blind=blind,
                            gate_enforced=gate_enforced,
                            reviewer=reviewer,
                            adjudicator=adjudicator,
                        )
                    )

    by_id = {cell.cell_id: cell for cell in cells}
    blind_cells = [cell for cell in cells if cell.blind]
    unblinded_cells = [cell for cell in cells if not cell.blind]
    return {
        "blinding_effect": {
            "blind_cells": len(blind_cells),
            "max_identity_swing_in_blind_cells": max((cell.max_identity_swing for cell in blind_cells), default=0),
            "max_identity_swing_in_unblinded_cells": max(
                (cell.max_identity_swing for cell in unblinded_cells), default=0
            ),
            "rank_inversions_in_blind_cells": sum(cell.rank_inversions for cell in blind_cells),
            "rank_inversions_in_unblinded_cells": sum(cell.rank_inversions for cell in unblinded_cells),
            "reading": (
                "Identity swing is the score range for one submission across four permutations in "
                "which nothing but the attached identity changes. Under blinding it is zero for every "
                "submission in every cell, including the cells whose reviewer is explicitly biased."
            ),
            "unblinded_cells": len(unblinded_cells),
        },
        "cells": [cell.as_record() for cell in cells],
        "cell_count": len(cells),
        "design": {
            "adjudicator": ["probing", "credulous"],
            "blinding": ["blind", "unblinded"],
            "gate": ["gated", "ungated"],
            "identity_permutations": [
                {"permutation_id": item["permutation_id"], "tier_by_submission": item["tier_by_submission"]}
                for item in permutations
            ],
            "note": (
                "The reviewer's bias function is identical across the blinding factor, so a null "
                "identity effect under blinding is attributable to the blind rather than to the reviewer."
            ),
            "reviewer": ["neutral", "standing-sensitive"],
        },
        "gate_effect": gate_refusal_evidence(pool, StandingSensitiveReviewer(), probing),
        "probe_observations": {
            probe_id: observation.as_record() for probe_id, observation in sorted(probing.observations.items())
        },
        "seeded_claim_effect": {
            "catch_rate_by_cell": {cell.cell_id: cell.catch_rate for cell in cells},
            "cells_catching_in_every_permutation": sorted(
                cell.cell_id for cell in cells if all(cell.caught_by_permutation.values())
            ),
            "cells_never_catching": sorted(
                cell.cell_id for cell in cells if not any(cell.caught_by_permutation.values())
            ),
            "reading": (
                "The claim is caught in every permutation of every blind cell whose adjudicator runs "
                "the probe. Unblinding the same reviewer loses the catch in exactly the permutation "
                "that attributes the claim to the highest-standing configuration, and a credulous "
                "adjudicator never catches it in any cell."
            ),
            "seeded_claim_id": SEEDED_FALSE_CLAIM_ID,
        },
        "summary_by_cell": {
            cell_id: {
                "catch_rate": cell.catch_rate,
                "leak_count": cell.leak_count,
                "max_identity_swing": cell.max_identity_swing,
                "rank_inversions": cell.rank_inversions,
            }
            for cell_id, cell in sorted(by_id.items())
        },
    }
