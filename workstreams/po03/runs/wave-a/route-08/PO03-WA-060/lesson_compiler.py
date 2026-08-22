#!/usr/bin/env python3
"""Compile only terminally accepted G1 lessons into executable G2 changes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def accepted_lesson(result: dict) -> bool:
    acceptance = result.get("independent_acceptance", {})
    return (
        acceptance.get("state") == "ACCEPTED"
        and bool(acceptance.get("reviewer_id"))
        and bool(acceptance.get("receipt_uri"))
        and bool(result.get("result_transaction", {}).get("result_commit_id"))
    )


def compile_lessons(results: list[dict]) -> dict:
    candidates = [
        row
        for row in results
        if 41 <= int(row["task_id"].rsplit("-", 1)[1]) <= 48
    ]
    accepted = [row for row in candidates if accepted_lesson(row)]
    if len(accepted) < 3:
        return {
            "g1_candidates": len(candidates),
            "terminally_accepted_lessons": len(accepted),
            "required_lessons": 3,
            "compiled_route_changes": [],
            "recommendations_relabelled_as_acceptance": 0,
            "disposition": "NOT_YET",
            "reason": "fewer than three G1 lessons carry terminal independent acceptance",
        }
    changes = [
        {
            "change_id": f"G2-{row['task_id']}",
            "source_result_commit_id": row["result_transaction"]["result_commit_id"],
            "acceptance_receipt_uri": row["independent_acceptance"]["receipt_uri"],
            "executable_gate": {
                "require_source_commit": True,
                "require_acceptance_receipt": True,
                "fail_closed": True,
            },
        }
        for row in accepted[:3]
    ]
    return {
        "g1_candidates": len(candidates),
        "terminally_accepted_lessons": len(accepted),
        "required_lessons": 3,
        "compiled_route_changes": changes,
        "recommendations_relabelled_as_acceptance": 0,
        "disposition": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = [
        json.loads(path.read_text())
        for path in sorted((args.repo / "workstreams/po03/control/results").glob("PO03-WA-*.json"))
    ]
    report = compile_lessons(results)
    report.update(
        {
            "commands": [
                "python3 lesson_compiler.py --repo <checkout>",
                "python3 -m unittest discover -s <slot> -p 'test*.py' -q",
            ],
            "limitations": [
                "Recommendations are challenger evidence and are intentionally not treated as acceptance."
            ],
            "terminal_report": "READY_TO_COMMIT",
        }
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
