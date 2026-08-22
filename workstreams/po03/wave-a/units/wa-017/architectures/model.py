"""Shared immutable records and metric arithmetic for the three simulators.

The scheduling, concurrency, completion, and recovery algorithms deliberately
live in separate modules.  This file only parses the frozen wire format and
normalizes measurements so that candidate results are comparable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


ALLOWED_FAULTS = {
    "none",
    "artifact_corrupt_first",
    "provider_loss_first",
    "stale_completion_first",
    "duplicate_callback",
}


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    release_tick: int
    duration: int
    shard: int
    write_key: str
    fault: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "Task":
        required = {
            "task_id",
            "release_tick",
            "duration",
            "shard",
            "write_key",
            "fault",
        }
        if set(value) != required:
            raise ValueError(
                f"task fields differ: expected {sorted(required)}, "
                f"observed {sorted(value)}"
            )
        task = cls(
            task_id=str(value["task_id"]),
            release_tick=int(value["release_tick"]),
            duration=int(value["duration"]),
            shard=int(value["shard"]),
            write_key=str(value["write_key"]),
            fault=str(value["fault"]),
        )
        if (
            not task.task_id
            or not task.write_key
            or task.release_tick < 0
            or task.duration < 1
            or task.shard < 0
            or task.fault not in ALLOWED_FAULTS
        ):
            raise ValueError(f"invalid task: {task}")
        return task


@dataclass(slots=True)
class Attempt:
    task: Task
    number: int
    token: int
    started_tick: int
    finish_tick: int
    collided: bool = False

    @property
    def identity(self) -> tuple[str, int]:
        return self.task.task_id, self.number


@dataclass(frozen=True, slots=True)
class Produced:
    task: Task
    attempt_number: int
    token: int
    reported_tick: int
    artifact_valid: bool
    collided: bool
    callback_id: str


def parse_tasks(document: dict[str, Any]) -> list[Task]:
    raw = document.get("tasks")
    if not isinstance(raw, list) or not raw:
        raise ValueError("workload tasks must be a non-empty array")
    tasks = [Task.from_mapping(item) for item in raw]
    identities = [task.task_id for task in tasks]
    if len(set(identities)) != len(identities):
        raise ValueError("workload task_id values must be unique")
    return sorted(tasks, key=lambda task: (task.release_tick, task.task_id))


def first_attempt_fault(task: Task, attempt_number: int, name: str) -> bool:
    return attempt_number == 1 and task.fault == name


def mark_collision_pairs(active: Iterable[Attempt]) -> set[tuple[str, str]]:
    """Return distinct active task pairs sharing a write key."""
    by_key: dict[str, list[Attempt]] = {}
    for attempt in active:
        by_key.setdefault(attempt.task.write_key, []).append(attempt)
    pairs: set[tuple[str, str]] = set()
    for attempts in by_key.values():
        if len(attempts) < 2:
            continue
        ordered = sorted(attempt.task.task_id for attempt in attempts)
        for left_index, left in enumerate(ordered):
            for right in ordered[left_index + 1 :]:
                pairs.add((left, right))
    return pairs


def percentile_nearest(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, int((len(ordered) * percentile) + 0.999999999))
    return ordered[min(rank, len(ordered)) - 1]


def finalize_result(
    *,
    candidate_id: str,
    mechanism_signature: str,
    task_count: int,
    accepted_at: dict[str, int],
    release_at: dict[str, int],
    final_tick: int,
    attempts_started: int,
    collision_pairs: set[tuple[str, str]],
    unverified_exposure_ticks: int,
    false_completions: int,
    duplicate_external_effects: int,
    lost_committed_results: int,
    recovery_events: int,
    verification_backlog_peak: int,
    mechanism_evidence: dict[str, Any],
    trace: list[dict[str, Any]],
) -> dict[str, Any]:
    accepted = sorted(accepted_at)
    elapsed_ticks = final_tick + 1
    latencies = [
        accepted_at[task_id] - release_at[task_id] + 1 for task_id in accepted
    ]
    return {
        "accepted_tasks": accepted,
        "candidate_id": candidate_id,
        "completed_workload": len(accepted) == task_count,
        "mechanism_evidence": mechanism_evidence,
        "mechanism_signature": mechanism_signature,
        "metrics": {
            "accepted_task_count": len(accepted),
            "accepted_throughput": round(
                len(accepted) / elapsed_ticks if elapsed_ticks else 0.0, 6
            ),
            "collision_events": len(collision_pairs),
            "duplicate_external_effects": duplicate_external_effects,
            "elapsed_ticks": elapsed_ticks,
            "false_completions": false_completions,
            "latency_p95_ticks": percentile_nearest(latencies, 0.95),
            "lost_committed_results": lost_committed_results,
            "recovery_events": recovery_events,
            "rework_attempts": max(0, attempts_started - len(accepted)),
            "unverified_exposure_ticks": unverified_exposure_ticks,
            "verification_backlog_peak": verification_backlog_peak,
        },
        "trace": trace,
    }
