"""Candidate 3: optimistic workers feeding an append-only event reducer."""

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


CANDIDATE_ID = "event-log"
MECHANISM_SIGNATURE = "append-only-log|optimistic-workers|asynchronous-materializer"


class EventLogFactory:
    """Optimistic execution with asynchronous, replayable materialization."""

    def __init__(self, tasks: list[Task], parameters: dict[str, Any], maximum: int):
        self.tasks = tasks
        self.worker_capacity = int(parameters["worker_capacity"])
        self.materializer_capacity = int(parameters["materializer_capacity"])
        self.materializer_ticks = int(parameters["materializer_ticks"])
        self.maximum = maximum

    def run(self) -> dict[str, Any]:
        unreleased = list(self.tasks)
        ready: list[Task] = []
        delayed: list[tuple[int, Task]] = []
        active: list[Attempt] = []
        reduction_queue: deque[Produced] = deque()
        reducing: list[tuple[int, Produced]] = []
        attempts: dict[str, int] = {}
        generation: dict[str, int] = {}
        accepted_at: dict[str, int] = {}
        release_at = {task.task_id: task.release_tick for task in self.tasks}
        processed_callbacks: set[str] = set()
        exposed_since: dict[str, int] = {}
        serialized_keys: set[str] = set()
        collision_pairs: set[tuple[str, str]] = set()
        events: list[dict[str, Any]] = []
        attempts_started = 0
        recoveries = 0
        duplicate_effects = 0
        false_completions = 0
        backlog_peak = 0
        exposure_ticks = 0

        def append_event(tick: int, kind: str, **detail: Any) -> None:
            events.append(
                {
                    "event": kind,
                    "event_seq": len(events) + 1,
                    "tick": tick,
                    **detail,
                }
            )

        def retry(task: Task, tick: int, reason: str) -> None:
            nonlocal recoveries
            recoveries += 1
            suffix = int(task.task_id.rsplit("-", 1)[1])
            available = tick + 1 + (suffix % 2)
            delayed.append((available, task))
            append_event(
                tick,
                "RETRY_APPENDED",
                available_tick=available,
                reason=reason,
                task_id=task.task_id,
            )

        for tick in range(self.maximum):
            due_now = [task for task in unreleased if task.release_tick <= tick]
            unreleased = [
                task for task in unreleased if task.release_tick > tick
            ]
            for task in sorted(due_now, key=lambda item: item.task_id):
                ready.append(task)
                append_event(tick, "TASK_RELEASED", task_id=task.task_id)
            due_retries = sorted(
                (item for item in delayed if item[0] <= tick),
                key=lambda item: (item[0], item[1].task_id),
            )
            delayed = [item for item in delayed if item[0] > tick]
            ready.extend(task for _, task in due_retries)
            ready.sort(key=lambda task: (task.release_tick, task.task_id))

            completed_workers = sorted(
                (attempt for attempt in active if attempt.finish_tick <= tick),
                key=lambda attempt: attempt.task.task_id,
            )
            active = [
                attempt for attempt in active if attempt.finish_tick > tick
            ]
            for attempt in completed_workers:
                task = attempt.task
                if first_attempt_fault(task, attempt.number, "provider_loss_first"):
                    append_event(
                        tick,
                        "WORKER_LOST",
                        generation=attempt.number,
                        task_id=task.task_id,
                    )
                    retry(task, tick, "MISSING_RESULT_EVENT")
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
                    callback_id=f"event:{task.task_id}:{attempt.number}",
                )
                copies = (
                    2
                    if first_attempt_fault(
                        task, attempt.number, "duplicate_callback"
                    )
                    else 1
                )
                for copy_index in range(copies):
                    append_event(
                        tick,
                        "RESULT_REPORTED",
                        callback_id=produced.callback_id,
                        copy_index=copy_index,
                        generation=token,
                        task_id=task.task_id,
                    )
                    reduction_queue.append(produced)
                exposed_since.setdefault(task.task_id, tick)

            completed_reductions = sorted(
                (item for item in reducing if item[0] <= tick),
                key=lambda item: (
                    item[1].task.task_id,
                    item[1].attempt_number,
                ),
            )
            reducing = [item for item in reducing if item[0] > tick]
            for _, produced in completed_reductions:
                task = produced.task
                if produced.callback_id in processed_callbacks:
                    append_event(
                        tick,
                        "DUPLICATE_EVENT_REDUCED",
                        callback_id=produced.callback_id,
                        task_id=task.task_id,
                    )
                    continue
                processed_callbacks.add(produced.callback_id)
                valid = (
                    produced.token == generation[task.task_id]
                    and produced.artifact_valid
                    and not produced.collided
                )
                if not valid:
                    exposed_since.pop(task.task_id, None)
                    if produced.collided:
                        serialized_keys.add(task.write_key)
                        reason = "OPTIMISTIC_WRITE_CONFLICT"
                    elif produced.token != generation[task.task_id]:
                        reason = "STALE_GENERATION"
                    else:
                        reason = "ARTIFACT_HASH_MISMATCH"
                    append_event(
                        tick,
                        "RESULT_REJECTED_BY_REDUCER",
                        reason=reason,
                        task_id=task.task_id,
                    )
                    retry(task, tick, reason)
                    continue
                exposed_since.pop(task.task_id, None)
                if task.task_id in accepted_at:
                    duplicate_effects += 1
                    append_event(
                        tick,
                        "DUPLICATE_EFFECT_REFUSED",
                        task_id=task.task_id,
                    )
                    continue
                accepted_at[task.task_id] = tick
                append_event(
                    tick,
                    "MATERIALIZED_ACCEPTED",
                    generation=produced.attempt_number,
                    task_id=task.task_id,
                )

            while (
                reduction_queue
                and len(reducing) < self.materializer_capacity
            ):
                produced = reduction_queue.popleft()
                reducing.append((tick + self.materializer_ticks, produced))

            while ready and len(active) < self.worker_capacity:
                eligible_index = next(
                    (
                        index
                        for index, task in enumerate(ready)
                        if task.write_key not in serialized_keys
                        or all(
                            attempt.task.write_key != task.write_key
                            for attempt in active
                        )
                    ),
                    None,
                )
                if eligible_index is None:
                    break
                task = ready.pop(eligible_index)
                number = attempts.get(task.task_id, 0) + 1
                attempts[task.task_id] = number
                generation[task.task_id] = number
                attempts_started += 1
                active.append(
                    Attempt(
                        task=task,
                        number=number,
                        token=number,
                        started_tick=tick,
                        finish_tick=tick + task.duration,
                    )
                )
                append_event(
                    tick,
                    "OPTIMISTIC_DISPATCH",
                    generation=number,
                    task_id=task.task_id,
                )

            observed_pairs = mark_collision_pairs(active)
            new_pairs = observed_pairs - collision_pairs
            collision_pairs.update(new_pairs)
            for left, right in sorted(new_pairs):
                append_event(
                    tick,
                    "OPTIMISTIC_COLLISION_OBSERVED",
                    tasks=[left, right],
                )
            collided_ids = {task_id for pair in observed_pairs for task_id in pair}
            for attempt in active:
                if attempt.task.task_id in collided_ids:
                    attempt.collided = True

            backlog_peak = max(
                backlog_peak, len(reduction_queue) + len(reducing)
            )
            exposure_ticks += len(exposed_since)
            if len(accepted_at) == len(self.tasks):
                replayed_projection = {
                    event["task_id"]
                    for event in events
                    if event["event"] == "MATERIALIZED_ACCEPTED"
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
                    unverified_exposure_ticks=exposure_ticks,
                    false_completions=false_completions,
                    duplicate_external_effects=duplicate_effects,
                    lost_committed_results=len(
                        set(accepted_at) - replayed_projection
                    ),
                    recovery_events=recoveries,
                    verification_backlog_peak=backlog_peak,
                    mechanism_evidence={
                        "completion_authority": (
                            "asynchronous reducer over RESULT_REPORTED events"
                        ),
                        "concurrency_guard": (
                            "optimistic first execution; reducer adds dependency "
                            "serialization after a conflict"
                        ),
                        "durable_projection": (
                            "set replayed from MATERIALIZED_ACCEPTED events"
                        ),
                        "event_count": len(events),
                        "recovery": "append retry and replay from event sequence",
                        "scheduler": "single optimistic arrival queue",
                    },
                    trace=events,
                )
        raise RuntimeError(f"{CANDIDATE_ID} exceeded {self.maximum} ticks")
