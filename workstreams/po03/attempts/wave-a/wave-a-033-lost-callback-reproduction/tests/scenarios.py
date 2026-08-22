#!/usr/bin/env python3
"""Deterministic lost-provider-callback fault injection against the live factory.

Each scenario drives the pinned controller through its own public API, drops the
callback that a healthy route would deliver, and then asks the controller to
reclassify the unit from immutable input plus the hash-chained ledger alone.
Observations are returned as plain data so the assertions and the recorded
result read from the same source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from sandbox import (
    Sandbox,
    build_sandbox,
    lease_reservation,
    provider_starts_running,
    seed_task,
    wait_for_lease_expiry,
)

FORGED_COMMIT = "0" * 39 + "1"


def _attempt(action: Callable[[], Any]) -> dict[str, Any]:
    """Run one fault-injection step and capture the controller's verdict."""
    try:
        value = action()
    except Exception as error:  # noqa: BLE001 - the verdict class is the observation
        return {
            "outcome": "REJECTED",
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
    if isinstance(value, Path):
        value = value.name
    return {"outcome": "ACCEPTED", "value": value}


def _classification(sandbox: Sandbox, task_id: str) -> dict[str, Any]:
    """Rebuild the controller's view from immutable state only."""
    factory = sandbox.factory
    events = factory.task_events(task_id)
    unit = factory._recovery_unit(task_id)
    scan = {finding["task_id"]: finding for finding in factory.recovery_scan()}
    return {
        "obzio_state": unit["obzio_state"],
        "provider_state": unit["provider_state"],
        "recovery_action": unit["recovery_action"],
        "fence_token": unit["fence_token"],
        "result_commit_id": unit["result_commit_id"],
        "latest_event_sequence": unit["latest_event_sequence"],
        "provider_execution_evidence": factory._has_provider_execution_evidence(events),
        "visible_in_recovery_scan": task_id in scan,
        "chain_errors": factory.verify_chain(task_id),
        "event_count": sandbox.event_count(task_id),
    }


def scenario_pre_provider_reservation_loss() -> dict[str, Any]:
    """Fault: the dispatch callback is lost before any provider worker runs.

    Only a reservation exists. The controller must not mistake it for a running
    provider, must not preempt a still-valid lease, and must schedule a retry
    once the frozen lease expires.
    """
    sandbox = build_sandbox("s1")
    factory = sandbox.factory
    observations: dict[str, Any] = {
        "scenario_id": "S1",
        "title": "pre-provider reservation loss",
        "fault_injected": "dispatch callback dropped after LEASED; no RUNNING event ever arrives",
        "sandbox_root": str(sandbox.root),
        "steps": [],
    }

    # A long lease reproduces the real capsule's 1800s reservation window.
    long_task = "s1-reservation-lease-valid"
    seed_task(sandbox, long_task, lease_seconds=1800)
    lease_reservation(sandbox, long_task, worker_id=f"{long_task}-producer")
    observations["classification_lease_valid"] = _classification(sandbox, long_task)
    observations["recover_while_lease_valid"] = _attempt(
        lambda: factory.recover_undispatched_task(
            long_task, reason="dispatch callback lost before provider admission"
        )
    )
    observations["events_after_rejected_recovery"] = sandbox.event_count(long_task)

    # A one-second lease reproduces the same fault past its expiry boundary.
    short_task = "s1-reservation-lease-expired"
    seed_task(sandbox, short_task, lease_seconds=1)
    lease_reservation(sandbox, short_task, worker_id=f"{short_task}-producer")
    observations["classification_before_expiry"] = _classification(sandbox, short_task)
    observations["lease_expiry_wait_seconds"] = wait_for_lease_expiry(sandbox, short_task)
    observations["classification_after_expiry_before_recovery"] = _classification(
        sandbox, short_task
    )
    observations["recover_after_lease_expiry"] = _attempt(
        lambda: factory.recover_undispatched_task(
            short_task, reason="dispatch callback lost before provider admission"
        )
    )
    observations["classification_after_recovery"] = _classification(sandbox, short_task)

    events_before_replay = sandbox.event_count(short_task)
    observations["duplicate_recovery_callback"] = _attempt(
        lambda: factory.recover_undispatched_task(
            short_task, reason="dispatch callback lost before provider admission"
        )
    )
    observations["duplicate_recovery_new_events"] = (
        sandbox.event_count(short_task) - events_before_replay
    )

    # Recovery must return the unit to execution under a higher fence token.
    observations["release_after_recovery"] = _attempt(
        lambda: lease_reservation(
            sandbox, short_task, worker_id=f"{short_task}-producer-2", fence_token=2
        )
    )
    observations["classification_after_release"] = _classification(sandbox, short_task)
    observations["stale_worker_after_transfer"] = _attempt(
        lambda: provider_starts_running(
            sandbox,
            short_task,
            worker_id=f"{short_task}-producer-2",
            provider_task_id="agent:stale-fence-probe",
            worker_agent_id="stale-fence-probe",
            fence_token=1,
        )
    )
    return observations


def scenario_running_provider_callback_loss() -> dict[str, Any]:
    """Fault: a genuinely running provider's return message is lost.

    Provider execution evidence exists, so the controller must keep provider
    state distinct from Obzio state and must never preempt the live worker as an
    undispatched reservation - even after the lease has expired.
    """
    sandbox = build_sandbox("s2")
    factory = sandbox.factory
    task_id = "s2-running-provider-callback-lost"
    observations: dict[str, Any] = {
        "scenario_id": "S2",
        "title": "running-provider callback loss",
        "fault_injected": "return message dropped after a real RUNNING event carrying provider_task_id and worker_agent_id",
        "sandbox_root": str(sandbox.root),
    }

    seed_task(sandbox, task_id, lease_seconds=1)
    worker = f"{task_id}-producer"
    lease_reservation(sandbox, task_id, worker_id=worker)
    provider_starts_running(
        sandbox,
        task_id,
        worker_id=worker,
        provider_task_id="agent:27e78ee2-5623-403b-9d96-01926cc4ca2f",
        worker_agent_id="27e78ee2-5623-403b-9d96-01926cc4ca2f",
    )
    observations["classification_callback_lost"] = _classification(sandbox, task_id)

    # The lease is expired, yet the worker is genuinely running. The guard must
    # key on provider execution evidence rather than on elapsed lease time.
    observations["lease_expiry_wait_seconds"] = wait_for_lease_expiry(sandbox, task_id)
    observations["classification_after_lease_expiry"] = _classification(sandbox, task_id)
    observations["recover_as_undispatched_after_provider_ran"] = _attempt(
        lambda: factory.recover_undispatched_task(
            task_id, reason="return message lost from a running provider"
        )
    )
    observations["events_after_rejected_recovery"] = sandbox.event_count(task_id)

    # Provider transport now reports completion with nothing committed.
    observations["provider_completed_uncommitted"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="PROVIDER_COMPLETED_UNCOMMITTED",
            actor="integration-controller",
            fence_token=1,
            details={
                "provider_observation": "COMPLETED",
                "durable_result_commit": None,
                "reason": "provider reported completion but no verified result commit exists",
            },
        )
    )
    observations["classification_provider_completed_uncommitted"] = _classification(
        sandbox, task_id
    )
    observations["false_completion_from_uncommitted"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="COMPLETED",
            actor="integration-controller",
            fence_token=1,
            details={"result_commit_id": FORGED_COMMIT},
        )
    )
    observations["reconcile_to_recovery_required"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="RECOVERY_REQUIRED",
            actor="integration-controller",
            fence_token=1,
            details={"provider_dispatched": True, "reason": "uncommitted provider completion"},
        )
    )
    observations["classification_recovery_required"] = _classification(sandbox, task_id)
    observations["retry_scheduled"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="RETRY_SCHEDULED",
            actor="integration-controller",
            fence_token=1,
            details={"provider_dispatched": True, "reason": "replay from immutable input"},
        )
    )
    observations["release_at_higher_fence"] = _attempt(
        lambda: lease_reservation(sandbox, task_id, worker_id=f"{worker}-2", fence_token=2)
    )
    observations["classification_after_ownership_transfer"] = _classification(sandbox, task_id)
    observations["stale_worker_commit_after_transfer"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="RESULT_STAGING",
            actor=worker,
            fence_token=1,
            details={"note": "lost original worker attempts to commit after ownership transfer"},
        )
    )
    observations["non_owner_at_current_fence"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="RESULT_STAGING",
            actor=worker,
            fence_token=2,
            details={"note": "lost original worker attempts to commit at the current fence"},
        )
    )
    observations["classification_final"] = _classification(sandbox, task_id)
    return observations


def scenario_false_completion_ladder() -> dict[str, Any]:
    """Deliberately incorrect path: drive the unit toward a false completion.

    Every rung asserts that a provider observation, a forged commit identifier
    or an illegal shortcut cannot become Obzio completion.
    """
    sandbox = build_sandbox("s3")
    factory = sandbox.factory
    task_id = "s3-false-completion-ladder"
    observations: dict[str, Any] = {
        "scenario_id": "S3",
        "title": "false completion refutation ladder",
        "fault_injected": "illegal shortcuts and a forged result commit after a lost callback",
        "sandbox_root": str(sandbox.root),
    }

    seed_task(sandbox, task_id, lease_seconds=1800)
    worker = f"{task_id}-producer"
    lease_reservation(sandbox, task_id, worker_id=worker)
    provider_starts_running(
        sandbox,
        task_id,
        worker_id=worker,
        provider_task_id="agent:false-completion-probe",
        worker_agent_id="false-completion-probe",
    )

    observations["running_to_completed_shortcut"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="COMPLETED",
            actor="integration-controller",
            fence_token=1,
            details={"result_commit_id": FORGED_COMMIT},
        )
    )
    observations["running_to_parent_ingested_shortcut"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="PARENT_INGESTED",
            actor="integration-controller",
            fence_token=1,
            details={"parent_readback": "PASS", "result_commit_id": FORGED_COMMIT},
        )
    )
    observations["result_staged_without_hashes"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="RESULT_STAGING",
            actor=worker,
            fence_token=1,
            details={"note": "staging begins"},
        )
    )
    observations["result_staged_missing_manifest_hash"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="RESULT_STAGED",
            actor=worker,
            fence_token=1,
            details={"total_bytes": 128},
        )
    )
    observations["result_staged_with_hashes"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="RESULT_STAGED",
            actor=worker,
            fence_token=1,
            details={"manifest_sha256": "a" * 64, "total_bytes": 128},
        )
    )
    observations["result_verified_without_readback"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="RESULT_VERIFIED",
            actor=worker,
            fence_token=1,
            details={"verified_artifacts": 3, "parent_remote_readback": "FAIL"},
        )
    )
    observations["result_verified_with_readback"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="RESULT_VERIFIED",
            actor=worker,
            fence_token=1,
            details={"verified_artifacts": 3, "parent_remote_readback": "PASS"},
        )
    )
    observations["result_committed_with_forged_commit"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="RESULT_COMMITTED",
            actor="integration-controller",
            fence_token=1,
            details={"result_commit_id": FORGED_COMMIT},
        )
    )
    observations["classification_after_forged_commit"] = _classification(sandbox, task_id)
    observations["parent_ingested_on_forged_commit"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="PARENT_INGESTED",
            actor="integration-controller",
            fence_token=1,
            details={"parent_readback": "PASS", "result_commit_id": FORGED_COMMIT},
        )
    )
    observations["ingest_forged_commit_through_controller"] = _attempt(
        lambda: factory.ingest_committed_result(
            task_id,
            result_commit_id=FORGED_COMMIT,
            result_base_commit_id=sandbox.head_sha(),
            result_ref="HEAD",
            provider_run_id="agent:false-completion-probe",
        )
    )
    observations["producer_self_completion"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="COMPLETED",
            actor=worker,
            fence_token=1,
            details={"result_commit_id": FORGED_COMMIT},
        )
    )
    observations["classification_final"] = _classification(sandbox, task_id)
    observations["reached_completed"] = (
        observations["classification_final"]["obzio_state"] == "COMPLETED"
    )

    # Fairness check: a unit stranded on a forged result commit must still have a
    # route back to execution, otherwise fail-closed would mean fail-stuck.
    observations["strand_recovery_required"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="RECOVERY_REQUIRED",
            actor="integration-controller",
            fence_token=1,
            details={
                "provider_dispatched": True,
                "reason": "result commit id could not be verified against immutable Git bytes",
            },
        )
    )
    observations["strand_retry_scheduled"] = _attempt(
        lambda: factory.advance_task(
            task_id,
            state="RETRY_SCHEDULED",
            actor="integration-controller",
            fence_token=1,
            details={"provider_dispatched": True, "reason": "replay from immutable input"},
        )
    )
    observations["strand_released_at_higher_fence"] = _attempt(
        lambda: lease_reservation(sandbox, task_id, worker_id=f"{worker}-2", fence_token=2)
    )
    observations["classification_after_strand_recovery"] = _classification(sandbox, task_id)
    return observations


def scenario_duplicate_callback_replay() -> dict[str, Any]:
    """Fault: a lost callback is retried, so the same event arrives twice."""
    sandbox = build_sandbox("s4")
    factory = sandbox.factory
    task_id = "s4-duplicate-callback-replay"
    observations: dict[str, Any] = {
        "scenario_id": "S4",
        "title": "duplicate callback replay",
        "fault_injected": "identical and conflicting replays of an already-recorded event",
        "sandbox_root": str(sandbox.root),
    }

    seed_task(sandbox, task_id, lease_seconds=1800)
    worker = f"{task_id}-producer"
    lease_reservation(sandbox, task_id, worker_id=worker)
    running_path = provider_starts_running(
        sandbox,
        task_id,
        worker_id=worker,
        provider_task_id="agent:duplicate-callback-probe",
        worker_agent_id="duplicate-callback-probe",
    )
    original_bytes = running_path.read_bytes()
    events_before = sandbox.event_count(task_id)

    observations["identical_replay"] = _attempt(
        lambda: factory.write_once(running_path, original_bytes)
    )
    observations["identical_replay_new_events"] = sandbox.event_count(task_id) - events_before
    observations["identical_replay_bytes_unchanged"] = running_path.read_bytes() == original_bytes

    conflicting = original_bytes.replace(b"duplicate-callback-probe", b"conflicting-probe-xxxx")
    observations["conflicting_replay"] = _attempt(
        lambda: factory.write_once(running_path, conflicting)
    )
    observations["conflicting_replay_bytes_unchanged"] = (
        running_path.read_bytes() == original_bytes
    )

    # A replayed capsule creation must also be harmless.
    observations["capsule_replay"] = _attempt(
        lambda: seed_task(sandbox, task_id, lease_seconds=1800)
    )
    observations["classification_after_replays"] = _classification(sandbox, task_id)

    # A second RUNNING callback from the same worker appends a fresh sequence
    # rather than colliding, so a retried transport message is not lost.
    observations["repeated_running_callback"] = _attempt(
        lambda: provider_starts_running(
            sandbox,
            task_id,
            worker_id=worker,
            provider_task_id="agent:duplicate-callback-probe",
            worker_agent_id="duplicate-callback-probe",
        )
    )
    observations["classification_after_repeated_callback"] = _classification(sandbox, task_id)

    # The transition function documents idempotency-key replay tolerance. Check
    # whether the implementation actually consults an idempotency key.
    observations["idempotency_key_consulted_in_transition"] = _idempotency_key_consulted(sandbox)
    observations["result_commit_verified_at_transition"] = _result_commit_verified_at_transition(
        sandbox
    )
    return observations


def _idempotency_key_consulted(sandbox: Sandbox) -> bool:
    """Report whether the fenced transition function reads an idempotency key."""
    import ast

    path = sandbox.root / "workstreams" / "po03" / "tools" / "transactional_factory.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_advance_task_locked":
            return "idempotency_key" in ast.dump(node)
    raise AssertionError("_advance_task_locked not found in the pinned mechanism")


def _result_commit_verified_at_transition(sandbox: Sandbox) -> bool:
    """Report whether the RESULT_COMMITTED guard resolves the commit in Git."""
    import ast

    path = sandbox.root / "workstreams" / "po03" / "tools" / "transactional_factory.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_validate_transition_evidence":
            body = ast.dump(node)
            return "git" in body or "cat_file" in body or "_resolve_visible_commit" in body
    raise AssertionError("_validate_transition_evidence not found in the pinned mechanism")


def scenario_escalation_probe() -> dict[str, Any]:
    """Probe the escalation half of the hypothesis, which may be refuted.

    Classification can be correct while the controller still offers no automatic
    time-bounded route back to execution for a permanently lost callback from a
    genuinely running provider. This scenario measures that directly.
    """
    sandbox = build_sandbox("s5")
    factory = sandbox.factory
    task_id = "s5-escalation-probe"
    observations: dict[str, Any] = {
        "scenario_id": "S5",
        "title": "automatic escalation probe for a permanently lost callback",
        "fault_injected": "running-provider callback lost permanently; no operator action taken",
        "sandbox_root": str(sandbox.root),
    }

    seed_task(sandbox, task_id, lease_seconds=1)
    worker = f"{task_id}-producer"
    lease_reservation(sandbox, task_id, worker_id=worker)
    provider_starts_running(
        sandbox,
        task_id,
        worker_id=worker,
        provider_task_id="agent:escalation-probe",
        worker_agent_id="escalation-probe",
    )

    before = _classification(sandbox, task_id)
    observations["classification_before_lease_expiry"] = before
    observations["lease_expiry_wait_seconds"] = wait_for_lease_expiry(sandbox, task_id)
    after = _classification(sandbox, task_id)
    observations["classification_after_lease_expiry"] = after
    observations["classification_changed_on_lease_expiry"] = before != after

    # Every automatic entry point the mechanism exposes, exercised after expiry.
    observations["recovery_scan_after_expiry"] = [
        finding for finding in factory.recovery_scan() if finding["task_id"] == task_id
    ]
    projection = factory.rebuild_recovery_state(run_id="po03-wave-a-033-escalation-probe")
    observations["rebuilt_projection_unit"] = projection["units"][task_id]
    observations["projection_verification_errors"] = factory.verify_recovery_state()
    observations["recover_undispatched_available"] = _attempt(
        lambda: factory.recover_undispatched_task(task_id, reason="permanently lost callback")
    )

    # Does any exposed command escalate a dispatched, lease-expired unit?
    observations["exposed_subcommands"] = sorted(
        factory.build_parser()._subparsers._group_actions[0].choices.keys()
    )
    observations["heartbeat_written_nonnull_anywhere"] = _heartbeat_ever_set(sandbox)
    observations["lease_expiry_consulted_outside_undispatched_recovery"] = (
        _lease_expiry_scope(sandbox)
    )
    observations["events_after_all_automatic_routes"] = sandbox.event_count(task_id)
    observations["escalation_route_available"] = (
        observations["classification_changed_on_lease_expiry"]
        or observations["recover_undispatched_available"]["outcome"] == "ACCEPTED"
    )
    return observations


def _heartbeat_ever_set(sandbox: Sandbox) -> bool:
    """Report whether the mechanism ever records a non-null heartbeat."""
    source = (
        sandbox.root / "workstreams" / "po03" / "tools" / "transactional_factory.py"
    ).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if "heartbeat_at" in stripped and "None" not in stripped:
            return True
    return False


def _lease_expiry_scope(sandbox: Sandbox) -> list[str]:
    """Name every function that consults the frozen lease duration."""
    import ast

    path = sandbox.root / "workstreams" / "po03" / "tools" / "transactional_factory.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = ast.dump(node)
            if "lease_seconds" in body or "lease_deadline" in body:
                names.append(node.name)
    return sorted(set(names))


SCENARIOS: tuple[Callable[[], dict[str, Any]], ...] = (
    scenario_pre_provider_reservation_loss,
    scenario_running_provider_callback_loss,
    scenario_false_completion_ladder,
    scenario_duplicate_callback_replay,
    scenario_escalation_probe,
)
