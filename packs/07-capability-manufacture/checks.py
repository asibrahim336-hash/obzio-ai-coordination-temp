"""
Pack 07 - deterministic checks over a capability-manufacture run directory.

Usage:  python3 checks.py <workdir>   -> JSON report, exit 0/1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List

import _spine
from _spine import (
    CheckReport, check_acceptance_provenance, check_commit_first_ordering,
    check_independent_review_recorded, check_pack_manifest, check_required_files,
    check_run_ledger, load_jsonl, read_json,
)
from state_machine import Verdict

PACK_DIR = Path(__file__).resolve().parent

REQUIRED_ARTEFACTS = ["run_ledger.jsonl", "commission.json",
                      "return_inventory.json", "assessment.json",
                      "probe_log.jsonl"]


def missing_artefacts(workdir: Path | str) -> List[str]:
    w = Path(workdir)
    return [f for f in REQUIRED_ARTEFACTS
            if not (w / f).exists() or (w / f).stat().st_size == 0]


def run_checks(workdir: Path | str) -> CheckReport:
    w = Path(workdir)
    rep = CheckReport()

    check_required_files(rep, w, REQUIRED_ARTEFACTS)
    led = check_run_ledger(rep, w)
    check_acceptance_provenance(rep, led)
    check_independent_review_recorded(rep, led)
    check_commit_first_ordering(rep, led)
    check_pack_manifest(rep, PACK_DIR)

    try:
        com = read_json(w / "commission.json")
    except Exception as e:  # noqa: BLE001
        rep.add("commission_readable", False, str(e))
        return rep
    rep.add("commission_readable", True, com.get("spec", {}).get("commission_id", "?"))

    try:
        a = read_json(w / "assessment.json")
    except Exception as e:  # noqa: BLE001
        rep.add("assessment_readable", False, str(e))
        return rep
    rep.add("assessment_readable", True, a.get("verdict", "?"))

    # -- the spec was pinned before the return was judged -----------------
    rep.add("spec_digest_unchanged",
            a.get("spec_digest") == com.get("spec_digest"),
            f"assessment {str(a.get('spec_digest'))[:12]} vs "
            f"commission {str(com.get('spec_digest'))[:12]}")

    rep.add("spec_pinned_before_return",
            float(com.get("dispatched_at", 0)) <= float(a.get("return_received_at", 0)),
            f"dispatched {com.get('dispatched_at')} <= received "
            f"{a.get('return_received_at')}")

    try:
        inv = read_json(w / "return_inventory.json")
        rep.add("return_inventory_recorded", inv.get("file_count", 0) >= 0,
                f"{inv.get('file_count')} files, {inv.get('total_bytes')} bytes")
    except Exception as e:  # noqa: BLE001
        rep.add("return_inventory_recorded", False, str(e))

    # -- verdict is from the closed set ------------------------------------
    verdicts = {v.value for v in Verdict}
    rep.add("verdict_in_closed_set", a.get("verdict") in verdicts,
            f"{a.get('verdict')!r} in {sorted(verdicts)}")

    # -- every declared deliverable was assessed --------------------------
    declared = [d["path"] for d in com.get("spec", {}).get("deliverables", [])]
    assessed = [d["path"] for d in a.get("deliverables", [])]
    rep.add("every_deliverable_assessed", sorted(declared) == sorted(assessed),
            f"declared {declared} vs assessed {assessed}")

    probes = load_jsonl(w / "probe_log.jsonl")
    probe_rows = [r for r in probes if r.get("kind") in ("PROBE", "PROBE_SKIPPED")]
    rep.add("probe_log_has_rows", bool(probes), f"{len(probes)} rows")

    # -- probes ran inside quarantine only ---------------------------------
    escapes = [r for r in probes if r.get("kind") == "PROBE"
               and not r.get("inside_quarantine")]
    rep.add("probes_confined_to_quarantine", not escapes,
            f"{len(escapes)} probe(s) outside quarantine")

    # -- the count in the assessment matches the probe log ----------------
    logged_pass = sum(1 for r in probes if r.get("kind") == "PROBE"
                      and r.get("passed") is True)
    rep.add("probe_count_matches_log", logged_pass == a.get("probes_passed"),
            f"log {logged_pass} vs assessment {a.get('probes_passed')}")

    # -- CORE: MATERIAL requires our own execution evidence ---------------
    if a.get("verdict") == Verdict.MATERIAL.value:
        ok = (a.get("probes_passed", 0) >= 1
              and a.get("probes_passed") == a.get("probes_defined")
              and not a.get("missing")
              and not a.get("type_failures"))
        rep.add("material_backed_by_execution", ok,
                f"probes {a.get('probes_passed')}/{a.get('probes_defined')}, "
                f"missing={a.get('missing')}, type_failures={a.get('type_failures')}")
    else:
        rep.add("material_backed_by_execution", True,
                f"n/a: verdict is {a.get('verdict')}")

    # -- CORE: vendor self-reports never counted as material --------------
    att_names = {x["file"] for x in a.get("self_attestation_ignored", [])}
    counted = att_names & set(assessed)
    rep.add("self_attestation_not_counted", not counted,
            f"self-report(s) counted as deliverables: {sorted(counted)}"
            if counted else f"{len(att_names)} self-report(s) excluded")

    # -- undeclared files contributed nothing ------------------------------
    declared_set = set(declared)
    leaked = [f for f in a.get("undeclared_files", []) if f in declared_set]
    rep.add("undeclared_files_carry_no_credit", not leaked,
            f"{len(a.get('undeclared_files', []))} undeclared file(s), "
            f"{a.get('undeclared_bytes', 0)} bytes, all excluded from material")

    # -- narrative signals are always recorded, even when empty ------------
    rep.add("narrative_signals_recorded",
            isinstance(a.get("claims_found"), list)
            and isinstance(a.get("self_attestation_ignored"), list)
            and isinstance(a.get("reasoning"), list) and bool(a.get("reasoning")),
            f"{len(a.get('claims_found', []))} claim(s); "
            f"reasoning: {'; '.join(a.get('reasoning', []))[:110]}")

    # -- promotion only after acceptance ------------------------------------
    prom = w / "promotion.json"
    if prom.exists():
        pj = read_json(prom)
        accepted_ok = bool(pj.get("acceptor_id")) and \
            a.get("verdict") == Verdict.MATERIAL.value
        rep.add("promotion_only_after_acceptance", accepted_ok,
                f"promoted {pj.get('promoted')} by {pj.get('acceptor_id')!r}")
    else:
        rep.add("promotion_only_after_acceptance", True, "n/a: nothing promoted")

    return rep


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print("usage: checks.py <workdir>", file=sys.stderr)
        return 2
    rep = run_checks(argv[1])
    print(json.dumps(rep.to_dict(), indent=2))
    return 0 if rep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
