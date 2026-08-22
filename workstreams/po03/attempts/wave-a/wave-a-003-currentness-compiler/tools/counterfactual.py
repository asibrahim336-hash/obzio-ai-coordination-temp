#!/usr/bin/env python3
"""Measure what a naive currentness classifier would have concluded.

Each hardening rule in the compiler is only worth keeping if a simpler rule
gives a different and worse answer on the live estate. This script replays
four naive variants over one compiled report and counts their disagreements,
so the rules are defended by measurement rather than by assertion.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

COUNTERFACTUAL_VERSION = "PO03-CURRENTNESS-COUNTERFACTUAL-v1"


def _leaf_role(key_path: str) -> str:
    named = [part for part in key_path.split("/") if part and not part.startswith("[")]
    return named[-1] if named else "root"


def naive_substring_supersession(report: dict[str, Any], prefix: str = "SUPERSEDED") -> dict[str, Any]:
    """Variant: treat any standing containing the word as a supersession."""
    flagged = {
        edge["target"]
        for edge in report["edges"]
        if isinstance(edge.get("standing"), str) and prefix in edge["standing"].upper()
    }
    actual = set(report["retained_superseded_set"])
    current = set(report["current_source_set"])
    false_exclusions = sorted(flagged & current)
    return {
        "variant": "standing_substring_supersession",
        "naive_superseded_count": len(flagged),
        "compiler_superseded_count": len(actual),
        "false_exclusions": false_exclusions,
        "changes_verdict": bool(false_exclusions),
    }


def naive_missing_reference_gate(report: dict[str, Any]) -> dict[str, Any]:
    """Variant: fail on every absent referenced path, whatever the role."""
    would_fail_on = sorted({item["target"] for item in report["declared_absent_objects"]})
    return {
        "variant": "any_absent_path_fails",
        "naive_violation_count": len(report["declared_absent_objects"]),
        "compiler_violation_count": len(report["missing_references"]),
        "false_failures": would_fail_on,
        "changes_verdict": bool(would_fail_on),
    }


def naive_any_cycle_gate(report: dict[str, Any]) -> dict[str, Any]:
    """Variant: fail on any repeated node, including self-description."""
    self_described = sorted({item["object"] for item in report["self_describing_references"]})
    back = sorted({item["referenced_by"] for item in report["non_routing_back_references"]})
    return {
        "variant": "any_repeated_node_is_a_cycle",
        "naive_violation_count": len(report["self_describing_references"])
        + len(report["non_routing_back_references"]),
        "compiler_violation_count": sum(
            1 for item in report["violations"] if item["violation"] == "ROUTING_POINTER_CYCLE"
        ),
        "false_failures": sorted(set(self_described) | set(back)),
        "changes_verdict": bool(self_described or back),
    }


def naive_leaf_key_roles(report: dict[str, Any], single_valued: list[str]) -> dict[str, Any]:
    """Variant: name the pointer role from the literal leaf key."""
    single = set(single_valued)
    hardened = {edge["role"] for edge in report["edges"]} & single
    naive = {_leaf_role(edge["key_path"]) for edge in report["edges"]} & single
    return {
        "variant": "leaf_key_role_naming",
        "single_valued_roles_detected_naively": sorted(naive),
        "single_valued_roles_detected_by_compiler": sorted(hardened),
        "lost_ambiguity_checks": sorted(hardened - naive),
        "changes_verdict": bool(hardened - naive),
    }


def evaluate(report: dict[str, Any], single_valued: list[str]) -> dict[str, Any]:
    variants = [
        naive_substring_supersession(report),
        naive_missing_reference_gate(report),
        naive_any_cycle_gate(report),
        naive_leaf_key_roles(report, single_valued),
    ]
    return {
        "counterfactual_version": COUNTERFACTUAL_VERSION,
        "source_commit": report["commit"],
        "source_determinism_digest": report["determinism_digest"],
        "compiler_gate": report["gate"],
        "variants": variants,
        "rules_defended_by_measurement": sum(variant["changes_verdict"] for variant in variants),
        "rules_evaluated": len(variants),
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare naive currentness rules against the compiler.")
    parser.add_argument("--report", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--out", default=None)
    arguments = parser.parse_args(argv)
    report = json.loads(Path(arguments.report).read_text(encoding="utf-8"))
    spec = json.loads(Path(arguments.spec).read_text(encoding="utf-8"))
    summary = evaluate(report, spec.get("single_valued_roles", []))
    payload = (json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    if arguments.out:
        Path(arguments.out).write_bytes(payload)
    print(
        f"CURRENTNESS_COUNTERFACTUAL defended={summary['rules_defended_by_measurement']}"
        f"/{summary['rules_evaluated']}"
    )
    for variant in summary["variants"]:
        print(f"  {variant['variant']}: changes_verdict={variant['changes_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
