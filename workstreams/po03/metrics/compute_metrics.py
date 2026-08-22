#!/usr/bin/env python3
"""a7-u03: compute every report-level rate with an explicit numerator and
denominator, reproducibly, from committed inputs.

Inputs are exactly: workstreams/po03/metrics/work-unit-runs.jsonl (a7-u02's
ledger-derived rows), workstreams/po03/control/events/ledger.jsonl (for
events that are not per-unit, such as DUPLICATE_IGNORED and FENCE_REJECTED
counts and founder-actor rows), and workstreams/po03/control/wave-a-spec.json
(for the declared-unit denominator). No value here is invented: a metric
whose denominator is currently zero is reported as ``UNDEFINED_0_OF_0`` with
the denominator stated, never as 0 or 100%.

This tool intentionally excludes coordination_overhead_ratio (a7-u05) and
per_model_contribution / per_model_disagreement (a7-u06), which have their
own dedicated tools and frozen acceptance texts.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


TERMINAL_OUTCOMES = {"PASS", "FAIL"}
COMMITTED_STATES = {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"}
TERMINAL_STATES = COMMITTED_STATES | {"FAILED_TERMINAL", "CANCELLED"}


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rate(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator == 0:
        return {"numerator": numerator, "denominator": 0, "value": "UNDEFINED_0_OF_0"}
    return {"numerator": numerator, "denominator": denominator, "value": numerator / denominator}


def compute(root: Path) -> dict[str, Any]:
    control_plane = _load_module(root / "workstreams/po03/tools/control_plane.py", "control_plane_ro")
    ledger_rows = control_plane.ledger_rows()
    chain_errors = control_plane.verify_chain(ledger_rows)
    if chain_errors:
        raise SystemExit("ledger chain invalid: " + "; ".join(chain_errors))
    units_projection = control_plane.project_units(ledger_rows)

    runs_path = root / "workstreams/po03/metrics/work-unit-runs.jsonl"
    all_rows = load_jsonl(runs_path)
    meta = next(r for r in all_rows if r["record_type"] == "generation_metadata")
    unit_rows = [r for r in all_rows if r["record_type"] == "unit_run"]

    wave_spec = json.loads((root / "workstreams/po03/control/wave-a-spec.json").read_text(encoding="utf-8"))
    declared_units = wave_spec["declared_units"]

    # --- independently_accepted_throughput ---
    accepted_count = sum(1 for r in unit_rows if r["independent_disposition"] == "ACCEPTED")
    independently_accepted_throughput = rate(accepted_count, declared_units)

    # --- first_pass_acceptance_rate ---
    terminal_rows = [r for r in unit_rows if r["first_pass_outcome"] in TERMINAL_OUTCOMES]
    pass_count = sum(1 for r in terminal_rows if r["first_pass_outcome"] == "PASS")
    first_pass_acceptance_rate = rate(pass_count, len(terminal_rows))

    # --- escaped_defect_rate ---
    accepted_units = {r["unit_id"] for r in unit_rows if r["independent_disposition"] == "ACCEPTED"}
    rows_by_unit: dict[str, list[dict[str, Any]]] = {}
    for row in ledger_rows:
        rows_by_unit.setdefault(row["unit_id"], []).append(row)
    escaped_defect_count = 0
    for unit_id in accepted_units:
        unit_ledger_rows = rows_by_unit.get(unit_id, [])
        accepted_seq = next(r["seq"] for r in unit_ledger_rows if r["event"] == "ACCEPTED")
        if any(r["seq"] > accepted_seq and r["event"] == "REJECTED" for r in unit_ledger_rows):
            escaped_defect_count += 1
    escaped_defect_rate = rate(escaped_defect_count, len(accepted_units))

    # --- cycle_time (wall_time_seconds distribution) ---
    wall_times = sorted(r["wall_time_seconds"] for r in unit_rows if r["wall_time_seconds"] is not None)
    if wall_times:
        n = len(wall_times)
        mid = n // 2
        median = wall_times[mid] if n % 2 else (wall_times[mid - 1] + wall_times[mid]) / 2
        cycle_time = {
            "numerator_sum_seconds": sum(wall_times),
            "denominator_unit_count": n,
            "mean_seconds": sum(wall_times) / n,
            "median_seconds": median,
        }
    else:
        cycle_time = {"numerator_sum_seconds": 0, "denominator_unit_count": 0, "value": "UNDEFINED_0_OF_0"}

    # --- recovery_time ---
    recovery_gaps: list[float] = []
    for unit_id, rows in rows_by_unit.items():
        expiry_events = [r for r in rows if r["event"] in {"LEASE_EXPIRED", "RECOVERY_REQUIRED"}]
        leased_events = [r for r in rows if r["event"] == "LEASED"]
        for expiry in expiry_events:
            later_higher_fence = [
                r for r in leased_events if r["seq"] > expiry["seq"] and int(r["fence_token"]) > int(expiry.get("fence_token") or 0)
            ]
            if later_higher_fence:
                next_lease = min(later_higher_fence, key=lambda r: r["seq"])
                gap = MODULE_SECONDS_BETWEEN(expiry["ts"], next_lease["ts"])
                if gap is not None:
                    recovery_gaps.append(gap)
    if recovery_gaps:
        recovery_time = {
            "numerator_sum_seconds": sum(recovery_gaps),
            "denominator_pair_count": len(recovery_gaps),
            "mean_seconds": sum(recovery_gaps) / len(recovery_gaps),
        }
    else:
        recovery_time = {"numerator_sum_seconds": 0, "denominator_pair_count": 0, "value": "UNDEFINED_0_OF_0"}

    # --- founder_interventions ---
    founder_rows = [r for r in ledger_rows if str(r.get("actor", "")).lower() == "founder"]
    founder_interventions = rate(len(founder_rows), len(ledger_rows))

    # --- orphan / duplicate / collision / false-complete counts ---
    orphan_units = sorted(
        unit_id
        for unit_id, unit in units_projection.items()
        if unit["obzio_state"] not in TERMINAL_STATES and not unit.get("lease")
    )
    duplicate_count = sum(1 for r in ledger_rows if r["event"] == "DUPLICATE_IGNORED")
    collision_count = sum(1 for r in ledger_rows if r["event"] == "FENCE_REJECTED")
    false_complete_units = sorted(
        unit_id
        for unit_id, unit in units_projection.items()
        if unit["obzio_state"] in COMMITTED_STATES and not unit.get("result_commit_id")
    )

    # --- research_to_reproduction_conversion (NOT_YET check) ---
    hypotheses_path = root / "workstreams/po03/research/hypotheses.jsonl"
    reproduction_path = root / "workstreams/po03/research/reproduction-ledger.jsonl"
    if hypotheses_path.exists() and reproduction_path.exists():
        hyp_rows = load_jsonl(hypotheses_path)
        repro_rows = load_jsonl(reproduction_path)
        research_to_reproduction_conversion = rate(len(repro_rows), len(hyp_rows))
    else:
        research_to_reproduction_conversion = {
            "value": "NOT_YET",
            "boundary": "workstreams/po03/research/ (owned by po03-worker-a5) is absent from the tree at measurement time.",
        }

    # --- lesson_to_live_change_conversion (NOT_YET check) ---
    lesson_lineage_candidates = [
        root / "workstreams/po03/successor/lesson-lineage.json",
        root / "workstreams/po03/research/lesson-lineage.json",
    ]
    lesson_path = next((p for p in lesson_lineage_candidates if p.exists()), None)
    if lesson_path is not None:
        lineage = json.loads(lesson_path.read_text(encoding="utf-8"))
        lessons = lineage.get("lessons", [])
        converted = sum(1 for lesson in lessons if lesson.get("disposition") in {"RETAIN", "SUPERSEDE", "RETEST"})
        lesson_to_live_change_conversion = rate(converted, len(lessons))
    else:
        lesson_to_live_change_conversion = {
            "value": "NOT_YET",
            "boundary": "Neither workstreams/po03/successor/lesson-lineage.json (a8) nor workstreams/po03/research/lesson-lineage.json (a5) exists at measurement time.",
        }

    # --- false_green_rate (NOT_YET check) ---
    false_green_path = root / "workstreams/po03/review/luna/false_green_results.json"
    if false_green_path.exists():
        results = json.loads(false_green_path.read_text(encoding="utf-8"))
        examined = results.get("examined", [])
        flagged = [item for item in examined if item.get("false_green")]
        false_green_rate = rate(len(flagged), len(examined))
    else:
        false_green_rate = {
            "value": "NOT_YET",
            "boundary": "workstreams/po03/review/luna/false_green_results.json (owned by po03-worker-a6, unit a6-u03) is absent from the tree at measurement time.",
        }

    # --- successor_lift (deferred) ---
    successor_lift = {
        "value": "NOT_YET",
        "boundary": "Reported in full in workstreams/po03/metrics/generation-comparison.json (a8-u05 populates G0/G1/G2 scores); this report only cross-references it.",
    }

    return {
        "protocol_version": "OBZIO-METRICS-REPORT-v1",
        "unit_id": "a7-u03",
        "measured_against": {
            "ledger_head_sha256": meta["ledger_head_sha256"],
            "ledger_rows": meta["ledger_rows"],
        },
        "metrics": {
            "independently_accepted_throughput": independently_accepted_throughput,
            "first_pass_acceptance_rate": first_pass_acceptance_rate,
            "escaped_defect_rate": escaped_defect_rate,
            "false_green_rate": false_green_rate,
            "cycle_time": cycle_time,
            "recovery_time": recovery_time,
            "founder_interventions": founder_interventions,
            "context_waste": {
                "value": "NOT_SUPPORTED",
                "observed_boundary": "See workstreams/po03/metrics/telemetry-probe-result.json (a7-u04): no context-admission byte count is exposed to this process by any means found.",
            },
            "orphan_duplicate_collision_falsecomplete_counts": {
                "orphan_count": len(orphan_units),
                "orphan_units": orphan_units,
                "duplicate_count": duplicate_count,
                "collision_count": collision_count,
                "false_complete_count": len(false_complete_units),
                "false_complete_units": false_complete_units,
                "denominator_units_total": len(units_projection),
                "denominator_ledger_rows_total": len(ledger_rows),
            },
            "research_to_reproduction_conversion": research_to_reproduction_conversion,
            "lesson_to_live_change_conversion": lesson_to_live_change_conversion,
            "successor_lift": successor_lift,
        },
    }


def MODULE_SECONDS_BETWEEN(start: str | None, end: str | None):
    from datetime import datetime, timezone

    if not start or not end:
        return None

    def parse(value: str):
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    return (parse(end) - parse(start)).total_seconds()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="workstreams/po03/metrics/metrics-report.json")
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
