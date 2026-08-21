"""Continuity recovery: rebuild operating state from durable artefacts alone.

The premise: the conversation is gone. Whatever was in it — the plan, the
caveats, the "we agreed to skip that" — is unavailable and unrecoverable.
The only thing left is what was written to disk.

The failure this engine is built against is not forgetting. It is CONFABULATION:
an operator reconstructs a plausible state, presents it with confidence, and
nobody can tell which parts came from artefacts and which were inferred to make
the story hang together.

So the central rule is enforced by the type system, not by discipline:

    A field cannot be constructed without a provenance pointer.

`Fact.__init__` requires source_file + pointer + raw value, and every pointer
is RE-RESOLVED against the file at check time. A field whose pointer does not
resolve to the claimed value is a fabrication and is caught mechanically.

The second rule: contradictions are REPORTED, never resolved. Two artefacts
disagreeing is information. An operator that quietly picks the newer one has
destroyed the only signal that something is wrong.
"""

import json
import os
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any


class RecoveryError(RuntimeError):
    pass


class ProvenanceError(RecoveryError):
    """A fact was constructed without resolvable provenance."""


# --------------------------------------------------------------- json pointer

def resolve_pointer(doc, pointer: str):
    """RFC-6901-ish pointer resolution. Raises on any miss -- a pointer that
    silently returns None is how fabricated provenance survives."""
    if pointer in ("", "/"):
        return doc
    if not pointer.startswith("/"):
        raise ProvenanceError(f"pointer {pointer!r} must start with '/'")
    cur = doc
    for rawtok in pointer[1:].split("/"):
        tok = rawtok.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            try:
                idx = int(tok)
            except ValueError:
                raise ProvenanceError(
                    f"pointer {pointer!r}: {tok!r} is not a list index")
            if not (0 <= idx < len(cur)):
                raise ProvenanceError(
                    f"pointer {pointer!r}: index {idx} out of range")
            cur = cur[idx]
        elif isinstance(cur, dict):
            if tok not in cur:
                raise ProvenanceError(
                    f"pointer {pointer!r}: key {tok!r} not present")
            cur = cur[tok]
        else:
            raise ProvenanceError(
                f"pointer {pointer!r}: cannot descend into {type(cur).__name__}")
    return cur


# ---------------------------------------------------------------------- facts

@dataclass(frozen=True)
class Fact:
    """A recovered value that carries where it came from.

    There is deliberately no constructor that omits provenance."""
    key: str
    value: Any
    source_file: str          # relative to the recovery root
    pointer: str

    def to_json(self):
        return asdict(self)


class Ledger:
    """Accumulates facts, gaps, and contradictions."""

    def __init__(self, root: str):
        self.root = os.path.realpath(root)
        self.facts: List[Fact] = []
        self.gaps: List[dict] = []
        self.contradictions: List[dict] = []
        self.sources_used: set = set()
        self.sources_ignored: Dict[str, str] = {}

    def record(self, key, source_rel, pointer, doc=None):
        """Read the value FROM the source, never from a caller-supplied literal.

        This is the anti-confabulation move: the caller names where the value
        lives; it does not get to say what the value is."""
        full = os.path.join(self.root, source_rel)
        if not os.path.exists(full):
            raise ProvenanceError(f"source {source_rel!r} does not exist")
        if doc is None:
            with open(full, encoding="utf-8") as f:
                doc = json.load(f)
        value = resolve_pointer(doc, pointer)
        f_ = Fact(key=key, value=value, source_file=source_rel, pointer=pointer)
        self.facts.append(f_)
        self.sources_used.add(source_rel)
        return f_

    def gap(self, what, why, expected_at=None):
        self.gaps.append({"missing": what, "reason": why,
                          "expected_at": expected_at or ""})

    def contradiction(self, key, a: "Fact", b: "Fact"):
        self.contradictions.append({
            "key": key,
            "values": [a.value, b.value],
            "sources": [
                {"file": a.source_file, "pointer": a.pointer, "value": a.value},
                {"file": b.source_file, "pointer": b.pointer, "value": b.value},
            ],
            "resolution": "UNRESOLVED_BY_DESIGN",
            "note": ("two durable artefacts disagree; this operator reports the "
                     "disagreement and does not choose between them"),
        })

    def ignore(self, source_rel, reason):
        self.sources_ignored[source_rel] = reason


# ----------------------------------------------------------------- the scanner

INTERESTING = {
    "return_state.json", "journal.json", "reconciliation.json",
    "commissions.json", "objective.json", "pr_record.json",
    "change_orders.json", "verdict.json", "readback_verification.json",
}


def scan(root: str) -> List[str]:
    """Every file under root, relative, sorted. Deterministic by construction."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for fn in sorted(filenames):
            out.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return sorted(out)


def _load(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return json.load(f)


def recover(root: str) -> dict:
    """Rebuild operating state. Returns the three artefact payloads."""
    root = os.path.realpath(root)
    led = Ledger(root)
    all_files = scan(root)
    if not all_files:
        raise RecoveryError(f"no artefacts under {root!r}: nothing to recover from")

    # Group by run directory (the dir containing a return_state.json).
    run_dirs = sorted({os.path.dirname(p) for p in all_files
                       if os.path.basename(p) == "return_state.json"})
    if not run_dirs:
        led.gap("any completed run", "no return_state.json found anywhere",
                expected_at="<run_dir>/return_state.json")

    for rel in all_files:
        if os.path.basename(rel) not in INTERESTING:
            led.ignore(rel, "not a recognised state-bearing artefact")

    # Orphan work: a directory holding real artefacts but NO return_state.json.
    # These are runs that stopped before recording an outcome. An earlier
    # version skipped them entirely -- they contributed no facts and no gaps,
    # so a corpus full of abandoned work recovered as "clean". That silence was
    # the single most dangerous behaviour in this pack, because the report
    # looked complete. They are now surfaced as explicit gaps.
    artefact_dirs = sorted({os.path.dirname(p) for p in all_files
                            if os.path.basename(p) in INTERESTING})
    orphan_dirs = [d for d in artefact_dirs if d not in run_dirs]
    for od in orphan_dirs:
        label = od or "."
        led.gap(f"completion record for {label}",
                "directory holds work artefacts but no return_state.json: the "
                "run stopped before recording an outcome",
                expected_at=os.path.join(od, "return_state.json"))
        jrel = os.path.join(od, "journal.json") if od else "journal.json"
        if os.path.exists(os.path.join(root, jrel)):
            jdoc = _load(root, jrel)
            if jdoc:
                led.record(f"orphan.{label}.last_event", jrel,
                           f"/{len(jdoc) - 1}/event", jdoc)
                led.record(f"orphan.{label}.last_state", jrel,
                           f"/{len(jdoc) - 1}/state", jdoc)

    runs = []
    # Contradiction tracking keys on (objective_id, field) -- the SAME logical
    # thing asserted twice. An earlier version keyed on pack name, which
    # flagged two perfectly normal independent runs as contradicting each
    # other. Different runs SHOULD have different digests; that is not a
    # disagreement, and a detector that says so is worse than none.
    objective_claims: Dict[tuple, Fact] = {}

    for rd in run_dirs:
        rs_rel = os.path.join(rd, "return_state.json") if rd else "return_state.json"
        doc = _load(root, rs_rel)
        run_id = rd or "."

        pack = led.record(f"run.{run_id}.pack", rs_rel, "/pack", doc)
        state = led.record(f"run.{run_id}.final_state", rs_rel, "/final_state", doc)
        producer = led.record(f"run.{run_id}.producer_id", rs_rel, "/producer_id", doc)

        try:
            verdict = led.record(f"run.{run_id}.verdict", rs_rel, "/verdict", doc)
            verdict_v = verdict.value
        except ProvenanceError:
            led.gap(f"verdict for run {run_id}",
                    "return_state.json has no /verdict key", expected_at=rs_rel)
            verdict_v = None

        try:
            dg = led.record(f"run.{run_id}.accepted_run_digest", rs_rel,
                            "/accepted_run_digest", doc)
            digest_v = dg.value
        except ProvenanceError:
            led.gap(f"accepted digest for run {run_id}",
                    "no /accepted_run_digest", expected_at=rs_rel)
            digest_v = None

        if state.value != "COMPLETE":
            led.gap(f"completion of run {run_id}",
                    f"final_state is {state.value!r}, not COMPLETE",
                    expected_at=rs_rel)
        if verdict_v == "REJECT":
            led.gap(f"acceptance of run {run_id}",
                    "run was REJECTED and has not been re-run",
                    expected_at=rs_rel)

        runs.append({
            "run_id": run_id, "pack": pack.value, "producer_id": producer.value,
            "final_state": state.value, "verdict": verdict_v,
            "accepted_run_digest": digest_v, "source": rs_rel,
        })

        # ---- pack-specific outstanding work ----------------------------
        recon_rel = os.path.join(rd, "reconciliation.json") if rd else "reconciliation.json"
        if os.path.exists(os.path.join(root, recon_rel)):
            rdoc = _load(root, recon_rel)
            mr = led.record(f"run.{run_id}.missing_returns", recon_rel,
                            "/missing_returns", rdoc)
            for i, cid in enumerate(mr.value):
                led.record(f"outstanding.commission.{run_id}.{cid}", recon_rel,
                           f"/missing_returns/{i}", rdoc)
                led.gap(f"return for commission {cid}",
                        "commissioned but never reconciled", expected_at=recon_rel)

        pr_rel = os.path.join(rd, "pr_record.json") if rd else "pr_record.json"
        if os.path.exists(os.path.join(root, pr_rel)):
            pdoc = _load(root, pr_rel)
            st = led.record(f"run.{run_id}.pr_state", pr_rel, "/state", pdoc)
            led.record(f"run.{run_id}.pr_head", pr_rel, "/head", pdoc)
            if st.value == "open":
                led.gap(f"merge decision for PR on run {run_id}",
                        "PR is open and awaiting a decision", expected_at=pr_rel)

        obj_rel = os.path.join(rd, "objective.json") if rd else "objective.json"
        if os.path.exists(os.path.join(root, obj_rel)):
            odoc = _load(root, obj_rel)
            obj_id = odoc.get("id", "<unidentified>")
            for key, ptr in (("id", "/id"), ("statement", "/statement"),
                             ("budget_units", "/budget_units"),
                             ("deadline_iso", "/deadline_iso")):
                try:
                    fct = led.record(f"objective.{run_id}.{key}", obj_rel, ptr, odoc)
                except ProvenanceError:
                    led.gap(f"objective {key} for run {run_id}",
                            f"objective.json has no {ptr}", expected_at=obj_rel)
                    continue
                # THE contradiction test: the same objective, asserted twice,
                # with different values. That is a genuine disagreement between
                # durable artefacts and must never be silently reconciled.
                ck = (obj_id, key)
                if ck in objective_claims and objective_claims[ck].value != fct.value:
                    led.contradiction(f"objective[{obj_id}].{key}",
                                      objective_claims[ck], fct)
                else:
                    objective_claims.setdefault(ck, fct)

        com_rel = os.path.join(rd, "commissions.json") if rd else "commissions.json"
        if os.path.exists(os.path.join(root, com_rel)):
            cdoc2 = _load(root, com_rel)
            for i, c in enumerate(cdoc2):
                led.record(f"commission.{run_id}.{c.get('id', i)}.id",
                           com_rel, f"/{i}/id", cdoc2)
                led.record(f"commission.{run_id}.{c.get('id', i)}.owner_capability",
                           com_rel, f"/{i}/owner_capability", cdoc2)
                led.record(f"commission.{run_id}.{c.get('id', i)}.budget_units",
                           com_rel, f"/{i}/budget_units", cdoc2)

        jrn_rel = os.path.join(rd, "journal.json") if rd else "journal.json"
        if os.path.exists(os.path.join(root, jrn_rel)):
            jdoc = _load(root, jrn_rel)
            if jdoc:
                led.record(f"run.{run_id}.journal_last_event",
                           jrn_rel, f"/{len(jdoc) - 1}/event", jdoc)
                led.record(f"run.{run_id}.journal_last_state",
                           jrn_rel, f"/{len(jdoc) - 1}/state", jdoc)
            if not any(e.get("event") == "ACCEPTANCE_VERIFIED" for e in jdoc):
                led.gap(f"acceptance event for run {run_id}",
                        "journal records no ACCEPTANCE_VERIFIED event",
                        expected_at=jrn_rel)

        co_rel = os.path.join(rd, "change_orders.json") if rd else "change_orders.json"
        if os.path.exists(os.path.join(root, co_rel)):
            cdoc = _load(root, co_rel)
            for i, o in enumerate(cdoc):
                if o.get("requires_founder_confirmation"):
                    led.record(f"awaiting_founder.{run_id}.{o['id']}", co_rel,
                               f"/{i}/id", cdoc)
                    led.gap(f"founder confirmation for {o['id']}",
                            "change order is gated on founder confirmation",
                            expected_at=co_rel)

    # Inventory sweep. Any recognised artefact from which no state-bearing
    # field was extracted is recorded as ignored WITH A REASON, so the
    # inventory is total and nothing is silently dropped. This is deliberately
    # explicit rather than convenient: an artefact type this engine does not
    # read is a known limitation, and it should appear in the record as one.
    for rel in all_files:
        if rel not in led.sources_used and rel not in led.sources_ignored:
            led.ignore(rel, "recognised artefact type, but this engine version "
                            "extracts no state-bearing field from it")

    recovered = {
        "recovery_root": root,
        "runs": sorted(runs, key=lambda r: r["run_id"]),
        "run_count": len(runs),
        "packs_seen": sorted({r["pack"] for r in runs}),
        "open_items": len(led.gaps),
        "contradiction_count": len(led.contradictions),
        "recovered_field_count": len(led.facts),
        "conversation_history_used": False,
    }

    provenance = {
        "root": root,
        "fact_count": len(led.facts),
        "facts": [f.to_json() for f in sorted(
            led.facts, key=lambda x: (x.key, x.source_file, x.pointer))],
        "sources_used": sorted(led.sources_used),
        "sources_ignored": [{"file": k, "reason": v}
                            for k, v in sorted(led.sources_ignored.items())],
        "files_scanned": all_files,
    }

    gap_report = {
        "gap_count": len(led.gaps),
        "gaps": sorted(led.gaps, key=lambda g: (g["missing"], g["reason"])),
        "contradiction_count": len(led.contradictions),
        "contradictions": sorted(led.contradictions, key=lambda c: c["key"]),
        "note": ("gaps are things the artefacts do not answer. They are listed "
                 "rather than guessed. Contradictions are left unresolved."),
    }

    return {"recovered_state": recovered, "provenance": provenance,
            "gap_report": gap_report}
