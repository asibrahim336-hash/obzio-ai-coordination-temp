#!/usr/bin/env python3
"""Deterministically compare coordination topologies on the Wave A shape."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
WAVE_PATH = "workstreams/po03/control/wave-a-spec.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_specs() -> list[dict[str, Any]]:
    common = {
        "binding_state": "PROPOSAL_ONLY",
        "applied_to_active_wave": False,
        "decision_changed": [],
    }
    return [
        {
            **common,
            "topology_id": "T1-CENTRAL-SERIAL",
            "name": "single serialized integration controller",
            "worker_result_surface": "disjoint worker branches",
            "verification_writers": 1,
            "final_promotion_authorities": 1,
            "mutable_coordination_surfaces": ["one global ledger head"],
            "scheduling": "FIFO, one unit verified and promoted per simulation tick",
            "collision_rule": "serialization prevents simultaneous mutation",
            "recovery_rule": "durable queue resumes after three downtime ticks; the interrupted item is replayed",
            "batch_size": 1,
        },
        {
            **common,
            "topology_id": "T2-COHORT-SHARDS",
            "name": "cohort-sharded verification with serialized promotion",
            "worker_result_surface": "one isolated verification shard per Wave A cohort",
            "verification_writers": 10,
            "final_promotion_authorities": 1,
            "mutable_coordination_surfaces": [
                "ten disjoint cohort heads",
                "one global cohort-promotion head",
            ],
            "scheduling": "each shard verifies one unit per tick; one compact cohort checkpoint is promoted per tick after verification",
            "collision_rule": "cohort ownership prevents cross-shard mutation; promotion remains serialized",
            "recovery_rule": "only the interrupted shard pauses for three ticks and replays one item",
            "batch_size": "one cohort checkpoint",
        },
        {
            **common,
            "topology_id": "T3-OPTIMISTIC-PEERS",
            "name": "optimistic peer integration against a shared head",
            "worker_result_surface": "ten peers contend directly on one global mutable head",
            "verification_writers": 10,
            "final_promotion_authorities": 10,
            "mutable_coordination_surfaces": ["one global ledger head"],
            "scheduling": "all available peers attempt compare-and-swap each tick; one wins and losers retry",
            "collision_rule": "each losing compare-and-swap is a measured collision",
            "recovery_rule": "after three downtime ticks, every in-flight peer retries",
            "batch_size": 1,
        },
        {
            **common,
            "topology_id": "T4-CONTENT-FANIN",
            "name": "content-addressed immutable manifests with batched fan-in",
            "worker_result_surface": "ten peers write immutable content IDs to disjoint branches",
            "verification_writers": 10,
            "final_promotion_authorities": 1,
            "mutable_coordination_surfaces": ["one append-only batched reference index"],
            "scheduling": "ten manifests stage per tick; the singleton authority appends up to eight verified references per tick",
            "collision_rule": "content IDs are immutable and duplicate references are idempotent",
            "recovery_rule": "after three downtime ticks, the interrupted reference batch is replayed without re-running producers",
            "batch_size": 8,
        },
    ]


def _metrics(
    *,
    topology_id: str,
    completed: int,
    makespan: int,
    collisions: int,
    replayed: int,
    recovery_ticks: int,
    shared_writes: int,
    artifact_reexecutions: int = 0,
) -> dict[str, Any]:
    return {
        "topology_id": topology_id,
        "completed_units": completed,
        "result_loss_count": 0,
        "collision_attempts": collisions,
        "replayed_integration_items": replayed,
        "artifact_reexecution_count": artifact_reexecutions,
        "recovery_to_success_ticks": recovery_ticks,
        "shared_mutable_write_count": shared_writes,
        "makespan_ticks": makespan,
        "throughput_units_per_tick": round(completed / makespan, 6),
    }


def simulate(wave: dict[str, Any]) -> dict[str, Any]:
    units = wave["units"]
    unit_count = len(units)
    cohort_counts = Counter(unit["cohort_id"] for unit in units)
    workers = len(cohort_counts)
    downtime = 3
    failure_after_items = unit_count // 4

    # T1: one failed pre-commit attempt plus downtime and 74 successful writes.
    central_ticks = unit_count + 1 + downtime
    central = _metrics(
        topology_id="T1-CENTRAL-SERIAL",
        completed=unit_count,
        makespan=central_ticks,
        collisions=0,
        replayed=1,
        recovery_ticks=downtime + 1,
        shared_writes=unit_count,
    )

    # T2: fail the lexicographically first largest shard. Other shards continue.
    largest_size = max(cohort_counts.values())
    failed_shard = sorted(
        cohort for cohort, size in cohort_counts.items() if size == largest_size
    )[0]
    failed_shard_ticks = cohort_counts[failed_shard] + 1 + downtime
    verification_ticks = max(
        failed_shard_ticks if cohort == failed_shard else size
        for cohort, size in cohort_counts.items()
    )
    promotion_ticks = len(cohort_counts)
    sharded = _metrics(
        topology_id="T2-COHORT-SHARDS",
        completed=unit_count,
        makespan=verification_ticks + promotion_ticks,
        collisions=0,
        replayed=1,
        recovery_ticks=downtime + 1,
        shared_writes=promotion_ticks,
    )
    sharded["failed_shard"] = failed_shard
    sharded["verification_phase_ticks"] = verification_ticks
    sharded["promotion_phase_ticks"] = promotion_ticks

    # T3: only one compare-and-swap can win. All other attempts collide.
    optimistic_collisions = sum(
        max(0, min(workers, unit_count - completed) - 1)
        for completed in range(unit_count)
    )
    remaining_at_failure = unit_count - failure_after_items
    optimistic_collisions += max(0, min(workers, remaining_at_failure) - 1)
    optimistic = _metrics(
        topology_id="T3-OPTIMISTIC-PEERS",
        completed=unit_count,
        makespan=unit_count + 1 + downtime,
        collisions=optimistic_collisions,
        replayed=min(workers, remaining_at_failure),
        recovery_ticks=downtime + 1,
        shared_writes=unit_count,
    )

    # T4: immutable staging and batched singleton indexing are separate phases.
    staging_ticks = math.ceil(unit_count / workers)
    batch_size = 8
    batches = math.ceil(unit_count / batch_size)
    fanin = _metrics(
        topology_id="T4-CONTENT-FANIN",
        completed=unit_count,
        makespan=staging_ticks + batches + 1 + downtime,
        collisions=0,
        replayed=min(batch_size, unit_count),
        recovery_ticks=downtime + 1,
        shared_writes=batches,
    )
    fanin["immutable_staging_ticks"] = staging_ticks
    fanin["reference_batches"] = batches
    fanin["reference_batch_size"] = batch_size

    results = [central, sharded, optimistic, fanin]
    safe_results = [
        row
        for row in results
        if row["collision_attempts"] == 0 and row["result_loss_count"] == 0
    ]
    fastest_safe = max(safe_results, key=lambda row: row["throughput_units_per_tick"])
    slowest_safe = min(safe_results, key=lambda row: row["throughput_units_per_tick"])
    return {
        "simulation_id": "PO03-A9-TOPOLOGY-SIM-v001",
        "unit_id": "a9-u02",
        "model": "deterministic discrete-event operation-count simulation",
        "workload": {
            "source": WAVE_PATH,
            "declared_units": wave["declared_units"],
            "simulated_units": unit_count,
            "cohort_counts": dict(sorted(cohort_counts.items())),
            "all_results_available_at_tick_zero": True,
            "note": "This isolates integration topology. A tick is one abstract service opportunity, not wall-clock time.",
        },
        "failure_fixture": {
            "failure": "one pre-commit integration crash after the first quarter of items",
            "failure_after_items": failure_after_items,
            "downtime_ticks": downtime,
            "durable_inputs_survive": True,
        },
        "metric_definitions": {
            "collision_attempts": "losing simultaneous attempts to mutate the same coordination head",
            "replayed_integration_items": "references or integration operations retried after the injected crash",
            "result_loss_count": "durable worker results absent after recovery",
            "makespan_ticks": "abstract service ticks through recovery and all 74 integrations",
            "throughput_units_per_tick": "completed_units / makespan_ticks",
        },
        "results": results,
        "comparison": {
            "fastest_zero_collision_topology": fastest_safe["topology_id"],
            "fastest_zero_collision_throughput": fastest_safe[
                "throughput_units_per_tick"
            ],
            "slowest_zero_collision_topology": slowest_safe["topology_id"],
            "slowest_zero_collision_throughput": slowest_safe[
                "throughput_units_per_tick"
            ],
            "simulated_safe_throughput_ratio": round(
                fastest_safe["throughput_units_per_tick"]
                / slowest_safe["throughput_units_per_tick"],
                6,
            ),
            "finding": "A singleton final promotion authority is a safety property, not by itself the throughput unit. Sharding or batching verification changes throughput while preserving one final authority.",
            "limitation": "These are deterministic operation-count measurements on the committed Wave A shape, not production latency or acceptance evidence.",
        },
        "proposal": {
            "proposal_id": "P-TOPOLOGY-SUCCESSOR-01",
            "proposal": "Evaluate T4 content-addressed batched fan-in and T2 cohort sharding in a successor recurrence test while retaining T1 for active Wave A.",
            "binding_state": "PROPOSAL_ONLY",
            "founder_interlock": "REQUIRED_BEFORE_ANY_STRATEGY_DECISION",
            "applied_to_active_wave": False,
            "decision_changed": [],
        },
        "decision_changed": [],
    }


def build_artifacts(root: Path = REPO_ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    wave_path = root / WAVE_PATH
    wave = json.loads(wave_path.read_text(encoding="utf-8"))
    candidates = {
        "artifact_id": "PO03-A9-TOPOLOGY-CANDIDATES-v001",
        "unit_id": "a9-u02",
        "wave_source": {
            "path": WAVE_PATH,
            "sha256": sha256_file(wave_path),
            "declared_units": wave["declared_units"],
        },
        "topologies": candidate_specs(),
        "decision_changed": [],
    }
    return candidates, simulate(wave)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("workstreams/po03/strategy/topology-candidates.json"),
    )
    parser.add_argument(
        "--comparison",
        type=Path,
        default=Path("workstreams/po03/strategy/topology-comparison.json"),
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    candidates, comparison = build_artifacts(root)
    candidate_path = args.candidates if args.candidates.is_absolute() else root / args.candidates
    comparison_path = args.comparison if args.comparison.is_absolute() else root / args.comparison
    candidate_path.write_text(
        json.dumps(candidates, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    comparison_path.write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    winner = comparison["comparison"]["fastest_zero_collision_topology"]
    ratio = comparison["comparison"]["simulated_safe_throughput_ratio"]
    print(
        f"WROTE {candidate_path.relative_to(root)} and {comparison_path.relative_to(root)} "
        f"topologies={len(candidates['topologies'])} units={comparison['workload']['simulated_units']} "
        f"fastest_safe={winner} ratio={ratio} decision_changed=[]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
