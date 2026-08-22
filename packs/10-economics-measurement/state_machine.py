"""
Pack 10 - economics-measurement
Cost per ACCEPTED work unit, with model cost and harness cost held apart.

THE FAILURE THIS PACK IS BUILT AGAINST
--------------------------------------
A weak model inside a strong harness read as a strong model.

The mechanism is almost always the same: someone quotes cost per accepted unit
using MODEL cost, because model cost is the number the vendor puts on an
invoice. The harness cost - the retries, the extra verification passes, the
orchestration tokens, the reviewer's time - is real, is often larger, and is
nobody's line item. A model that needs three attempts per accepted unit looks
cheap exactly in the metric that ignores what those attempts cost.

WHAT IS ENFORCED
----------------
  * every cost event declares a basis, and each basis belongs to exactly one
    of MODEL or HARNESS. An unknown basis is not "other" - it is a refusal
  * the sum of events must reconcile to the declared spend, so cost cannot
    quietly leave the report
  * cost per accepted unit is UNDEFINED when nothing was accepted. It is never
    silently computed over attempts
  * a unit accepted by its own producer is not an accepted unit
  * two configurations whose harness amplification differs materially are
    reported NOT_COMPARABLE on raw cost, and are re-scored against a common
    reference harness before any ranking is offered

All money is integer micro-USD. No floats accumulate.
"""
from __future__ import annotations

import enum
import json
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import _spine
from _spine import (
    AcceptanceGate, AcceptanceOutcome, CheckReport, CommitFirstAcceptor,
    Objective, Phase, Run, sha256_obj, write_json,
)

PACK = "10-economics-measurement"

MICRO = 1_000_000            # micro-USD per USD


class CostClass(str, enum.Enum):
    MODEL = "MODEL"
    HARNESS = "HARNESS"


# A basis is what the money was spent ON. The two sets are disjoint and closed.
# Adding a basis is a deliberate act; it is never inferred at runtime.
MODEL_BASES = {
    "input_tokens", "output_tokens", "reasoning_tokens",
    "cache_read_tokens", "cache_write_tokens",
}
HARNESS_BASES = {
    "orchestration_tokens",   # tokens the scaffold spends, not the work call
    "scaffold_tokens",
    "tool_invocation",
    "retry_overhead",
    "verification_pass",
    "acceptance_review",
    "infra_seconds",
    "human_review_seconds",
}
ALL_BASES = MODEL_BASES | HARNESS_BASES
assert not (MODEL_BASES & HARNESS_BASES), "bases must be disjoint"

#: raw cost/unit comparisons across configs whose amplification differs by
#: more than this factor are refused
AMPLIFICATION_RATIO_THRESHOLD = 1.5


class EconomicsError(Exception):
    pass


class UnattributedCost(EconomicsError):
    pass


class UnreconciledSpend(EconomicsError):
    pass


class SelfAcceptedUnit(EconomicsError):
    pass


class ReportRefused(EconomicsError):
    pass


def classify(basis: str) -> CostClass:
    if basis in MODEL_BASES:
        return CostClass.MODEL
    if basis in HARNESS_BASES:
        return CostClass.HARNESS
    raise UnattributedCost(
        f"basis {basis!r} belongs to neither MODEL nor HARNESS. There is no "
        f"'other' bucket: unattributed cost is how harness cost disappears "
        f"from a report. Known bases: {sorted(ALL_BASES)}")


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class CostEvent:
    event_id: str
    config_id: str
    basis: str
    amount_micro: int
    unit_id: Optional[str] = None
    detail: str = ""

    @property
    def cls(self) -> CostClass:
        return classify(self.basis)

    def to_dict(self):
        return {**asdict(self), "cost_class": self.cls.value}


@dataclass(frozen=True)
class WorkUnit:
    unit_id: str
    config_id: str
    attempts: int
    accepted: bool
    produced_by: str
    accepted_by: Optional[str] = None
    first_pass: bool = False

    def to_dict(self):
        return asdict(self)


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------
@dataclass
class Metrics:
    config_id: str
    status: str = "OK"
    units_attempted: int = 0
    units_accepted: int = 0
    first_pass_accepted: int = 0
    total_attempts: int = 0
    model_micro: int = 0
    harness_micro: int = 0
    total_micro: int = 0
    declared_total_micro: int = 0
    cost_per_accepted_micro: Optional[float] = None
    model_per_accepted_micro: Optional[float] = None
    harness_per_accepted_micro: Optional[float] = None
    harness_amplification: Optional[float] = None   # harness / model
    harness_share: Optional[float] = None           # harness / total
    first_pass_yield: Optional[float] = None
    attempts_per_accepted: Optional[float] = None
    basis_breakdown: Dict[str, int] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class CostLedger:
    def __init__(self, config_id: str, declared_total_micro: int):
        self.config_id = config_id
        self.declared_total_micro = int(declared_total_micro)
        self.events: List[CostEvent] = []
        self.units: List[WorkUnit] = []

    # -- admission: the basis is validated HERE, at the door --------------
    def add_event(self, ev: CostEvent) -> CostEvent:
        if ev.config_id != self.config_id:
            raise EconomicsError(f"event {ev.event_id} is for {ev.config_id!r}")
        if ev.amount_micro < 0:
            raise EconomicsError(f"event {ev.event_id} has negative amount")
        classify(ev.basis)                      # raises UnattributedCost
        self.events.append(ev)
        return ev

    def add_unit(self, u: WorkUnit) -> WorkUnit:
        if u.attempts < 1:
            raise EconomicsError(f"unit {u.unit_id} has {u.attempts} attempts")
        if u.accepted and not u.accepted_by:
            raise EconomicsError(f"unit {u.unit_id} accepted by nobody")
        if u.accepted and u.accepted_by == u.produced_by:
            raise SelfAcceptedUnit(
                f"unit {u.unit_id} was accepted by its own producer "
                f"{u.produced_by!r}; a self-accepted unit is not an accepted unit")
        if u.first_pass and not u.accepted:
            raise EconomicsError(f"unit {u.unit_id} first_pass but not accepted")
        if u.first_pass and u.attempts != 1:
            raise EconomicsError(
                f"unit {u.unit_id} claims first_pass with {u.attempts} attempts")
        self.units.append(u)
        return u

    # -- reconciliation ----------------------------------------------------
    def reconcile(self) -> None:
        total = sum(e.amount_micro for e in self.events)
        if total != self.declared_total_micro:
            gap = self.declared_total_micro - total
            raise UnreconciledSpend(
                f"{self.config_id}: events sum to {total} micro-USD but "
                f"{self.declared_total_micro} was declared; {gap} micro-USD "
                f"({gap / MICRO:.4f} USD) is unaccounted for. Cost that leaves "
                "the report is how a harness stops being visible.")

    # -- the numbers -------------------------------------------------------
    def metrics(self) -> Metrics:
        self.reconcile()
        m = Metrics(config_id=self.config_id,
                    declared_total_micro=self.declared_total_micro)
        for e in self.events:
            if e.cls is CostClass.MODEL:
                m.model_micro += e.amount_micro
            else:
                m.harness_micro += e.amount_micro
            m.basis_breakdown[e.basis] = \
                m.basis_breakdown.get(e.basis, 0) + e.amount_micro
        m.total_micro = m.model_micro + m.harness_micro

        m.units_attempted = len(self.units)
        m.units_accepted = sum(1 for u in self.units if u.accepted)
        m.first_pass_accepted = sum(1 for u in self.units if u.first_pass)
        m.total_attempts = sum(u.attempts for u in self.units)

        if m.units_attempted:
            m.first_pass_yield = round(m.first_pass_accepted / m.units_attempted, 6)

        if m.units_accepted == 0:
            # The single most important refusal in this pack. Dividing by
            # attempts here is how a config that never shipped anything gets a
            # finite, flattering cost per unit.
            m.status = "NO_ACCEPTED_UNITS"
            m.cost_per_accepted_micro = None
            m.model_per_accepted_micro = None
            m.harness_per_accepted_micro = None
            m.attempts_per_accepted = None
        else:
            a = m.units_accepted
            m.cost_per_accepted_micro = round(m.total_micro / a, 6)
            m.model_per_accepted_micro = round(m.model_micro / a, 6)
            m.harness_per_accepted_micro = round(m.harness_micro / a, 6)
            m.attempts_per_accepted = round(m.total_attempts / a, 6)

        if m.model_micro > 0:
            m.harness_amplification = round(m.harness_micro / m.model_micro, 6)
        if m.total_micro > 0:
            m.harness_share = round(m.harness_micro / m.total_micro, 6)
        return m


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------
@dataclass
class Comparison:
    a: str
    b: str
    verdict: str                       # COMPARABLE | NOT_COMPARABLE
    reason: str
    amplification: Dict[str, Optional[float]] = field(default_factory=dict)
    amplification_ratio: Optional[float] = None
    raw_cost_per_accepted: Dict[str, Optional[float]] = field(default_factory=dict)
    model_only_cost_per_accepted: Dict[str, Optional[float]] = field(default_factory=dict)
    model_only_ranking: List[str] = field(default_factory=list)
    raw_ranking: List[str] = field(default_factory=list)
    reference_harness_micro_per_attempt: Optional[float] = None
    normalised_cost_per_accepted: Dict[str, Optional[float]] = field(default_factory=dict)
    normalised_ranking: List[str] = field(default_factory=list)
    model_only_is_misleading: bool = False

    def to_dict(self):
        return asdict(self)


def compare(m1: Metrics, m2: Metrics,
            threshold: float = AMPLIFICATION_RATIO_THRESHOLD) -> Comparison:
    """Rank two configurations, and refuse to do it naively when their harnesses
    are not alike."""
    c = Comparison(a=m1.config_id, b=m2.config_id, verdict="COMPARABLE", reason="")
    c.amplification = {m1.config_id: m1.harness_amplification,
                       m2.config_id: m2.harness_amplification}
    c.raw_cost_per_accepted = {m1.config_id: m1.cost_per_accepted_micro,
                               m2.config_id: m2.cost_per_accepted_micro}
    c.model_only_cost_per_accepted = {m1.config_id: m1.model_per_accepted_micro,
                                      m2.config_id: m2.model_per_accepted_micro}

    if m1.units_accepted == 0 or m2.units_accepted == 0:
        c.verdict = "NOT_COMPARABLE"
        c.reason = ("at least one configuration accepted zero units; cost per "
                    "accepted unit is undefined, not large")
        return c

    def rank(d):
        return [k for k, _ in sorted(d.items(), key=lambda kv: kv[1])]

    c.raw_ranking = rank(c.raw_cost_per_accepted)
    c.model_only_ranking = rank(c.model_only_cost_per_accepted)
    c.model_only_is_misleading = c.model_only_ranking != c.raw_ranking

    a1, a2 = m1.harness_amplification, m2.harness_amplification
    if a1 is None or a2 is None:
        c.verdict = "NOT_COMPARABLE"
        c.reason = "a configuration reported zero model cost; amplification undefined"
    else:
        lo, hi = sorted((max(a1, 1e-9), max(a2, 1e-9)))
        c.amplification_ratio = round(hi / lo, 6)
        if c.amplification_ratio > threshold:
            c.verdict = "NOT_COMPARABLE"
            c.reason = (
                f"harness amplification differs by {c.amplification_ratio}x "
                f"({m1.config_id}={a1}, {m2.config_id}={a2}), above the "
                f"{threshold}x threshold. Raw cost per accepted unit is "
                "measuring two different harnesses, not two models.")
        else:
            c.reason = (f"amplification within {threshold}x "
                        f"({c.amplification_ratio}x); raw comparison stands")

    # -- equal-harness re-scoring -----------------------------------------
    pooled_harness = m1.harness_micro + m2.harness_micro
    pooled_attempts = m1.total_attempts + m2.total_attempts
    if pooled_attempts:
        ref = pooled_harness / pooled_attempts
        c.reference_harness_micro_per_attempt = round(ref, 6)
        for m in (m1, m2):
            norm_total = m.model_micro + ref * m.total_attempts
            c.normalised_cost_per_accepted[m.config_id] = \
                round(norm_total / m.units_accepted, 6)
        c.normalised_ranking = rank(c.normalised_cost_per_accepted)
    return c


# --------------------------------------------------------------------------
# Pack run
# --------------------------------------------------------------------------
class EconomicsMeasurementRun(Run):
    def __init__(self, workdir, producer_id, gate, campaign_id, **kw):
        super().__init__(PACK, workdir, producer_id, gate,
                         mandate={"campaign_id": campaign_id,
                                  "amplification_threshold":
                                      AMPLIFICATION_RATIO_THRESHOLD}, **kw)
        self.campaign_id = campaign_id
        self.ledgers: Dict[str, CostLedger] = {}
        self.metrics: Dict[str, Metrics] = {}
        self.comparisons: List[Comparison] = []
        self.report: Optional[Dict[str, Any]] = None

    def preflight(self, declared: Dict[str, int]):
        for cid, total in declared.items():
            self.ledgers[cid] = CostLedger(cid, total)
        self.advance(Phase.PREFLIGHT, {"configs": sorted(declared),
                                       "declared_micro": declared})

    def recover_state(self):
        prior = self.workdir / "economics_report.json"
        prev = _spine.read_json(prior) if prior.exists() else None
        self.advance(Phase.CURRENT_STATE_RECOVERED,
                     {"prior_report": bool(prev),
                      "prior_status": (prev or {}).get("status")})
        return prev

    def admit(self, events: List[CostEvent], units: List[WorkUnit]) -> None:
        """Admission is where UnattributedCost and SelfAcceptedUnit are raised.
        Nothing that fails here reaches a number."""
        for ev in events:
            self.ledgers[ev.config_id].add_event(ev)
        for u in units:
            self.ledgers[u.config_id].add_unit(u)
        for cid, led in self.ledgers.items():
            led.reconcile()
        ep = self.workdir / "cost_events.jsonl"
        up = self.workdir / "work_units.jsonl"
        with open(ep, "w", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev.to_dict(), sort_keys=True) + "\n")
        with open(up, "w", encoding="utf-8") as fh:
            for u in units:
                fh.write(json.dumps(u.to_dict(), sort_keys=True) + "\n")
        self.advance(Phase.INPUT_ADMITTED,
                     {"events": len(events), "units": len(units),
                      "configs": sorted(self.ledgers)})

    def measure(self) -> Dict[str, Metrics]:
        self.metrics = {cid: led.metrics() for cid, led in self.ledgers.items()}
        ids = sorted(self.metrics)
        self.comparisons = [compare(self.metrics[ids[i]], self.metrics[ids[j]])
                            for i in range(len(ids)) for j in range(i + 1, len(ids))]
        self.advance(Phase.ACTION_EXECUTED,
                     {"configs_measured": ids,
                      "comparisons": len(self.comparisons)})
        return self.metrics

    def publish(self) -> Dict[str, Any]:
        zero = [c for c, m in self.metrics.items() if m.units_accepted == 0]
        self.report = {
            "campaign_id": self.campaign_id,
            "run_id": self.run_id,
            "generated_at": time.time(),
            "currency": "micro_usd",
            "amplification_threshold": AMPLIFICATION_RATIO_THRESHOLD,
            "model_bases": sorted(MODEL_BASES),
            "harness_bases": sorted(HARNESS_BASES),
            "configs": {c: m.to_dict() for c, m in self.metrics.items()},
            "comparisons": [c.to_dict() for c in self.comparisons],
            "configs_with_no_accepted_units": sorted(zero),
            "status": "PUBLISHED_WITH_UNDEFINED_RATIOS" if zero else "PUBLISHED",
        }
        write_json(self.workdir / "economics_report.json", self.report)
        import checks
        missing = checks.missing_artefacts(self.workdir)
        if missing:
            raise FileNotFoundError(f"missing artefacts: {missing}")
        self.advance(Phase.REQUIRED_ARTEFACTS_PRESENT,
                     {"status": self.report["status"],
                      "configs": sorted(self.metrics)})
        return self.report

    def machine_checks(self) -> CheckReport:
        import checks
        rep = checks.run_checks(self.workdir)
        write_json(self.workdir / "checks_report.json", rep.to_dict())
        if not rep.ok:
            raise RuntimeError(f"machine checks failed: {rep.failed}")
        self.advance(Phase.MACHINE_CHECKS_PASSED, {"check_digest": rep.digest()})
        return rep

    def finish(self, acceptor: CommitFirstAcceptor,
               objective: Objective) -> Path:
        """Commit-first acceptance against an INDEPENDENT METER.

        If the objective declares no meter this raises NoIndependentExpectation
        rather than fabricating a commitment - use finish_attested()."""
        acceptor.precommit(self, objective)
        outcome = acceptor.decide(self)
        self.accept_with(outcome)
        p = self.write_return_state({"status": self.report["status"],
                                     "report": "economics_report.json"})
        self.advance(Phase.RETURN_STATE_WRITTEN, {"return_state": p.name})
        self.advance(Phase.COMPLETE, {})
        return p

    def finish_attested(self, attestor, objective: Objective,
                        statement: str) -> Path:
        """For campaigns with no independent meter. Produces NO machine
        guarantee about magnitudes and says so in the artefact:
        `acceptance_machine_enforced: false`."""
        outcome = attestor.attest(self, objective, statement)
        self.accept_with(outcome)
        p = self.write_return_state({
            "status": self.report["status"],
            "report": "economics_report.json",
            "magnitudes_verified": False,
            "magnitude_acceptance": "BEHAVIOURAL_ONLY",
            "why": objective.note})
        self.advance(Phase.RETURN_STATE_WRITTEN, {"return_state": p.name})
        self.advance(Phase.COMPLETE, {})
        return p
