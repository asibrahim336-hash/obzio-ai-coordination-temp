"""
Pack 10 - deterministic checks over an economics-measurement run directory.

Every ratio in the report is re-derived here from cost_events.jsonl and
work_units.jsonl. A number that cannot be rebuilt from the events is a number
that failed.

Usage:  python3 checks.py <workdir>   -> JSON report, exit 0/1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

import _spine
from _spine import (
    CheckReport, check_acceptance_provenance, check_commit_first_ordering,
    check_independent_review_recorded, check_pack_manifest, check_required_files,
    check_run_ledger, load_jsonl, read_json,
)
from state_machine import (
    ALL_BASES, AMPLIFICATION_RATIO_THRESHOLD, HARNESS_BASES, MODEL_BASES,
)

PACK_DIR = Path(__file__).resolve().parent

REQUIRED_ARTEFACTS = ["run_ledger.jsonl", "cost_events.jsonl",
                      "work_units.jsonl", "economics_report.json"]


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
        r = read_json(w / "economics_report.json")
    except Exception as e:  # noqa: BLE001
        rep.add("report_readable", False, str(e))
        return rep
    rep.add("report_readable", True, f"status={r.get('status')}")

    events = load_jsonl(w / "cost_events.jsonl")
    units = load_jsonl(w / "work_units.jsonl")
    rep.add("inputs_present", bool(events) and bool(units),
            f"{len(events)} event(s), {len(units)} unit(s)")

    # -- CORE: every cost is attributed to exactly one class ---------------
    unknown = sorted({e.get("basis") for e in events
                      if e.get("basis") not in ALL_BASES})
    rep.add("every_basis_is_known", not unknown,
            f"unattributed bases: {unknown}" if unknown
            else f"{len(ALL_BASES)} known bases, none violated")

    both = sorted({e.get("basis") for e in events
                   if e.get("basis") in MODEL_BASES and e.get("basis") in HARNESS_BASES})
    rep.add("classes_are_disjoint", not both, f"ambiguous: {both}")

    mislabelled = [e.get("event_id") for e in events
                   if e.get("basis") in ALL_BASES
                   and e.get("cost_class") != ("MODEL" if e.get("basis") in MODEL_BASES
                                               else "HARNESS")]
    rep.add("recorded_class_matches_basis", not mislabelled,
            f"mislabelled events: {mislabelled}")

    negatives = [e.get("event_id") for e in events if e.get("amount_micro", 0) < 0]
    rep.add("no_negative_cost_events", not negatives, f"negative: {negatives}")

    # -- re-derive every configuration from the raw events -----------------
    problems: List[str] = []
    ratio_problems: List[str] = []
    zero_div: List[str] = []
    for cid, m in r.get("configs", {}).items():
        ce = [e for e in events if e.get("config_id") == cid]
        cu = [u for u in units if u.get("config_id") == cid]
        model = sum(e["amount_micro"] for e in ce if e["basis"] in MODEL_BASES)
        harness = sum(e["amount_micro"] for e in ce if e["basis"] in HARNESS_BASES)
        total = model + harness
        accepted = sum(1 for u in cu if u.get("accepted"))
        attempted = len(cu)
        attempts = sum(u.get("attempts", 0) for u in cu)

        if m.get("model_micro") != model:
            problems.append(f"{cid}: model {m.get('model_micro')} != {model}")
        if m.get("harness_micro") != harness:
            problems.append(f"{cid}: harness {m.get('harness_micro')} != {harness}")
        if m.get("total_micro") != total:
            problems.append(f"{cid}: total {m.get('total_micro')} != {total}")
        if m.get("total_micro") != m.get("model_micro", 0) + m.get("harness_micro", 0):
            problems.append(f"{cid}: total is not model+harness")
        if m.get("declared_total_micro") != total:
            problems.append(f"{cid}: declared {m.get('declared_total_micro')} "
                            f"!= events {total}")
        if m.get("units_accepted") != accepted:
            problems.append(f"{cid}: accepted {m.get('units_accepted')} != {accepted}")
        if m.get("units_attempted") != attempted:
            problems.append(f"{cid}: attempted {m.get('units_attempted')} != {attempted}")
        if not (0 <= m.get("first_pass_accepted", 0) <= accepted <= attempted):
            problems.append(f"{cid}: first_pass/accepted/attempted inconsistent")

        # -- CORE: cost per accepted unit is undefined, never approximated --
        if accepted == 0:
            if m.get("cost_per_accepted_micro") is not None:
                zero_div.append(f"{cid}: cost_per_accepted computed with 0 accepted")
            if m.get("status") != "NO_ACCEPTED_UNITS":
                zero_div.append(f"{cid}: status {m.get('status')} with 0 accepted")
            if attempted and m.get("cost_per_accepted_micro") == round(total / attempted, 6):
                zero_div.append(f"{cid}: cost_per_accepted equals cost per ATTEMPT")
        else:
            for name, num in (("cost_per_accepted_micro", total),
                              ("model_per_accepted_micro", model),
                              ("harness_per_accepted_micro", harness)):
                want = round(num / accepted, 6)
                if m.get(name) != want:
                    ratio_problems.append(f"{cid}.{name}: {m.get(name)} != {want}")
            if attempts and m.get("attempts_per_accepted") != round(attempts / accepted, 6):
                ratio_problems.append(f"{cid}.attempts_per_accepted wrong")
        if model > 0:
            want = round(harness / model, 6)
            if m.get("harness_amplification") != want:
                ratio_problems.append(
                    f"{cid}.harness_amplification: {m.get('harness_amplification')} "
                    f"!= {want}")

    rep.add("totals_rederived_from_events", not problems, "; ".join(problems[:4])
            or f"{len(r.get('configs', {}))} config(s) reconcile exactly")
    rep.add("ratios_rederived_from_events", not ratio_problems,
            "; ".join(ratio_problems[:4]) or "every published ratio recomputes")
    rep.add("no_division_by_attempts_when_nothing_accepted", not zero_div,
            "; ".join(zero_div) or "undefined stays undefined")

    # -- CORE: self-accepted units do not count ----------------------------
    selfacc = [u.get("unit_id") for u in units
               if u.get("accepted") and u.get("accepted_by") == u.get("produced_by")]
    rep.add("no_self_accepted_units", not selfacc, f"self-accepted: {selfacc}")

    nobody = [u.get("unit_id") for u in units
              if u.get("accepted") and not u.get("accepted_by")]
    rep.add("accepted_units_name_an_acceptor", not nobody, f"unattributed: {nobody}")

    # -- comparability -------------------------------------------------------
    comp_problems = []
    for c in r.get("comparisons", []):
        ratio = c.get("amplification_ratio")
        if ratio is not None:
            should = "NOT_COMPARABLE" if ratio > r.get(
                "amplification_threshold", AMPLIFICATION_RATIO_THRESHOLD) else "COMPARABLE"
            if c.get("verdict") != should:
                comp_problems.append(
                    f"{c.get('a')}~{c.get('b')}: ratio {ratio} -> "
                    f"{c.get('verdict')}, expected {should}")
        if c.get("verdict") == "NOT_COMPARABLE" and not c.get("reason"):
            comp_problems.append(f"{c.get('a')}~{c.get('b')}: refusal with no reason")
    rep.add("comparability_verdicts_consistent", not comp_problems,
            "; ".join(comp_problems) or
            f"{len(r.get('comparisons', []))} comparison(s) consistent with the "
            f"{r.get('amplification_threshold')}x threshold")

    # -- the model-only trap is always surfaced ----------------------------
    rep.add("model_only_view_reported",
            all("model_only_cost_per_accepted" in c and "model_only_is_misleading" in c
                for c in r.get("comparisons", [])),
            "every comparison publishes the model-only view alongside the full one")

    rep.add("equal_harness_normalisation_present",
            all(c.get("normalised_cost_per_accepted")
                for c in r.get("comparisons", [])
                if c.get("verdict") == "NOT_COMPARABLE"),
            "every refused comparison carries an equal-harness re-scoring")

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
