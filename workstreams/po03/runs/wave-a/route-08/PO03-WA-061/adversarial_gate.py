#!/usr/bin/env python3
"""Gate successor claims on evaluator-held novel and adversarial cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def gate(public_passed: bool, held_cases: list[dict]) -> dict:
    if not held_cases:
        return {"verdict": "RETEST", "reason": "no evaluator-held case was executed"}
    failures = [row["case_id"] for row in held_cases if row.get("status") == "FAIL"]
    unsupported = [
        row["case_id"] for row in held_cases if row.get("status") not in {"PASS", "FAIL"}
    ]
    if not public_passed or failures:
        return {
            "verdict": "RECOMMEND_REJECT",
            "public_passed": public_passed,
            "held_failures": failures,
            "held_unsupported": unsupported,
        }
    if unsupported:
        return {
            "verdict": "RETEST",
            "public_passed": public_passed,
            "held_failures": [],
            "held_unsupported": unsupported,
        }
    return {
        "verdict": "RECOMMEND_ACCEPT",
        "public_passed": True,
        "held_failures": [],
        "held_unsupported": [],
    }


def evaluate_reports(report_dir: Path, held_results: dict) -> dict:
    hidden = {row["task_id"]: row for row in held_results["cases"]}
    units = []
    for path in sorted(report_dir.glob("PO03-WA-*.json")):
        report = json.loads(path.read_text())
        task_id = report["task_id"]
        public_passed = all(row.get("passed") is True for row in report["tests"])
        decision = gate(public_passed, [hidden[task_id]] if task_id in hidden else [])
        units.append({"task_id": task_id, **decision})
    hidden_failures = {
        row["task_id"] for row in held_results["cases"] if row.get("status") == "FAIL"
    }
    blocked = {
        row["task_id"] for row in units if row["verdict"] != "RECOMMEND_ACCEPT"
    }
    escaped = sorted(hidden_failures - blocked)
    return {
        "units_evaluated": len(units),
        "public_pass_hidden_failures": len(hidden_failures),
        "overfit_claims_blocked": len(hidden_failures & blocked),
        "overfit_claims_escaped": escaped,
        "units": units,
        "disposition": "PASS" if units and not escaped else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--held-results", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate_reports(args.reports, json.loads(args.held_results.read_text()))
    report.update(
        {
            "commands": [
                "python3 adversarial_gate.py --reports <review-reports> --held-results <held-results>",
                "python3 -m unittest discover -s <slot> -p 'test*.py' -q",
            ],
            "limitations": [
                "The held suite is frozen for this wave; a later generation requires newly held cases."
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
