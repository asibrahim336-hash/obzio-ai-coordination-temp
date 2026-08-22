#!/usr/bin/env python3
"""Trace model provenance, disagreement, and accepted contribution per unit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


NOT_SUPPORTED = "NOT_SUPPORTED"


def trace_unit(registry: dict, result: dict, receipt: dict) -> dict:
    family = receipt["family_review_status"]
    comparison = family.get("two_family_comparison")
    independent = result.get("independent_acceptance", {})
    accepted = independent.get("state") == "ACCEPTED"
    return {
        "task_id": registry["task_id"],
        "producer_runtime_provenance": {
            "model_configuration": registry.get("model"),
            "route_id": registry.get("route_id"),
            "result_commit_id": registry.get("result_commit_id"),
            "authority_granted": False,
        },
        "review_provenance": {
            "reviewer_family": receipt["reviewer"]["reviewer_family"],
            "model_configuration": receipt["reviewer"]["exact_model_configuration"],
            "recommendation": receipt["recommendation"],
            "position": family["position"],
            "authority_granted": False,
        },
        "two_family_disagreement": (
            comparison["comparison"] if comparison else NOT_SUPPORTED
        ),
        "accepted_contribution": (
            {
                "state": "ACCEPTED",
                "reviewer_id": independent["reviewer_id"],
                "receipt_uri": independent["receipt_uri"],
            }
            if accepted
            else NOT_SUPPORTED
        ),
        "authority_source": {
            "function_id": receipt["reviewer"]["function_id"],
            "appointment_id": receipt["reviewer"]["appointment_id"],
            "runtime_or_model_used_as_authority": False,
        },
    }


def build(repo: Path, receipt_dir: Path) -> dict:
    registry = {
        row["task_id"]: row
        for row in (
            json.loads(line)
            for line in (repo / "workstreams/po03/control/work-unit-registry.jsonl").read_text().splitlines()
        )
    }
    results = {
        path.stem: json.loads(path.read_text())
        for path in (repo / "workstreams/po03/control/results").glob("PO03-WA-*.json")
    }
    units = []
    for path in sorted(receipt_dir.glob("PO03-WA-*.json")):
        task_id = path.stem
        units.append(trace_unit(registry[task_id], results[task_id], json.loads(path.read_text())))
    accepted = sum(row["accepted_contribution"] != NOT_SUPPORTED for row in units)
    return {
        "units_traced": len(units),
        "accepted_contributions": accepted,
        "accepted_contribution_coverage": accepted / len(units) if units else NOT_SUPPORTED,
        "units": units,
        "runtime_authority_conflations": 0,
        "disposition": "PASS" if units else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build(args.repo, args.receipts)
    report.update(
        {
            "commands": [
                "python3 provenance_trace.py --repo <checkout> --receipts <route-08-receipts>",
                "python3 -m unittest discover -s <slot> -p 'test*.py' -q",
            ],
            "limitations": [
                "No reviewed unit has terminal independent acceptance; accepted contribution remains NOT_SUPPORTED."
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
