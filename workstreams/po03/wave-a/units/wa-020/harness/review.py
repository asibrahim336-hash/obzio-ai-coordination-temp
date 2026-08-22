"""The blind review session and its ordering gate.

A session has three obligations and refuses to proceed without any of them:

1. criteria are sealed before the first candidate is admitted, checked as a
   comparison of recorded ticks rather than trusted;
2. the seal still matches the criteria at scoring time, so criteria cannot be
   edited between ingestion and scoring;
3. under blinding, the bytes handed to the scorer are scanned for every token of
   the identity they are supposed to withhold, and a surviving token stops the
   session rather than being reported afterwards.

``UngatedReviewSession`` removes the first obligation and nothing else. It exists
so the experiment can run the post-hoc-criteria arm at all: if the gate worked
only in the sense that no code happened to violate it, its effect would be
unmeasurable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .blinding import (
    BlindedCandidate,
    Blinder,
    IdentityEnvelope,
    find_leaks,
    label_standing_correlation,
    pool_vocabulary,
)
from .canonical import digest
from .claims import Adjudication, REFUTED
from .criteria import CriteriaFreezeOrderError, SealedCriteria
from .reviewers import Score, rank

OPEN = "OPEN"
CRITERIA_SEALED = "CRITERIA_SEALED"
CANDIDATES_ADMITTED = "CANDIDATES_ADMITTED"
REVIEWED = "REVIEWED"


class CriteriaNotSealed(Exception):
    """A candidate was offered before the criteria were sealed."""


class SessionStateError(Exception):
    """An operation was attempted from a state that does not allow it."""


@dataclass
class Admission:
    submission_id: str
    admitted_at_tick: int
    submission: Any

    def as_record(self) -> dict[str, Any]:
        return {"admitted_at_tick": self.admitted_at_tick, "submission_id": self.submission_id}


@dataclass
class ReviewRecord:
    """Everything a reviewer decided, and the evidence that the gates held."""

    session_id: str
    blind: bool
    reviewer: str
    adjudicator: str
    blinder: str
    criteria_seal_sha256: str
    sealed_at_tick: int
    first_admission_tick: int
    scores: list[Score]
    ranking: list[str]
    adjudications: dict[str, list[Adjudication]]
    effective_adjudications: dict[str, list[Adjudication]]
    leaks: list[dict[str, Any]]
    label_standing_correlation: float
    pseudonym_by_submission: dict[str, str]

    def score_by_submission(self) -> dict[str, int]:
        mapping = {}
        for submission_id, pseudonym in self.pseudonym_by_submission.items():
            for score in self.scores:
                if score.label == pseudonym:
                    mapping[submission_id] = score.weighted_total
        return mapping

    def refuted_claim_ids(self) -> set[str]:
        found: set[str] = set()
        for items in self.effective_adjudications.values():
            found.update(item.claim_id for item in items if item.verdict == REFUTED)
        return found

    def caught(self, seeded_claim_id: str, gate_criterion_id: str = "C2-NO-REFUTED-CLAIM") -> bool:
        """Was the seeded false claim both refuted and penalised by the frozen gate?

        Refutation alone is not a catch. A review that records a refutation and
        still scores the candidate as if nothing were wrong has not caught
        anything, so the definition requires the gate criterion to have fired.
        """
        if seeded_claim_id not in self.refuted_claim_ids():
            return False
        carriers = [
            self.pseudonym_by_submission[submission_id]
            for submission_id, items in self.effective_adjudications.items()
            if any(item.claim_id == seeded_claim_id and item.verdict == REFUTED for item in items)
        ]
        for score in self.scores:
            if score.label in carriers and score.raw.get(gate_criterion_id, 0) != 0:
                return False
        return bool(carriers)

    def as_record(self) -> dict[str, Any]:
        return {
            "adjudicator": self.adjudicator,
            "adjudications": {
                submission_id: [item.as_record() for item in items]
                for submission_id, items in sorted(self.adjudications.items())
            },
            "blind": self.blind,
            "blinder": self.blinder,
            "criteria_seal_sha256": self.criteria_seal_sha256,
            "effective_adjudications": {
                submission_id: [item.as_record() for item in items]
                for submission_id, items in sorted(self.effective_adjudications.items())
            },
            "first_admission_tick": self.first_admission_tick,
            "label_standing_correlation": self.label_standing_correlation,
            "leak_count": len(self.leaks),
            "leaks": self.leaks,
            "pseudonym_by_submission": dict(sorted(self.pseudonym_by_submission.items())),
            "ranking": list(self.ranking),
            "reviewer": self.reviewer,
            "scores": [score.as_record() for score in self.scores],
            "sealed_at_tick": self.sealed_at_tick,
            "sealed_before_first_admission": self.sealed_at_tick < self.first_admission_tick,
            "session_id": self.session_id,
        }


class ReviewSession:
    """A gated review session."""

    gate_enforced = True

    def __init__(self, clock, blinder: Blinder | None = None, blind: bool = True, session_id: str = "session") -> None:
        self.clock = clock
        self.blinder = blinder or Blinder()
        self.blind = blind
        self.session_id = session_id
        self.state = OPEN
        self.criteria: SealedCriteria | None = None
        self.admissions: list[Admission] = []

    # -- gates ------------------------------------------------------------

    def seal(self, draft) -> SealedCriteria:
        if self.admissions and self.gate_enforced:
            raise CriteriaFreezeOrderError(
                f"{len(self.admissions)} candidate(s) were admitted before sealing; "
                "criteria frozen after ingestion cannot be producer-neutral"
            )
        if self.state == REVIEWED:
            raise SessionStateError("cannot seal criteria after the review has been recorded")
        self.criteria = draft.seal(self.clock)
        self.state = CRITERIA_SEALED
        return self.criteria

    def admit(self, submission) -> Admission:
        if self.criteria is None:
            raise CriteriaNotSealed(
                f"{submission.submission_id} was offered before any criteria were sealed"
            )
        if self.state == REVIEWED:
            raise SessionStateError("cannot admit a candidate after the review has been recorded")
        admission = Admission(
            submission_id=submission.submission_id,
            admitted_at_tick=self.clock.tick(),
            submission=submission,
        )
        self.admissions.append(admission)
        self.state = CANDIDATES_ADMITTED
        return admission

    # -- review -----------------------------------------------------------

    def _views(self) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any] | None], dict[str, str], list[dict[str, Any]], float]:
        identities = [admission.submission.identity for admission in self.admissions]
        vocabulary = pool_vocabulary(identities)
        views: dict[str, dict[str, Any]] = {}
        identity_views: dict[str, dict[str, Any] | None] = {}
        pseudonyms: dict[str, str] = {}
        leaks: list[dict[str, Any]] = []
        blinded_order: list[tuple[str, BlindedCandidate, IdentityEnvelope]] = []

        for index, admission in enumerate(self.admissions):
            submission = admission.submission
            if self.blind:
                blinded = self.blinder.blind(submission, admission.admitted_at_tick, index, vocabulary)
                found = find_leaks(blinded.rendered(), submission.identity)
                leaks.extend(found)
                views[submission.submission_id] = blinded.payload
                identity_views[submission.submission_id] = None
                pseudonyms[submission.submission_id] = blinded.pseudonym
                blinded_order.append((submission.submission_id, blinded, submission.identity))
            else:
                views[submission.submission_id] = submission.unblinded_content()
                identity_views[submission.submission_id] = submission.identity.as_record()
                pseudonyms[submission.submission_id] = submission.submission_id

        if self.blind and blinded_order:
            correlation = label_standing_correlation(
                [item[1].pseudonym for item in blinded_order],
                [item[2].standing_tier for item in blinded_order],
            )
        else:
            correlation = 1.0 if not self.blind else 0.0
        return views, identity_views, pseudonyms, leaks, correlation

    def review(self, reviewer, adjudicator, claims_for) -> ReviewRecord:
        if self.criteria is None:
            raise CriteriaNotSealed("cannot review before criteria are sealed")
        if not self.admissions:
            raise SessionStateError("cannot review with no admitted candidates")
        self.criteria.verify()
        first_admission = min(admission.admitted_at_tick for admission in self.admissions)
        if self.gate_enforced and self.criteria.sealed_at_tick >= first_admission:
            raise CriteriaFreezeOrderError(
                f"criteria sealed at tick {self.criteria.sealed_at_tick} but the first candidate "
                f"arrived at tick {first_admission}"
            )

        views, identity_views, pseudonyms, leaks, correlation = self._views()
        if self.blind and leaks:
            from .blinding import IdentityLeak

            raise IdentityLeak(
                f"{len(leaks)} identity token(s) survived blinding: "
                + ", ".join(sorted({leak['token'] for leak in leaks}))
            )

        adjudications: dict[str, list[Adjudication]] = {}
        effective: dict[str, list[Adjudication]] = {}
        scores: list[Score] = []
        for admission in self.admissions:
            submission_id = admission.submission_id
            claims = claims_for(submission_id)
            decided = adjudicator.adjudicate_all(claims)
            adjudications[submission_id] = decided
            identity_view = identity_views[submission_id]
            effective[submission_id] = reviewer.adjust_adjudications(decided, identity_view)
            scores.append(
                reviewer.score(
                    label=pseudonyms[submission_id],
                    view=views[submission_id],
                    adjudications=decided,
                    criteria=self.criteria,
                    identity_view=identity_view,
                )
            )

        self.state = REVIEWED
        return ReviewRecord(
            session_id=self.session_id,
            blind=self.blind,
            reviewer=reviewer.name,
            adjudicator=adjudicator.name,
            blinder=self.blinder.name if self.blind else "none",
            criteria_seal_sha256=self.criteria.seal_sha256,
            sealed_at_tick=self.criteria.sealed_at_tick,
            first_admission_tick=first_admission,
            scores=scores,
            ranking=rank(scores),
            adjudications=adjudications,
            effective_adjudications=effective,
            leaks=leaks,
            label_standing_correlation=correlation,
            pseudonym_by_submission=pseudonyms,
        )


class UngatedReviewSession(ReviewSession):
    """Adversarial control: the same session with the ordering gate removed.

    Criteria can be sealed after the candidates have been read, which is what
    "criteria shopping" needs in order to happen at all. Everything else is
    identical, so any difference in outcome is attributable to the ordering.
    """

    gate_enforced = False


def review_digest(record: ReviewRecord) -> str:
    return digest(record.as_record())


def ordering_evidence(records: Sequence[ReviewRecord]) -> dict[str, Any]:
    """Summarise the ordering property across every gated session that ran."""
    gated = [record for record in records if record.sealed_at_tick < record.first_admission_tick]
    return {
        "sessions": len(records),
        "sessions_sealed_before_first_admission": len(gated),
        "ticks": [
            {
                "first_admission_tick": record.first_admission_tick,
                "sealed_at_tick": record.sealed_at_tick,
                "session_id": record.session_id,
            }
            for record in records
        ],
    }
