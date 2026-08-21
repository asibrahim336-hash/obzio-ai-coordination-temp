"""
Pack 06 - deterministic checks over a browser-execution run directory.

Every check answers a yes/no question from bytes on disk. None of them ask
the producing process what it believes happened.

Usage:  python3 checks.py <workdir>   -> JSON report, exit 0/1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import _spine
from _spine import (
    CheckReport, check_acceptance_provenance, check_commit_first_ordering,
    check_independent_review_recorded, check_pack_manifest, check_required_files,
    check_run_ledger, load_jsonl, read_json,
)
from state_machine import REFUSAL_CODES

PACK_DIR = Path(__file__).resolve().parent

REQUIRED_ARTEFACTS = ["run_ledger.jsonl", "route_ledger.jsonl", "transcript.json"]


def missing_artefacts(workdir: Path | str) -> List[str]:
    w = Path(workdir)
    return [f for f in REQUIRED_ARTEFACTS
            if not (w / f).exists() or (w / f).stat().st_size == 0]


def _mandate_max_sends(led) -> int:
    if led is None:
        return -1
    for e in led.entries:
        if e.kind == "PHASE" and e.payload.get("phase") == "PREFLIGHT":
            return int(e.payload.get("evidence", {}).get("max_sends", -1))
    return -1


def run_checks(workdir: Path | str) -> CheckReport:
    w = Path(workdir)
    rep = CheckReport()

    check_required_files(rep, w, REQUIRED_ARTEFACTS)
    led = check_run_ledger(rep, w)
    check_acceptance_provenance(rep, led)
    check_independent_review_recorded(rep, led)
    check_commit_first_ordering(rep, led)
    check_pack_manifest(rep, PACK_DIR)

    rows = load_jsonl(w / "route_ledger.jsonl")
    rep.add("route_ledger_nonempty", bool(rows), f"{len(rows)} rows")

    # -- shape ------------------------------------------------------------
    malformed = [i for i, r in enumerate(rows)
                 if "kind" not in r or "verdict" not in r or "ts" not in r]
    rep.add("route_rows_wellformed", not malformed, f"malformed idx {malformed}")

    # -- closed refusal vocabulary ---------------------------------------
    allowed = REFUSAL_CODES | {"OK"}
    unknown = sorted({r.get("verdict") for r in rows
                      if r.get("verdict") not in allowed})
    rep.add("refusal_codes_closed", not unknown,
            f"unknown verdicts {unknown}" if unknown
            else f"vocabulary of {len(allowed)} respected")

    sends = [(i, r) for i, r in enumerate(rows) if r.get("kind") == "SEND"]
    ok_sends = [(i, r) for i, r in sends if r.get("verdict") == "OK"]
    verifies = [(i, r) for i, r in enumerate(rows) if r.get("kind") == "VERIFY"]
    ok_verify_nonce_at = {r["nonce"]: i for i, r in verifies
                          if r.get("verdict") == "OK" and r.get("nonce")}

    # -- CORE: no send without a preceding successful verify of that nonce
    orphans = [i for i, r in ok_sends
               if r.get("nonce") not in ok_verify_nonce_at]
    rep.add("every_send_has_verified_route", not orphans,
            f"sends without an OK VERIFY: idx {orphans}" if orphans
            else f"{len(ok_sends)} send(s) each traced to a verify")

    out_of_order = [i for i, r in ok_sends
                    if r.get("nonce") in ok_verify_nonce_at
                    and ok_verify_nonce_at[r["nonce"]] >= i]
    rep.add("verify_precedes_send", not out_of_order,
            f"verify not before send at idx {out_of_order}" if out_of_order
            else "ordering holds for all sends")

    # -- CORE: what was actually on screen at send == what was intended ---
    misrouted = [i for i, r in ok_sends
                 if r.get("surface_digest_at_send") != r.get("intended_digest")]
    rep.add("no_send_to_unintended_route", not misrouted,
            f"MISROUTE at idx {misrouted}" if misrouted
            else f"{len(ok_sends)} send(s) landed on the intended route")

    # -- replay ------------------------------------------------------------
    nonces = [r.get("nonce") for _, r in ok_sends]
    dupes = sorted({n for n in nonces if nonces.count(n) > 1})
    rep.add("no_token_reuse", not dupes, f"reused nonces {dupes}" if dupes
            else f"{len(set(nonces))} unique token(s)")

    # -- mandate ----------------------------------------------------------
    cap = _mandate_max_sends(led)
    rep.add("send_count_within_mandate", 0 <= len(ok_sends) <= cap if cap >= 0
            else False, f"{len(ok_sends)} send(s), mandate cap {cap}")

    # -- refusals are recorded, not silent --------------------------------
    refused = [r for _, r in sends if r.get("verdict") != "OK"]
    detailed = all(r.get("verdict") in REFUSAL_CODES for r in refused)
    rep.add("refusals_recorded_with_reason", detailed,
            f"{len(refused)} refusal(s): "
            + ",".join(sorted({r.get('verdict') for r in refused}) or ["none"]))

    # -- transcript agrees with the ledger --------------------------------
    tpath = w / "transcript.json"
    if tpath.exists():
        try:
            t = read_json(tpath)
            claimed = list(t.get("sent", []))
            actual = [r.get("message_id") for _, r in ok_sends]
            rep.add("transcript_matches_route_ledger", claimed == actual,
                    f"transcript {claimed} vs ledger {actual}")
        except Exception as e:  # noqa: BLE001
            rep.add("transcript_matches_route_ledger", False, f"unreadable: {e}")
    else:
        rep.add("transcript_matches_route_ledger", False, "transcript.json absent")

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
