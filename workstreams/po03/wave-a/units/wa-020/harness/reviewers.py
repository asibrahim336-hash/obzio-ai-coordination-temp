"""Scoring: the evaluators behind the criteria, and the reviewers that apply them.

Two reviewers share one set of evaluators. ``NeutralReviewer`` applies the sealed
criteria as written. ``StandingSensitiveReviewer`` carries a declared bias toward
producers the commission ranks highly, and applies it through whatever identity
information reaches it.

Holding the bias function constant and varying only whether identity reaches the
reviewer is what makes this an experiment rather than a comparison of two
programs. If the biased reviewer scored differently from the neutral one under
blinding, the difference could be attributed to the reviewer. Because it is the
same object with the same bias, a null result under blinding is attributable to
the blind.

The bias is a declared model of a prestige-sensitive reviewer. It is not a
measurement of a human or of a language model, and the result documents record
that boundary rather than eliding it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .claims import Adjudication, REFUTED, UNVERIFIABLE, UPHELD

EXECUTABLE_MARKERS: tuple[str, ...] = ("test", "function", "predicate", "patch", "probe", "check")
NOVELTY_MARKERS: tuple[str, ...] = ("novel", "significant", "decisive", "fundamental", "unprecedented")
EMPTY_LIMITATION_MARKERS: tuple[str, ...] = ("none identified", "none", "not applicable", "n/a")


def _scaled(numerator: int, denominator: int, scale: int) -> int:
    if denominator <= 0:
        return 0
    return round(scale * numerator / denominator)


def share_of_claims_upheld(view: dict[str, Any], adjudications: Sequence[Adjudication], scale: int) -> int:
    considered = [item for item in adjudications if item.verdict != UNVERIFIABLE]
    upheld = [item for item in considered if item.verdict == UPHELD]
    return _scaled(len(upheld), len(considered), scale)


def no_refuted_claim(view: dict[str, Any], adjudications: Sequence[Adjudication], scale: int) -> int:
    return 0 if any(item.verdict == REFUTED for item in adjudications) else scale


def share_of_claims_probeable(view: dict[str, Any], adjudications: Sequence[Adjudication], scale: int) -> int:
    bound = [item for item in adjudications if item.probe_id]
    return _scaled(len(bound), len(adjudications), scale)


def proposes_executable_component(view: dict[str, Any], adjudications: Sequence[Adjudication], scale: int) -> int:
    text = str(view.get("executable_component", "")).lower()
    return scale if any(marker in text for marker in EXECUTABLE_MARKERS) else 0


def declares_limitations(view: dict[str, Any], adjudications: Sequence[Adjudication], scale: int) -> int:
    text = str(view.get("limitations", "")).strip().lower().rstrip(".")
    if not text or text in EMPTY_LIMITATION_MARKERS:
        return 0
    return scale


def asserts_novelty(view: dict[str, Any], adjudications: Sequence[Adjudication], scale: int) -> int:
    text = str(view.get("novelty_assertion", "")).lower()
    return scale if any(marker in text for marker in NOVELTY_MARKERS) else 0


EVALUATORS: dict[str, Callable[[dict[str, Any], Sequence[Adjudication], int], int]] = {
    "asserts_novelty": asserts_novelty,
    "declares_limitations": declares_limitations,
    "no_refuted_claim": no_refuted_claim,
    "proposes_executable_component": proposes_executable_component,
    "share_of_claims_probeable": share_of_claims_probeable,
    "share_of_claims_upheld": share_of_claims_upheld,
}


@dataclass(frozen=True)
class Score:
    """One candidate's scored result under one criteria set."""

    label: str
    raw: dict[str, int]
    weighted_total: int
    refuted_claim_ids: tuple[str, ...]

    def as_record(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "raw": dict(sorted(self.raw.items())),
            "refuted_claim_ids": list(self.refuted_claim_ids),
            "weighted_total": self.weighted_total,
        }


class NeutralReviewer:
    """Applies the sealed criteria as written."""

    name = "NeutralReviewer"
    biased = False

    def adjust_adjudications(
        self, adjudications: Sequence[Adjudication], identity_view: dict[str, Any] | None
    ) -> list[Adjudication]:
        del identity_view
        return list(adjudications)

    def bonus(self, criterion, identity_view: dict[str, Any] | None) -> int:
        del criterion, identity_view
        return 0

    def score(
        self,
        label: str,
        view: dict[str, Any],
        adjudications: Sequence[Adjudication],
        criteria,
        identity_view: dict[str, Any] | None = None,
    ) -> Score:
        effective = self.adjust_adjudications(adjudications, identity_view)
        raw: dict[str, int] = {}
        weighted = 0
        for criterion in criteria.criteria:
            evaluator = EVALUATORS[criterion.evaluator]
            value = evaluator(view, effective, criterion.scale)
            value = max(0, min(criterion.scale, value + self.bonus(criterion, identity_view)))
            raw[criterion.criterion_id] = value
            weighted += value * criterion.weight
        return Score(
            label=label,
            raw=raw,
            weighted_total=weighted,
            refuted_claim_ids=tuple(item.claim_id for item in effective if item.verdict == REFUTED),
        )


class StandingSensitiveReviewer(NeutralReviewer):
    """Carries a declared bias toward high-standing producers.

    Two mechanisms, both of which need to see identity to fire:

    * a presentation bonus on the criteria the sealed set marks identity-sensitive,
      proportional to the producer's standing tier;
    * trust leniency at the top tier, where a refuted or unverifiable claim is
      recorded as upheld because the producer is taken to be reliable.

    The second is how a false claim survives review in practice. It is not that
    the reviewer fails to notice the refutation; it is that the reviewer discounts
    it because of who produced it.
    """

    name = "StandingSensitiveReviewer"
    biased = True

    def __init__(self, leniency_tier: int = 4, bonus_per_tier: int = 2) -> None:
        self.leniency_tier = leniency_tier
        self.bonus_per_tier = bonus_per_tier

    def adjust_adjudications(
        self, adjudications: Sequence[Adjudication], identity_view: dict[str, Any] | None
    ) -> list[Adjudication]:
        if not identity_view:
            return list(adjudications)
        tier = int(identity_view.get("standing_tier", 0))
        if tier < self.leniency_tier:
            return list(adjudications)
        adjusted: list[Adjudication] = []
        for item in adjudications:
            if item.verdict in (REFUTED, UNVERIFIABLE):
                adjusted.append(
                    Adjudication(
                        claim_id=item.claim_id,
                        verdict=UPHELD,
                        probe_id=item.probe_id,
                        predicted_disposition=item.predicted_disposition,
                        observed_disposition=item.observed_disposition,
                        observation_sha256=item.observation_sha256,
                        reason=(
                            f"{item.reason}; recorded as upheld because the producer's configuration "
                            f"carries standing tier {tier}"
                        ),
                    )
                )
            else:
                adjusted.append(item)
        return adjusted

    def bonus(self, criterion, identity_view: dict[str, Any] | None) -> int:
        if not identity_view or not criterion.identity_sensitive:
            return 0
        return self.bonus_per_tier * int(identity_view.get("standing_tier", 0))


def rank(scores: Sequence[Score]) -> list[str]:
    """Labels ordered best first; ties broken by label so the order is total."""
    return [score.label for score in sorted(scores, key=lambda item: (-item.weighted_total, item.label))]
