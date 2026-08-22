#!/usr/bin/env python3
"""a7-u05: derive queue/active/wall/review time per unit from ledger
timestamps and report coordination overhead as a computed ratio.

Reuses the per-unit timestamps already derived by a7-u02's
work-unit-runs.jsonl (itself ledger-only) rather than re-deriving them, so
the two artifacts cannot silently disagree. This tool adds the aggregate
ratio and the per-unit breakdown table that a7-u05's acceptance requires.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def compute(root: Path) -> dict[str, Any]:
    runs_path = root / "workstreams/po03/metrics/work-unit-runs.jsonl"
    all_rows = load_jsonl(runs_path)
    meta = next(r for r in all_rows if r["record_type"] == "generation_metadata")
    unit_rows = [r for r in all_rows if r["record_type"] == "unit_run"]

    per_unit = []
    for row in sorted(unit_rows, key=lambda r: r["unit_id"]):
        per_unit.append(
            {
                "unit_id": row["unit_id"],
                "queue_time_seconds": row["queue_time_seconds"],
                "active_time_seconds": row["active_time_seconds"],
                "wall_time_seconds": row["wall_time_seconds"],
                "review_time_seconds": row["review_time_seconds"],
            }
        )

    units_with_wall_time = [r for r in unit_rows if r["wall_time_seconds"] is not None]
    total_wall = sum(r["wall_time_seconds"] for r in units_with_wall_time)
    total_queue_over_wall_units = sum(
        (r["queue_time_seconds"] or 0) for r in units_with_wall_time
    )
    total_review_over_wall_units = sum(
        (r["review_time_seconds"] or 0) for r in units_with_wall_time
    )
    overhead_numerator = total_queue_over_wall_units + total_review_over_wall_units

    if units_with_wall_time:
        coordination_overhead_ratio = {
            "numerator_seconds": overhead_numerator,
            "denominator_seconds": total_wall,
            "value": overhead_numerator / total_wall if total_wall else "UNDEFINED_0_OF_0",
            "denominator_unit_count": len(units_with_wall_time),
        }
    else:
        coordination_overhead_ratio = {
            "numerator_seconds": 0,
            "denominator_seconds": 0,
            "denominator_unit_count": 0,
            "value": "UNDEFINED_0_OF_0",
        }

    units_with_queue_time = [r for r in unit_rows if r["queue_time_seconds"] is not None]
    if units_with_queue_time:
        queue_values = [r["queue_time_seconds"] for r in units_with_queue_time]
        queue_time_summary = {
            "numerator_sum_seconds": sum(queue_values),
            "denominator_unit_count": len(queue_values),
            "mean_seconds": sum(queue_values) / len(queue_values),
            "min_seconds": min(queue_values),
            "max_seconds": max(queue_values),
        }
    else:
        queue_time_summary = {"numerator_sum_seconds": 0, "denominator_unit_count": 0, "value": "UNDEFINED_0_OF_0"}

    units_with_review_time = [r for r in unit_rows if r["review_time_seconds"] is not None]
    if units_with_review_time:
        review_values = [r["review_time_seconds"] for r in units_with_review_time]
        review_time_summary = {
            "numerator_sum_seconds": sum(review_values),
            "denominator_unit_count": len(review_values),
            "mean_seconds": sum(review_values) / len(review_values),
        }
    else:
        review_time_summary = {"numerator_sum_seconds": 0, "denominator_unit_count": 0, "value": "UNDEFINED_0_OF_0"}

    return {
        "protocol_version": "OBZIO-COORDINATION-OVERHEAD-v1",
        "unit_id": "a7-u05",
        "measured_against": {
            "ledger_head_sha256": meta["ledger_head_sha256"],
            "ledger_rows": meta["ledger_rows"],
        },
        "denominator_units_total": len(unit_rows),
        "coordination_overhead_ratio": coordination_overhead_ratio,
        "queue_time_summary": queue_time_summary,
        "review_time_summary": review_time_summary,
        "per_unit": per_unit,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="workstreams/po03/metrics/coordination-overhead-report.json")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    report = compute(root)

    out_path = root / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(canonical({"wrote": str(out_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
