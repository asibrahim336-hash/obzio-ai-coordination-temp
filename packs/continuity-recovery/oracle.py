"""Independent acceptance oracle for continuity-recovery.

DOES NOT IMPORT engine.py.

The corpus is the acceptor's legitimate input -- it must read it to form any
expectation at all. What it may not see before committing is the RECOVERY'S
OUTPUT: recovered_state.json, provenance.json, gap_report.json. The machine's
anchoring check covers exactly those.

Everything below re-derives the headline facts by walking the corpus directly
with os.walk and json.load. The artefact-name list is restated here rather
than imported, so this file is a second opinion about what counts as
state-bearing rather than an echo of the first.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obzio_spine.expectation import Expectation, Derivation, canonical_digest

# Restated deliberately -- NOT imported from engine.INTERESTING.
STATE_BEARING = {
    "return_state.json", "journal.json", "reconciliation.json",
    "commissions.json", "objective.json", "pr_record.json",
    "change_orders.json", "verdict.json", "readback_verification.json",
}

COVERS = ("run_count", "packs_seen", "producer_ids", "orphan_dir_count",
          "objective_contradiction_count", "conversation_history_used",
          "completed_run_count")

UNCOVERED = (
    "whether the semantic mapping from artefact to state is RIGHT",
    "state that no artefact records (unknowable from inside the corpus)",
    "whether a well-formed artefact is genuine or forged",
    "the full gap list (only structural gap classes are re-derived)",
)


def _walk(root):
    out = []
    for dp, dn, fn in os.walk(root):
        dn[:] = sorted(d for d in dn if d != "__pycache__")
        for f in sorted(fn):
            out.append(os.path.relpath(os.path.join(dp, f), root))
    return sorted(out)


def _load(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return json.load(f)


def scan_corpus(root: str) -> dict:
    """Independent walk. Plain os + json, no engine involvement."""
    files = _walk(root)
    run_dirs = sorted({os.path.dirname(p) for p in files
                       if os.path.basename(p) == "return_state.json"})
    artefact_dirs = sorted({os.path.dirname(p) for p in files
                            if os.path.basename(p) in STATE_BEARING})
    orphans = [d for d in artefact_dirs if d not in run_dirs]

    packs, producers, completed = set(), set(), 0
    for rd in run_dirs:
        rel = os.path.join(rd, "return_state.json") if rd else "return_state.json"
        rs = _load(root, rel)
        packs.add(rs.get("pack"))
        producers.add(rs.get("producer_id"))
        if rs.get("final_state") == "COMPLETE":
            completed += 1

    # Same objective id asserted with different budgets = a real contradiction.
    claims, contradictions = {}, 0
    for rd in run_dirs:
        rel = os.path.join(rd, "objective.json") if rd else "objective.json"
        if not os.path.exists(os.path.join(root, rel)):
            continue
        doc = _load(root, rel)
        oid = doc.get("id", "<unidentified>")
        for key in ("budget_units", "deadline_iso", "statement"):
            if key not in doc:
                continue
            k = (oid, key)
            if k in claims and claims[k] != doc[key]:
                contradictions += 1
            else:
                claims.setdefault(k, doc[key])

    return {
        "run_count": len(run_dirs),
        "completed_run_count": completed,
        "packs_seen": sorted(p for p in packs if p),
        "producer_ids": sorted(p for p in producers if p),
        "orphan_dir_count": len(orphans),
        "objective_contradiction_count": contradictions,
    }


def inputs_digest(root: str) -> str:
    return canonical_digest({"root": os.path.realpath(root),
                             "scan": scan_corpus(root)})


def derive_expectation(root: str) -> Expectation:
    scan = scan_corpus(root)
    fields = dict(scan)
    fields["conversation_history_used"] = False
    return Expectation(fields=fields, derivation=Derivation.INDEPENDENT_ORACLE,
                       covers=COVERS, uncovered=UNCOVERED)


def extract_actual(run_dir: str) -> dict:
    def rd(n):
        return _load(run_dir, n)
    st = rd("recovered_state.json")
    gaps = rd("gap_report.json")
    runs = st.get("runs", [])
    orphan_gaps = [g for g in gaps.get("gaps", [])
                   if g.get("missing", "").startswith("completion record for")]
    return {
        "run_count": st.get("run_count"),
        "completed_run_count": sum(1 for r in runs
                                   if r.get("final_state") == "COMPLETE"),
        "packs_seen": sorted(st.get("packs_seen", [])),
        "producer_ids": sorted({r.get("producer_id") for r in runs
                                if r.get("producer_id")}),
        "orphan_dir_count": len(orphan_gaps),
        "objective_contradiction_count": st.get("contradiction_count"),
        "conversation_history_used": st.get("conversation_history_used"),
    }
