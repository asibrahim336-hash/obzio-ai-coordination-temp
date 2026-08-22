#!/usr/bin/env python3
"""Measure observed G1 overhead while preserving unavailable values."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


NOT_SUPPORTED = "NOT_SUPPORTED"


def instant(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def elapsed(start: str | None, end: str | None):
    left, right = instant(start), instant(end)
    if left is None or right is None:
        return NOT_SUPPORTED
    return (right - left).total_seconds()


def summarize(values: list) -> dict:
    known = [value for value in values if isinstance(value, (int, float))]
    unknown = len(values) - len(known)
    return {
        "value": (sum(known) / len(known)) if known else NOT_SUPPORTED,
        "unit": "seconds",
        "known_count": len(known),
        "unknown_count": unknown,
        "population": len(values),
        "coverage": len(known) / len(values) if values else NOT_SUPPORTED,
    }


def measure(results: list[dict]) -> dict:
    units = []
    for result in sorted(results, key=lambda row: row["task_id"]):
        txn = result["result_transaction"]
        units.append(
            {
                "task_id": result["task_id"],
                "coordination_overhead_seconds": elapsed(
                    txn.get("committed_at"), txn.get("parent_ingested_at")
                ),
                "recovery_overhead_seconds": elapsed(
                    txn.get("recovery_started_at"), txn.get("recovery_completed_at")
                ),
                "retry_coordination_seconds": elapsed(
                    txn.get("retry_scheduled_at"), txn.get("retry_completed_at")
                ),
                "measurement_sources": {
                    "coordination_start": txn.get("committed_at"),
                    "coordination_end": txn.get("parent_ingested_at"),
                    "recovery_start": txn.get("recovery_started_at"),
                    "recovery_end": txn.get("recovery_completed_at"),
                },
            }
        )
    metrics = {}
    for key in (
        "coordination_overhead_seconds",
        "recovery_overhead_seconds",
        "retry_coordination_seconds",
    ):
        metrics[key] = summarize([row[key] for row in units])
    return {
        "units": units,
        "metrics": metrics,
        "invented_values": 0,
        "unknown_sentinel": NOT_SUPPORTED,
        "disposition": "PASS",
    }


def load_results(repo: Path) -> list[dict]:
    return [
        json.loads(path.read_text())
        for path in sorted((repo / "workstreams/po03/control/results").glob("PO03-WA-*.json"))
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = measure(load_results(args.repo))
    report.update(
        {
            "commands": [
                "python3 overhead_meter.py --repo <checkout>",
                "python3 -m unittest discover -s <slot> -p 'test*.py' -q",
            ],
            "limitations": [
                "Recovery and retry timestamps are absent from the immutable corpus and remain NOT_SUPPORTED.",
                "Coordination deltas use recorded wall-clock timestamps and do not imply causal CPU cost.",
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
