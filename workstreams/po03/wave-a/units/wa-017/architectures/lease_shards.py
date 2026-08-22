"""Candidate 2: partitioned lease/fence stores with local verification."""

from __future__ import annotations

from collections import deque
from typing import Any

from .model import (
    Attempt,
    Produced,
    Task,
    finalize_result,
    first_attempt_fault,
    mark_collision_pairs,
)


CANDIDATE_ID = "lease-shards"
MECHANISM_SIGNATURE = "partitioned-fifo|local-write-lock|fenced-per-shard-verification"


class LeaseShardFactory:
    """Independent shard queues; cross-shard conflicts are learned on recovery."""

    def __init__(self, tasks: list[Task], parameters: dict[str, Any], maximum: int):
        self.tasks = tasks
        self.shard_count = int(parameters["shard_count"])
        self.workers_per_shard = int(parameters["workers_per_shard"])
        self.verifiers_per_shard = int(parameters["verifiers_per_shard"])
        self.verification_ticks = int(parameters["verification_ticks"])
        self.maximum = maximum
        if any(task.shard >= self.shard_count for task in tasks):
            raise ValueError("task references an unavailable shard")

    def run(self) -> dict[str, Any]:
        shard_state = {
            shard: {
                "ready": [],
                "active": [],
                "verify_queue": deque(),
                "verifying": [],
                "callback_ids": set(),
                "projection": set(),
            }
            for shard in range(self.shard_count)
        }
        unreleased = list(self.tasks)
        delayed: list[tuple[int, int, Task]] = []
        attempts: dict[str, int] = {}
        fence: dict[str, int] = {}
        accepted_at: dict[str, int] = {}
        release_at = {task.task_id: task.release_tick for task in self.tasks}
        contested_keys: set[str] = set()
        collision_pairs: set[tuple[str, str]] = set()
        trace: list[dict[str, Any]] = []
        attempts_started = 0
        recoveries = 0
        duplicate_effects = 0
        false_completions = 0
        backlog_peak = 0

        def retry(task: Task, tick: int, reason: str) -> None:
            nonlocal recoveries
            recoveries += 1
            # Different shard offsets prevent recovered conflicts from marching
            # in lockstep.  This is recovery coordination, not normal dispatch.
            available = tick + 1 + task.shard
            delayed.append((available, task.shard, task))
            trace.append(
                {
                    "event": "SHARD_RETRY_SCHEDULED",
                    "reason": reason,
                    "shard": task.shard,
                    "task_id": task.task_id,
                    "tick": available,
                }
            )

        for tick in range(self.maximum):
            due_now = [task for task in unreleased if task.release_tick <= tick]
            unreleased = [
                task for task in unreleased if task.release_tick > tick
            ]
            for task in due_now:
                shard_state[task.shard]["ready"].append(task)
            due_retries = sorted(
                (item for item in delayed if item[0] <= tick),
                key=lambda item: (item[0], item[1], item[2].task_id),
            )
            delayed = [item for item in delayed if item[0] > tick]
            for _, shard, task in due_retries:
                shard_state[shard]["ready"].append(task)
            for state in shard_state.values():
                state["ready"].sort(
                    key=lambda task: (task.release_tick, task.task_id)
                )

            for shard in range(self.shard_count):
                state = shard_state[shard]
                completed = sorted(
                    (
                        attempt
                        for attempt in state["active"]
                        if attempt.finish_tick <= tick
                    ),
                    key=lambda attempt: attempt.task.task_id,
                )
                state["active"] = [
                    attempt
                    for attempt in state["active"]
                    if attempt.finish_tick > tick
                ]
                for attempt in completed:
                    task = attempt.task
                    if first_attempt_fault(
                        task, attempt.number, "provider_loss_first"
                    ):
                        retry(task, tick, "LEASED_WORKER_LOST")
                        continue
                    token = attempt.token
                    if first_attempt_fault(
                        task, attempt.number, "stale_completion_first"
                    ):
                        token -= 1
                    produced = Produced(
                        task=task,
                        attempt_number=attempt.number,
                        token=token,
                        reported_tick=tick,
                        artifact_valid=not first_attempt_fault(
                            task, attempt.number, "artifact_corrupt_first"
                        ),
                        collided=attempt.collided,
                        callback_id=(
                            f"shard-{shard}:{task.task_id}:{attempt.number}"
                        ),
                    )
                    copies = (
                        2
                        if first_attempt_fault(
                            task, attempt.number, "duplicate_callback"
                        )
                        else 1
                    )
                    for _ in range(copies):
                        if produced.callback_id in state["callback_ids"]:
                            trace.append(
                                {
                                    "event": "SHARD_DUPLICATE_IGNORED",
                                    "shard": shard,
                                    "task_id": task.task_id,
                                    "tick": tick,
                                }
                            )
                            continue
                        state["callback_ids"].add(produced.callback_id)
                        state["verify_queue"].append(produced)

            for shard in range(self.shard_count):
                state = shard_state[shard]
                completed = sorted(
                    (
                        item
                        for item in state["verifying"]
                        if item[0] <= tick
                    ),
                    key=lambda item: item[1].task.task_id,
                )
                state["verifying"] = [
                    item for item in state["verifying"] if item[0] > tick
                ]
                for _, produced in completed:
                    task = produced.task
                    valid = (
                        produced.token == fence[task.task_id]
                        and produced.artifact_valid
                        and not produced.collided
                    )
                    if not valid:
                        if produced.collided:
                            contested_keys.add(task.write_key)
                            reason = "CROSS_SHARD_COLLISION"
                        elif produced.token != fence[task.task_id]:
                            reason = "STALE_FENCE"
                        else:
                            reason = "ARTIFACT_HASH_MISMATCH"
                        retry(task, tick, reason)
                        continue
                    if task.task_id in accepted_at:
                        duplicate_effects += 1
                        continue
                    accepted_at[task.task_id] = tick
                    state["projection"].add(task.task_id)
                    trace.append(
                        {
                            "event": "SHARD_ACCEPTED",
                            "shard": shard,
                            "task_id": task.task_id,
                            "tick": tick,
                        }
                    )
                while (
                    state["verify_queue"]
                    and len(state["verifying"]) < self.verifiers_per_shard
                ):
                    produced = state["verify_queue"].popleft()
                    state["verifying"].append(
                        (tick + self.verification_ticks, produced)
                    )

            for shard in range(self.shard_count):
                state = shard_state[shard]
                while (
                    state["ready"]
                    and len(state["active"]) < self.workers_per_shard
                ):
                    local_locked = {
                        attempt.task.write_key for attempt in state["active"]
                    }
                    global_active = [
                        attempt
                        for other in shard_state.values()
                        for attempt in other["active"]
                    ]
                    eligible_index = next(
                        (
                            index
                            for index, task in enumerate(state["ready"])
                            if task.write_key not in local_locked
                            and (
                                task.write_key not in contested_keys
                                or all(
                                    active.task.write_key != task.write_key
                                    for active in global_active
                                )
                            )
                        ),
                        None,
                    )
                    if eligible_index is None:
                        break
                    task = state["ready"].pop(eligible_index)
                    number = attempts.get(task.task_id, 0) + 1
                    attempts[task.task_id] = number
                    fence[task.task_id] = number
                    attempts_started += 1
                    state["active"].append(
                        Attempt(
                            task=task,
                            number=number,
                            token=number,
                            started_tick=tick,
                            finish_tick=tick + task.duration,
                        )
                    )
                    trace.append(
                        {
                            "event": "SHARD_DISPATCH",
                            "fence": number,
                            "shard": shard,
                            "task_id": task.task_id,
                            "tick": tick,
                        }
                    )

            all_active = [
                attempt
                for state in shard_state.values()
                for attempt in state["active"]
            ]
            observed_pairs = mark_collision_pairs(all_active)
            new_pairs = observed_pairs - collision_pairs
            if new_pairs:
                collision_pairs.update(new_pairs)
                for left, right in sorted(new_pairs):
                    trace.append(
                        {
                            "event": "CROSS_SHARD_COLLISION_OBSERVED",
                            "tasks": [left, right],
                            "tick": tick,
                        }
                    )
            collided_ids = {task_id for pair in observed_pairs for task_id in pair}
            for attempt in all_active:
                if attempt.task.task_id in collided_ids:
                    attempt.collided = True

            backlog_peak = max(
                backlog_peak,
                sum(
                    len(state["verify_queue"]) + len(state["verifying"])
                    for state in shard_state.values()
                ),
            )
            if len(accepted_at) == len(self.tasks):
                projection = {
                    task_id
                    for state in shard_state.values()
                    for task_id in state["projection"]
                }
                return finalize_result(
                    candidate_id=CANDIDATE_ID,
                    mechanism_signature=MECHANISM_SIGNATURE,
                    task_count=len(self.tasks),
                    accepted_at=accepted_at,
                    release_at=release_at,
                    final_tick=tick,
                    attempts_started=attempts_started,
                    collision_pairs=collision_pairs,
                    unverified_exposure_ticks=0,
                    false_completions=false_completions,
                    duplicate_external_effects=duplicate_effects,
                    lost_committed_results=len(set(accepted_at) - projection),
                    recovery_events=recoveries,
                    verification_backlog_peak=backlog_peak,
                    mechanism_evidence={
                        "completion_authority": "independent per-shard verifiers",
                        "concurrency_guard": (
                            "local write locks and monotonic fences; contested "
                            "keys gain a recovery-only global exclusion"
                        ),
                        "durable_projection": "union of three shard projections",
                        "recovery": "fenced retry with shard-offset staggering",
                        "scheduler": "three partitioned release-ordered FIFOs",
                    },
                    trace=trace,
                )
        raise RuntimeError(f"{CANDIDATE_ID} exceeded {self.maximum} ticks")
