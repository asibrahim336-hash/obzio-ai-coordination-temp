"""Deterministic checks for continuity-recovery artefacts.

The question these answer: is this reconstructed state, or is it a story?"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from obzio_spine.artefacts import read_json, canonical, sha256_bytes
from obzio_spine.checkkit import CheckReport

REQUIRED_ARTEFACTS = [
    "recovered_state.json",
    "provenance.json",
    "gap_report.json",
]


def run_checks(run_dir: str) -> CheckReport:
    r = CheckReport("continuity-recovery")

    missing = [a for a in REQUIRED_ARTEFACTS
               if not os.path.exists(os.path.join(run_dir, a))]
    if missing:
        r.fail("artefacts_present", f"missing artefacts: {missing}", missing=missing)
        return r

    state = read_json(os.path.join(run_dir, "recovered_state.json"))
    prov = read_json(os.path.join(run_dir, "provenance.json"))
    gaps = read_json(os.path.join(run_dir, "gap_report.json"))

    root = prov.get("root", "")

    # --- CHK-CR-01 every fact RE-RESOLVES against its source -------------
    # The anti-confabulation control. We do not trust the recorded value; we
    # open the file, walk the pointer, and compare.
    from engine import resolve_pointer, ProvenanceError
    cache = {}
    for f in prov.get("facts", []):
        src = f.get("source_file", "")
        full = os.path.join(root, src)
        if not os.path.exists(full):
            r.fail("CHK-CR-01_provenance_resolves",
                   f"fact {f.get('key')!r} cites {src!r} which does not exist",
                   key=f.get("key"), source=src)
            continue
        if src not in cache:
            try:
                with open(full, encoding="utf-8") as fh:
                    cache[src] = json.load(fh)
            except Exception as e:
                r.fail("CHK-CR-01_provenance_resolves",
                       f"cited source {src!r} is not readable JSON: {e}", source=src)
                cache[src] = None
        doc = cache.get(src)
        if doc is None:
            continue
        try:
            actual = resolve_pointer(doc, f.get("pointer", ""))
        except ProvenanceError as e:
            r.fail("CHK-CR-01_provenance_resolves",
                   f"fact {f.get('key')!r}: {e}", key=f.get("key"))
            continue
        if actual != f.get("value"):
            r.fail("CHK-CR-01_provenance_resolves",
                   f"fact {f.get('key')!r} claims value {f.get('value')!r} but "
                   f"{src}{f.get('pointer')} actually holds {actual!r}",
                   key=f.get("key"), claimed=f.get("value"), actual=actual)

    # --- CHK-CR-02 no fact without complete provenance -------------------
    for f in prov.get("facts", []):
        for k in ("key", "source_file", "pointer"):
            if not str(f.get(k, "")).strip():
                r.fail("CHK-CR-02_no_unsourced_field",
                       f"fact {f.get('key', '<unnamed>')!r} is missing {k!r}",
                       key=f.get("key"))
    if state.get("recovered_field_count") != len(prov.get("facts", [])):
        r.fail("CHK-CR-02_no_unsourced_field",
               f"state claims {state.get('recovered_field_count')} recovered "
               f"fields but provenance carries {len(prov.get('facts', []))}")

    # --- CHK-CR-03 every cited source is inside the recovery root --------
    rroot = os.path.realpath(root) if root else "/nonexistent"
    for f in prov.get("facts", []):
        p = os.path.realpath(os.path.join(root, f.get("source_file", "")))
        if not (p == rroot or p.startswith(rroot + os.sep)):
            r.fail("CHK-CR-03_sources_within_root",
                   f"fact {f.get('key')!r} cites {f.get('source_file')!r} "
                   f"outside the recovery root", key=f.get("key"))

    # --- CHK-CR-04 the file inventory is complete ------------------------
    scanned = set(prov.get("files_scanned", []))
    used = set(prov.get("sources_used", []))
    ignored = {x["file"] for x in prov.get("sources_ignored", [])}
    unaccounted = sorted(scanned - used - ignored)
    if unaccounted:
        r.fail("CHK-CR-04_inventory_complete",
               f"{len(unaccounted)} scanned files are neither used nor "
               f"explicitly ignored: {unaccounted[:8]}",
               unaccounted=unaccounted[:8])
    for x in prov.get("sources_ignored", []):
        if not x.get("reason", "").strip():
            r.fail("CHK-CR-04_inventory_complete",
                   f"{x.get('file')!r} was ignored with no reason given")
    if not scanned:
        r.fail("CHK-CR-04_inventory_complete", "no files were scanned at all")

    # --- CHK-CR-05 contradictions are reported, never resolved -----------
    for c in gaps.get("contradictions", []):
        if c.get("resolution") != "UNRESOLVED_BY_DESIGN":
            r.fail("CHK-CR-05_contradictions_unresolved",
                   f"contradiction on {c.get('key')!r} was resolved to "
                   f"{c.get('resolution')!r}; this operator must not choose",
                   key=c.get("key"))
        if len(c.get("sources", [])) < 2:
            r.fail("CHK-CR-05_contradictions_unresolved",
                   f"contradiction on {c.get('key')!r} cites fewer than two "
                   f"sources", key=c.get("key"))
    if state.get("contradiction_count") != len(gaps.get("contradictions", [])):
        r.fail("CHK-CR-05_contradictions_unresolved",
               f"state reports {state.get('contradiction_count')} contradictions "
               f"but the gap report lists {len(gaps.get('contradictions', []))}")

    # --- CHK-CR-06 gaps are declared, not silently absorbed --------------
    if gaps.get("gap_count") != len(gaps.get("gaps", [])):
        r.fail("CHK-CR-06_gaps_declared",
               f"gap_count {gaps.get('gap_count')} disagrees with the list "
               f"({len(gaps.get('gaps', []))})")
    if state.get("open_items") != len(gaps.get("gaps", [])):
        r.fail("CHK-CR-06_gaps_declared",
               f"recovered_state.open_items ({state.get('open_items')}) "
               f"disagrees with the gap report ({len(gaps.get('gaps', []))})")
    for g in gaps.get("gaps", []):
        if not g.get("missing", "").strip() or not g.get("reason", "").strip():
            r.fail("CHK-CR-06_gaps_declared",
                   f"gap entry is incomplete: {g}")

    # --- CHK-CR-07 no conversation history was used ----------------------
    if state.get("conversation_history_used") is not False:
        r.fail("CHK-CR-07_no_conversation_source",
               "recovered state does not assert conversation_history_used=false")

    # --- CHK-CR-08 recovery is deterministic -----------------------------
    # Re-run recovery over the same root and require byte-identical state.
    if root and os.path.isdir(root):
        try:
            from engine import recover
            again = recover(root)
            a = sha256_bytes(canonical(again["recovered_state"]))
            b = sha256_bytes(canonical(state))
            if a != b:
                r.fail("CHK-CR-08_deterministic",
                       f"re-running recovery over the same root produced a "
                       f"different state ({a[:12]} != {b[:12]})")
            pa = sha256_bytes(canonical(again["gap_report"]))
            pb = sha256_bytes(canonical(gaps))
            if pa != pb:
                r.fail("CHK-CR-08_deterministic",
                       "re-running recovery produced a different gap report")
        except Exception as e:
            r.fail("CHK-CR-08_deterministic",
                   f"recovery could not be re-run for determinism: "
                   f"{type(e).__name__}: {e}")
    else:
        r.warn("CHK-CR-08_deterministic",
               "recovery root is unavailable; determinism unverified")

    return r


if __name__ == "__main__":
    rep = run_checks(sys.argv[1])
    print(rep.summary())
    for f in rep.findings:
        print(f"  [{f.severity}] {f.check}: {f.message}")
    sys.exit(0 if rep.passed else 1)
