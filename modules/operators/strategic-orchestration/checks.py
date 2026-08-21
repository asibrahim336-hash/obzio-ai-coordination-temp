"""Deterministic checks for strategic-orchestration artefacts.

Each check is named, pure, and reads only files. Run order is irrelevant:
no check depends on another having run."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obzio_spine.artefacts import read_json
from obzio_spine.checkkit import CheckReport

REQUIRED_ARTEFACTS = [
    "objective.json",
    "commissions.json",
    "routing_table.json",
    "reconciliation.json",
]


def run_checks(run_dir: str) -> CheckReport:
    r = CheckReport("strategic-orchestration")

    # --- presence -------------------------------------------------------
    missing = [a for a in REQUIRED_ARTEFACTS
               if not os.path.exists(os.path.join(run_dir, a))]
    if missing:
        r.fail("artefacts_present", f"missing artefacts: {missing}", missing=missing)
        return r   # nothing downstream is meaningful

    obj = read_json(os.path.join(run_dir, "objective.json"))
    comms = read_json(os.path.join(run_dir, "commissions.json"))
    routing = read_json(os.path.join(run_dir, "routing_table.json"))
    recon = read_json(os.path.join(run_dir, "reconciliation.json"))

    # --- CHK-SO-01 budget conservation ----------------------------------
    committed = sum(int(c["budget_units"]) for c in comms)
    if committed > int(obj["budget_units"]):
        r.fail("CHK-SO-01_budget_conservation",
               f"commissions commit {committed} units against objective budget "
               f"{obj['budget_units']}",
               committed=committed, budget=obj["budget_units"])

    # --- CHK-SO-02 every commission is boundable ------------------------
    for c in comms:
        if not c.get("acceptance_criteria"):
            r.fail("CHK-SO-02_bounded_commission",
                   f"commission {c['id']} has no acceptance criteria", commission=c["id"])
        if not c.get("max_authority"):
            r.fail("CHK-SO-02_bounded_commission",
                   f"commission {c['id']} has no authority ceiling", commission=c["id"])

    # --- CHK-SO-03 authority never exceeds the orchestrator's own -------
    # An orchestrator holding PROPOSE_ONLY cannot mint WRITE authority.
    ceiling = obj.get("orchestrator_max_authority", "PROPOSE_ONLY")
    LADDER = ["VERDICT_ONLY", "PROPOSE_ONLY", "WRITE_BRANCH_ONLY", "WRITE_MAIN"]
    for c in comms:
        ma = c.get("max_authority")
        if ma in LADDER and ceiling in LADDER and LADDER.index(ma) > LADDER.index(ceiling):
            r.fail("CHK-SO-03_authority_not_escalated",
                   f"commission {c['id']} delegates {ma} but orchestrator ceiling "
                   f"is {ceiling}", commission=c["id"], delegated=ma, ceiling=ceiling)

    # --- CHK-SO-04 routing covers exactly the commission set ------------
    cids = {c["id"] for c in comms}
    assigned = set(routing.get("assignments", {}))
    if cids != assigned:
        r.fail("CHK-SO-04_routing_total",
               f"routing covers {sorted(assigned)} but commissions are {sorted(cids)}",
               unrouted=sorted(cids - assigned), phantom=sorted(assigned - cids))

    # --- CHK-SO-05 wave order respects dependencies ---------------------
    waves = routing.get("waves", [])
    pos = {cid: i for i, w in enumerate(waves) for cid in w}
    for c in comms:
        for dep in c.get("depends_on", []):
            if dep in pos and c["id"] in pos and pos[dep] >= pos[c["id"]]:
                r.fail("CHK-SO-05_dependency_order",
                       f"{c['id']} (wave {pos[c['id']]}) runs at or before its "
                       f"dependency {dep} (wave {pos[dep]})",
                       commission=c["id"], dependency=dep)

    # --- CHK-SO-06 reconciliation is total ------------------------------
    for field in ("missing_returns", "orphan_returns", "duplicate_returns"):
        if recon.get(field):
            r.fail("CHK-SO-06_reconciliation_total",
                   f"{field}: {recon[field]}", field=field, values=recon[field])
    if recon.get("unmet_criteria"):
        r.fail("CHK-SO-06_reconciliation_total",
               f"commissions returned with unmet acceptance criteria: "
               f"{sorted(recon['unmet_criteria'])}",
               unmet=recon["unmet_criteria"])

    # --- CHK-SO-07 spend within commitment ------------------------------
    if int(recon.get("units_spent", 0)) > int(recon.get("units_committed", 0)):
        r.fail("CHK-SO-07_spend_within_commitment",
               f"spent {recon['units_spent']} against committed "
               f"{recon['units_committed']}")

    # --- CHK-SO-08 non-goals not silently commissioned (WARN) -----------
    for ng in obj.get("non_goals", []):
        for c in comms:
            if ng.lower() in c["title"].lower():
                r.warn("CHK-SO-08_non_goal_drift",
                       f"commission {c['id']} title touches declared non-goal {ng!r}",
                       commission=c["id"], non_goal=ng)
    return r


if __name__ == "__main__":
    rep = run_checks(sys.argv[1])
    print(rep.summary())
    for f in rep.findings:
        print(f"  [{f.severity}] {f.check}: {f.message}")
    sys.exit(0 if rep.passed else 1)
