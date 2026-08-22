"""Strategic orchestration: the actual work.

Takes a founder objective with a finite budget and a deadline, decomposes it
into bounded commissions, routes each to a capable operator, then reconciles
what came back against what was commissioned.

The three hard properties this engine must hold, because the checks test them:
  * budget conservation  -- committed effort never exceeds the objective's
  * dependency acyclicity -- a commission graph with a cycle can never start
  * return completeness   -- every commission reconciles exactly once
"""

from dataclasses import dataclass, asdict, field
from typing import List, Dict


class DecompositionError(ValueError):
    pass


@dataclass
class Commission:
    id: str
    title: str
    owner_capability: str      # capability required, not a named person
    budget_units: int
    depends_on: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    max_authority: str = "PROPOSE_ONLY"

    def to_json(self):
        return asdict(self)


@dataclass
class Objective:
    id: str
    statement: str
    budget_units: int
    deadline_iso: str
    non_goals: List[str] = field(default_factory=list)

    def to_json(self):
        return asdict(self)


# Capability routing table. Deliberately explicit: routing by declared
# capability, never by "whoever is free", so a return can be audited against
# the capability that was commissioned.
ROUTING_POLICY = {
    "research":    {"pool": "analyst-pool",   "max_authority": "PROPOSE_ONLY"},
    "build":       {"pool": "engineer-pool",  "max_authority": "WRITE_BRANCH_ONLY"},
    "review":      {"pool": "reviewer-pool",  "max_authority": "VERDICT_ONLY"},
    "synthesis":   {"pool": "strategy-pool",  "max_authority": "PROPOSE_ONLY"},
}


def decompose(objective: Objective, spec: List[dict]) -> List[Commission]:
    """Turn an objective + a decomposition spec into bounded commissions.

    Refuses, rather than truncates, on over-budget: silently shrinking a
    commission to fit is how an orchestrator ships an under-scoped result and
    reports success."""
    commissions = []
    seen = set()
    for row in spec:
        cid = row["id"]
        if cid in seen:
            raise DecompositionError(f"duplicate commission id {cid!r}")
        seen.add(cid)
        cap = row["owner_capability"]
        if cap not in ROUTING_POLICY:
            raise DecompositionError(
                f"commission {cid!r} needs capability {cap!r} which has no route"
            )
        if not row.get("acceptance_criteria"):
            raise DecompositionError(
                f"commission {cid!r} has no acceptance criteria; an unacceptable "
                f"commission cannot be reconciled"
            )
        commissions.append(Commission(
            id=cid,
            title=row["title"],
            owner_capability=cap,
            budget_units=int(row["budget_units"]),
            depends_on=list(row.get("depends_on", [])),
            acceptance_criteria=list(row["acceptance_criteria"]),
            max_authority=ROUTING_POLICY[cap]["max_authority"],
        ))

    total = sum(c.budget_units for c in commissions)
    if total > objective.budget_units:
        raise DecompositionError(
            f"decomposition commits {total} units against an objective budget of "
            f"{objective.budget_units}; refusing to over-commit"
        )

    unknown = {d for c in commissions for d in c.depends_on} - seen
    if unknown:
        raise DecompositionError(f"dependencies on unknown commissions: {sorted(unknown)}")

    _assert_acyclic(commissions)
    return commissions


def _assert_acyclic(commissions: List[Commission]):
    graph = {c.id: list(c.depends_on) for c in commissions}
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {k: WHITE for k in graph}
    stack = []

    def visit(n):
        colour[n] = GREY
        stack.append(n)
        for m in graph[n]:
            if colour[m] == GREY:
                cyc = stack[stack.index(m):] + [m]
                raise DecompositionError(f"dependency cycle: {' -> '.join(cyc)}")
            if colour[m] == WHITE:
                visit(m)
        stack.pop()
        colour[n] = BLACK

    for n in graph:
        if colour[n] == WHITE:
            visit(n)


def topological_order(commissions: List[Commission]) -> List[str]:
    """Deterministic execution order. Ties broken by id so two runs of the
    same decomposition produce byte-identical routing tables."""
    graph = {c.id: set(c.depends_on) for c in commissions}
    out = []
    while graph:
        ready = sorted(k for k, deps in graph.items() if not deps)
        if not ready:
            raise DecompositionError("cycle detected during ordering")
        for k in ready:
            out.append(k)
            del graph[k]
        for deps in graph.values():
            deps.difference_update(ready)
    return out


def route(commissions: List[Commission]) -> dict:
    order = topological_order(commissions)
    waves, placed = [], set()
    remaining = {c.id: set(c.depends_on) for c in commissions}
    while remaining:
        wave = sorted(k for k, d in remaining.items() if d <= placed)
        if not wave:
            raise DecompositionError("unroutable graph")
        waves.append(wave)
        placed.update(wave)
        for k in wave:
            del remaining[k]
    return {
        "objective_order": order,
        "waves": waves,
        "assignments": {
            c.id: {
                "pool": ROUTING_POLICY[c.owner_capability]["pool"],
                "capability": c.owner_capability,
                "max_authority": c.max_authority,
                "budget_units": c.budget_units,
            }
            for c in sorted(commissions, key=lambda x: x.id)
        },
    }


def reconcile(commissions: List[Commission], returns: List[dict]) -> dict:
    """Match returns to commissions. Reports, never repairs."""
    by_id = {c.id: c for c in commissions}
    seen: Dict[str, int] = {}
    for r in returns:
        seen[r["commission_id"]] = seen.get(r["commission_id"], 0) + 1

    missing = sorted(set(by_id) - set(seen))
    orphan = sorted(set(seen) - set(by_id))
    duplicate = sorted(k for k, n in seen.items() if n > 1)

    criteria_gaps = {}
    spent = 0
    for r in returns:
        c = by_id.get(r["commission_id"])
        if not c:
            continue
        spent += int(r.get("units_spent", 0))
        met = set(r.get("criteria_met", []))
        gap = [x for x in c.acceptance_criteria if x not in met]
        if gap:
            criteria_gaps[c.id] = gap

    return {
        "commission_count": len(by_id),
        "return_count": len(returns),
        "missing_returns": missing,
        "orphan_returns": orphan,
        "duplicate_returns": duplicate,
        "unmet_criteria": criteria_gaps,
        "units_committed": sum(c.budget_units for c in commissions),
        "units_spent": spent,
        "reconciled": not (missing or orphan or duplicate or criteria_gaps),
    }
