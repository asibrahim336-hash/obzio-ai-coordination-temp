"""Input model and validation for the matched logical-clock benchmark."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkItem:
    task_id: str
    shard: int
    work_ticks: int
    artifact_count: int


@dataclass(frozen=True)
class Fault:
    tick: int
    kind: str
    target_shard: int


@dataclass(frozen=True)
class BenchmarkConfig:
    worker_slots: int
    coordination_ops_per_tick: int
    restart_ticks: int
    reconcile_tasks_per_tick: int
    replay_events_per_tick: int
    max_ticks: int


@dataclass(frozen=True)
class Workload:
    fixture_id: str
    fixture_sha256: str
    tasks: tuple[WorkItem, ...]
    fault: Fault
    config: BenchmarkConfig
    source_path: str


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be an integer >= 1")
    return value


def _nonnegative_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be an integer >= 0")
    return value


def load_workload(path: Path) -> Workload:
    raw_bytes = path.read_bytes()
    fixture_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    doc = json.loads(raw_bytes)
    if not isinstance(doc, dict):
        raise ValueError("fixture root must be an object")

    required = {"protocol_version", "fixture_id", "sanitization", "tasks", "fault", "configuration"}
    missing = sorted(required - set(doc))
    if missing:
        raise ValueError(f"fixture is missing: {', '.join(missing)}")
    if doc["protocol_version"] != "PO03-TOPOLOGY-BENCHMARK-WORKLOAD-v1":
        raise ValueError("unsupported fixture protocol")
    if not isinstance(doc["fixture_id"], str) or not doc["fixture_id"].strip():
        raise ValueError("fixture_id must be non-empty")

    sanitization = doc["sanitization"]
    if not isinstance(sanitization, dict) or sanitization.get("contains_secrets") is not False:
        raise ValueError("fixture must explicitly attest contains_secrets=false")
    if sanitization.get("contains_external_identifiers") is not False:
        raise ValueError("fixture must explicitly attest contains_external_identifiers=false")

    raw_tasks = doc["tasks"]
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("tasks must be a non-empty array")
    tasks: list[WorkItem] = []
    task_ids: set[str] = set()
    for index, raw in enumerate(raw_tasks):
        if not isinstance(raw, dict):
            raise ValueError(f"tasks[{index}] must be an object")
        task_id = raw.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError(f"tasks[{index}].task_id must be non-empty")
        if task_id in task_ids:
            raise ValueError(f"duplicate task_id: {task_id}")
        task_ids.add(task_id)
        tasks.append(
            WorkItem(
                task_id=task_id,
                shard=_nonnegative_integer(raw.get("shard"), f"tasks[{index}].shard"),
                work_ticks=_positive_integer(raw.get("work_ticks"), f"tasks[{index}].work_ticks"),
                artifact_count=_positive_integer(
                    raw.get("artifact_count"), f"tasks[{index}].artifact_count"
                ),
            )
        )

    raw_fault = doc["fault"]
    if not isinstance(raw_fault, dict):
        raise ValueError("fault must be an object")
    fault = Fault(
        tick=_nonnegative_integer(raw_fault.get("tick"), "fault.tick"),
        kind=str(raw_fault.get("kind", "")),
        target_shard=_nonnegative_integer(raw_fault.get("target_shard"), "fault.target_shard"),
    )
    if fault.kind != "COORDINATOR_PROCESS_LOSS":
        raise ValueError("fault.kind must be COORDINATOR_PROCESS_LOSS")

    raw_config = doc["configuration"]
    if not isinstance(raw_config, dict):
        raise ValueError("configuration must be an object")
    config = BenchmarkConfig(
        worker_slots=_positive_integer(raw_config.get("worker_slots"), "configuration.worker_slots"),
        coordination_ops_per_tick=_positive_integer(
            raw_config.get("coordination_ops_per_tick"),
            "configuration.coordination_ops_per_tick",
        ),
        restart_ticks=_positive_integer(raw_config.get("restart_ticks"), "configuration.restart_ticks"),
        reconcile_tasks_per_tick=_positive_integer(
            raw_config.get("reconcile_tasks_per_tick"),
            "configuration.reconcile_tasks_per_tick",
        ),
        replay_events_per_tick=_positive_integer(
            raw_config.get("replay_events_per_tick"),
            "configuration.replay_events_per_tick",
        ),
        max_ticks=_positive_integer(raw_config.get("max_ticks"), "configuration.max_ticks"),
    )
    if fault.target_shard not in {task.shard for task in tasks}:
        raise ValueError("fault.target_shard does not exist in the workload")

    return Workload(
        fixture_id=doc["fixture_id"],
        fixture_sha256=fixture_sha256,
        tasks=tuple(tasks),
        fault=fault,
        config=config,
        source_path=str(path),
    )
