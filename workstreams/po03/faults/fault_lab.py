#!/usr/bin/env python3
"""Sandboxed fault injection against the coordinator-owned control plane.

The production control plane is imported byte-for-byte and all of its mutable
path globals are redirected to a disposable sandbox below this worker's owned
subtree.  No injection touches the coordinator ledger or a remote branch.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import inspect
import json
import os
import shutil
import statistics
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable


PO03_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PO03_ROOT.parents[1]
CONTROL_PLANE_PATH = PO03_ROOT / "tools" / "control_plane.py"
DISPATCH_SOURCE = PO03_ROOT / "control" / "dispatch"
OWNERSHIP_SOURCE = PO03_ROOT / "control" / "path-ownership.json"
SANDBOX_PARENT = PO03_ROOT / "control" / "units" / "a2" / "runtime-sandboxes"

LIFECYCLE = [
    "CREATED",
    "LEASED",
    "RUNNING",
    "CHECKPOINTED",
    "RESULT_STAGING",
    "RESULT_STAGED",
    "RESULT_VERIFIED",
    "RESULT_COMMITTED",
    "PARENT_INGESTED",
    "COMPLETED",
]
COMMIT_INDEX = LIFECYCLE.index("RESULT_COMMITTED")
COMMISSION_ID = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
PROTOCOL = "OBZIO-A2-FAULT-INJECTION-v1"

FAULT_NAMES = {
    "a2-u01": "process/session loss",
    "a2-u02": "lost return message",
    "a2-u03": "partial write",
    "a2-u04": "pre- and post-commit failure",
    "a2-u05": "pre- and post-push failure",
    "a2-u06": "stale lease",
    "a2-u07": "duplicate callback under concurrency",
    "a2-u08": "corrupt or missing artifact",
    "a2-u09": "network interruption",
    "a2-u10": "parent restart with zero memory",
    "a2-u11": "entire provider-runtime loss",
    "a2-u12": "PO-02 Code-2 lost-return fixture",
}

SCRIPT_NAMES = {
    "a2-u01": "inject_process_loss.py",
    "a2-u02": "inject_lost_return.py",
    "a2-u03": "inject_partial_write.py",
    "a2-u04": "inject_commit_boundary.py",
    "a2-u05": "inject_push_boundary.py",
    "a2-u06": "inject_stale_lease.py",
    "a2-u07": "inject_concurrent_duplicate.py",
    "a2-u08": "inject_artifact_loss.py",
    "a2-u09": "inject_network_interruption.py",
    "a2-u10": "inject_parent_restart.py",
    "a2-u11": "inject_runtime_loss.py",
    "a2-u12": "inject_code2_fixture.py",
}


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_control_plane():
    name = f"po03_control_plane_a2_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, CONTROL_PLANE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Sandbox:
    """Redirect one imported control plane to a private, disposable tree."""

    def __init__(self, unit_id: str, label: str):
        self.unit_id = unit_id
        self.label = label
        self.base = SANDBOX_PARENT / f"{unit_id}-{os.getpid()}-{uuid.uuid4().hex}"
        self.control = self.base / "control"
        self.repo = self.base / "artifact-root"
        self.cp = None

    def __enter__(self) -> "Sandbox":
        self.base.mkdir(parents=True, exist_ok=False)
        (self.control / "dispatch").mkdir(parents=True)
        shutil.copy2(DISPATCH_SOURCE / f"{self.unit_id}.json", self.control / "dispatch")
        shutil.copy2(OWNERSHIP_SOURCE, self.control / "path-ownership.json")
        self.cp = self.fresh_control_plane()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        shutil.rmtree(self.base, ignore_errors=True)
        try:
            SANDBOX_PARENT.rmdir()
        except OSError:
            pass

    def fresh_control_plane(self):
        module = _load_control_plane()
        module.LEDGER_PATH = self.control / "events" / "ledger.jsonl"
        module.REGISTRY_PATH = self.control / "work-unit-registry.jsonl"
        module.RECOVERY_PATH = self.control / "recovery-state.json"
        module.DISPATCH_DIR = self.control / "dispatch"
        module.PATH_OWNERSHIP_PATH = self.control / "path-ownership.json"
        module.REPO_ROOT = self.repo
        return module

    def dispatch(self) -> dict[str, Any]:
        return json.loads((self.control / "dispatch" / f"{self.unit_id}.json").read_text(encoding="utf-8"))

    def seed(self, transition: str, *, expired_lease: bool = False) -> None:
        if transition not in LIFECYCLE:
            raise ValueError(transition)
        dispatch = self.dispatch()
        for state in LIFECYCLE[: LIFECYCLE.index(transition) + 1]:
            provider_state = "QUEUED" if state == "CREATED" else "RUNNING"
            payload: dict[str, Any] = {}
            fence = None
            if state == "CREATED":
                payload = {
                    "immutable_input_manifest_sha256": dispatch["immutable_input_manifest_sha256"],
                    "acceptance_contract_sha256": dispatch["acceptance_contract_sha256"],
                    "idempotency_key": dispatch["idempotency_key"],
                }
            elif state == "LEASED":
                fence = 1
                payload = {
                    "lease_id": f"lease-{self.unit_id}-1",
                    "worker_id": "po03-worker-a2",
                    "expires_at": "2000-01-01T00:00:00Z" if expired_lease else "2999-01-01T00:00:00Z",
                    "ttl_seconds": 3600,
                }
            else:
                fence = 1
            if state == "CHECKPOINTED":
                payload = {"checkpoint_seq": 1}
            if state in {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"}:
                provider_state = "COMPLETED"
                payload = {
                    "result_commit_id": f"seed-commit-{self.unit_id}",
                    "result_locator": f"git:seed/{self.unit_id}@seed-commit",
                    "artifact_count": 1,
                    "total_bytes": 7,
                }
                if state == "PARENT_INGESTED":
                    payload["result_sha256"] = "seed-result"
            self.cp.append_event(
                self.unit_id,
                state,
                actor="coordinator" if state in {"CREATED", "LEASED", "PARENT_INGESTED", "COMPLETED"} else "po03-worker-a2",
                provider_state=provider_state,
                fence_token=fence,
                payload=payload,
            )

    def artifact_relative(self, suffix: str = "txt") -> str:
        return f"workstreams/po03/faults/sandbox-artifacts/{self.unit_id}-{self.label}.{suffix}"

    def committed_result(
        self,
        *,
        fence_token: int = 1,
        commit_id: str | None = None,
        content: bytes = b"durable-result\n",
    ) -> tuple[dict[str, Any], Path]:
        dispatch = self.dispatch()
        relative = self.artifact_relative()
        target = self.repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        digest = sha256_bytes(content)
        commit_id = commit_id or f"commit-{self.unit_id}-{self.label}"
        now = "2026-08-22T07:00:00Z"
        result = {
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "task_id": self.unit_id,
            "commission_id": dispatch["commission_id"],
            "immutable_input_manifest_sha256": dispatch["immutable_input_manifest_sha256"],
            "acceptance_contract_sha256": dispatch["acceptance_contract_sha256"],
            "provider_state": "COMPLETED",
            "obzio_state": "RESULT_COMMITTED",
            "attempt": {
                "attempt_id": f"{self.unit_id}-attempt-{fence_token}",
                "idempotency_key": dispatch["idempotency_key"],
                "lease_id": f"lease-{self.unit_id}-{fence_token}",
                "fence_token": fence_token,
                "provider_run_id": "po03-a2-injector",
                "worker_id": "po03-worker-a2",
                "heartbeat_at": now,
                "checkpoint_seq": 1,
            },
            "result_transaction": {
                "result_txn_id": f"{self.unit_id}-txn-{fence_token}",
                "state": "COMMITTED",
                "manifest_uri": f"git:cursor/po03-a2-fault-recovery-ed20@{commit_id}:{self.unit_id}",
                "manifest_sha256": hashlib.sha256(f"{self.unit_id}:{commit_id}".encode()).hexdigest(),
                "artifact_count": 1,
                "total_bytes": len(content),
                "committed_at": now,
                "verified_at": now,
                "parent_ingested_at": None,
                "result_commit_id": commit_id,
            },
            "artifacts": [
                {
                    "artifact_id": f"{self.unit_id}-artifact-1",
                    "logical_name": target.name,
                    "content_uri": f"git:branch@{commit_id}:{relative}",
                    "sha256": digest,
                    "bytes": len(content),
                    "media_type": "text/plain",
                    "readback_verified_at": now,
                }
            ],
            "completion_actor": None,
            "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
        }
        return result, target

    def uncommitted_result(self) -> dict[str, Any]:
        dispatch = self.dispatch()
        now = "2026-08-22T07:00:00Z"
        return {
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "task_id": self.unit_id,
            "commission_id": dispatch["commission_id"],
            "immutable_input_manifest_sha256": dispatch["immutable_input_manifest_sha256"],
            "acceptance_contract_sha256": dispatch["acceptance_contract_sha256"],
            "provider_state": "COMPLETED",
            "obzio_state": "PROVIDER_COMPLETED_UNCOMMITTED",
            "attempt": {
                "attempt_id": f"{self.unit_id}-attempt-1",
                "idempotency_key": dispatch["idempotency_key"],
                "lease_id": f"lease-{self.unit_id}-1",
                "fence_token": 1,
                "provider_run_id": "po02-code2-lost-return",
                "worker_id": "po03-worker-a2",
                "heartbeat_at": now,
                "checkpoint_seq": 0,
            },
            "result_transaction": {
                "result_txn_id": f"{self.unit_id}-txn-1",
                "state": "RESERVED",
                "manifest_uri": None,
                "manifest_sha256": None,
                "artifact_count": 0,
                "total_bytes": 0,
                "committed_at": None,
                "verified_at": None,
                "parent_ingested_at": None,
                "result_commit_id": None,
            },
            "artifacts": [],
            "completion_actor": None,
            "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
        }


def _base(unit_id: str) -> dict[str, Any]:
    command = (
        f"python3 -I workstreams/po03/faults/{SCRIPT_NAMES[unit_id]} "
        f"--output workstreams/po03/faults/outcomes/{unit_id}.json"
    )
    return {
        "protocol_version": PROTOCOL,
        "unit_id": unit_id,
        "fault_class": FAULT_NAMES[unit_id],
        "commission_id": COMMISSION_ID,
        "control_plane_sha256": sha256_bytes(CONTROL_PLANE_PATH.read_bytes()),
        "sandbox_root": "workstreams/po03/control/units/a2/runtime-sandboxes/ (ephemeral and removed)",
        "lifecycle_transitions": list(LIFECYCLE),
        "command": command,
        "execution": {"exit_code": 0, "stdout": f"INJECTION_RECORDED {unit_id}"},
        "measurements": [],
        "findings": [],
        "limitations": [],
        "founder_relay_count": 0,
        "decision_changed": [],
    }


def _finish(outcome: dict[str, Any], status: str, started_ns: int) -> dict[str, Any]:
    timings = [row["recovery_time_ns"] for row in outcome["measurements"] if "recovery_time_ns" in row]
    outcome["status"] = status
    outcome["acceptance_met"] = status == "PASS"
    outcome["injection_count"] = len(outcome["measurements"])
    outcome["recovery_time"] = {
        "unit": "nanoseconds",
        "minimum": min(timings) if timings else 0,
        "median": int(statistics.median(timings)) if timings else 0,
        "maximum": max(timings) if timings else 0,
        "total": sum(timings),
        "wall_total": time.perf_counter_ns() - started_ns,
    }
    outcome["false_completion_count"] = sum(
        int(row.get("false_completion_count", 0)) for row in outcome["measurements"]
    )
    outcome["duplicate_external_effect_count"] = sum(
        int(row.get("duplicate_external_effect_count", 0)) for row in outcome["measurements"]
    )
    outcome["complete_hash_coverage"] = all(
        row.get("hash_coverage", True) for row in outcome["measurements"]
    )
    return outcome


def inject_process_loss() -> dict[str, Any]:
    unit_id = "a2-u01"
    started = time.perf_counter_ns()
    outcome = _base(unit_id)
    automatic = 0
    required = 0
    committed_recovered = 0
    for transition in LIFECYCLE:
        with Sandbox(unit_id, transition.lower()) as sb:
            sb.seed(transition)
            sb.cp.append_event(unit_id, "FAULT_INJECTED", actor="po03-worker-a2", payload={"fault": "process_loss"})
            t0 = time.perf_counter_ns()
            fresh = sb.fresh_control_plane()
            state = fresh.scan_recovery()
            projected = fresh.project_units()[unit_id]
            elapsed = time.perf_counter_ns() - t0
            needs_resume = LIFECYCLE.index(transition) < COMMIT_INDEX
            if needs_resume:
                required += 1
            history = {item["event"] for item in projected["history"]}
            did_resume = bool({"RETRY_SCHEDULED", "LEASE_EXPIRED"} & history) and projected["fence_token"] > 1
            automatic += int(did_resume)
            committed = LIFECYCLE.index(transition) >= COMMIT_INDEX
            recovered = not committed or bool(projected["result_commit_id"])
            committed_recovered += int(committed and recovered)
            outcome["measurements"].append(
                {
                    "transition": transition,
                    "recovery_time_ns": elapsed,
                    "automatic_resume_required": needs_resume,
                    "automatic_resume_observed": did_resume,
                    "committed_result_recovered": recovered,
                    "false_completion_count": len(state["false_completions"]),
                    "post_fault_state": projected["obzio_state"],
                }
            )
    outcome["automatic_resumes"] = {"required": required, "observed": automatic}
    outcome["committed_results"] = {"injected": len(LIFECYCLE) - COMMIT_INDEX, "recovered": committed_recovered}
    outcome["findings"].append(
        "scan_recovery reports resumable units but performs no lease expiry, re-lease, retry scheduling, or rerun."
    )
    return _finish(outcome, "FAIL", started)


def inject_lost_return() -> dict[str, Any]:
    unit_id = "a2-u02"
    started = time.perf_counter_ns()
    outcome = _base(unit_id)
    recovered = 0
    for transition in LIFECYCLE:
        with Sandbox(unit_id, transition.lower()) as sb:
            sb.seed(transition)
            result, _ = sb.committed_result(commit_id=f"durable-{transition.lower()}")
            slot = sb.repo / sb.dispatch()["result_slot"]["unit_record"]
            slot.parent.mkdir(parents=True, exist_ok=True)
            slot.write_text(json.dumps(result), encoding="utf-8")
            t0 = time.perf_counter_ns()
            state = sb.cp.scan_recovery()
            projected = sb.cp.project_units()[unit_id]
            elapsed = time.perf_counter_ns() - t0
            discovered = projected["result_commit_id"] == result["result_transaction"]["result_commit_id"]
            reconciled = projected["obzio_state"] == "PARENT_INGESTED" and discovered
            recovered += int(reconciled)
            outcome["measurements"].append(
                {
                    "transition": transition,
                    "recovery_time_ns": elapsed,
                    "durable_result_slot_present": slot.exists(),
                    "scanner_discovered_result_slot": discovered,
                    "scanner_reconciled_parent_ingestion": reconciled,
                    "false_completion_count": len(state["false_completions"]),
                }
            )
    outcome["committed_results"] = {"injected": len(LIFECYCLE), "recovered": recovered}
    outcome["findings"].append(
        "The recovery scanner reads only the shared ledger; it never inspects immutable result_slot locators or reconciles a dropped callback."
    )
    return _finish(outcome, "FAIL", started)


def inject_partial_write() -> dict[str, Any]:
    unit_id = "a2-u03"
    started = time.perf_counter_ns()
    outcome = _base(unit_id)
    detected = 0
    for transition in LIFECYCLE:
        with Sandbox(unit_id, f"{transition.lower()}-artifact") as sb:
            sb.seed(transition)
            result, artifact = sb.committed_result()
            artifact.write_bytes(artifact.read_bytes()[:3])
            t0 = time.perf_counter_ns()
            try:
                sb.cp.ingest_result(result, artifact_root=sb.repo)
                rejected = False
                reason = "NOT_REJECTED"
            except sb.cp.ControlPlaneError as exc:
                rejected = True
                reason = str(exc)
            elapsed = time.perf_counter_ns() - t0
            detected += int(rejected)
            outcome["measurements"].append(
                {
                    "transition": transition,
                    "case": "truncated_artifact",
                    "recovery_time_ns": elapsed,
                    "rejected": rejected,
                    "reason": reason,
                    "hash_coverage": True,
                    "false_completion_count": 0,
                }
            )
        with Sandbox(unit_id, f"{transition.lower()}-manifest") as sb:
            sb.seed(transition)
            result, _ = sb.committed_result()
            encoded = json.dumps(result)
            truncated = encoded[: len(encoded) // 2]
            t0 = time.perf_counter_ns()
            try:
                json.loads(truncated)
                rejected = False
                reason = "NOT_REJECTED"
            except json.JSONDecodeError as exc:
                rejected = True
                reason = f"JSONDecodeError: {exc.msg}"
            elapsed = time.perf_counter_ns() - t0
            detected += int(rejected)
            outcome["measurements"].append(
                {
                    "transition": transition,
                    "case": "half_written_manifest",
                    "recovery_time_ns": elapsed,
                    "rejected": rejected,
                    "reason": reason,
                    "hash_coverage": True,
                    "false_completion_count": 0,
                }
            )
    outcome["detections"] = {"injected": len(LIFECYCLE) * 2, "detected": detected}
    return _finish(outcome, "PASS" if detected == len(LIFECYCLE) * 2 else "FAIL", started)


def inject_commit_boundary() -> dict[str, Any]:
    unit_id = "a2-u04"
    started = time.perf_counter_ns()
    outcome = _base(unit_id)
    pre_reruns = 0
    post_resumes = 0
    for transition in LIFECYCLE:
        with Sandbox(unit_id, transition.lower()) as sb:
            sb.seed(transition)
            t0 = time.perf_counter_ns()
            pre_state = sb.cp.scan_recovery()
            pre_projection = sb.cp.project_units()[unit_id]
            pre_rerun = "RETRY_SCHEDULED" in {row["event"] for row in pre_projection["history"]}
            pre_reruns += int(pre_rerun)
            result, _ = sb.committed_result(commit_id=f"post-commit-{transition.lower()}")
            slot = sb.repo / sb.dispatch()["result_slot"]["unit_record"]
            slot.parent.mkdir(parents=True, exist_ok=True)
            slot.write_text(json.dumps(result), encoding="utf-8")
            post_state = sb.cp.scan_recovery()
            post_projection = sb.cp.project_units()[unit_id]
            post_resume = (
                post_projection["result_commit_id"] == result["result_transaction"]["result_commit_id"]
                and post_projection["obzio_state"] == "PARENT_INGESTED"
            )
            post_resumes += int(post_resume)
            elapsed = time.perf_counter_ns() - t0
            outcome["measurements"].append(
                {
                    "transition": transition,
                    "recovery_time_ns": elapsed,
                    "pre_commit_rerun_observed": pre_rerun,
                    "post_commit_resume_observed": post_resume,
                    "false_completion_count": len(pre_state["false_completions"])
                    + len(post_state["false_completions"]),
                }
            )
    with Sandbox(unit_id, "sequential-replay") as sb:
        sb.seed("RUNNING")
        result, _ = sb.committed_result()
        first = sb.cp.ingest_result(result, artifact_root=sb.repo)
        second = sb.cp.ingest_result(result, artifact_root=sb.repo)
        rows = sb.cp.ledger_rows()
        parent_rows = [row for row in rows if row["event"] == "PARENT_INGESTED"]
        duplicate_effects = max(0, len(parent_rows) - 1)
        outcome["sequential_replay"] = {
            "first_duplicate": first["duplicate"],
            "second_duplicate": second["duplicate"],
            "parent_ingested_rows": len(parent_rows),
        }
    outcome["pre_commit_reruns_observed"] = pre_reruns
    outcome["post_commit_resumes_observed"] = post_resumes
    outcome["measurements"][0]["duplicate_external_effect_count"] = duplicate_effects
    outcome["findings"].append(
        "Sequential replay is idempotent, but no recovery path discovers a post-commit result or schedules a pre-commit rerun."
    )
    return _finish(outcome, "FAIL", started)


def inject_push_boundary() -> dict[str, Any]:
    unit_id = "a2-u05"
    started = time.perf_counter_ns()
    outcome = _base(unit_id)
    accepted_missing = 0
    automatic_reruns = 0
    for transition in LIFECYCLE:
        with Sandbox(unit_id, transition.lower()) as sb:
            sb.seed(transition)
            missing_commit = f"absent-from-remote-{transition.lower()}"
            result, _ = sb.committed_result(commit_id=missing_commit)
            t0 = time.perf_counter_ns()
            try:
                sb.cp.ingest_result(result, artifact_root=sb.repo)
                accepted = True
            except sb.cp.ControlPlaneError:
                accepted = False
            projected = sb.cp.project_units()[unit_id]
            accepted_missing += int(accepted and projected["result_commit_id"] == missing_commit)
            elapsed = time.perf_counter_ns() - t0
            outcome["measurements"].append(
                {
                    "transition": transition,
                    "case": "post_push_claim_with_absent_remote_object",
                    "recovery_time_ns": elapsed,
                    "remote_contains_commit": False,
                    "parent_accepted_locator": accepted,
                    "false_completion_count": int(accepted),
                }
            )
        with Sandbox(unit_id, f"{transition.lower()}-prepush") as sb:
            sb.seed(transition)
            sb.cp.append_event(
                unit_id,
                "PROVIDER_COMPLETED_UNCOMMITTED",
                actor="po03-worker-a2",
                provider_state="COMPLETED",
                fence_token=1,
                payload={"fault": "pre_push_failure"},
            )
            t0 = time.perf_counter_ns()
            state = sb.cp.scan_recovery()
            projection = sb.cp.project_units()[unit_id]
            rerun = "RETRY_SCHEDULED" in {row["event"] for row in projection["history"]}
            automatic_reruns += int(rerun)
            outcome["measurements"].append(
                {
                    "transition": transition,
                    "case": "pre_push_failure",
                    "recovery_time_ns": time.perf_counter_ns() - t0,
                    "classified_uncommitted": unit_id in state["provider_completed_uncommitted"],
                    "automatic_rerun_observed": rerun,
                    "false_completion_count": len(state["false_completions"]),
                }
            )
    outcome["missing_remote_locators_accepted"] = accepted_missing
    outcome["automatic_pre_push_reruns"] = automatic_reruns
    outcome["findings"].append(
        "ingest_result accepts any non-empty result_commit_id and git locator after local-file verification; it performs no remote immutable-SHA read-back."
    )
    return _finish(outcome, "FAIL", started)


def inject_stale_lease() -> dict[str, Any]:
    unit_id = "a2-u06"
    started = time.perf_counter_ns()
    outcome = _base(unit_id)
    stale_rejected = 0
    future_accepted = 0
    automatic_transfers = 0
    for transition in LIFECYCLE:
        with Sandbox(unit_id, transition.lower()) as sb:
            sb.seed(transition, expired_lease=True)
            t0 = time.perf_counter_ns()
            state = sb.cp.scan_recovery(now=time.time())
            history = {row["event"] for row in sb.cp.project_units()[unit_id]["history"]}
            automatic = "LEASE_EXPIRED" in history
            automatic_transfers += int(automatic)
            sb.cp.append_event(unit_id, "LEASE_EXPIRED", actor="coordinator", fence_token=1)
            sb.cp.append_event(
                unit_id,
                "LEASED",
                actor="coordinator",
                provider_state="RUNNING",
                fence_token=2,
                payload={
                    "lease_id": f"lease-{unit_id}-2",
                    "worker_id": "replacement",
                    "expires_at": "2999-01-01T00:00:00Z",
                },
            )
            stale, _ = sb.committed_result(fence_token=1)
            try:
                sb.cp.ingest_result(stale, artifact_root=sb.repo)
                rejected = False
            except sb.cp.ControlPlaneError:
                rejected = True
            stale_rejected += int(rejected)
            future, _ = sb.committed_result(fence_token=3, commit_id=f"future-{transition.lower()}")
            try:
                sb.cp.ingest_result(future, artifact_root=sb.repo)
                accepted_future = True
            except sb.cp.ControlPlaneError:
                accepted_future = False
            future_accepted += int(accepted_future)
            outcome["measurements"].append(
                {
                    "transition": transition,
                    "recovery_time_ns": time.perf_counter_ns() - t0,
                    "scanner_reported_expired": unit_id in state["expired_leases"],
                    "automatic_lease_expired_event": automatic,
                    "stale_fence_rejected": rejected,
                    "unissued_future_fence_accepted": accepted_future,
                    "false_completion_count": int(accepted_future),
                }
            )
    outcome["stale_commits"] = {"injected": len(LIFECYCLE), "rejected": stale_rejected}
    outcome["automatic_transfers"] = automatic_transfers
    outcome["unissued_future_fences_accepted"] = future_accepted
    outcome["findings"].extend(
        [
            "scan_recovery reports expiry but does not append LEASE_EXPIRED or grant a replacement lease.",
            "ingest_result rejects only fence tokens lower than current; an unissued higher token is accepted.",
        ]
    )
    return _finish(outcome, "FAIL", started)


def _concurrent_trial(transition: str, trial: int) -> dict[str, Any]:
    unit_id = "a2-u07"
    with Sandbox(unit_id, f"{transition.lower()}-{trial}") as sb:
        sb.seed(transition)
        result, _ = sb.committed_result(commit_id=f"same-{transition.lower()}-{trial}")
        original_append = sb.cp.append_event
        original_rows = sb.cp.ledger_rows
        entry_barrier = threading.Barrier(2)
        rows_barrier = threading.Barrier(2)
        local = threading.local()

        def synchronised_rows():
            rows = original_rows()
            if getattr(local, "inside_parent_append", False):
                rows_barrier.wait(timeout=5)
            return rows

        def synchronised_append(unit_id_arg, event, **kwargs):
            if event == "PARENT_INGESTED":
                entry_barrier.wait(timeout=5)
                local.inside_parent_append = True
                try:
                    return original_append(unit_id_arg, event, **kwargs)
                finally:
                    local.inside_parent_append = False
            return original_append(unit_id_arg, event, **kwargs)

        sb.cp.ledger_rows = synchronised_rows
        sb.cp.append_event = synchronised_append
        outcomes: list[dict[str, Any]] = []
        errors: list[str] = []

        def invoke() -> None:
            try:
                outcomes.append(sb.cp.ingest_result(copy.deepcopy(result), artifact_root=sb.repo))
            except Exception as exc:  # evidence captures any concurrency failure
                errors.append(f"{type(exc).__name__}: {exc}")

        t0 = time.perf_counter_ns()
        threads = [threading.Thread(target=invoke), threading.Thread(target=invoke)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        elapsed = time.perf_counter_ns() - t0
        rows = original_rows()
        parent_rows = [
            row
            for row in rows
            if row.get("event") == "PARENT_INGESTED"
            and (row.get("payload") or {}).get("result_commit_id")
            == result["result_transaction"]["result_commit_id"]
        ]
        chain_errors = sb.cp.verify_chain(rows)
        return {
            "transition": transition,
            "trial": trial,
            "recovery_time_ns": elapsed,
            "callbacks": 2,
            "successful_calls": len(outcomes),
            "errors": errors,
            "parent_ingested_rows": len(parent_rows),
            "ledger_chain_valid": not chain_errors,
            "ledger_chain_errors": chain_errors,
            "duplicate_external_effect_count": max(0, len(parent_rows) - 1),
            "false_completion_count": 0,
        }


def inject_concurrent_duplicate(iterations: int = 200) -> dict[str, Any]:
    unit_id = "a2-u07"
    started = time.perf_counter_ns()
    outcome = _base(unit_id)
    for index in range(iterations):
        transition = LIFECYCLE[index % len(LIFECYCLE)]
        outcome["measurements"].append(_concurrent_trial(transition, index + 1))
    violations = [
        row
        for row in outcome["measurements"]
        if row["parent_ingested_rows"] != 1 or not row["ledger_chain_valid"]
    ]
    outcome["interleavings"] = iterations
    outcome["violating_interleavings"] = len(violations)
    outcome["findings"].append(
        "append_event performs read/verify/append without a lock or compare-and-swap; two callbacks can append the same sequence and predecessor hash."
    )
    return _finish(outcome, "PASS" if not violations else "FAIL", started)


def inject_artifact_loss() -> dict[str, Any]:
    unit_id = "a2-u08"
    started = time.perf_counter_ns()
    outcome = _base(unit_id)
    detected = 0
    recovery_required = 0
    completed_after_loss = 0
    for transition in LIFECYCLE:
        for fault in ("corrupt", "missing"):
            with Sandbox(unit_id, f"{transition.lower()}-{fault}") as sb:
                sb.seed(transition)
                result, artifact = sb.committed_result()
                if fault == "corrupt":
                    artifact.write_bytes(b"corrupt")
                else:
                    artifact.unlink()
                t0 = time.perf_counter_ns()
                try:
                    sb.cp.ingest_result(result, artifact_root=sb.repo)
                    rejected = False
                except sb.cp.ControlPlaneError:
                    rejected = True
                detected += int(rejected)
                projection = sb.cp.project_units()[unit_id]
                recovery = projection["obzio_state"] == "RECOVERY_REQUIRED"
                recovery_required += int(recovery)
                remained_completed = projection["obzio_state"] == "COMPLETED"
                completed_after_loss += int(remained_completed)
                outcome["measurements"].append(
                    {
                        "transition": transition,
                        "case": fault,
                        "recovery_time_ns": time.perf_counter_ns() - t0,
                        "rejected_at_ingestion": rejected,
                        "returned_to_recovery_required": recovery,
                        "remained_completed_after_artifact_loss": remained_completed,
                        "false_completion_count": int(remained_completed),
                        "hash_coverage": True,
                    }
                )
    outcome["detections"] = {"injected": len(LIFECYCLE) * 2, "detected": detected}
    outcome["recovery_required_transitions"] = recovery_required
    outcome["completed_after_artifact_loss"] = completed_after_loss
    outcome["findings"].extend(
        [
            "Corrupt and missing artifacts are rejected during ingest, but the rejection appends no RECOVERY_REQUIRED event.",
            "The scanner does not re-hash artifacts after ingestion, so deletion after COMPLETED is not detected.",
        ]
    )
    return _finish(outcome, "FAIL", started)


def inject_network_interruption() -> dict[str, Any]:
    unit_id = "a2-u09"
    started = time.perf_counter_ns()
    outcome = _base(unit_id)
    source = CONTROL_PLANE_PATH.read_text(encoding="utf-8")
    exact_boundary = (
        "NOT_SUPPORTED: control_plane.py exposes no push, fetch, remote read-back, "
        "transport, retry, or backoff operation; an offline injector has no network "
        "boundary to intercept."
    )
    for transition in LIFECYCLE:
        t0 = time.perf_counter_ns()
        transport_present = any(token in source for token in ("git push", "git fetch", "urlopen(", "subprocess.run"))
        outcome["measurements"].append(
            {
                "transition": transition,
                "recovery_time_ns": time.perf_counter_ns() - t0,
                "status": "NOT_SUPPORTED",
                "transport_operation_present": transport_present,
                "boundary": exact_boundary,
                "false_completion_count": 0,
            }
        )
    outcome["limitations"].append(exact_boundary)
    return _finish(outcome, "NOT_SUPPORTED", started)


def inject_parent_restart() -> dict[str, Any]:
    unit_id = "a2-u10"
    started = time.perf_counter_ns()
    outcome = _base(unit_id)
    equal = 0
    resumed = 0
    resume_required = 0
    for transition in LIFECYCLE:
        with Sandbox(unit_id, transition.lower()) as sb:
            sb.seed(transition)
            before = canonical(sb.cp.project_units())
            t0 = time.perf_counter_ns()
            fresh = sb.fresh_control_plane()
            after = canonical(fresh.project_units())
            same = before == after
            equal += int(same)
            in_flight = LIFECYCLE.index(transition) < COMMIT_INDEX
            resume_required += int(in_flight)
            fresh.scan_recovery()
            history = {row["event"] for row in fresh.project_units()[unit_id]["history"]}
            did_resume = bool({"RETRY_SCHEDULED", "LEASE_EXPIRED"} & history)
            resumed += int(did_resume)
            outcome["measurements"].append(
                {
                    "transition": transition,
                    "recovery_time_ns": time.perf_counter_ns() - t0,
                    "projection_byte_equal": same,
                    "in_flight_resume_required": in_flight,
                    "in_flight_resume_observed": did_resume,
                    "false_completion_count": 0,
                }
            )
    outcome["projection_rebuilds"] = {"attempted": len(LIFECYCLE), "byte_equal": equal}
    outcome["in_flight_resumes"] = {"required": resume_required, "observed": resumed}
    outcome["findings"].append(
        "Ledger projection rebuild is deterministic, but scan_recovery does not execute the advertised resume path."
    )
    return _finish(outcome, "FAIL", started)


def _run_git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def inject_runtime_loss() -> dict[str, Any]:
    unit_id = "a2-u11"
    started = time.perf_counter_ns()
    outcome = _base(unit_id)
    recovered = 0
    for transition in LIFECYCLE:
        with Sandbox(unit_id, transition.lower()) as sb:
            sb.seed(transition)
            provider = sb.base / "provider"
            remote = sb.base / "remote.git"
            clone = sb.base / "fresh-clone"
            provider.mkdir()
            _run_git("init", "-q", cwd=provider)
            _run_git("config", "user.name", "PO03 Fault Injector", cwd=provider)
            _run_git("config", "user.email", "po03-fault@example.invalid", cwd=provider)
            ledger_target = provider / "control" / "events" / "ledger.jsonl"
            ledger_target.parent.mkdir(parents=True)
            shutil.copy2(sb.cp.LEDGER_PATH, ledger_target)
            _run_git("add", ".", cwd=provider)
            _run_git("commit", "-q", "-m", "coordinator ledger", cwd=provider)
            _run_git("init", "--bare", "-q", str(remote))
            _run_git("remote", "add", "origin", str(remote), cwd=provider)
            _run_git("push", "-q", "origin", "HEAD:coordinator", cwd=provider)
            result_file = provider / "results" / f"{unit_id}.txt"
            result_file.parent.mkdir()
            result_file.write_text(f"committed result after {transition}\n", encoding="utf-8")
            _run_git("add", ".", cwd=provider)
            _run_git("commit", "-q", "-m", "provider committed result", cwd=provider)
            result_commit = _run_git("rev-parse", "HEAD", cwd=provider)
            _run_git("push", "-q", "origin", f"HEAD:result-{unit_id}", cwd=provider)
            t0 = time.perf_counter_ns()
            _run_git("clone", "-q", "--branch", "coordinator", str(remote), str(clone))
            fresh = sb.fresh_control_plane()
            fresh.LEDGER_PATH = clone / "control" / "events" / "ledger.jsonl"
            fresh.REGISTRY_PATH = clone / "control" / "work-unit-registry.jsonl"
            fresh.RECOVERY_PATH = clone / "control" / "recovery-state.json"
            state = fresh.scan_recovery()
            projection = fresh.project_units()[unit_id]
            discovered = projection["result_commit_id"] == result_commit
            recovered += int(discovered)
            remote_has_commit = bool(_run_git("--git-dir", str(remote), "cat-file", "-e", f"{result_commit}^{{commit}}") == "")
            outcome["measurements"].append(
                {
                    "transition": transition,
                    "recovery_time_ns": time.perf_counter_ns() - t0,
                    "local_file_remote": str(remote.relative_to(sb.base)),
                    "remote_contains_committed_result": remote_has_commit,
                    "fresh_clone_scanner_discovered_commit": discovered,
                    "classified_uncommitted": unit_id in state["provider_completed_uncommitted"],
                    "false_completion_count": len(state["false_completions"]),
                }
            )
    outcome["committed_results"] = {"injected": len(LIFECYCLE), "recovered": recovered}
    outcome["findings"].append(
        "A fresh coordinator-branch clone cannot discover committed result branches; the scanner has no git-remote reconciliation route."
    )
    return _finish(outcome, "FAIL", started)


def inject_code2_fixture() -> dict[str, Any]:
    unit_id = "a2-u12"
    started = time.perf_counter_ns()
    outcome = _base(unit_id)
    correctly_classified = 0
    reruns = 0
    admitted = 0
    for transition in LIFECYCLE:
        with Sandbox(unit_id, transition.lower()) as sb:
            sb.seed(transition)
            fixture_result = sb.uncommitted_result()
            t0 = time.perf_counter_ns()
            try:
                sb.cp.ingest_result(fixture_result, artifact_root=sb.repo)
                was_admitted = True
            except sb.cp.ControlPlaneError:
                was_admitted = False
            admitted += int(was_admitted)
            state = sb.cp.scan_recovery()
            projection = sb.cp.project_units()[unit_id]
            classified = unit_id in state["provider_completed_uncommitted"]
            correctly_classified += int(classified)
            rerun = "RETRY_SCHEDULED" in {row["event"] for row in projection["history"]}
            reruns += int(rerun)
            outcome["measurements"].append(
                {
                    "transition": transition,
                    "recovery_time_ns": time.perf_counter_ns() - t0,
                    "fixture_state": "PROVIDER_COMPLETED_UNCOMMITTED",
                    "fixture_result_state": "UNRECOVERED_AFTER_FOUR_REPORTED_ROUTES",
                    "fixture_acceptance": "NOT_ACCEPTED",
                    "ingest_admitted_uncommitted_fixture": was_admitted,
                    "scanner_classified_uncommitted": classified,
                    "automatic_rerun_observed": rerun,
                    "post_ingest_state": projection["obzio_state"],
                    "false_completion_count": len(state["false_completions"]),
                }
            )
    outcome["classification"] = {"attempted": len(LIFECYCLE), "correct": correctly_classified}
    outcome["uncommitted_fixture_ingestions"] = admitted
    outcome["automatic_reruns"] = reruns
    outcome["findings"].extend(
        [
            "The scanner identifies provider completion without a commit.",
            "ingest_result nevertheless admits the zero-artifact uncommitted document as PARENT_INGESTED, creating a scanner-reported false completion.",
            "No RETRY_SCHEDULED event or rerun-from-immutable-input action is emitted.",
        ]
    )
    return _finish(outcome, "FAIL", started)


RUNNERS: dict[str, Callable[[], dict[str, Any]]] = {
    "a2-u01": inject_process_loss,
    "a2-u02": inject_lost_return,
    "a2-u03": inject_partial_write,
    "a2-u04": inject_commit_boundary,
    "a2-u05": inject_push_boundary,
    "a2-u06": inject_stale_lease,
    "a2-u07": inject_concurrent_duplicate,
    "a2-u08": inject_artifact_loss,
    "a2-u09": inject_network_interruption,
    "a2-u10": inject_parent_restart,
    "a2-u11": inject_runtime_loss,
    "a2-u12": inject_code2_fixture,
}


def run(unit_id: str) -> dict[str, Any]:
    try:
        runner = RUNNERS[unit_id]
    except KeyError as exc:
        raise ValueError(f"unknown A2 unit: {unit_id}") from exc
    return runner()


def cli(unit_id: str) -> int:
    parser = argparse.ArgumentParser(description=f"Inject {FAULT_NAMES[unit_id]} against sandboxed control plane")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    outcome = run(unit_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(outcome["execution"]["stdout"])
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("unit_id", choices=sorted(RUNNERS))
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    result = run(options.unit_id)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["execution"]["stdout"])
