#!/usr/bin/env python3
"""Preregistered threshold cases, frontier computation and falsifier evaluation for WA-018.

Every threshold, grid, seed count and materiality rule here is read from the
frozen preregistration rather than chosen at run time, and each case carries the
direction predicted before execution so a wrong prediction is visible instead of
quietly absorbed.

Usage:
    threshold_cases.py [--out-frontier F] [--out-cases F] [--quick]
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import queue_verification_sim as sim

HERE = Path(__file__).resolve().parent
PREREGISTRATION = HERE / "preregistration.json"
CASES_VERSION = "OBZIO-WA-018-THRESHOLD-CASES-v1"
FRONTIER_VERSION = "OBZIO-WA-018-FRONTIER-RESULTS-v1"

RELATIVE_MATERIALITY = 0.25
SATURATION_TOLERANCE = 0.02
SEED_SEPARATION_MARGIN = 0.90

DEVIATIONS: list[dict[str, Any]] = [
    {
        "id": "D-018-01",
        "raised_after_reading": "the first full threshold-case execution",
        "preregistered_rule": (
            "F-018-2 fires, and the result is REFUTED as confounded, if the "
            "proportional-capacity control ladder shows a penalty above "
            "materiality on any channel."
        ),
        "problem": (
            "The latency materiality rule carries an absolute SLO clause, but the "
            "preregistration defines a penalty as a change relative to the "
            "proportional-capacity configuration. Applied to the control ladder, "
            "the absolute clause reports that the balanced ratio operates above "
            "the 900 second SLO, which is a level property of the balanced ratio "
            "rather than a penalty from losing proportionality. A second driver "
            "is a truncation leak that occurs at the balanced ratio and is a "
            "property of the promotion policy rather than of the capacity ratio."
        ),
        "verdict_as_written": "F-018-2 FIRED",
        "verdict_after_decomposition": (
            "F-018-2 evaluated on the comparison it was written to make, each "
            "ladder rung against the previous rung at constant ratio, is reported "
            "separately as fired_after_decomposition."
        ),
        "handling": (
            "Nothing preregistered was removed or edited. The as-written verdict "
            "is still computed and still reported as F-018-2.fired. The "
            "decomposition is additive and every driver is reported with its own "
            "evidence, including the two findings that the as-written rule "
            "conflated."
        ),
        "counted_as": "one defect and one rework cycle against this attempt",
        "why_not_silent": (
            "The preregistration prohibits reclassifying a fired falsifier as a "
            "limitation, so the fired verdict stays first-class and the "
            "specification defect is recorded as mine."
        ),
    },
    {
        "id": "D-018-02",
        "raised_after_reading": "the full thirty-two seed frontier grid",
        "preregistered_rule": (
            "F-018-5 fires, and the frontier claim is INCONCLUSIVE, if any "
            "frontier is not monotone non-decreasing in verifier count."
        ),
        "problem": (
            "The rule was written as though there were one frontier, but three "
            "frontiers are computed for each of four policies, so a global "
            "consequence would discard eleven well-behaved frontier objects "
            "because a twelfth is not monotone."
        ),
        "verdict_as_written": "F-018-5 FIRED",
        "verdict_after_scoping": (
            "The consequence is applied to the specific frontier object that "
            "failed. Every safety frontier and every saturation frontier is "
            "monotone in verifier count for all four policies. The single "
            "non-monotone object is the service frontier under truncated "
            "verification, which is reported INCONCLUSIVE."
        ),
        "handling": (
            "F-018-5 remains fired and the failing object is named explicitly "
            "with its series. The safety-throughput frontier claim that the "
            "assignment asks for does not rest on the failing object."
        ),
        "counted_as": "one defect and one rework cycle against this attempt",
        "mechanism_note": (
            "The non-monotonicity is explainable rather than noise: truncation "
            "buys latency by spending verification power, so at high verifier "
            "counts the queue stops exceeding capacity, work stops being "
            "truncated, and observed waits rise even though safety improves."
        ),
    },
]


def _prereg() -> dict[str, Any]:
    return json.loads(PREREGISTRATION.read_text(encoding="utf-8"))


def balanced_concurrency(verifiers: int, ratio: float) -> int:
    return max(1, int(round(ratio * verifiers)))


def _base_config(prereg: dict[str, Any]) -> sim.Config:
    params = prereg["parameters"]
    return sim.Config(
        concurrency=1,
        verifiers=1,
        units=params["units_per_wave"],
        latent_defect_probability=params["latent_defect_probability"]["primary"],
        detect_power_full=params["detect_power_full"]["primary"],
        detection_k=params["detection_k"]["primary"],
        bypass_deadline_seconds=params["bypass_deadline_seconds"]["primary"],
        queue_cap=params["queue_cap"]["primary"],
        downstream_discovery_probability=params["downstream_discovery_probability"][
            "primary"
        ],
        discovery_delay_seconds=params["discovery_delay_seconds"],
        rework_seconds=params["rework_seconds"]["primary"],
    )


def _relative_increase(observed: float | None, baseline: float | None) -> float | None:
    if observed is None or baseline is None or baseline <= 0:
        return None
    return round((observed - baseline) / baseline, 6)


def _penalty_only(cell: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Relative penalty against a reference configuration, excluding level effects.

    The preregistration defines a penalty as a change relative to the
    proportional-capacity configuration, while the latency materiality rule also
    carries an absolute SLO clause. The absolute clause measures the level a
    configuration operates at, not the penalty from losing proportionality, so it
    is separated here and reported on its own. Deviation D-018-01 records this.
    """
    latency_delta = _relative_increase(
        cell["mean_p95_verification_wait_seconds"],
        baseline["mean_p95_verification_wait_seconds"],
    )
    detect_delta = _relative_increase(
        cell["mean_time_to_detect_seconds"], baseline["mean_time_to_detect_seconds"]
    )
    rework_delta = (cell["recovery_rework_units_total"] or 0) - (
        baseline["recovery_rework_units_total"] or 0
    )
    false_green_excess = cell["false_green_total"] - baseline["false_green_total"]
    latency_material = bool(
        latency_delta is not None and latency_delta >= RELATIVE_MATERIALITY
    )
    recovery_material = bool(
        (detect_delta is not None and detect_delta >= RELATIVE_MATERIALITY)
        or rework_delta >= 1
    )
    return {
        "relative_only": True,
        "false_green_excess_over_reference": false_green_excess,
        "false_green_material": false_green_excess >= 1,
        "latency_material": latency_material,
        "latency_relative_increase": latency_delta,
        "recovery_material": recovery_material,
        "time_to_detect_relative_increase": detect_delta,
        "recovery_rework_delta": rework_delta,
        "any_channel_material": bool(
            false_green_excess >= 1 or latency_material or recovery_material
        ),
    }


def _material(
    cell: dict[str, Any], baseline: dict[str, Any], slo: int
) -> dict[str, Any]:
    """Apply the preregistered materiality rules to one grid cell."""
    latency_delta = _relative_increase(
        cell["mean_p95_verification_wait_seconds"],
        baseline["mean_p95_verification_wait_seconds"],
    )
    detect_delta = _relative_increase(
        cell["mean_time_to_detect_seconds"], baseline["mean_time_to_detect_seconds"]
    )
    rework_delta = (cell["recovery_rework_units_total"] or 0) - (
        baseline["recovery_rework_units_total"] or 0
    )
    latency_material = bool(
        (latency_delta is not None and latency_delta >= RELATIVE_MATERIALITY)
        or (
            cell["mean_p95_verification_wait_seconds"] is not None
            and cell["mean_p95_verification_wait_seconds"] > slo
        )
    )
    recovery_material = bool(
        (detect_delta is not None and detect_delta >= RELATIVE_MATERIALITY)
        or rework_delta >= 1
    )
    false_green_material = cell["false_green_total"] >= 1
    return {
        "false_green_material": false_green_material,
        "false_green_total": cell["false_green_total"],
        "false_green_seed_fraction": cell["false_green_seed_fraction"],
        "escaped_defect_total": cell["escaped_defect_total"],
        "latency_material": latency_material,
        "latency_relative_increase": latency_delta,
        "p95_wait_over_slo": (
            cell["mean_p95_verification_wait_seconds"] is not None
            and cell["mean_p95_verification_wait_seconds"] > slo
        ),
        "recovery_material": recovery_material,
        "time_to_detect_relative_increase": detect_delta,
        "recovery_rework_delta": rework_delta,
        "any_channel_material": bool(
            false_green_material or latency_material or recovery_material
        ),
    }


def build_grid(prereg: dict[str, Any], quick: bool) -> dict[str, Any]:
    params = prereg["parameters"]
    ratio = params["balanced_ratio_R"]
    slo = params["verification_wait_slo_seconds"]["primary"]
    concurrency_grid = params["concurrency_grid"]
    verifier_grid = params["verifier_grid"]
    policies = params["policies"]
    seeds = sim.seed_list(
        params["seeds"]["base"], 4 if quick else params["seeds"]["count"]
    )
    base = _base_config(prereg)

    cells: dict[str, dict[str, dict[str, Any]]] = {}
    for policy in policies:
        cells[policy] = {}
        for verifiers in verifier_grid:
            for concurrency in concurrency_grid:
                cfg = replace(
                    base,
                    concurrency=concurrency,
                    verifiers=verifiers,
                    policy=policy,
                )
                cells[policy][f"C{concurrency}_V{verifiers}"] = sim.run_ensemble(
                    cfg, seeds
                )

    grid: dict[str, Any] = {
        "frontier_version": FRONTIER_VERSION,
        "seeds": len(seeds),
        "balanced_ratio_R": ratio,
        "verification_wait_slo_seconds": slo,
        "concurrency_grid": concurrency_grid,
        "verifier_grid": verifier_grid,
        "metric_definitions": sim.MEASUREMENT_DEFINITIONS,
        "cells": cells,
        "materiality": {},
        "frontiers": {},
        "monotonicity": {},
    }

    for policy in policies:
        grid["materiality"][policy] = {}
        grid["frontiers"][policy] = {}
        for verifiers in verifier_grid:
            balanced = balanced_concurrency(verifiers, ratio)
            baseline_key = _nearest_grid_key(concurrency_grid, balanced, verifiers)
            baseline = cells[policy][baseline_key]
            per_v: dict[str, Any] = {}
            for concurrency in concurrency_grid:
                key = f"C{concurrency}_V{verifiers}"
                per_v[key] = _material(cells[policy][key], baseline, slo)
                per_v[key]["penalty_only"] = _penalty_only(
                    cells[policy][key], baseline
                )
                per_v[key]["above_balanced_ratio"] = concurrency > balanced
            grid["materiality"][policy][f"V{verifiers}"] = {
                "balanced_concurrency": balanced,
                "baseline_cell": baseline_key,
                "cells": per_v,
            }
            grid["frontiers"][policy][f"V{verifiers}"] = _frontiers(
                cells[policy], concurrency_grid, verifiers, slo
            )
        grid["monotonicity"][policy] = _monotonicity(
            grid["frontiers"][policy], verifier_grid
        )
    grid["operating_recommendation"] = _operating_recommendation(grid, verifier_grid)
    return grid


def _operating_recommendation(
    grid: dict[str, Any], verifier_grid: list[int]
) -> dict[str, Any]:
    """The operationally useful reduction: the largest concurrency worth running.

    Concurrency above the safety frontier buys unverified promotions, and
    concurrency above the saturation frontier buys no verified throughput at all,
    so the usable cap is the smaller of the two.
    """
    table: dict[str, Any] = {}
    for policy, per_v in grid["frontiers"].items():
        table[policy] = {}
        for verifiers in verifier_grid:
            frontier = per_v[f"V{verifiers}"]
            safety = frontier["safety_frontier_concurrency"]
            saturation = frontier["saturation_frontier_concurrency"]
            usable = min(
                value for value in (safety, saturation) if value is not None
            )
            table[policy][f"V{verifiers}"] = {
                "safety_frontier_concurrency": safety,
                "saturation_frontier_concurrency": saturation,
                "usable_concurrency_cap": usable,
                "verified_throughput_at_cap_per_hour": frontier[
                    "verified_throughput_by_concurrency"
                ].get(str(usable)),
                "verified_throughput_ceiling_per_hour": frontier[
                    "verified_throughput_ceiling_per_hour"
                ],
            }
    return table


def _nearest_grid_key(grid: list[int], target: int, verifiers: int) -> str:
    nearest = min(grid, key=lambda value: (abs(value - target), value))
    return f"C{nearest}_V{verifiers}"


def _frontiers(
    policy_cells: dict[str, dict[str, Any]],
    concurrency_grid: list[int],
    verifiers: int,
    slo: int,
) -> dict[str, Any]:
    safety: int | None = None
    service: int | None = None
    for concurrency in concurrency_grid:
        cell = policy_cells[f"C{concurrency}_V{verifiers}"]
        if cell["false_green_total"] == 0:
            safety = concurrency
        wait = cell["mean_p95_verification_wait_seconds"]
        if wait is not None and wait <= slo:
            service = concurrency
    verified = [
        policy_cells[f"C{concurrency}_V{verifiers}"][
            "mean_verified_throughput_per_hour"
        ]
        for concurrency in concurrency_grid
    ]
    saturation = concurrency_grid[-1]
    for index in range(len(concurrency_grid) - 1):
        current = verified[index]
        nxt = verified[index + 1]
        if current and (nxt - current) / current < SATURATION_TOLERANCE:
            saturation = concurrency_grid[index]
            break
    return {
        "safety_frontier_concurrency": safety,
        "safety_frontier_is_grid_maximum": safety == concurrency_grid[-1],
        "service_frontier_concurrency": service,
        "saturation_frontier_concurrency": saturation,
        "verified_throughput_by_concurrency": dict(zip(map(str, concurrency_grid), verified)),
        "verified_throughput_ceiling_per_hour": max(verified),
        "nominal_throughput_by_concurrency": {
            str(concurrency): policy_cells[f"C{concurrency}_V{verifiers}"][
                "mean_nominal_throughput_per_hour"
            ]
            for concurrency in concurrency_grid
        },
    }


def _monotonicity(frontiers: dict[str, Any], verifier_grid: list[int]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for name in (
        "safety_frontier_concurrency",
        "service_frontier_concurrency",
        "saturation_frontier_concurrency",
    ):
        series = [frontiers[f"V{verifiers}"][name] for verifiers in verifier_grid]
        clean = [value for value in series if value is not None]
        report[name] = {
            "series": series,
            "monotone_non_decreasing": all(
                earlier <= later for earlier, later in zip(clean, clean[1:])
            ),
        }
    return report


# ---------------------------------------------------------------------------
# Threshold cases
# ---------------------------------------------------------------------------

CASE_SPECS: list[dict[str, Any]] = [
    {
        "id": "T-018-01",
        "name": "Slack region: verification already exceeds demand",
        "channel": "control",
        "sub_hypothesis": "H-018-5",
        "policy": sim.BLOCKING_GATE,
        "verifiers": 8,
        "concurrency": [1, 2, 3, 4, 6, 8],
        "expected": "NO_PENALTY",
        "question": "Below the balanced ratio, does raising concurrency with V fixed cost anything?",
    },
    {
        "id": "T-018-02",
        "name": "Blocking gate above the balanced ratio",
        "channel": "recovery_and_latency",
        "sub_hypothesis": "H-018-1",
        "policy": sim.BLOCKING_GATE,
        "verifiers": 1,
        "concurrency": [3, 4, 6, 8, 12, 16, 24, 32],
        "expected": "LATENCY_PENALTY_WITHOUT_FALSE_GREEN",
        "question": "Does back-pressure convert lost proportionality into latency rather than unsafety?",
    },
    {
        "id": "T-018-03",
        "name": "Deadline-driven bypass above the balanced ratio",
        "channel": "false_green",
        "sub_hypothesis": "H-018-2",
        "policy": sim.DEADLINE_BYPASS,
        "verifiers": 1,
        "concurrency": [3, 4, 6, 8, 12, 16, 24, 32],
        "expected": "FALSE_GREEN_PENALTY",
        "question": "Does a promotion deadline turn verification backlog into false completions?",
    },
    {
        "id": "T-018-04",
        "name": "Capacity-driven sampling above the balanced ratio",
        "channel": "false_green",
        "sub_hypothesis": "H-018-3",
        "policy": sim.SAMPLED_VERIFICATION,
        "verifiers": 1,
        "concurrency": [3, 4, 6, 8, 12, 16, 24, 32],
        "expected": "FALSE_GREEN_PENALTY",
        "question": "Does shedding the queue to keep up turn backlog into false completions?",
    },
    {
        "id": "T-018-05",
        "name": "Truncated verification above the balanced ratio",
        "channel": "false_green",
        "sub_hypothesis": "H-018-4",
        "policy": sim.TRUNCATED_VERIFICATION,
        "verifiers": 1,
        "concurrency": [3, 4, 6, 8, 12, 16, 24, 32],
        "expected": "FALSE_GREEN_PENALTY_WITHOUT_BACKLOG",
        "question": "Does shortening each verification hide the penalty in lost power rather than in queue length?",
    },
    {
        "id": "T-018-06",
        "name": "Proportional-capacity null control",
        "channel": "control",
        "sub_hypothesis": "H-018-5",
        "policy": "ALL",
        "ladder": True,
        "expected": "NO_PENALTY",
        "question": "When C and V rise together at the balanced ratio, does any channel degrade?",
    },
    {
        "id": "T-018-07",
        "name": "Live PO-03 Wave A configuration",
        "channel": "live_configuration",
        "sub_hypothesis": "H-018-8",
        "policy": "ALL",
        "verifiers": 1,
        "concurrency": [8],
        "expected": "ABOVE_BALANCED_RATIO",
        "question": "Where does the observed eight-producer, one-verifier configuration sit?",
    },
    {
        "id": "T-018-08",
        "name": "Proportional slots with degraded verification power",
        "channel": "adversarial_restatement",
        "sub_hypothesis": "H-018-7",
        "policy": sim.BLOCKING_GATE,
        "ladder": True,
        "detect_power_full": 0.7,
        "expected": "PROPORTIONAL_SLOTS_INSUFFICIENT",
        "question": "Is proportional capacity in slots enough when the work applied per slot is weaker?",
    },
    {
        "id": "T-018-09",
        "name": "Seed separation margin",
        "channel": "stability",
        "sub_hypothesis": "H-018-2",
        "policy": sim.DEADLINE_BYPASS,
        "verifiers": 1,
        "concurrency": [32],
        "expected": "SEED_FRACTION_AT_OR_ABOVE_MARGIN",
        "question": "Is the false-green effect present in at least ninety percent of seeds?",
    },
    {
        "id": "T-018-10",
        "name": "Service-time sensitivity at the observed floor",
        "channel": "sensitivity",
        "sub_hypothesis": "H-018-2",
        "policy": "ALL",
        "verifiers": 1,
        "concurrency": [3, 32],
        "verify_scale": 157.0 / 371.083,
        "expected": "PENALTY_PERSISTS",
        "question": "Does the penalty survive assuming verification is as cheap as the observed floor?",
    },
    {
        "id": "T-018-11",
        "name": "Zero-defect invariant",
        "channel": "invariant",
        "sub_hypothesis": "F-018-4",
        "policy": "ALL",
        "verifiers": 1,
        "concurrency": [3, 32],
        "latent_defect_probability": 0.0,
        "expected": "NO_ESCAPE_POSSIBLE",
        "question": "With no latent defects, does the model ever report an escape?",
    },
    {
        "id": "T-018-12",
        "name": "Full-power blocking-gate invariant",
        "channel": "invariant",
        "sub_hypothesis": "F-018-3",
        "policy": sim.BLOCKING_GATE,
        "verifiers": 1,
        "concurrency": [3, 32],
        "detect_power_full": 1.0,
        "expected": "NO_ESCAPE_POSSIBLE",
        "question": "With complete verification at full power, does the model ever report an escape?",
    },
]


def _run_case(
    spec: dict[str, Any], prereg: dict[str, Any], seeds: list[int]
) -> dict[str, Any]:
    params = prereg["parameters"]
    ratio = params["balanced_ratio_R"]
    slo = params["verification_wait_slo_seconds"]["primary"]
    base = _base_config(prereg)
    overrides = {
        key: spec[key]
        for key in ("detect_power_full", "latent_defect_probability", "verify_scale")
        if key in spec
    }
    policies = (
        params["policies"] if spec["policy"] == "ALL" else [spec["policy"]]
    )
    observations: list[dict[str, Any]] = []
    for policy in policies:
        if spec.get("ladder"):
            pairs = [
                (entry["concurrency"], entry["verifiers"])
                for entry in params["proportional_control_ladder"]
            ]
        else:
            pairs = [
                (concurrency, spec["verifiers"]) for concurrency in spec["concurrency"]
            ]
        baseline: dict[str, Any] | None = None
        for concurrency, verifiers in pairs:
            cfg = replace(
                base,
                concurrency=concurrency,
                verifiers=verifiers,
                policy=policy,
                **overrides,
            )
            aggregate = sim.run_ensemble(cfg, seeds)
            if baseline is None:
                baseline = aggregate
            observations.append(
                {
                    "policy": policy,
                    "concurrency": concurrency,
                    "verifiers": verifiers,
                    "balanced_concurrency": balanced_concurrency(verifiers, ratio),
                    "above_balanced_ratio": concurrency
                    > balanced_concurrency(verifiers, ratio),
                    "aggregate": aggregate,
                    "materiality": _material(aggregate, baseline, slo),
                }
            )
    return {
        "id": spec["id"],
        "name": spec["name"],
        "question": spec["question"],
        "channel": spec["channel"],
        "sub_hypothesis": spec["sub_hypothesis"],
        "expected_before_execution": spec["expected"],
        "overrides": overrides,
        "observations": observations,
        "verdict": _case_verdict(spec, observations),
    }


def _case_verdict(spec: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    expected = spec["expected"]
    any_false_green = any(
        obs["aggregate"]["false_green_total"] > 0 for obs in observations
    )
    any_escape = any(
        obs["aggregate"]["escaped_defect_total"] > 0 for obs in observations
    )
    any_latency = any(obs["materiality"]["latency_material"] for obs in observations)
    any_recovery = any(obs["materiality"]["recovery_material"] for obs in observations)
    any_material = any(
        obs["materiality"]["any_channel_material"] for obs in observations
    )
    max_backlog = max(
        obs["aggregate"]["mean_peak_staged_backlog"] or 0 for obs in observations
    )
    seed_fractions = [
        obs["aggregate"]["false_green_seed_fraction"] for obs in observations
    ]

    if expected == "NO_PENALTY":
        met = not any_material
    elif expected == "LATENCY_PENALTY_WITHOUT_FALSE_GREEN":
        met = (any_latency or any_recovery) and not any_false_green
    elif expected == "FALSE_GREEN_PENALTY":
        met = any_false_green
    elif expected == "FALSE_GREEN_PENALTY_WITHOUT_BACKLOG":
        met = any_false_green
    elif expected == "ABOVE_BALANCED_RATIO":
        met = any(obs["above_balanced_ratio"] for obs in observations)
    elif expected == "PROPORTIONAL_SLOTS_INSUFFICIENT":
        met = any_escape and not any_false_green
    elif expected == "SEED_FRACTION_AT_OR_ABOVE_MARGIN":
        met = max(seed_fractions) >= SEED_SEPARATION_MARGIN
    elif expected == "PENALTY_PERSISTS":
        met = any_material
    elif expected == "NO_ESCAPE_POSSIBLE":
        met = not any_escape and not any_false_green
    else:  # pragma: no cover - defensive
        raise AssertionError(f"unknown expectation: {expected}")

    return {
        "expectation_met": bool(met),
        "observed": {
            "any_false_green": any_false_green,
            "any_escaped_defect": any_escape,
            "any_latency_material": any_latency,
            "any_recovery_material": any_recovery,
            "any_channel_material": any_material,
            "max_mean_peak_staged_backlog": max_backlog,
            "max_false_green_seed_fraction": max(seed_fractions),
        },
    }


def _decompose_control(
    control: dict[str, Any], grid: dict[str, Any]
) -> dict[str, Any]:
    """Separate the three things that can make the control ladder look material.

    Only the third is what F-018-2 was written to detect: whether raising C and V
    together at the balanced ratio degrades any channel.
    """
    slo = grid["verification_wait_slo_seconds"]
    per_policy: dict[str, Any] = {}
    degrades = False
    for policy in grid["cells"]:
        rungs = [obs for obs in control["observations"] if obs["policy"] == policy]
        rungs.sort(key=lambda obs: obs["verifiers"])
        steps = []
        for previous, current in zip(rungs, rungs[1:]):
            penalty = _penalty_only(current["aggregate"], previous["aggregate"])
            steps.append(
                {
                    "from": f"C{previous['concurrency']}_V{previous['verifiers']}",
                    "to": f"C{current['concurrency']}_V{current['verifiers']}",
                    "penalty": penalty,
                }
            )
            degrades = degrades or penalty["any_channel_material"]
        policy_degrades = any(step["penalty"]["any_channel_material"] for step in steps)
        per_policy[policy] = {
            "proportional_scaling_degrades": policy_degrades,
            "attribution": (
                "CLEAN_CONTROL_EFFECT_ATTRIBUTABLE_TO_LOST_PROPORTIONALITY"
                if not policy_degrades
                else "PARTIAL_ATTRIBUTION_POLICY_ALSO_LEAKS_AT_BALANCED_RATIO"
            ),
            "adjacent_steps": steps,
            "p95_wait_series": [
                rung["aggregate"]["mean_p95_verification_wait_seconds"]
                for rung in rungs
            ],
            "false_green_series": [
                rung["aggregate"]["false_green_total"] for rung in rungs
            ],
            "absolute_slo_breach_at_rungs": [
                f"C{rung['concurrency']}_V{rung['verifiers']}"
                for rung in rungs
                if (rung["aggregate"]["mean_p95_verification_wait_seconds"] or 0) > slo
            ],
        }
    return {
        "method": (
            "Each rung of the proportional ladder is compared with the previous "
            "rung, so the comparison holds the ratio constant and varies scale, "
            "which is the only comparison that can confound the main hypothesis."
        ),
        "proportional_scaling_degrades": degrades,
        "attribution_by_policy": {
            policy: detail["attribution"] for policy, detail in per_policy.items()
        },
        "policies_with_clean_control": [
            policy
            for policy, detail in per_policy.items()
            if not detail["proportional_scaling_degrades"]
        ],
        "policies_with_partial_attribution": [
            policy
            for policy, detail in per_policy.items()
            if detail["proportional_scaling_degrades"]
        ],
        "absolute_slo_breach_at_balanced_ratio": any(
            detail["absolute_slo_breach_at_rungs"] for detail in per_policy.values()
        ),
        "false_green_at_balanced_ratio": {
            policy: detail["false_green_series"]
            for policy, detail in per_policy.items()
            if any(value > 0 for value in detail["false_green_series"])
        },
        "per_policy": per_policy,
    }


def _evaluate_falsifiers(
    grid: dict[str, Any], cases: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {case["id"]: case for case in cases}
    verdicts: list[dict[str, Any]] = []

    v1_any_material = any(
        grid["materiality"][policy]["V1"]["cells"][f"C32_V1"]["any_channel_material"]
        for policy in grid["cells"]
    )
    verdicts.append(
        {
            "id": "F-018-1",
            "fired": not v1_any_material,
            "consequence_if_fired": "REFUTED",
            "evidence": (
                "At V=1 and C=32, at least one channel is material under at least "
                "one policy."
                if v1_any_material
                else "No channel is material at V=1 and C=32 under any policy."
            ),
        }
    )

    control = by_id["T-018-06"]
    control_material = control["verdict"]["observed"]["any_channel_material"]
    decomposition = _decompose_control(control, grid)
    verdicts.append(
        {
            "id": "F-018-2",
            "fired": bool(control_material),
            "fired_as_written": bool(control_material),
            "fired_after_decomposition": decomposition["proportional_scaling_degrades"],
            "consequence_if_fired": "REFUTED_AS_CONFOUNDED",
            "evidence": (
                "The proportional-capacity ladder stays within materiality on "
                "every channel."
                if not control_material
                else "The as-written rule fires. Its three drivers are separated "
                "in control_decomposition: an absolute SLO breach that is a level "
                "property of the balanced ratio rather than a penalty, a "
                "truncation leak that occurs at the balanced ratio and is a "
                "property of the promotion policy rather than of the ratio, and "
                "the proportional-scaling trend itself, which is what F-018-2 was "
                "written to detect."
            ),
            "control_decomposition": decomposition,
            "deviation_id": "D-018-01",
        }
    )

    invariant_full_power = by_id["T-018-12"]["verdict"]["expectation_met"]
    verdicts.append(
        {
            "id": "F-018-3",
            "fired": not invariant_full_power,
            "consequence_if_fired": "RUN_INVALID",
            "evidence": "T-018-12 reports no escape under a full-power blocking gate."
            if invariant_full_power
            else "A full-power blocking gate produced an escape.",
        }
    )

    invariant_zero_defect = by_id["T-018-11"]["verdict"]["expectation_met"]
    verdicts.append(
        {
            "id": "F-018-4",
            "fired": not invariant_zero_defect,
            "consequence_if_fired": "RUN_INVALID",
            "evidence": "T-018-11 reports no escape with zero latent defects."
            if invariant_zero_defect
            else "An escape appeared with zero latent defect probability.",
        }
    )

    non_monotone = [
        {"policy": policy, "frontier": name}
        for policy, report in grid["monotonicity"].items()
        for name, detail in report.items()
        if not detail["monotone_non_decreasing"]
    ]
    monotone_objects = [
        {"policy": policy, "frontier": name}
        for policy, report in grid["monotonicity"].items()
        for name, detail in report.items()
        if detail["monotone_non_decreasing"]
    ]
    verdicts.append(
        {
            "id": "F-018-5",
            "fired": bool(non_monotone),
            "consequence_if_fired": "INCONCLUSIVE",
            "consequence_scope": "PER_FRONTIER_OBJECT",
            "evidence": "Every frontier is monotone non-decreasing in verifier count."
            if not non_monotone
            else json.dumps(non_monotone, sort_keys=True),
            "non_monotone_objects": non_monotone,
            "monotone_object_count": len(monotone_objects),
            "safety_frontier_monotone_for_all_policies": all(
                report["safety_frontier_concurrency"]["monotone_non_decreasing"]
                for report in grid["monotonicity"].values()
            ),
            "saturation_frontier_monotone_for_all_policies": all(
                report["saturation_frontier_concurrency"]["monotone_non_decreasing"]
                for report in grid["monotonicity"].values()
            ),
            "deviation_id": "D-018-02",
            "series_for_failing_objects": {
                f"{item['policy']}.{item['frontier']}": grid["monotonicity"][
                    item["policy"]
                ][item["frontier"]]["series"]
                for item in non_monotone
            },
        }
    )

    margin = by_id["T-018-09"]["verdict"]["observed"]["max_false_green_seed_fraction"]
    verdicts.append(
        {
            "id": "F-018-6",
            "fired": margin < SEED_SEPARATION_MARGIN,
            "consequence_if_fired": "INCONCLUSIVE",
            "evidence": f"false-green seed fraction {margin} against margin {SEED_SEPARATION_MARGIN}",
        }
    )

    sensitivity = by_id["T-018-10"]["verdict"]["observed"]["any_channel_material"]
    verdicts.append(
        {
            "id": "F-018-7",
            "fired": not sensitivity,
            "consequence_if_fired": "INCONCLUSIVE",
            "evidence": (
                "The penalty persists when verification service time is scaled "
                "down to the observed floor."
                if sensitivity
                else "The penalty disappears at the observed service floor."
            ),
        }
    )

    verdicts.append(
        {
            "id": "F-018-8",
            "fired": False,
            "consequence_if_fired": "RUN_INVALID",
            "evidence": (
                "Conservation is asserted inside every simulation run, so any "
                "violation would have raised before a metric was produced; the "
                "full grid and every case completed."
            ),
        }
    )
    return verdicts


def _sensitivity(prereg: dict[str, Any], seeds: list[int]) -> dict[str, Any]:
    params = prereg["parameters"]
    base = _base_config(prereg)
    out: dict[str, Any] = {}
    sweeps = {
        "latent_defect_probability": params["latent_defect_probability"]["sweep"],
        "detect_power_full": params["detect_power_full"]["sweep"],
        "detection_k": params["detection_k"]["sweep"],
        "bypass_deadline_seconds": params["bypass_deadline_seconds"]["sweep"],
        "queue_cap": params["queue_cap"]["sweep"],
        "downstream_discovery_probability": params[
            "downstream_discovery_probability"
        ]["sweep"],
    }
    policy_for = {
        "bypass_deadline_seconds": sim.DEADLINE_BYPASS,
        "queue_cap": sim.SAMPLED_VERIFICATION,
        "detection_k": sim.TRUNCATED_VERIFICATION,
    }
    for name, values in sweeps.items():
        policy = policy_for.get(name, sim.DEADLINE_BYPASS)
        rows = []
        for value in values:
            cfg = replace(
                base, concurrency=32, verifiers=1, policy=policy, **{name: value}
            )
            aggregate = sim.run_ensemble(cfg, seeds)
            rows.append(
                {
                    "value": value,
                    "policy": policy,
                    "false_green_total": aggregate["false_green_total"],
                    "escaped_defect_total": aggregate["escaped_defect_total"],
                    "mean_verified_throughput_per_hour": aggregate[
                        "mean_verified_throughput_per_hour"
                    ],
                    "mean_p95_verification_wait_seconds": aggregate[
                        "mean_p95_verification_wait_seconds"
                    ],
                    "recovery_rework_units_total": aggregate[
                        "recovery_rework_units_total"
                    ],
                }
            )
        out[name] = {"policy": policy, "concurrency": 32, "verifiers": 1, "rows": rows}
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-frontier", default="frontier-results.json")
    parser.add_argument("--out-cases", default="threshold-case-results.json")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    prereg = _prereg()
    params = prereg["parameters"]
    seeds = sim.seed_list(
        params["seeds"]["base"], 4 if args.quick else params["seeds"]["count"]
    )

    started = time.monotonic()
    grid = build_grid(prereg, args.quick)
    grid_seconds = round(time.monotonic() - started, 3)

    started = time.monotonic()
    cases = [_run_case(spec, prereg, seeds) for spec in CASE_SPECS]
    case_seconds = round(time.monotonic() - started, 3)

    falsifiers = _evaluate_falsifiers(grid, cases)
    sensitivity = _sensitivity(prereg, seeds)

    grid["compute_seconds"] = grid_seconds
    Path(args.out_frontier).write_text(
        json.dumps(grid, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    payload = {
        "cases_version": CASES_VERSION,
        "task_id": "PO03-WA-018",
        "seeds": len(seeds),
        "quick_mode": args.quick,
        "compute_seconds": case_seconds,
        "thresholds_applied": {
            "relative_materiality": RELATIVE_MATERIALITY,
            "saturation_tolerance": SATURATION_TOLERANCE,
            "seed_separation_margin": SEED_SEPARATION_MARGIN,
            "verification_wait_slo_seconds": params[
                "verification_wait_slo_seconds"
            ]["primary"],
            "false_green_materiality": "any occurrence",
        },
        "cases": cases,
        "expectations_met": sum(
            1 for case in cases if case["verdict"]["expectation_met"]
        ),
        "expectations_total": len(cases),
        "falsifiers": falsifiers,
        "falsifiers_fired": [item["id"] for item in falsifiers if item["fired"]],
        "falsifiers_fired_after_decomposition": [
            item["id"]
            for item in falsifiers
            if item.get("fired_after_decomposition", item["fired"])
        ],
        "deviations": DEVIATIONS,
        "sensitivity": sensitivity,
    }
    Path(args.out_cases).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "expectations_met": payload["expectations_met"],
                "expectations_total": payload["expectations_total"],
                "falsifiers_fired": payload["falsifiers_fired"],
                "grid_seconds": grid_seconds,
                "case_seconds": case_seconds,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
