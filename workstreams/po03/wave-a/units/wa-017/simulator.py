#!/usr/bin/env python3
"""Run three independent repository-factory candidates on one frozen workload."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


UNIT_ROOT = Path(__file__).resolve().parent
if str(UNIT_ROOT) not in sys.path:
    sys.path.insert(0, str(UNIT_ROOT))

from architectures import (  # noqa: E402
    CentralGateFactory,
    EventLogFactory,
    LeaseShardFactory,
)
from architectures.central_gate import (  # noqa: E402
    CANDIDATE_ID as CENTRAL_ID,
    MECHANISM_SIGNATURE as CENTRAL_SIGNATURE,
)
from architectures.event_log import (  # noqa: E402
    CANDIDATE_ID as EVENT_ID,
    MECHANISM_SIGNATURE as EVENT_SIGNATURE,
)
from architectures.lease_shards import (  # noqa: E402
    CANDIDATE_ID as SHARD_ID,
    MECHANISM_SIGNATURE as SHARD_SIGNATURE,
)
from architectures.model import parse_tasks  # noqa: E402


PROTOCOL_VERSION = "OBZIO-PO03-ARCHITECTURE-COMPARISON-RESULT-v1"


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_object(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value, data


def _candidate_contracts(comparison: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = comparison.get("candidate_contracts")
    if not isinstance(raw, list):
        raise ValueError("comparison candidate_contracts must be an array")
    contracts = {
        str(item["candidate_id"]): item
        for item in raw
        if isinstance(item, dict) and "candidate_id" in item
    }
    expected = {CENTRAL_ID, SHARD_ID, EVENT_ID}
    if set(contracts) != expected or len(raw) != 3:
        raise ValueError(
            f"comparison candidates differ: expected {sorted(expected)}, "
            f"observed {sorted(contracts)}"
        )
    expected_signatures = {
        CENTRAL_ID: CENTRAL_SIGNATURE,
        SHARD_ID: SHARD_SIGNATURE,
        EVENT_ID: EVENT_SIGNATURE,
    }
    for candidate_id, expected_signature in expected_signatures.items():
        if contracts[candidate_id].get("mechanism_signature") != expected_signature:
            raise ValueError(f"{candidate_id} mechanism signature differs")
    return contracts


def _pairwise_evaluations(
    results: list[dict[str, Any]], comparison: dict[str, Any]
) -> list[dict[str, Any]]:
    rule = comparison["decision_rule"]["material_pairwise_difference"]
    alternatives = rule["satisfied_when_either"]
    throughput_minimum = float(
        alternatives["throughput_relative_difference_minimum"]
    )
    safety_minimum = int(alternatives["safety_distance_minimum"])
    safety_metrics = list(alternatives["safety_distance_metrics"])
    rows: list[dict[str, Any]] = []
    ordered = sorted(results, key=lambda result: result["candidate_id"])
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            left_throughput = float(left["metrics"]["accepted_throughput"])
            right_throughput = float(right["metrics"]["accepted_throughput"])
            denominator = min(left_throughput, right_throughput)
            relative = (
                abs(left_throughput - right_throughput) / denominator
                if denominator
                else 0.0
            )
            safety_components = {
                metric: abs(
                    int(left["metrics"][metric]) - int(right["metrics"][metric])
                )
                for metric in safety_metrics
            }
            safety_distance = sum(safety_components.values())
            rows.append(
                {
                    "candidates": [
                        left["candidate_id"],
                        right["candidate_id"],
                    ],
                    "passes": (
                        relative >= throughput_minimum
                        or safety_distance >= safety_minimum
                    ),
                    "safety_components": safety_components,
                    "safety_distance": safety_distance,
                    "throughput_relative_difference": round(relative, 6),
                }
            )
    return rows


def evaluate(
    results: list[dict[str, Any]],
    comparison: dict[str, Any],
    task_count: int,
) -> dict[str, Any]:
    rules = comparison["decision_rule"]
    expected_count = int(
        rules["workload_completion_gate"]["accepted_task_count"]
    )
    completion_rows = {
        result["candidate_id"]: (
            result["completed_workload"]
            and result["metrics"]["accepted_task_count"] == expected_count
            and result["metrics"]["accepted_task_count"] == task_count
        )
        for result in results
    }

    critical_fields = rules["critical_safety_gate"]["required_equal_zero"]
    critical_rows = {
        result["candidate_id"]: {
            field: result["metrics"][field] for field in critical_fields
        }
        for result in results
    }
    critical_pass = all(
        value == 0
        for row in critical_rows.values()
        for value in row.values()
    )

    contracts = _candidate_contracts(comparison)
    signatures = {result["mechanism_signature"] for result in results}
    dimensions = rules["independence_gate"]["required_distinct_dimensions"]
    dimension_counts = {
        dimension: len(
            {str(contract[dimension]) for contract in contracts.values()}
        )
        for dimension in dimensions
    }
    independence_pass = (
        len(signatures)
        == int(rules["independence_gate"]["distinct_mechanism_signatures"])
        and all(count == 3 for count in dimension_counts.values())
    )

    throughputs = [
        float(result["metrics"]["accepted_throughput"]) for result in results
    ]
    spread = max(throughputs) / min(throughputs) if min(throughputs) else 0.0
    spread_pass = (
        spread >= float(rules["throughput_spread_gate"]["minimum_ratio"])
    )
    pairwise = _pairwise_evaluations(results, comparison)
    pairwise_pass = len(pairwise) == 3 and all(row["passes"] for row in pairwise)

    gates = {
        "critical_safety": critical_pass,
        "independent_mechanisms": independence_pass,
        "material_pairwise_difference": pairwise_pass,
        "throughput_spread": spread_pass,
        "workload_completion": all(completion_rows.values()),
    }
    outcome = "SUPPORTED" if all(gates.values()) else "REFUTED"
    return {
        "critical_safety_observations": critical_rows,
        "dimension_distinct_value_counts": dimension_counts,
        "gates": gates,
        "hypothesis_outcome": outcome,
        "pairwise": pairwise,
        "throughput_spread_ratio": round(spread, 6),
        "workload_completion": completion_rows,
    }


def run(
    workload_path: Path,
    comparison_path: Path,
) -> dict[str, Any]:
    workload, workload_bytes = load_object(workload_path)
    comparison, comparison_bytes = load_object(comparison_path)
    expected = comparison["workload"]
    observed_hash = sha256(workload_bytes)
    if observed_hash != expected["sha256"] or len(workload_bytes) != expected["bytes"]:
        raise ValueError(
            "frozen workload differs from preregistration: "
            f"sha256={observed_hash} bytes={len(workload_bytes)}"
        )
    if workload.get("simulation_id") != "PO03-WA-017-FROZEN-SIM-001":
        raise ValueError("unexpected simulation_id")
    if comparison.get("frozen_before_execution") is not True:
        raise ValueError("comparison is not marked frozen before execution")
    _candidate_contracts(comparison)

    tasks = parse_tasks(workload)
    maximum = int(workload["logical_time"]["maximum_ticks"])
    parameters = workload["candidate_parameters"]
    candidates = [
        CentralGateFactory(tasks, parameters[CENTRAL_ID], maximum),
        LeaseShardFactory(tasks, parameters[SHARD_ID], maximum),
        EventLogFactory(tasks, parameters[EVENT_ID], maximum),
    ]
    results = [candidate.run() for candidate in candidates]
    assessment = evaluate(results, comparison, len(tasks))
    return {
        "assessment": assessment,
        "candidates": sorted(results, key=lambda result: result["candidate_id"]),
        "comparison": {
            "bytes": len(comparison_bytes),
            "path": comparison_path.relative_to(UNIT_ROOT).as_posix(),
            "sha256": sha256(comparison_bytes),
        },
        "hypothesis": (
            "At least three independently reasoned repository-factory "
            "architectures expose materially different safety/throughput "
            "trade-offs under one frozen simulation."
        ),
        "hypothesis_id": comparison["hypothesis_id"],
        "hypothesis_outcome": assessment["hypothesis_outcome"],
        "protocol_version": PROTOCOL_VERSION,
        "simulation_id": workload["simulation_id"],
        "task_count": len(tasks),
        "workload": {
            "bytes": len(workload_bytes),
            "path": workload_path.relative_to(UNIT_ROOT).as_posix(),
            "sha256": observed_hash,
        },
    }


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workload",
        type=Path,
        default=UNIT_ROOT / "fixtures" / "frozen-simulation.json",
    )
    parser.add_argument(
        "--comparison",
        type=Path,
        default=UNIT_ROOT / "result" / "preregistered-comparison.json",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = arguments(argv)
    try:
        result = run(args.workload.resolve(), args.comparison.resolve())
        data = json_bytes(result)
        if args.output:
            output = args.output.resolve()
            if output.parent != UNIT_ROOT / "result":
                raise ValueError("--output must be directly under the unit result slot")
            output.write_bytes(data)
        else:
            sys.stdout.buffer.write(data)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
