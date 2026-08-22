"""Candidate 1: one global queue, write lock, and synchronous verifier."""

from __future__ import annotations

from collections import deque
from typing import Any

from .model import (
    Attempt,
    Produced,
    Task,
    finalize_result,
    first_attempt_fault,
)


CANDIDATE_ID = "central-gate"
MECHANISM_SIGNATURE = "shared-fifo|global-write-lock|synchronous-verification-gate"


class CentralGateFactory:
    """Strict global exclusion with a deliberately serialized custody gate."""

    def __init__(self, tasks: list[Task], parameters: dict[str, Any], maximum: int):
        self.tasks = tasks
        self.worker_capacity = int(parameters["worker_capacity"])
        self.verification_capacity = int(parameters["verification_capacity"])
        self.verification_ticks = int(parameters["verification_ticks"])
        self.maximum = maximum

    def run(self) -> dict[str, Any]:
        pending = deque(self.tasks)
        ready: list[Task] = []
        delayed: list[tuple[int, Task]] = []
        active: list[Attempt] = []
        verify_queue: deque[Produced] = deque()
        verifying: list[tuple[int, Produced]] = []
        accepted_at: dict[str, int] = {}
        release_at = {task.task_id: task.release_tick for task in self.tasks}
        attempts: dict[str, int] = {}
        current_token: dict[str, int] = {}
        callback_ids: set[str] = set()
        final_projection: set[str] = set()
        trace: list[dict[str, Any]] = []
        attempts_started = 0
        recoveries = 0
        duplicate_effects = 0
        false_completions = 0
        backlog_peak = 0

        def schedule_retry(task: Task, available: int, reason: str) -> None:
            nonlocal recoveries
            recoveries += 1
            delayed.append((available, task))
            trace.append(
                {
                    "event": "RETRY_SCHEDULED",
                    "reason": reason,
                    "task_id": task.task_id,
                    "tick": available,
                }
            )

        for tick in range(self.maximum):
            while pending and pending[0].release_tick <= tick:
                ready.append(pending.popleft())
            due = sorted(
                (item for item in delayed if item[0] <= tick),
                key=lambda item: (item[0], item[1].task_id),
            )
            delayed = [item for item in delayed if item[0] > tick]
            ready.extend(task for _, task in due)
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
                    schedule_retry(task, tick + 2, "PROVIDER_LOSS")
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
                    collided=False,
                    callback_id=f"{task.task_id}:{attempt.number}",
                )
                deliveries = (
                    [produced, produced]
                    if first_attempt_fault(
                        task, attempt.number, "duplicate_callback"
                    )
                    else [produced]
                )
                for delivery in deliveries:
                    if delivery.callback_id in callback_ids:
                        trace.append(
                            {
                                "event": "DUPLICATE_CALLBACK_IGNORED",
                                "task_id": task.task_id,
                                "tick": tick,
                            }
                        )
                        continue
                    callback_ids.add(delivery.callback_id)
                    verify_queue.append(delivery)
                    trace.append(
                        {
                            "event": "RESULT_QUEUED_FOR_GLOBAL_VERIFICATION",
                            "task_id": task.task_id,
                            "tick": tick,
                        }
                    )

            completed_verifications = sorted(
                (item for item in verifying if item[0] <= tick),
                key=lambda item: item[1].task.task_id,
            )
            verifying = [item for item in verifying if item[0] > tick]
            for _, produced in completed_verifications:
                task = produced.task
                valid = (
                    produced.token == current_token[task.task_id]
                    and produced.artifact_valid
                    and not produced.collided
                )
                if not valid:
                    reason = (
                        "STALE_TOKEN"
                        if produced.token != current_token[task.task_id]
                        else "ARTIFACT_HASH_MISMATCH"
                    )
                    schedule_retry(task, tick + 1, reason)
                    continue
                if task.task_id in accepted_at:
                    duplicate_effects += 1
                    continue
                accepted_at[task.task_id] = tick
                final_projection.add(task.task_id)
                trace.append(
                    {
                        "event": "ACCEPTED_BY_GLOBAL_GATE",
                        "task_id": task.task_id,
                        "tick": tick,
                    }
                )

            while (
                verify_queue
                and len(verifying) < self.verification_capacity
            ):
                produced = verify_queue.popleft()
                verifying.append((tick + self.verification_ticks, produced))

            while ready and len(active) < self.worker_capacity:
                locked = {attempt.task.write_key for attempt in active}
                eligible_index = next(
                    (
                        index
                        for index, task in enumerate(ready)
                        if task.write_key not in locked
                    ),
                    None,
                )
                if eligible_index is None:
                    break
                task = ready.pop(eligible_index)
                number = attempts.get(task.task_id, 0) + 1
                attempts[task.task_id] = number
                current_token[task.task_id] = number
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
                trace.append(
                    {
                        "event": "GLOBAL_DISPATCH",
                        "task_id": task.task_id,
                        "tick": tick,
                        "token": number,
                    }
                )

            backlog_peak = max(
                backlog_peak, len(verify_queue) + len(verifying)
            )
            if len(accepted_at) == len(self.tasks):
                lost = len(set(accepted_at) - final_projection)
                return finalize_result(
                    candidate_id=CANDIDATE_ID,
                    mechanism_signature=MECHANISM_SIGNATURE,
                    task_count=len(self.tasks),
                    accepted_at=accepted_at,
                    release_at=release_at,
                    final_tick=tick,
                    attempts_started=attempts_started,
                    collision_pairs=set(),
                    unverified_exposure_ticks=0,
                    false_completions=false_completions,
                    duplicate_external_effects=duplicate_effects,
                    lost_committed_results=lost,
                    recovery_events=recoveries,
                    verification_backlog_peak=backlog_peak,
                    mechanism_evidence={
                        "completion_authority": "single global synchronous verifier",
                        "concurrency_guard": "global active write-key lock",
                        "durable_projection": "central accepted task set",
                        "recovery": "central delayed retry queue",
                        "scheduler": "shared release-ordered FIFO",
                    },
                    trace=trace,
                )
        raise RuntimeError(f"{CANDIDATE_ID} exceeded {self.maximum} ticks")
