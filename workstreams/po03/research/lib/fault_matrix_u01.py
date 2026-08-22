"""The four fault classes a5-u01 predicts map 1:1 onto the four invariants.

Each ``run_fault_*`` function returns ``True`` if the engine survived the
injected fault (no duplicate external effect, no accepted stale write, no
permanently ambiguous recovery state) and ``False`` otherwise.
"""

from __future__ import annotations

from .counterfactual_engine import MinimalCustodyEngine

FAULT_TO_INVARIANT = {
    "duplicate_callback": "idempotency_key",
    "stale_writer_after_eviction": "fence_token",
    "crash_before_local_record": "outbox",
    "restart_with_no_checkpoint": "checkpoint",
}


def run_fault_duplicate_callback(engine: MinimalCustodyEngine, unit_id: str) -> bool:
    fence = engine.lease(unit_id, "w1")
    engine.submit(unit_id, fence, "payload-A")
    engine.submit(unit_id, fence, "payload-A")  # network-retried duplicate callback
    return engine.effect_count(unit_id) == 1


def run_fault_stale_writer_after_eviction(engine: MinimalCustodyEngine, unit_id: str) -> bool:
    fence1 = engine.lease(unit_id, "w1")
    fence2 = engine.lease(unit_id, "w2")  # w1 presumed dead; ownership transferred to w2
    engine.submit(unit_id, fence2, "payload-from-w2")
    engine.submit(unit_id, fence1, "payload-from-stale-w1")  # w1 resurfaces after eviction
    return engine.effect_count(unit_id) == 1


def run_fault_crash_before_local_record(engine: MinimalCustodyEngine, unit_id: str) -> bool:
    fence = engine.lease(unit_id, "w1")
    engine.submit(unit_id, fence, "payload-A", crash_before_record=True)
    # process restarts; worker (or its immediate successor) retries the same
    # attempt because no durable record proved the earlier one landed
    engine.submit(unit_id, fence, "payload-A")
    return engine.effect_count(unit_id) == 1


def run_fault_restart_with_no_checkpoint(engine: MinimalCustodyEngine, unit_id: str) -> bool:
    fence = engine.lease(unit_id, "w1")
    engine.submit(unit_id, fence, "payload-A")
    return engine.can_recover_after_restart(unit_id)


FAULT_RUNNERS = {
    "duplicate_callback": run_fault_duplicate_callback,
    "stale_writer_after_eviction": run_fault_stale_writer_after_eviction,
    "crash_before_local_record": run_fault_crash_before_local_record,
    "restart_with_no_checkpoint": run_fault_restart_with_no_checkpoint,
}


def build_survival_matrix(configs) -> dict[str, dict[str, bool]]:
    """Return {config_label: {fault_name: survived_bool}} for N=20 unit instances per cell."""
    matrix: dict[str, dict[str, bool]] = {}
    for config in configs:
        row: dict[str, bool] = {}
        for fault_name, runner in FAULT_RUNNERS.items():
            survivals = []
            for i in range(20):
                engine = MinimalCustodyEngine(config)
                unit_id = f"unit-{fault_name}-{i}"
                survivals.append(runner(engine, unit_id))
            row[fault_name] = all(survivals)
            row[f"{fault_name}__survival_rate"] = sum(survivals) / len(survivals)
        matrix[config.label()] = row
    return matrix
