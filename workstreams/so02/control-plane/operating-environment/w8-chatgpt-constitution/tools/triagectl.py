#!/usr/bin/env python3
"""triagectl - plan and adjudicate a back-catalogue sweep from one founder number.

Standard library only. No network. No provider access. Reads and writes nothing
outside the paths given on the command line.

The founder sets exactly one number: the tolerable rate of *consequential*
misclassification, meaning a decision-bearing item sent somewhere it cannot be
found again. Everything else is derived - the sample size, the allocation across
strata, the accept/reject verdict, the retry budget and the terminal fallback.
He does not read the sample. Reading a sample is evidence comparison, which the
standing non-negotiable puts off-limits.

    triagectl.py plan   --tolerance 0.01 --strata strata.json
    triagectl.py judge  --plan plan.json --observed observed.json
    triagectl.py exit-check --history yield-history.json --consecutive 3

`plan` sizes the sample by the rule of three: observing zero consequential
errors in n items bounds the true rate above by about 3/n at 95% confidence, so
n = ceil(3 / tolerance). The bound is one-sided and approximate, which is the
honest shape of the claim - it answers "is the rate plausibly below the
tolerance", not "what is the rate".
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

# Dispositions, and the cost of getting each one wrong. The sample is allocated
# by cost, not in proportion to volume: a proportional sample under-samples the
# expensive stratum exactly when it is largest, which is when it matters most.
DISPOSITION_COST = {
    "ARCHIVE_UNCLAIMED": 3.0,   # a decision-bearing item leaves the visible set
    "QUARANTINE": 2.0,          # a live item is withheld from the functions that need it
    "FREEZE_AS_EVIDENCE": 1.5,  # a live mandate is mistaken for history
    "SALVAGE": 1.0,             # routed to the wrong function; recoverable
    "OPERATE": 1.0,             # left live when it should have moved; recoverable
    "CANNOT_ASSESS": 0.0,       # never sampled: it was not read, so there is nothing to check
}

CONFIDENCE_NUMERATOR = 3.0  # the rule of three, at ~95% one-sided


def _read(path: str) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _instrument_check(target: int, sampleable: int, tol: float) -> dict:
    """Is a sample even the right instrument at this population size?

    Sampling buys a reduction in review effort. When the size the tolerance
    demands approaches the population, it buys nothing and costs the statistical
    caveats, so the honest recommendation is a full audit. This only makes sense
    because the reviewer is an agent: for a person, "review all of them" is the
    founder afternoon the whole design exists to prevent.
    """
    if sampleable <= 0:
        return {"verdict": "NOTHING_SAMPLEABLE"}
    tightest = round(CONFIDENCE_NUMERATOR / sampleable, 4)
    if target >= sampleable:
        return {
            "verdict": "FULL_AUDIT_RECOMMENDED",
            "reason": (
                f"the tolerance demands {target} items and only {sampleable} are readable, so the "
                "'sample' is the population. Sampling buys nothing here and costs the caveats."
            ),
            "recommendation": "audit every readable item; the measured rate is then exact rather than bounded",
            "tightest_tolerance_a_sample_could_support": tightest,
            "why_this_is_acceptable": "the reviewer is an agent, not the founder. Full audit of a small population is cheap for a batch job and impossible for a person.",
        }
    return {
        "verdict": "SAMPLE_IS_APPROPRIATE",
        "fraction_of_population_reviewed": round(target / sampleable, 4),
        "tightest_tolerance_a_sample_could_support": tightest,
    }


def _write(obj: dict, path: str | None) -> None:
    text = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    if path:
        pathlib.Path(path).write_text(text, encoding="utf-8")
    print(text, end="")


def cmd_plan(args: argparse.Namespace) -> int:
    tol = float(args.tolerance)
    if not 0.0 < tol < 1.0:
        print("ERROR --tolerance must be strictly between 0 and 1", file=sys.stderr)
        return 2

    strata = _read(args.strata)
    counts: dict[str, int] = {k: int(v) for k, v in strata.get("counts", {}).items()}
    unknown = sorted(set(counts) - set(DISPOSITION_COST))
    if unknown:
        print(f"ERROR unknown disposition(s) {unknown}; an unregistered class is never trusted by default", file=sys.stderr)
        return 2

    n_total = math.ceil(CONFIDENCE_NUMERATOR / tol)

    # Sampleable population excludes CANNOT_ASSESS by definition, but it stays
    # in the denominator of every coverage figure this tool emits.
    sampleable = {k: v for k, v in counts.items() if DISPOSITION_COST.get(k, 0.0) > 0.0 and v > 0}
    weight = {k: v * DISPOSITION_COST[k] for k, v in sampleable.items()}
    weight_total = sum(weight.values())

    allocation: dict[str, int] = {}
    if weight_total > 0:
        for k, w in sorted(weight.items()):
            allocation[k] = min(sampleable[k], max(1, round(n_total * w / weight_total)))
    drawn = sum(allocation.values())

    population = sum(counts.values())
    unreadable = counts.get("CANNOT_ASSESS", 0)

    plan = {
        "artifact": "OE-W8-TRIAGE-SAMPLE-PLAN",
        "founder_input": {
            "consequential_misclassification_tolerance": tol,
            "count_of_founder_decisions_required": 1,
            "founder_reads_the_sample": False,
            "why": "reading a sample is evidence comparison, which the standing non-negotiable puts off-limits",
        },
        "population": {
            "total_items": population,
            "sampleable": sum(sampleable.values()),
            "cannot_assess": unreadable,
            "coverage_denominator_includes_cannot_assess": True,
            "coverage_if_sweep_completes": round((population - unreadable) / population, 4) if population else 0.0,
        },
        "sample": {
            "target_size": n_total,
            "allocated_size": drawn,
            "allocation_by_disposition": allocation,
            "allocation_rule": "by cost of error, not in proportion to volume",
            "sizing_rule": f"n = ceil({CONFIDENCE_NUMERATOR} / tolerance); zero consequential errors in n bounds the true rate above by about {CONFIDENCE_NUMERATOR}/n at ~95% one-sided",
        },
        "instrument_check": _instrument_check(n_total, sum(sampleable.values()), tol),
        "acceptance_rule_declared_in_advance": {
            "accept_if": "observed consequential errors <= floor(tolerance * allocated_size)",
            "max_consequential_errors": math.floor(tol * drawn),
            "on_reject": "the whole sweep is rejected and re-run with corrected claim predicates; it is never patched item by item",
            "retry_budget": int(args.retries),
            "terminal_fallback": "after the retry budget is exhausted the sweep does not run again. Every unresolved item is dispositioned FREEZE_AS_EVIDENCE, which is reversible and loses no information, and the repeated failure is recorded as a finding about the claim predicates rather than carried as a backlog.",
            "why_a_fallback_exists": "reject-and-re-run with no bound has no termination guarantee; three failed sweeps cost more than the review they replaced",
        },
        "auditor_independence": {
            "requirement": "the lane computing the sample verdict must not be the lane that wrote the claim predicates",
            "reason": "a sweep grading its own sample is self-acceptance one level up",
            "reads": "committed artifacts only",
        },
        "nuisance_rate": "measured and reported alongside, never gated on. Wrongly archiving thirty chit-chat threads costs nothing; wrongly archiving one founder decision costs the estate its memory. One number from the founder, two rates measured.",
    }
    _write(plan, args.out)
    return 0


def cmd_judge(args: argparse.Namespace) -> int:
    plan = _read(args.plan)
    obs = _read(args.observed)

    drawn = plan["sample"]["allocated_size"]
    limit = plan["acceptance_rule_declared_in_advance"]["max_consequential_errors"]
    consequential = int(obs.get("consequential_errors", 0))
    nuisance = int(obs.get("nuisance_errors", 0))
    attempt = int(obs.get("attempt", 1))
    budget = int(plan["acceptance_rule_declared_in_advance"]["retry_budget"])
    auditor = obs.get("auditor_lane")
    sweeper = obs.get("sweeper_lane")

    errors = []
    if not auditor or not sweeper:
        errors.append("AUDITOR_OR_SWEEPER_UNDECLARED")
    elif auditor == sweeper:
        errors.append("AUDITOR_IS_SWEEPER — a sweep may not grade its own sample")
    if int(obs.get("reviewed", 0)) != drawn:
        errors.append(f"SAMPLE_SIZE_MISMATCH reviewed={obs.get('reviewed')} planned={drawn}")

    if errors:
        _write({"verdict": "INADMISSIBLE", "errors": errors}, args.out)
        return 1

    accepted = consequential <= limit
    exhausted = attempt >= budget

    verdict = {
        "artifact": "OE-W8-TRIAGE-SWEEP-VERDICT",
        "attempt": attempt,
        "retry_budget": budget,
        "reviewed": drawn,
        "consequential_errors": consequential,
        "max_permitted": limit,
        "consequential_rate": round(consequential / drawn, 4) if drawn else None,
        "nuisance_rate": round(nuisance / drawn, 4) if drawn else None,
        "verdict": "ACCEPT" if accepted else ("REJECT_AND_FALLBACK" if exhausted else "REJECT_AND_RERUN"),
        "self_accepts_under": "the rule the founder declared before the sweep ran",
        "founder_involvement_this_cycle": "informed, not asked",
    }
    if not accepted and exhausted:
        verdict["fallback_applied"] = plan["acceptance_rule_declared_in_advance"]["terminal_fallback"]
    _write(verdict, args.out)
    return 0 if accepted else 1


def cmd_exit_check(args: argparse.Namespace) -> int:
    """The exit condition, restated so that it is reachable.

    The old exit - retire when the unswept backlog is zero and new chats arrive
    pre-bound - is structurally unreachable, because chats started outside any
    project are a supported first-class flow, so unbound chats keep arriving by
    construction. The reachable exit is not "no unbound chats exist" but
    "unbound chats no longer carry anything new".
    """
    hist = _read(args.history)
    runs = hist.get("sweeps", [])
    need = int(args.consecutive)

    series = [
        {
            "sweep_id": r.get("sweep_id"),
            "items_swept": r.get("items_swept"),
            "novel_decision_bearing": r.get("novel_decision_bearing"),
            "novel_yield": (
                round(r["novel_decision_bearing"] / r["items_swept"], 4)
                if r.get("items_swept") else None
            ),
        }
        for r in runs
    ]
    tail = series[-need:] if len(series) >= need else series
    zero_tail = len(tail) == need and all(s["novel_decision_bearing"] == 0 for s in tail)

    out = {
        "artifact": "OE-W8-SALVAGE-EXIT-CHECK",
        "exit_condition": "novel decision-bearing yield is zero across N consecutive sweeps",
        "consecutive_required": need,
        "series": series,
        "state": "EXIT_MET_DOWNGRADE_TO_SPOT_CHECK" if zero_tail else "CONTINUE_EXHAUSTIVE",
        "why_this_exit_is_reachable": "it does not require unbound chats to stop existing. It requires them to stop containing anything the ledger does not already hold, which is what a working capture route produces.",
        "dual_use": "a persistently non-zero yield is the pre-registered falsifier for the capture function: intent is still being formed outside capture and the sweep is the only thing catching it.",
        "cost_shape": "indexed to what the sweep finds, rather than a fixed rate paid whether or not it finds anything",
    }
    _write(out, args.out)
    return 0 if zero_tail else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan")
    p.add_argument("--tolerance", required=True)
    p.add_argument("--strata", required=True)
    p.add_argument("--retries", default="2")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_plan)

    j = sub.add_parser("judge")
    j.add_argument("--plan", required=True)
    j.add_argument("--observed", required=True)
    j.add_argument("--out")
    j.set_defaults(fn=cmd_judge)

    e = sub.add_parser("exit-check")
    e.add_argument("--history", required=True)
    e.add_argument("--consecutive", default="3")
    e.add_argument("--out")
    e.set_defaults(fn=cmd_exit_check)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
