"""
Pack 09 - deterministic checks over an infrastructure-operation run directory.

Usage:  python3 checks.py <workdir>   -> JSON report, exit 0/1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List

import _spine
from _spine import (
    CheckReport, Phase, check_acceptance_provenance, check_commit_first_ordering,
    check_independent_review_recorded, check_pack_manifest, check_required_files,
    check_run_ledger, load_jsonl, read_json,
)

PACK_DIR = Path(__file__).resolve().parent

REQUIRED_ARTEFACTS = ["run_ledger.jsonl", "op_log.jsonl",
                      "consolidation_report.json", "db_state.json"]


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

    ops = load_jsonl(w / "op_log.jsonl")
    applies = [o for o in ops if o.get("kind") == "APPLY"]
    replays = [o for o in ops if o.get("kind") == "REPLAY"]

    # -- CORE: an idempotency key is applied at most once ------------------
    keys = [o.get("idem_key") for o in applies]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    rep.add("no_idem_key_applied_twice", not dupes,
            f"keys applied more than once: {dupes}" if dupes
            else f"{len(applies)} apply(ies), {len(set(keys))} distinct key(s), "
                 f"{len(replays)} replay(s) suppressed")

    rep.add("replays_had_no_effect",
            all(o.get("applied") is False for o in replays),
            f"{len(replays)} replay row(s), none applied")

    try:
        c = read_json(w / "consolidation_report.json")
    except Exception as e:  # noqa: BLE001
        rep.add("consolidation_report_readable", False, str(e))
        return rep
    rep.add("consolidation_report_readable", True,
            f"{len(c.get('batches', []))} batch(es)")

    batches = c.get("batches", [])
    ceil_b = c.get("ceiling_bytes", 0)
    ceil_r = c.get("ceiling_rows", 0)

    # -- CORE: every request stayed under the per-request ceiling ----------
    over_b = [b["batch_no"] for b in batches if b.get("request_bytes", 0) > ceil_b]
    rep.add("no_request_exceeded_byte_ceiling", not over_b,
            f"batches over {ceil_b}B: {over_b}" if over_b
            else f"max {c.get('max_request_bytes_seen', 0)}B of {ceil_b}B ceiling")

    over_r = [b["batch_no"] for b in batches if b.get("rows", 0) > ceil_r]
    rep.add("no_request_exceeded_row_ceiling", not over_r,
            f"batches over {ceil_r} rows: {over_r}" if over_r
            else f"all batches <= {ceil_r} rows")

    # -- the watermark advanced contiguously, never backwards --------------
    problems = []
    prev = c.get("start_position", 0)
    for b in batches:
        if b.get("from") != prev:
            problems.append(f"batch {b['batch_no']} starts at {b.get('from')}, "
                            f"expected {prev}")
        if b.get("to", 0) < b.get("from", 0):
            problems.append(f"batch {b['batch_no']} moved backwards")
        prev = b.get("to", prev)
    if batches and prev != c.get("end_position"):
        problems.append(f"final batch ends {prev}, cursor says {c.get('end_position')}")
    rep.add("watermark_contiguous_and_monotonic", not problems,
            "; ".join(problems) if problems
            else f"{c.get('start_position')} -> {c.get('end_position')} "
                 f"across {len(batches)} batch(es)")

    rep.add("cursor_never_regressed",
            c.get("end_position", 0) >= c.get("start_position", 0),
            f"{c.get('start_position')} -> {c.get('end_position')}")

    # -- row accounting -----------------------------------------------------
    counted = sum(b.get("rows", 0) for b in batches if not b.get("replayed"))
    rep.add("batch_rows_account_for_total",
            counted == c.get("rows_consolidated", -1),
            f"batches sum {counted} vs reported {c.get('rows_consolidated')}")

    # -- THE DEFECT PRE-MORTEM, on the record ------------------------------
    full = c.get("full_state_bytes_at_start", 0)
    rep.add("whole_state_size_recorded", isinstance(full, int),
            f"whole state was {full}B against a {ceil_b}B ceiling"
            + (" - a whole-state read WOULD have failed here"
               if full > ceil_b else ""))

    # -- growth guard ran during recovery ----------------------------------
    guard = None
    if led is not None:
        for e in led.entries:
            if e.kind == "PHASE" and e.payload.get("phase") == "CURRENT_STATE_RECOVERED":
                guard = e.payload.get("evidence", {}).get("growth_guard")
    rep.add("growth_guard_recorded", bool(guard) and guard.get("bounded_path_in_use") is True,
            f"guard: {json.dumps(guard, sort_keys=True)[:150]}" if guard
            else "no growth guard recorded at recovery")

    # -- db reflects the log -------------------------------------------------
    try:
        st = read_json(w / "db_state.json")
        rep.add("db_state_captured", "balances" in st and "cursors" in st,
                f"{len(st.get('balances', {}))} account(s), "
                f"cursors={st.get('cursors')}, applied_ops={st.get('applied_ops')}")
        rep.add("applied_ops_at_least_logged_applies",
                st.get("applied_ops", 0) >= len(set(keys)),
                f"db has {st.get('applied_ops')} key(s), log shows "
                f"{len(set(keys))} distinct applied key(s)")
        rep.add("cursor_in_db_matches_report",
                st.get("cursors", {}).get(c.get("cursor_name")) ==
                c.get("end_position"),
                f"db {st.get('cursors', {}).get(c.get('cursor_name'))} vs report "
                f"{c.get('end_position')}")
    except Exception as e:  # noqa: BLE001
        rep.add("db_state_captured", False, str(e))

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
