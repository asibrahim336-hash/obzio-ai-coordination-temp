#!/usr/bin/env python3
"""Run one candidate or the complete matched topology benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .model import Workload, load_workload
from .topologies import TOPOLOGIES, Simulation


HYPOTHESIS_ID = "H-PO03-WA-019"
FALSIFIABLE_HYPOTHESIS = (
    "Centralized, sharded, and event-sourced coordination topologies produce "
    "distinguishable accepted-throughput and recovery outcomes."
)
UNIT_ROOT = Path(__file__).parents[1]
DEFAULT_FIXTURE = UNIT_ROOT / "fixtures" / "sanitized-wave-workload.json"


def run_topology(workload: Workload, topology_name: str) -> dict[str, Any]:
    try:
        topology_type = TOPOLOGIES[topology_name]
    except KeyError as exc:
        raise ValueError(f"unknown topology: {topology_name}") from exc
    baseline = Simulation(workload, topology_type(), inject_fault=False).run()
    faulted = Simulation(workload, topology_type(), inject_fault=True).run()
    return {
        "candidate": topology_name,
        "baseline": baseline,
        "coordinator_loss": faulted,
    }


def assess_hypothesis(candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    faulted = {
        name: candidate["coordinator_loss"] for name, candidate in candidates.items()
    }
    throughput_values = {
        result["accepted_throughput_per_tick"] for result in faulted.values()
    }
    recovery_vectors = {
        (
            result["recovery"]["recovery_ticks"],
            result["recovery"]["accepted_during_outage"],
            result["recovery"]["lost_work_ticks"],
            result["recovery"]["replayed_events"],
        )
        for result in faulted.values()
    }
    all_safe = all(
        result["all_tasks_accepted"] and result["duplicate_acceptances"] == 0
        for result in faulted.values()
    )
    throughput_distinguishable = len(throughput_values) == len(faulted)
    recovery_distinguishable = len(recovery_vectors) == len(faulted)
    supported = all_safe and throughput_distinguishable and recovery_distinguishable
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "falsifiable_hypothesis": FALSIFIABLE_HYPOTHESIS,
        "outcome": "SUPPORTED" if supported else "REFUTED",
        "all_candidates_safe_in_model": all_safe,
        "accepted_throughput_distinguishable": throughput_distinguishable,
        "recovery_outcomes_distinguishable": recovery_distinguishable,
        "distinct_throughput_values": sorted(throughput_values),
        "distinct_recovery_vectors": [list(vector) for vector in sorted(recovery_vectors)],
        "falsification_rule": (
            "REFUTED unless all three candidates accept every task without a duplicate, "
            "all three coordinator-loss accepted-throughput values differ, and all three "
            "recovery vectors differ."
        ),
    }


def run_matched_benchmark(workload: Workload) -> dict[str, Any]:
    candidates = {
        name: run_topology(workload, name)
        for name in ("centralized", "sharded", "event-sourced")
    }
    assessment = assess_hypothesis(candidates)
    return {
        "protocol_version": "PO03-MATCHED-TOPOLOGY-BENCHMARK-v1",
        "fixture": {
            "fixture_id": workload.fixture_id,
            "path": workload.source_path,
            "sha256": workload.fixture_sha256,
            "task_count": len(workload.tasks),
        },
        "matched_controls": {
            "same_task_bytes": True,
            "same_task_order": True,
            "same_fault_kind_and_tick": True,
            "same_worker_slots": workload.config.worker_slots,
            "same_coordination_ops_per_tick": workload.config.coordination_ops_per_tick,
            "same_logical_clock": True,
            "third_party_dependencies": 0,
        },
        "candidates": candidates,
        "hypothesis_assessment": assessment,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--topology",
        choices=("all", "centralized", "sharded", "event-sourced"),
        default="all",
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workload = load_workload(args.fixture)
    if args.topology == "all":
        result = run_matched_benchmark(workload)
    else:
        result = {
            "protocol_version": "PO03-TOPOLOGY-CANDIDATE-RUN-v1",
            "fixture_sha256": workload.fixture_sha256,
            "result": run_topology(workload, args.topology),
        }
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.topology == "all":
        return 0 if result["hypothesis_assessment"]["outcome"] == "SUPPORTED" else 1
    return 0 if result["result"]["coordinator_loss"]["all_tasks_accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
