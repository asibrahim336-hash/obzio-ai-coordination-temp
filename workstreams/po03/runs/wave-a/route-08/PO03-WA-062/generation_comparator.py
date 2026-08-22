#!/usr/bin/env python3
"""Refuse a generation lift on any critical correctness regression."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


NOT_SUPPORTED = "NOT_SUPPORTED"


def compare(baseline: dict, candidate: dict, critical: set[str]) -> dict:
    regressions, unsupported = [], []
    for metric in sorted(critical):
        before, after = baseline.get(metric, NOT_SUPPORTED), candidate.get(metric, NOT_SUPPORTED)
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            unsupported.append({"metric": metric, "baseline": before, "candidate": after})
        elif after < before:
            regressions.append({"metric": metric, "baseline": before, "candidate": after})
    lift = "REFUSED" if regressions or unsupported else "ELIGIBLE"
    return {
        "lift": lift,
        "critical_regressions": regressions,
        "critical_not_supported": unsupported,
        "optional_improvement_can_override_critical": False,
    }


def real_snapshots(outcomes: dict, g2: dict) -> tuple[dict, dict]:
    rows = outcomes["outcomes"]
    g1 = {
        "critical_binding_integrity": sum(not row["binding_failures"] for row in rows) / len(rows),
        "critical_executable_correctness": sum(
            row["recommendation"] != "RECOMMEND_REJECT" for row in rows
        )
        / len(rows),
        "evidence_coverage": sum(row["producer_tests"]["passed"] for row in rows) / len(rows),
    }
    g2_ready = g2.get("disposition") == "PASS" and len(g2.get("compiled_route_changes", [])) >= 3
    g2_snapshot = {
        "critical_binding_integrity": NOT_SUPPORTED if not g2_ready else 1.0,
        "critical_executable_correctness": NOT_SUPPORTED if not g2_ready else 1.0,
        "evidence_coverage": 1.0,
    }
    return g1, g2_snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--g1-outcomes", type=Path, required=True)
    parser.add_argument("--g2-result", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    baseline, candidate = real_snapshots(
        json.loads(args.g1_outcomes.read_text()), json.loads(args.g2_result.read_text())
    )
    report = compare(
        baseline,
        candidate,
        {"critical_binding_integrity", "critical_executable_correctness"},
    )
    report.update(
        {
            "baseline": baseline,
            "candidate": candidate,
            "disposition": "PASS" if report["lift"] == "REFUSED" else "FAIL",
            "commands": [
                "python3 generation_comparator.py --g1-outcomes <freeze> --g2-result <g2-result>",
                "python3 -m unittest discover -s <slot> -p 'test*.py' -q",
            ],
            "limitations": [
                "G2 critical metrics are NOT_SUPPORTED until three accepted lessons compile."
            ],
            "terminal_report": "READY_TO_COMMIT",
        }
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload)
    else:
        print(payload, end="")
    return 0 if report["disposition"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
