"""
Pack 08 - deterministic checks over a knowledge-currentness run directory.

The central check is `every_match_row_has_this_run_evidence`: it re-derives,
from the evidence log on disk, that every MATCH in the published report was
backed by a full-byte read performed during THIS run. That is the check the
observed defect would have failed.

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
from state_machine import ReportStatus, Verdict

PACK_DIR = Path(__file__).resolve().parent

REQUIRED_ARTEFACTS = ["run_ledger.jsonl", "evidence_log.jsonl", "drift_report.json"]


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
        r = read_json(w / "drift_report.json")
    except Exception as e:  # noqa: BLE001
        rep.add("report_readable", False, str(e))
        return rep
    rep.add("report_readable", True, f"status={r.get('status')}")

    ev_rows = load_jsonl(w / "evidence_log.jsonl")
    by_id = {e["evidence_id"]: e for e in ev_rows}
    rep.add("evidence_log_nonempty", bool(ev_rows), f"{len(ev_rows)} reads logged")

    run_nonce = r.get("run_nonce")
    rows = r.get("rows", [])

    # -- THE CENTRAL CHECK -------------------------------------------------
    problems = []
    for row in rows:
        if row.get("verdict") != Verdict.MATCH.value:
            continue
        eid = row.get("evidence_id")
        if not eid:
            problems.append(f"{row.get('key')}: MATCH with no evidence_id")
            continue
        ev = by_id.get(eid)
        if ev is None:
            problems.append(f"{row.get('key')}: MATCH cites evidence {eid} "
                            "absent from this run's evidence log")
            continue
        if ev.get("run_nonce") != run_nonce:
            problems.append(f"{row.get('key')}: MATCH backed by evidence from "
                            f"run_nonce {str(ev.get('run_nonce'))[:8]}, report is "
                            f"{str(run_nonce)[:8]}")
        if not ev.get("full_read"):
            problems.append(f"{row.get('key')}: MATCH backed by a partial read")
        if ev.get("digest") != row.get("live_digest"):
            problems.append(f"{row.get('key')}: live_digest disagrees with evidence")
        if ev.get("digest") != row.get("pinned_digest"):
            problems.append(f"{row.get('key')}: MATCH but evidence digest != pin")
    rep.add("every_match_row_has_this_run_evidence", not problems,
            "; ".join(problems) if problems
            else f"{sum(1 for x in rows if x.get('verdict') == 'MATCH')} "
                 "MATCH row(s), each backed by a full read from this run")

    # -- every row belongs to this run ------------------------------------
    foreign = [x.get("key") for x in rows if x.get("run_nonce") != run_nonce]
    rep.add("no_carried_forward_rows", not foreign,
            f"rows from another run: {foreign}" if foreign
            else f"{len(rows)} row(s) all stamped {str(run_nonce)[:8]}")

    # -- MISSING rows must cite an attempted read --------------------------
    badmiss = []
    for row in rows:
        if row.get("verdict") != Verdict.MISSING.value:
            continue
        ev = by_id.get(row.get("evidence_id"))
        if ev is None or ev.get("outcome") != "MISSING":
            badmiss.append(row.get("key"))
    rep.add("missing_rows_cite_an_attempted_read", not badmiss,
            f"unevidenced MISSING rows: {badmiss}" if badmiss
            else f"{sum(1 for x in rows if x.get('verdict') == 'MISSING')} "
                 "MISSING row(s) each backed by a logged read attempt")

    # -- DRIFT rows must actually differ ------------------------------------
    bogus = [x.get("key") for x in rows if x.get("verdict") == Verdict.DRIFT.value
             and x.get("live_digest") == x.get("pinned_digest")]
    rep.add("drift_rows_actually_differ", not bogus, f"bogus drift: {bogus}")

    # -- a comparison actually happened -------------------------------------
    rep.add("comparisons_performed", r.get("comparisons_performed", 0) > 0,
            f"{r.get('comparisons_performed')} comparison(s), "
            f"{r.get('reads_performed')} read(s)")

    rep.add("reads_match_evidence_log", r.get("reads_performed") == len(ev_rows),
            f"report claims {r.get('reads_performed')}, log has {len(ev_rows)}")

    # -- coverage -----------------------------------------------------------
    rep.add("coverage_declared",
            isinstance(r.get("uncompared_pins"), list)
            and (not r["uncompared_pins"]
                 or r.get("status") == ReportStatus.INCOMPLETE.value),
            f"{len(r.get('uncompared_pins', []))} uncompared pin(s); "
            f"status {r.get('status')}")

    # -- staleness declared on every row ------------------------------------
    nostale = [x.get("key") for x in rows
               if "staleness_s_at_publication" not in x]
    rep.add("staleness_declared_per_row", not nostale, f"missing on {nostale}")

    over = [x.get("key") for x in rows
            if x.get("verdict") == Verdict.MATCH.value
            and x.get("staleness_s_at_publication", 0) > r.get("max_staleness_s", 0)]
    rep.add("no_match_over_staleness_ceiling", not over,
            f"stale MATCH rows survived: {over}" if over
            else f"ceiling {r.get('max_staleness_s')}s respected")

    # -- CURRENT is the strongest claim and needs the strongest support ----
    if r.get("status") == ReportStatus.CURRENT.value:
        ok = (not r.get("uncompared_pins")
              and r.get("counts", {}).get(Verdict.DRIFT.value, 0) == 0
              and r.get("counts", {}).get(Verdict.MISSING.value, 0) == 0
              and r.get("counts", {}).get(Verdict.UNKNOWN.value, 0) == 0
              and not r.get("downgraded")
              and r.get("counts", {}).get(Verdict.MATCH.value, 0) == r.get("pins_total"))
        rep.add("current_status_fully_supported", ok,
                f"counts={r.get('counts')}, pins={r.get('pins_total')}, "
                f"uncompared={r.get('uncompared_pins')}")
    else:
        rep.add("current_status_fully_supported", True,
                f"n/a: status is {r.get('status')}")

    rep.add("exit_code_consistent_with_status",
            (r.get("exit_code") == 0) == (r.get("status") == ReportStatus.CURRENT.value),
            f"status {r.get('status')} exit {r.get('exit_code')}")

    # -- the mtime tripwire is reported, never relied on --------------------
    rep.add("mtime_disagreements_surfaced",
            isinstance(r.get("mtime_shortcut_disagreements"), list),
            f"{len(r.get('mtime_shortcut_disagreements', []))} case(s) where an "
            "mtime shortcut would have said MATCH and content said otherwise")

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
