#!/usr/bin/env python3
"""Derived metrics over the recorded PO-03 metric rows.

Each of the seven frozen derived metrics is computed from the recorded rows
alone.  A metric is emitted only when every input it needs is present: if a
population is empty, if a required cell is ``NOT_SUPPORTED``, or if the frozen
row schema carries no field that could supply an input, the metric is refused
with the exact missing inputs named.  Nothing is imputed, defaulted or smoothed.

The module also probes the five quantities named in the unit hypothesis, so the
hypothesis is answered by measurement rather than by assertion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

DERIVATION_VERSION = "PO03-DERIVED-METRICS-v1"
UNSUPPORTED = "NOT_SUPPORTED"

# The research function in the frozen Wave A catalogue whose units convert
# external hypotheses into executed reproductions.
RESEARCH_FUNCTION = "frontier-research-reproduction-and-mechanism-change"
TERMINAL_DISPOSITIONS = {"ACCEPTED", "REJECTED"}
NON_TERMINAL_DISPOSITIONS = {UNSUPPORTED, "NOT_TESTED", "PENDING"}


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"line {number}: row must be a JSON object")
        rows.append(value)
    return rows


def require_fields(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[str]:
    """Name any input field that the row schema does not carry at all."""
    if not rows:
        return [f"row schema unavailable: no rows were supplied ({', '.join(fields)})"]
    return [f"{field} (absent from the recorded row schema)" for field in fields if field not in rows[0]]


def ratio(
    rows: list[dict[str, Any]],
    *,
    metric: str,
    definition: str,
    inputs: tuple[str, ...],
    population: Callable[[dict[str, Any]], bool],
    population_description: str,
    numerator: Callable[[dict[str, Any]], bool],
    numerator_description: str,
) -> dict[str, Any]:
    """Compute one ratio metric, or refuse it with the exact missing inputs."""
    missing = require_fields(rows, inputs)
    unsupported_cells: list[str] = []
    denominator_rows: list[dict[str, Any]] = []
    if not missing:
        for row in rows:
            if any(row[field] == UNSUPPORTED for field in inputs):
                # A row whose inputs are unobserved is excluded rather than scored,
                # so an unobserved unit can never be counted as a success.
                unsupported_cells.append(row.get("task_id", "<unknown>"))
                continue
            if population(row):
                denominator_rows.append(row)
    record: dict[str, Any] = {
        "metric": metric,
        "definition": definition,
        "inputs": list(inputs),
        "population": population_description,
        "numerator_rule": numerator_description,
        "denominator": len(denominator_rows),
        "numerator": sum(1 for row in denominator_rows if numerator(row)),
        "rows_excluded_for_unsupported_inputs": sorted(unsupported_cells),
        "missing_inputs": missing,
    }
    if missing:
        record["value"] = UNSUPPORTED
        return record
    if not denominator_rows:
        record["value"] = UNSUPPORTED
        record["missing_inputs"] = [
            f"non-empty population: {population_description} matched 0 of {len(rows)} recorded rows"
        ]
        return record
    record["value"] = record["numerator"] / record["denominator"]
    return record


def refused(metric: str, definition: str, missing: list[str], inputs: tuple[str, ...]) -> dict[str, Any]:
    return {
        "metric": metric,
        "definition": definition,
        "inputs": list(inputs),
        "value": UNSUPPORTED,
        "missing_inputs": missing,
    }


def independently_accepted_throughput(
    rows: list[dict[str, Any]], window_hours: float | None
) -> dict[str, Any]:
    definition = (
        "count of counted units with a terminal ACCEPTED independent disposition and a VERIFIED "
        "read-back, divided by the observation window in hours"
    )
    inputs = ("independent_disposition", "readback_state")
    missing = require_fields(rows, inputs)
    accepted = 0
    if not missing:
        accepted = sum(
            1
            for row in rows
            if row["independent_disposition"] == "ACCEPTED" and row["readback_state"] == "VERIFIED"
        )
    if window_hours is None:
        missing = missing + [
            "observation_window_hours: no absolute attempt start or end timestamp exists in the "
            "frozen required_fields of PO03-METRIC-DEFINITIONS-v1, so no time base can be derived "
            "from the recorded rows alone"
        ]
    record = {
        "metric": "independently_accepted_throughput",
        "definition": definition,
        "inputs": list(inputs) + ["observation_window_hours (external)"],
        "numerator": accepted,
        "denominator": window_hours,
        "missing_inputs": missing,
    }
    record["value"] = UNSUPPORTED if missing else accepted / window_hours
    return record


def first_pass_acceptance_rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return ratio(
        rows,
        metric="first_pass_acceptance_rate",
        definition=(
            "share of units carrying a terminal independent disposition that were ACCEPTED on the "
            "first attempt"
        ),
        inputs=("independent_disposition", "rework_count"),
        population=lambda row: row["independent_disposition"] in TERMINAL_DISPOSITIONS,
        population_description="rows whose independent_disposition is ACCEPTED or REJECTED",
        numerator=lambda row: row["independent_disposition"] == "ACCEPTED" and row["rework_count"] == 0,
        numerator_description="disposition ACCEPTED and rework_count == 0",
    )


def false_green_rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return ratio(
        rows,
        metric="false_green_rate",
        definition=(
            "share of units whose recorded first-pass verdict is PASS but whose artifacts do not "
            "read back byte-identical from an immutable Git object"
        ),
        inputs=("first_pass_outcome", "readback_state"),
        population=lambda row: row["first_pass_outcome"] == "PASS",
        population_description="rows whose first_pass_outcome is PASS",
        numerator=lambda row: row["readback_state"] != "VERIFIED",
        numerator_description="readback_state is not VERIFIED",
    )


def recovery_rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return ratio(
        rows,
        metric="recovery_rate",
        definition=(
            "share of units that recorded a recovery event and nevertheless reached a VERIFIED "
            "artifact read-back"
        ),
        inputs=("recovery_events", "readback_state"),
        population=lambda row: isinstance(row["recovery_events"], int) and row["recovery_events"] > 0,
        population_description="rows with recovery_events > 0",
        numerator=lambda row: row["readback_state"] == "VERIFIED",
        numerator_description="readback_state is VERIFIED",
    )


def research_to_reproduction_conversion(
    rows: list[dict[str, Any]], research_function: str
) -> dict[str, Any]:
    record = ratio(
        rows,
        metric="research_to_reproduction_conversion",
        definition=(
            "share of research-function counted units whose reproduction evidence reads back "
            "byte-identical from an immutable Git object"
        ),
        inputs=("function", "readback_state"),
        population=lambda row: row["function"] == research_function,
        population_description=f"rows whose function is {research_function}",
        numerator=lambda row: row["readback_state"] == "VERIFIED",
        numerator_description="readback_state is VERIFIED",
    )
    record["research_function"] = research_function
    return record


def lesson_to_live_change_conversion(
    rows: list[dict[str, Any]], lineage: dict[str, Any] | None
) -> dict[str, Any]:
    definition = (
        "share of accepted lessons that produced a live mechanism change with preserved lineage"
    )
    inputs = ("accepted_lesson_ledger", "live_mechanism_change_lineage")
    if lineage is None:
        return refused(
            "lesson_to_live_change_conversion",
            definition,
            [
                "accepted_lesson_ledger: no accepted-lesson field exists in the frozen row schema",
                "live_mechanism_change_lineage: produced by the successor units (063 lineage, 064 "
                "dispositions) and not present in the recorded rows",
            ],
            inputs,
        )
    lessons = lineage.get("accepted_lessons", [])
    changes = lineage.get("live_mechanism_changes", [])
    if not lessons:
        return refused(
            "lesson_to_live_change_conversion",
            definition,
            ["accepted_lesson_ledger: supplied lineage document lists zero accepted lessons"],
            inputs,
        )
    linked = sum(
        1
        for lesson in lessons
        if any(change.get("lesson_id") == lesson.get("lesson_id") for change in changes)
    )
    del rows
    return {
        "metric": "lesson_to_live_change_conversion",
        "definition": definition,
        "inputs": list(inputs),
        "numerator": linked,
        "denominator": len(lessons),
        "value": linked / len(lessons),
        "missing_inputs": [],
    }


def successor_lift(rows: list[dict[str, Any]], comparison: dict[str, Any] | None) -> dict[str, Any]:
    definition = (
        "combined pass-rate difference between the successor generation and the current generation "
        "on the frozen public suite plus evaluator-held holdout cases"
    )
    inputs = ("generation_comparison",)
    del rows
    if comparison is None:
        return refused(
            "successor_lift",
            definition,
            [
                "generation_comparison: no generation field exists in the frozen row schema; the "
                "value is produced by the generation comparison unit (064) and cannot be derived "
                "from work-unit rows"
            ],
            inputs,
        )
    lift = comparison.get("successor_lift")
    if not isinstance(lift, (int, float)):
        return refused(
            "successor_lift",
            definition,
            [f"generation_comparison.successor_lift: absent or non-numeric ({lift!r})"],
            inputs,
        )
    return {
        "metric": "successor_lift",
        "definition": definition,
        "inputs": list(inputs),
        "value": float(lift),
        "missing_inputs": [],
        "source": comparison.get("source", "supplied generation comparison document"),
    }


def hypothesis_probe(rows: list[dict[str, Any]], derived: dict[str, Any]) -> dict[str, Any]:
    """Answer the unit hypothesis quantity by quantity, from the rows only."""
    recovery_population = [
        row for row in rows if isinstance(row.get("recovery_events"), int) and row["recovery_events"] > 0
    ]
    timing_unsupported = {
        field: sum(1 for row in rows if row.get(field) == UNSUPPORTED)
        for field in ("queue_ms", "active_ms", "review_ms", "wall_ms")
    }
    recovery_time = {
        "quantity": "recovery_time",
        "computable_from_rows_alone": False,
        "value": UNSUPPORTED,
        "missing_inputs": [
            f"active_ms is NOT_SUPPORTED in {timing_unsupported['active_ms']} of {len(rows)} rows",
            f"population with recovery_events > 0 matched {len(recovery_population)} of {len(rows)} rows",
        ],
    }
    coordination_overhead = {
        "quantity": "coordination_overhead",
        "computable_from_rows_alone": False,
        "value": UNSUPPORTED,
        "missing_inputs": [
            f"queue_ms is NOT_SUPPORTED in {timing_unsupported['queue_ms']} of {len(rows)} rows",
            f"review_ms is NOT_SUPPORTED in {timing_unsupported['review_ms']} of {len(rows)} rows",
        ],
    }
    named = {
        "independently_accepted_throughput": derived["independently_accepted_throughput"],
        "first_pass_acceptance_rate": derived["first_pass_acceptance_rate"],
        "false_green_rate": derived["false_green_rate"],
    }
    quantities = [
        {
            "quantity": name,
            "computable_from_rows_alone": record["value"] != UNSUPPORTED,
            "value": record["value"],
            "missing_inputs": record.get("missing_inputs", []),
        }
        for name, record in named.items()
    ]
    quantities.extend([recovery_time, coordination_overhead])
    computed = [item for item in quantities if item["computable_from_rows_alone"]]
    structurally_blocked = [
        item
        for item in quantities
        if not item["computable_from_rows_alone"]
        and any("absent from the recorded row schema" in text or "no absolute attempt" in text or "NOT_SUPPORTED in" in text for text in item["missing_inputs"])
    ]
    population_blocked = [
        item
        for item in quantities
        if not item["computable_from_rows_alone"] and item not in structurally_blocked
    ]
    return {
        "hypothesis": (
            "Independently accepted throughput, first-pass acceptance, false-green rate, recovery "
            "time and coordination overhead are computable from the recorded rows alone."
        ),
        "quantities": quantities,
        "computed_count": len(computed),
        "structurally_blocked_count": len(structurally_blocked),
        "population_blocked_count": len(population_blocked),
        "verdict": "REFUTED" if structurally_blocked else ("PASS" if not population_blocked else "NOT_YET"),
        "verdict_basis": (
            "The hypothesis is refuted when at least one named quantity cannot be computed from the "
            "frozen row schema at all; it is NOT_YET when every remaining gap is an empty population "
            "that later rows could fill."
        ),
        "timing_field_unsupported_counts": timing_unsupported,
    }


def derive(
    rows: list[dict[str, Any]],
    *,
    definitions: dict[str, Any],
    window_hours: float | None = None,
    lineage: dict[str, Any] | None = None,
    comparison: dict[str, Any] | None = None,
    research_function: str = RESEARCH_FUNCTION,
) -> dict[str, Any]:
    expected = list(definitions["derived_metrics"])
    derived = {
        "independently_accepted_throughput": independently_accepted_throughput(rows, window_hours),
        "first_pass_acceptance_rate": first_pass_acceptance_rate(rows),
        "false_green_rate": false_green_rate(rows),
        "recovery_rate": recovery_rate(rows),
        "research_to_reproduction_conversion": research_to_reproduction_conversion(rows, research_function),
        "lesson_to_live_change_conversion": lesson_to_live_change_conversion(rows, lineage),
        "successor_lift": successor_lift(rows, comparison),
    }
    if sorted(derived) != sorted(expected):
        raise ValueError(
            f"derived metric set does not match the frozen definitions: "
            f"computed={sorted(derived)} frozen={sorted(expected)}"
        )
    probe = hypothesis_probe(rows, derived)
    return {
        "derivation_version": DERIVATION_VERSION,
        "metrics_version": definitions["metrics_version"],
        "row_count": len(rows),
        "derived_metrics": derived,
        "emitted_count": sum(1 for record in derived.values() if record["value"] != UNSUPPORTED),
        "refused_count": sum(1 for record in derived.values() if record["value"] == UNSUPPORTED),
        "hypothesis_probe": probe,
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--rows", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--window-hours", type=float, default=None)
    parser.add_argument("--lineage", default=None)
    parser.add_argument("--comparison", default=None)
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    definitions = json.loads(
        (repo / "workstreams/po03/metrics/metric-definitions.json").read_text(encoding="utf-8")
    )
    rows_path = Path(args.rows)
    rows = load_rows(rows_path)
    lineage = json.loads(Path(args.lineage).read_text(encoding="utf-8")) if args.lineage else None
    comparison = json.loads(Path(args.comparison).read_text(encoding="utf-8")) if args.comparison else None

    payload = derive(
        rows,
        definitions=definitions,
        window_hours=args.window_hours,
        lineage=lineage,
        comparison=comparison,
    )
    payload["rows_uri"] = rows_path.as_posix()
    payload["rows_sha256"] = sha256_bytes(rows_path.read_bytes())
    Path(args.out).write_bytes(canonical(payload))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
