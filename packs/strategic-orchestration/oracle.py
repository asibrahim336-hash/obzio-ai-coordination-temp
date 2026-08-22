"""Independent acceptance oracle for strategic-orchestration.

This module DELIBERATELY DOES NOT IMPORT engine.py.

That restriction is the entire point. If the acceptor derived its expectation
by calling the producer's own decomposition code, the two would be the same
function and would agree on the same wrong answer -- a shared blind spot
dressed up as verification. Everything here is recomputed from the declared
inputs with plain set and integer arithmetic.

An automated guard (`test_oracle_does_not_import_engine`) asserts the absence
of that import, so the independence claim degrades loudly if someone
"simplifies" this file later.
"""

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obzio_spine.expectation import Expectation, Derivation, canonical_digest

COVERS = ("commission_ids", "total_budget_committed", "budget_within_objective",
          "missing_returns", "orphan_returns", "duplicate_returns",
          "unmet_criteria_commissions", "reconciled", "wave_count")

UNCOVERED = (
    "whether the decomposition is a GOOD decomposition",
    "whether each commission is scoped sensibly",
    "whether the capability routing chose the right pool",
    "whether the returns are truthful about work actually done",
)


def inputs_digest(objective_doc, spec, returns) -> str:
    """Binds the commitment to exactly these declared inputs."""
    return canonical_digest({"objective": objective_doc, "spec": spec,
                             "returns": returns})


def _independent_wave_count(spec):
    """Kahn layering, written independently of engine.topological_order."""
    pending = {r["id"]: set(r.get("depends_on", [])) for r in spec}
    placed, waves = set(), 0
    while pending:
        ready = [k for k, deps in pending.items() if deps <= placed]
        if not ready:
            return -1                      # cycle: engine must have refused
        waves += 1
        placed.update(ready)
        for k in ready:
            del pending[k]
    return waves


def derive_expectation(objective_doc, spec, returns) -> Expectation:
    """What the acceptor expects, computed BEFORE seeing any artefact."""
    ids = sorted(r["id"] for r in spec)
    total = sum(int(r["budget_units"]) for r in spec)

    ret_ids = [r["commission_id"] for r in returns]
    seen = {}
    for c in ret_ids:
        seen[c] = seen.get(c, 0) + 1

    missing = sorted(set(ids) - set(seen))
    orphan = sorted(set(seen) - set(ids))
    duplicate = sorted(k for k, n in seen.items() if n > 1)

    crit = {r["id"]: list(r.get("acceptance_criteria", [])) for r in spec}
    met = {}
    for r in returns:
        met.setdefault(r["commission_id"], set()).update(r.get("criteria_met", []))
    unmet = sorted(cid for cid, cs in crit.items()
                   if cid in seen and any(c not in met.get(cid, set()) for c in cs))

    fields = {
        "commission_ids": ids,
        "total_budget_committed": total,
        "budget_within_objective": total <= int(objective_doc["budget_units"]),
        "missing_returns": missing,
        "orphan_returns": orphan,
        "duplicate_returns": duplicate,
        "unmet_criteria_commissions": unmet,
        "reconciled": not (missing or orphan or duplicate or unmet),
        "wave_count": _independent_wave_count(spec),
    }
    return Expectation(fields=fields, derivation=Derivation.INDEPENDENT_ORACLE,
                       covers=COVERS, uncovered=UNCOVERED)


def extract_actual(run_dir: str) -> dict:
    """Read the produced artefacts into the same field shape for comparison."""
    def rd(n):
        with open(os.path.join(run_dir, n), encoding="utf-8") as f:
            return json.load(f)
    comms = rd("commissions.json")
    obj = rd("objective.json")
    routing = rd("routing_table.json")
    recon = rd("reconciliation.json")
    total = sum(int(c["budget_units"]) for c in comms)
    return {
        "commission_ids": sorted(c["id"] for c in comms),
        "total_budget_committed": total,
        "budget_within_objective": total <= int(obj["budget_units"]),
        "missing_returns": sorted(recon.get("missing_returns", [])),
        "orphan_returns": sorted(recon.get("orphan_returns", [])),
        "duplicate_returns": sorted(recon.get("duplicate_returns", [])),
        "unmet_criteria_commissions": sorted(recon.get("unmet_criteria", {})),
        "reconciled": bool(recon.get("reconciled")),
        "wave_count": len(routing.get("waves", [])),
    }
