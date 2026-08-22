"""Three executable coordination candidates under one deterministic simulator."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

from .model import WorkItem, Workload, canonical_json_bytes


@dataclass(frozen=True)
class RecoveryPlan:
    end_tick: int
    impacted_tasks: int
    lost_work_ticks: int
    replayed_events: int


class Topology:
    name = "abstract"

    def apply_fault(self, simulation: "Simulation", tick: int) -> RecoveryPlan:
        raise NotImplementedError

    def task_available(self, simulation: "Simulation", task: WorkItem, tick: int) -> bool:
        if simulation.recovery is None:
            return True
        return tick >= simulation.recovery.end_tick

    def select_acceptances(
        self, simulation: "Simulation", tick: int, budget: int
    ) -> list[str]:
        return [
            task_id
            for task_id in simulation.waiting
            if self.task_available(simulation, simulation.task_by_id[task_id], tick)
        ][:budget]

    def select_dispatches(
        self, simulation: "Simulation", tick: int, budget: int
    ) -> list[str]:
        return [
            task_id
            for task_id in simulation.queued
            if self.task_available(simulation, simulation.task_by_id[task_id], tick)
        ][:budget]


class CentralizedTopology(Topology):
    """One volatile coordinator with a global queue and durable accept records."""

    name = "centralized"

    def apply_fault(self, simulation: "Simulation", tick: int) -> RecoveryPlan:
        impacted = list(simulation.running) + list(simulation.waiting)
        lost_work = 0
        for task_id, remaining in simulation.running.items():
            lost_work += simulation.task_by_id[task_id].work_ticks - remaining
        for task_id in simulation.waiting:
            lost_work += simulation.task_by_id[task_id].work_ticks
        simulation.requeue(impacted)
        recovery_ticks = simulation.workload.config.restart_ticks + math.ceil(
            len(impacted) / simulation.workload.config.reconcile_tasks_per_tick
        )
        return RecoveryPlan(
            end_tick=tick + recovery_ticks,
            impacted_tasks=len(impacted),
            lost_work_ticks=lost_work,
            replayed_events=0,
        )


class ShardedTopology(Topology):
    """Four independent shard coordinators sharing the matched worker pool."""

    name = "sharded"

    def apply_fault(self, simulation: "Simulation", tick: int) -> RecoveryPlan:
        target = simulation.workload.fault.target_shard
        impacted_running = [
            task_id
            for task_id in simulation.running
            if simulation.task_by_id[task_id].shard == target
        ]
        impacted_waiting = [
            task_id
            for task_id in simulation.waiting
            if simulation.task_by_id[task_id].shard == target
        ]
        lost_work = sum(
            simulation.task_by_id[task_id].work_ticks - simulation.running[task_id]
            for task_id in impacted_running
        )
        lost_work += sum(
            simulation.task_by_id[task_id].work_ticks for task_id in impacted_waiting
        )
        impacted = impacted_running + impacted_waiting
        simulation.requeue(impacted)
        recovery_ticks = simulation.workload.config.restart_ticks + math.ceil(
            len(impacted) / simulation.workload.config.reconcile_tasks_per_tick
        )
        return RecoveryPlan(
            end_tick=tick + recovery_ticks,
            impacted_tasks=len(impacted),
            lost_work_ticks=lost_work,
            replayed_events=0,
        )

    def task_available(self, simulation: "Simulation", task: WorkItem, tick: int) -> bool:
        if simulation.recovery is None:
            return True
        return (
            task.shard != simulation.workload.fault.target_shard
            or tick >= simulation.recovery.end_tick
        )

    def select_acceptances(
        self, simulation: "Simulation", tick: int, budget: int
    ) -> list[str]:
        selected: list[str] = []
        used_shards: set[int] = set()
        for task_id in simulation.waiting:
            task = simulation.task_by_id[task_id]
            if (
                len(selected) < budget
                and task.shard not in used_shards
                and self.task_available(simulation, task, tick)
            ):
                selected.append(task_id)
                used_shards.add(task.shard)
        return selected


class EventSourcedTopology(Topology):
    """A durable event log rebuilt by replay after coordinator loss."""

    name = "event-sourced"

    def apply_fault(self, simulation: "Simulation", tick: int) -> RecoveryPlan:
        replayed = simulation.events_written
        recovery_ticks = simulation.workload.config.restart_ticks + math.ceil(
            replayed / simulation.workload.config.replay_events_per_tick
        )
        return RecoveryPlan(
            end_tick=tick + recovery_ticks,
            impacted_tasks=len(simulation.running) + len(simulation.waiting),
            lost_work_ticks=0,
            replayed_events=replayed,
        )


TOPOLOGIES: dict[str, type[Topology]] = {
    CentralizedTopology.name: CentralizedTopology,
    ShardedTopology.name: ShardedTopology,
    EventSourcedTopology.name: EventSourcedTopology,
}


class Simulation:
    """A matched worker/coordination envelope driven only by logical ticks."""

    def __init__(self, workload: Workload, topology: Topology, inject_fault: bool):
        self.workload = workload
        self.topology = topology
        self.inject_fault = inject_fault
        self.task_by_id = {task.task_id: task for task in workload.tasks}
        self.task_order = {task.task_id: index for index, task in enumerate(workload.tasks)}
        self.queued = [task.task_id for task in workload.tasks]
        self.running: dict[str, int] = {}
        self.waiting: list[str] = []
        self.accepted: dict[str, int] = {}
        self.accept_order: list[str] = []
        self.recovery: RecoveryPlan | None = None
        self.fault_applied = False
        self.events_written = len(workload.tasks) if isinstance(topology, EventSourcedTopology) else 0
        self.trace: list[dict[str, Any]] = []
        self.duplicate_acceptances = 0

    def requeue(self, task_ids: list[str]) -> None:
        if not task_ids:
            return
        affected = set(task_ids)
        for task_id in affected:
            self.running.pop(task_id, None)
        self.waiting = [task_id for task_id in self.waiting if task_id not in affected]
        self.queued = sorted(set(self.queued) | affected, key=self.task_order.__getitem__)

    def _complete_work(self, tick: int) -> None:
        completed: list[str] = []
        for task_id in list(self.running):
            self.running[task_id] -= 1
            if self.running[task_id] == 0:
                completed.append(task_id)
                del self.running[task_id]
        for task_id in sorted(completed, key=self.task_order.__getitem__):
            self.waiting.append(task_id)
            if isinstance(self.topology, EventSourcedTopology):
                self.events_written += 1
            self.trace.append({"tick": tick, "event": "WORK_FINISHED", "task_id": task_id})

    def _accept_and_dispatch(self, tick: int) -> None:
        budget = self.workload.config.coordination_ops_per_tick
        accepted_now = self.topology.select_acceptances(self, tick, budget)
        for task_id in accepted_now:
            self.waiting.remove(task_id)
            if task_id in self.accepted:
                self.duplicate_acceptances += 1
                continue
            self.accepted[task_id] = tick
            self.accept_order.append(task_id)
            budget -= 1
            if isinstance(self.topology, EventSourcedTopology):
                self.events_written += 1
            self.trace.append({"tick": tick, "event": "ACCEPTED", "task_id": task_id})

        free_workers = self.workload.config.worker_slots - len(self.running)
        dispatch_budget = min(budget, free_workers)
        for task_id in self.topology.select_dispatches(self, tick, dispatch_budget):
            self.queued.remove(task_id)
            self.running[task_id] = self.task_by_id[task_id].work_ticks
            if isinstance(self.topology, EventSourcedTopology):
                self.events_written += 1
            self.trace.append({"tick": tick, "event": "DISPATCHED", "task_id": task_id})

    def run(self) -> dict[str, Any]:
        total = len(self.workload.tasks)
        makespan = self.workload.config.max_ticks
        for tick in range(self.workload.config.max_ticks):
            if (
                self.inject_fault
                and not self.fault_applied
                and tick == self.workload.fault.tick
            ):
                self.fault_applied = True
                self.recovery = self.topology.apply_fault(self, tick)
                self.trace.append(
                    {
                        "tick": tick,
                        "event": "COORDINATOR_PROCESS_LOSS",
                        "recovery_end_tick": self.recovery.end_tick,
                        "impacted_tasks": self.recovery.impacted_tasks,
                    }
                )
            self._complete_work(tick)
            self._accept_and_dispatch(tick)
            if len(self.accepted) == total:
                makespan = tick + 1
                break

        accepted_ticks = list(self.accepted.values())
        fault_tick = self.workload.fault.tick if self.inject_fault else None
        recovery_end = self.recovery.end_tick if self.recovery else None
        accepted_during_outage = (
            sum(
                1
                for tick in accepted_ticks
                if fault_tick is not None
                and recovery_end is not None
                and fault_tick <= tick < recovery_end
            )
            if self.recovery
            else 0
        )
        first_post_recovery = (
            min((tick for tick in accepted_ticks if tick >= recovery_end), default=None)
            if recovery_end is not None
            else None
        )
        throughput = round(len(self.accepted) / makespan, 6) if makespan else 0.0
        trace_digest = hashlib.sha256(canonical_json_bytes(self.trace)).hexdigest()
        result = {
            "topology": self.topology.name,
            "scenario": "coordinator-loss" if self.inject_fault else "baseline",
            "workload_sha256": self.workload.fixture_sha256,
            "task_count": total,
            "accepted_count": len(self.accepted),
            "all_tasks_accepted": len(self.accepted) == total,
            "makespan_ticks": makespan,
            "accepted_throughput_per_tick": throughput,
            "accepted_order": self.accept_order,
            "duplicate_acceptances": self.duplicate_acceptances,
            "trace_sha256": trace_digest,
            "coordination": {
                "worker_slots": self.workload.config.worker_slots,
                "coordination_ops_per_tick": self.workload.config.coordination_ops_per_tick,
            },
            "recovery": {
                "fault_tick": fault_tick,
                "recovery_end_tick": recovery_end,
                "recovery_ticks": (
                    recovery_end - fault_tick
                    if recovery_end is not None and fault_tick is not None
                    else 0
                ),
                "impacted_tasks": self.recovery.impacted_tasks if self.recovery else 0,
                "lost_work_ticks": self.recovery.lost_work_ticks if self.recovery else 0,
                "replayed_events": self.recovery.replayed_events if self.recovery else 0,
                "accepted_during_outage": accepted_during_outage,
                "first_acceptance_at_or_after_recovery": first_post_recovery,
            },
        }
        result["outcome_vector"] = [
            result["accepted_throughput_per_tick"],
            result["makespan_ticks"],
            result["recovery"]["recovery_ticks"],
            result["recovery"]["accepted_during_outage"],
            result["recovery"]["lost_work_ticks"],
            result["recovery"]["replayed_events"],
        ]
        return result
