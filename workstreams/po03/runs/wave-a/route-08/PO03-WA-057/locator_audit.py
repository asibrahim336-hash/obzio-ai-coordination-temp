#!/usr/bin/env python3
"""Audit counted PO-03 units for one immutable locator and legal disposition."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


LEGAL_RESULT_STATES = {"COMPLETED"}
LEGAL_ACCEPTANCE = {"PENDING", "ACCEPTED", "REJECTED"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_rows(registry_rows: list[dict], completion_rows: list[dict], root: Path) -> dict:
    by_task: dict[str, list[dict]] = {}
    for row in completion_rows:
        by_task.setdefault(row["task_id"], []).append(row)
    findings = []
    counted = [row for row in registry_rows if row.get("obzio_state") == "COMPLETED"]
    for unit in sorted(counted, key=lambda row: row["task_id"]):
        task_id = unit["task_id"]
        locators = by_task.get(task_id, [])
        defects = []
        if len(locators) != 1:
            defects.append(f"expected_one_locator_observed_{len(locators)}")
        if locators:
            locator = locators[0]
            path = root / locator["result_uri"]
            if not path.is_file():
                defects.append("result_uri_missing")
            else:
                observed = sha256(path)
                if observed != locator["completed_receipt_sha256"]:
                    defects.append("completed_receipt_hash_mismatch")
                result = json.loads(path.read_text())
                if result.get("obzio_state") not in LEGAL_RESULT_STATES:
                    defects.append("illegal_result_disposition")
                acceptance = result.get("independent_acceptance", {}).get("state")
                if acceptance not in LEGAL_ACCEPTANCE:
                    defects.append("illegal_acceptance_disposition")
                if result.get("result_transaction", {}).get("result_commit_id") != locator.get(
                    "result_commit_id"
                ):
                    defects.append("result_commit_locator_mismatch")
        findings.append(
            {
                "task_id": task_id,
                "locator_count": len(locators),
                "result_uri": locators[0]["result_uri"] if locators else None,
                "result_commit_id": locators[0].get("result_commit_id") if locators else None,
                "defects": defects,
            }
        )
    return {
        "counted_units": len(counted),
        "audited_units": len(findings),
        "units_with_defects": sum(bool(row["defects"]) for row in findings),
        "findings": findings,
        "disposition": "PASS" if findings and not any(row["defects"] for row in findings) else "FAIL",
    }


def load_real(root: Path) -> tuple[list[dict], list[dict]]:
    registry = [
        json.loads(line)
        for line in (root / "workstreams/po03/control/work-unit-registry.jsonl").read_text().splitlines()
    ]
    completions = []
    for path in sorted((root / "workstreams/po03/control/completions").glob("route-*.json")):
        completions.extend(json.loads(path.read_text()).get("task_results", []))
    return registry, completions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    registry, completions = load_real(args.repo)
    report = audit_rows(registry, completions, args.repo)
    report.update(
        {
            "commands": [
                "python3 locator_audit.py --repo <checkout>",
                "python3 -m unittest discover -s <slot> -p 'test*.py' -q",
            ],
            "limitations": [
                "The audit covers units counted COMPLETED in the immutable work-unit registry."
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
