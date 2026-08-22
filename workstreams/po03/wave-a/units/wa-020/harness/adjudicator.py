"""Deciding whether a candidate claim holds.

Two adjudicators. One runs the control the claim describes and compares the
observed disposition against the claim's own prediction. The other believes the
claim. The second exists because a harness that only ever runs the correct
adjudicator cannot show that running the probe is what catches anything: if the
credulous adjudicator also caught the seeded false claim, the catch would be
coming from somewhere else.

Probe observations are cached per adjudicator instance. The probes are
deterministic reads and subprocess runs against a fixed checkout, so caching does
not change any verdict, and the experiment runs sixteen cells over the same claim
set.
"""

from __future__ import annotations

from typing import Any, Sequence

from .claims import Adjudication, REFUTED, UNVERIFIABLE, UPHELD
from .probes import ProbeObservation, ProbeUnavailable, RepositoryProbes


class ProbingAdjudicator:
    """Adjudicates by executing the repository control the claim describes."""

    name = "ProbingAdjudicator"
    runs_probes = True

    def __init__(self, probes: RepositoryProbes) -> None:
        self.probes = probes
        self._cache: dict[str, ProbeObservation] = {}

    def observe(self, probe_id: str) -> ProbeObservation:
        if probe_id not in self._cache:
            self._cache[probe_id] = self.probes.run(probe_id)
        return self._cache[probe_id]

    @property
    def observations(self) -> dict[str, ProbeObservation]:
        return dict(self._cache)

    def adjudicate(self, claim) -> Adjudication:
        if not claim.probe_id or not claim.predicted_disposition:
            return Adjudication(
                claim_id=claim.claim_id,
                verdict=UNVERIFIABLE,
                probe_id=None,
                predicted_disposition=None,
                observed_disposition=None,
                observation_sha256=None,
                reason="the claim states no prediction an executable probe could contradict",
            )
        try:
            observation = self.observe(claim.probe_id)
        except ProbeUnavailable as exc:
            return Adjudication(
                claim_id=claim.claim_id,
                verdict=UNVERIFIABLE,
                probe_id=claim.probe_id,
                predicted_disposition=claim.predicted_disposition,
                observed_disposition=None,
                observation_sha256=None,
                reason=f"probe unavailable in this runtime: {exc}",
            )
        record = observation.as_record()
        matched = observation.disposition == claim.predicted_disposition
        return Adjudication(
            claim_id=claim.claim_id,
            verdict=UPHELD if matched else REFUTED,
            probe_id=claim.probe_id,
            predicted_disposition=claim.predicted_disposition,
            observed_disposition=observation.disposition,
            observation_sha256=record["observation_sha256"],
            reason=(
                f"{claim.probe_id} reported {observation.disposition}"
                + ("" if matched else f", contradicting the predicted {claim.predicted_disposition}")
                + (f"; control reported: {observation.reported_errors[0]}" if observation.reported_errors else "")
            ),
        )

    def adjudicate_all(self, claims: Sequence[Any]) -> list[Adjudication]:
        return [self.adjudicate(claim) for claim in claims]


class CredulousAdjudicator:
    """Adversarial control: accepts each claim's own prediction as its verdict.

    Runs nothing. This is the reviewer who reads a well-cited, confidently written
    claim and marks it as established, which is the behaviour the frozen criteria
    are meant to make impossible.
    """

    name = "CredulousAdjudicator"
    runs_probes = False

    def __init__(self, probes: RepositoryProbes | None = None) -> None:
        self.probes = probes

    @property
    def observations(self) -> dict[str, ProbeObservation]:
        return {}

    def adjudicate(self, claim) -> Adjudication:
        return Adjudication(
            claim_id=claim.claim_id,
            verdict=UPHELD,
            probe_id=claim.probe_id,
            predicted_disposition=claim.predicted_disposition,
            observed_disposition=claim.predicted_disposition,
            observation_sha256=None,
            reason="accepted as written; no control was executed",
        )

    def adjudicate_all(self, claims: Sequence[Any]) -> list[Adjudication]:
        return [self.adjudicate(claim) for claim in claims]
