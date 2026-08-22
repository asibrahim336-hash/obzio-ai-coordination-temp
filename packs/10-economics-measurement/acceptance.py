"""
Pack 10 - commit-first acceptance, and the honest limit of it.

THE PROBLEM, STATED PLAINLY
---------------------------
Commit-first requires the acceptor to derive the answer independently. For
currentness the acceptor can read the file. For infrastructure it can redo the
arithmetic. For economics it must know WHAT WAS SPENT - and spend is not
observable after the fact by looking harder at the workdir.

If the only record of spend is `cost_events.jsonl`, which the producer wrote,
then any "independent derivation" is just re-reading the producer's file. That
is the anchored configuration wearing a commitment as a hat. This pack refuses
to do that.

TWO PATHS, AND THE PACK MAKES YOU PICK ONE
------------------------------------------
1. BASIS_INDEPENDENT_SOURCE - an independent meter (billing export, metering
   service) that the producer does not write. The acceptor reads the meter,
   derives totals and cost per accepted unit itself, commits, then compares.
   Magnitudes are MACHINE_ENFORCED.

2. No meter - `objective_for(..., meter_path=None)` returns an objective with
   `derivable=False`. `CommitFirstAcceptor.precommit` then raises
   `NoIndependentExpectation` rather than fabricating a commitment. The run
   must go through `AttestedAcceptance`, which stamps
   `acceptance_machine_enforced: false` into the ledger and the return state.
   Arithmetic is still checked by `checks.py`; MAGNITUDES ARE NOT VERIFIED.

Accepted-unit counts come from the meter because the acceptor is the principal
that accepted them - its own count is not the producer's claim.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import _spine
from _spine import (
    BASIS_INDEPENDENT_SOURCE, BASIS_NONE, Objective, read_json,
)

OBJECTIVE_KIND = "cost-per-accepted-unit"

NO_METER_NOTE = (
    "no independent meter was supplied. Spend is not derivable from the "
    "producer's own event log without anchoring to it, so no commitment is "
    "made. Acceptance of MAGNITUDES is BEHAVIOURAL_ONLY; arithmetic and "
    "attribution remain machine-checked by checks.py."
)


def objective_for(campaign_id: str, declared_totals: Dict[str, int],
                  meter_path: Optional[str] = None) -> Objective:
    if meter_path is None:
        return Objective(
            objective_id=f"economics:{campaign_id}",
            kind=OBJECTIVE_KIND,
            declared={"campaign_id": campaign_id,
                      "declared_totals": dict(sorted(declared_totals.items()))},
            derivable=False,
            independence_basis=BASIS_NONE,
            note=NO_METER_NOTE,
        )
    return Objective(
        objective_id=f"economics:{campaign_id}",
        kind=OBJECTIVE_KIND,
        declared={"campaign_id": campaign_id,
                  "declared_totals": dict(sorted(declared_totals.items())),
                  "meter": str(meter_path)},
        derivable=True,
        independence_basis=BASIS_INDEPENDENT_SOURCE,
        note="totals derived from an independent meter the producer does not write",
    )


def derive_expectation(objective: Objective) -> Dict[str, Any]:
    """Derive cost per accepted unit from the METER, never from the producer's
    event log. Reached only when a meter was supplied."""
    meter = read_json(Path(objective.declared["meter"]))
    out: Dict[str, Any] = {"configs": {}, "meter_source": objective.declared["meter"]}
    for cid, m in sorted(meter.get("configs", {}).items()):
        model = int(m["model_micro"])
        harness = int(m["harness_micro"])
        total = model + harness
        accepted = int(m["accepted_units"])
        out["configs"][cid] = {
            "model_micro": model,
            "harness_micro": harness,
            "total_micro": total,
            "units_accepted": accepted,
            "cost_per_accepted_micro": (round(total / accepted, 6)
                                        if accepted else None),
            "harness_amplification": (round(harness / model, 6)
                                      if model else None),
        }
    return out


def compare_to_expectation(expected: Dict[str, Any], workdir: Path) -> bool:
    """One bit. The producer's published economics must equal what the meter
    says, config by config."""
    try:
        r = read_json(Path(workdir) / "economics_report.json")
    except Exception:  # noqa: BLE001
        return False
    published = r.get("configs", {})
    if set(published) != set(expected["configs"]):
        return False
    for cid, want in expected["configs"].items():
        got = published[cid]
        for field in ("model_micro", "harness_micro", "total_micro",
                      "units_accepted", "cost_per_accepted_micro",
                      "harness_amplification"):
            if got.get(field) != want[field]:
                return False
    return True
