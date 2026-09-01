#!/usr/bin/env python3
"""Cost arithmetic for an office of N cloud agents, with assumptions kept visible.

Nothing here measures token consumption. Token consumption is not observable from
inside an agent pod, and inventing a number would be exactly the confident,
useless answer this estate keeps producing. What this does is combine a price
table that was fetched live from Cursor's own documentation with token volumes
the operator supplies, and print which of its inputs are documented and which are
assumed, so a wrong answer is traceable to a wrong assumption rather than to
arithmetic nobody can see.

The one number that is not an assumption is the one on the Spending tab at
https://cursor.com/dashboard/usage after a wave has run.

    python3 tools/cost_model.py --agents 8 --model claude-opus-5 --input-mtok 2 --output-mtok 0.3
    python3 tools/cost_model.py --table
"""
from __future__ import annotations

import argparse
import json
import sys

# Per million tokens. DOCUMENTED: https://cursor.com/docs/models-and-pricing.md
# fetched 2026-08-23T00:01Z, sha256 recorded in INTERFACE-EVIDENCE-20260822-v001.json.
# `None` for cache write means the published table shows no separate cache-write fee.
PRICES = {
    "composer-2.5":      {"in": 0.5,  "cache_write": None, "cache_read": 0.2,  "out": 2.5,  "pool": "Cursor Models"},
    "composer-2.5-fast": {"in": 3.0,  "cache_write": None, "cache_read": 0.5,  "out": 15.0, "pool": "Cursor Models"},
    "grok-4.6":          {"in": 2.0,  "cache_write": None, "cache_read": 0.5,  "out": 6.0,  "pool": "Cursor Models"},
    "grok-4.6-fast":     {"in": 4.0,  "cache_write": None, "cache_read": 1.0,  "out": 12.0, "pool": "Cursor Models"},
    "grok-4.5":          {"in": 2.0,  "cache_write": None, "cache_read": 0.5,  "out": 6.0,  "pool": "Cursor Models"},
    "claude-opus-5":     {"in": 5.0,  "cache_write": 6.25, "cache_read": 0.5,  "out": 25.0, "pool": "Other Models"},
    "claude-sonnet-5":   {"in": 2.0,  "cache_write": 2.5,  "cache_read": 0.2,  "out": 10.0, "pool": "Other Models"},
    "claude-4.5-haiku":  {"in": 1.0,  "cache_write": 1.25, "cache_read": 0.1,  "out": 5.0,  "pool": "Other Models"},
    "gpt-5.6-sol":       {"in": 4.0,  "cache_write": 5.0,  "cache_read": 0.4,  "out": 20.0, "pool": "Other Models"},
    "gpt-5.6-terra":     {"in": 2.0,  "cache_write": 2.5,  "cache_read": 0.2,  "out": 12.0, "pool": "Other Models"},
    "gpt-5.6-luna":      {"in": 0.2,  "cache_write": 0.25, "cache_read": 0.02, "out": 1.2,  "pool": "Other Models"},
    "kimi-k2.7-code":    {"in": 0.95, "cache_write": None, "cache_read": 0.19, "out": 4.0,  "pool": "Other Models"},
}

# DOCUMENTED: https://cursor.com/docs/models-and-pricing.md and
# https://cursor.com/help/models-and-usage/usage-limits, both fetched 2026-08-23.
PLANS = {
    "Pro":      {"price_per_month": 20,  "other_models_included": 20},
    "Pro Plus": {"price_per_month": 60,  "other_models_included": 70},
    "Ultra":    {"price_per_month": 200, "other_models_included": 400},
}


def cost_for(model: str, in_mtok: float, out_mtok: float, cache_read_mtok: float, cache_write_mtok: float) -> dict:
    p = PRICES[model]
    cw = p["cache_write"] if p["cache_write"] is not None else 0.0
    parts = {
        "uncached_input": in_mtok * p["in"],
        "cache_write": cache_write_mtok * cw,
        "cache_read": cache_read_mtok * p["cache_read"],
        "output": out_mtok * p["out"],
    }
    return {"parts": {k: round(v, 4) for k, v in parts.items()}, "total": round(sum(parts.values()), 4), "pool": p["pool"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", action="store_true", help="print the documented price table and exit")
    ap.add_argument("--agents", type=int, default=1, help="how many agents fill the wave")
    ap.add_argument("--model", default="claude-opus-5", choices=sorted(PRICES))
    ap.add_argument("--input-mtok", type=float, default=1.0, help="ASSUMPTION: uncached input, millions of tokens, per agent")
    ap.add_argument("--output-mtok", type=float, default=0.15, help="ASSUMPTION: output, millions of tokens, per agent")
    ap.add_argument("--cache-read-mtok", type=float, default=0.0, help="ASSUMPTION: cached input read, millions of tokens, per agent")
    ap.add_argument("--cache-write-mtok", type=float, default=0.0, help="ASSUMPTION: cache write, millions of tokens, per agent")
    ap.add_argument("--waves-per-month", type=int, default=1)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.table:
        print(json.dumps({"prices_per_million_tokens": PRICES, "plans": PLANS,
                          "source": "https://cursor.com/docs/models-and-pricing.md",
                          "evidence_label": "DOCUMENTED", "fetched": "2026-08-23"}, indent=2))
        return 0

    per_agent = cost_for(a.model, a.input_mtok, a.output_mtok, a.cache_read_mtok, a.cache_write_mtok)
    wave = round(per_agent["total"] * a.agents, 2)
    month = round(wave * a.waves_per_month, 2)

    plan_fit = {}
    for name, p in PLANS.items():
        if per_agent["pool"] == "Other Models":
            plan_fit[name] = {
                "included_other_models": p["other_models_included"],
                "waves_covered_by_inclusion": round(p["other_models_included"] / wave, 2) if wave else None,
                "on_demand_needed_per_month": round(max(0.0, month - p["other_models_included"]), 2),
            }
        else:
            plan_fit[name] = {"note": "Draws from the Cursor Models pool, described as generous included usage rather than a dollar figure. Not computable here."}

    result = {
        "assumptions_not_measurements": {
            "input_mtok_per_agent": a.input_mtok,
            "output_mtok_per_agent": a.output_mtok,
            "cache_read_mtok_per_agent": a.cache_read_mtok,
            "cache_write_mtok_per_agent": a.cache_write_mtok,
            "warning": "These four numbers are supplied, not measured. Token consumption is not observable from inside an agent pod. Replace them with the figures on the Spending tab after one real wave.",
        },
        "documented_inputs": {
            "price_table": "https://cursor.com/docs/models-and-pricing.md",
            "plan_inclusions": "https://cursor.com/help/models-and-usage/usage-limits",
            "billing_rule": "Cloud Agents are charged at API pricing for the selected model; a larger context window can increase token usage and cost.",
            "evidence_label": "DOCUMENTED",
        },
        "model": a.model,
        "pool": per_agent["pool"],
        "cost_per_agent_usd": per_agent["total"],
        "cost_breakdown_per_agent_usd": per_agent["parts"],
        "agents_in_wave": a.agents,
        "cost_per_wave_usd": wave,
        "waves_per_month": a.waves_per_month,
        "cost_per_month_usd": month,
        "plan_fit": plan_fit,
        "where_the_real_number_is": "https://cursor.com/dashboard/usage — the Spending tab, after the wave has actually run.",
    }

    if a.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"model {a.model}  pool {per_agent['pool']}")
    print(f"  per agent   ${per_agent['total']:.2f}   {per_agent['parts']}")
    print(f"  per wave    ${wave:.2f}  ({a.agents} agents)")
    print(f"  per month   ${month:.2f}  ({a.waves_per_month} waves)")
    print()
    print("  ASSUMED, not measured: input/output/cache token volumes. Read the real numbers at")
    print("  https://cursor.com/dashboard/usage after one wave and re-run this with them.")
    print()
    for name, fit in plan_fit.items():
        print(f"  {name:<9} {fit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
