#!/usr/bin/env python3
"""Durable task custody for the PO-03 work-unit factory.

The controller writes immutable task capsules and a hash-chained event log
before a provider receives work. Provider completion is transport evidence,
not Obzio completion: only a fenced controller transition following immutable
result commit and independent read-back can reach ``COMPLETED``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PO03_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PO03_ROOT.parents[1]
CONTROL_ROOT = PO03_ROOT / "control"
RECEIPT_ROOT = REPO_ROOT / "receipts" / "po03" / "2026-08-22"
COMMISSION_ID = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
PROTOCOL_VERSION = "OBZIO-TRANSACTIONAL-RESULT-v1"
TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,95}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_OBJECT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

ALLOWED_WRITE_PREFIXES = (
    "workstreams/po03/",
    "receipts/po03/",
    ".github/workflows/po03-",
)
STATE_ORDER = (
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
)
TERMINAL_STATES = {"COMPLETED", "FAILED_TERMINAL", "CANCELLED"}
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"LEASED", "CANCELLED"},
    "LEASED": {"RUNNING", "RECOVERY_REQUIRED", "RETRY_SCHEDULED", "CANCELLED"},
    "RUNNING": {
        "CHECKPOINTED",
        "RESULT_STAGING",
        "PROVIDER_COMPLETED_UNCOMMITTED",
        "RECOVERY_REQUIRED",
        "FAILED_TERMINAL",
    },
    "CHECKPOINTED": {
        "RUNNING",
        "RESULT_STAGING",
        "PROVIDER_COMPLETED_UNCOMMITTED",
        "RECOVERY_REQUIRED",
        "FAILED_TERMINAL",
    },
    "RESULT_STAGING": {"RESULT_STAGED", "RECOVERY_REQUIRED", "FAILED_TERMINAL"},
    "RESULT_STAGED": {"RESULT_VERIFIED", "RECOVERY_REQUIRED", "FAILED_TERMINAL"},
    "RESULT_VERIFIED": {"RESULT_COMMITTED", "RECOVERY_REQUIRED", "FAILED_TERMINAL"},
    "RESULT_COMMITTED": {"PARENT_INGESTED", "RECOVERY_REQUIRED"},
    "PARENT_INGESTED": {"COMPLETED", "RECOVERY_REQUIRED"},
    "PROVIDER_COMPLETED_UNCOMMITTED": {"RECOVERY_REQUIRED", "RETRY_SCHEDULED"},
    "RECOVERY_REQUIRED": {"RETRY_SCHEDULED", "FAILED_TERMINAL", "CANCELLED"},
    "RETRY_SCHEDULED": {"LEASED", "CANCELLED"},
    "COMPLETED": set(),
    "FAILED_TERMINAL": set(),
    "CANCELLED": set(),
}
PRODUCER_STATES = {"RUNNING", "CHECKPOINTED", "RESULT_STAGING", "RESULT_STAGED", "RESULT_VERIFIED"}
CONTROLLER_STATES = {
    "LEASED",
    "PROVIDER_COMPLETED_UNCOMMITTED",
    "RECOVERY_REQUIRED",
    "RETRY_SCHEDULED",
    "RESULT_COMMITTED",
    "PARENT_INGESTED",
    "COMPLETED",
    "FAILED_TERMINAL",
    "CANCELLED",
}


class FactoryError(ValueError):
    """Raised when a custody or collision-boundary invariant is violated."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def allowed_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    return (
        normalized.startswith("workstreams/po03/")
        or normalized.startswith("receipts/po03/")
        or (normalized.startswith(".github/workflows/po03-") and normalized.endswith(".yml"))
    )


def assert_allowed_path(path: Path) -> None:
    relative = repo_relative(path)
    if not allowed_path(relative):
        raise FactoryError(f"write outside PO-03 allowlist: {relative}")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_once(path: Path, payload: bytes) -> None:
    """Atomically create an immutable file; the same bytes are idempotent."""
    assert_allowed_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"immutable file differs: {repo_relative(path)}")
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise FileExistsError(f"immutable file differs: {repo_relative(path)}")
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def replace_atomic(path: Path, payload: bytes) -> None:
    """Atomically replace a derived controller projection."""
    assert_allowed_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def append_jsonl(path: Path, document: dict[str, Any]) -> None:
    """Append one fsynced controller record without rewriting prior ledger rows."""
    assert_allowed_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(document)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def git(*arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def require_git_object_id(value: str, field: str) -> None:
    if not GIT_OBJECT_RE.fullmatch(value):
        raise FactoryError(f"{field} must be a full lowercase Git object ID")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FactoryError(f"{repo_relative(path)} must contain an object")
    return value


def _event_directory(task_id: str) -> Path:
    return CONTROL_ROOT / "events" / task_id


def _event_files(task_id: str) -> list[Path]:
    directory = _event_directory(task_id)
    return sorted(directory.glob("*.json")) if directory.exists() else []


def _event_payload(
    task_id: str,
    state: str,
    *,
    actor: str,
    details: dict[str, Any] | None,
    observed_at: str | None,
) -> tuple[Path, dict[str, Any]]:
    if state not in ALLOWED_TRANSITIONS:
        raise FactoryError(f"unsupported event state: {state}")
    prior_events = _event_files(task_id)
    sequence = len(prior_events) + 1
    previous_hash = sha256_file(prior_events[-1]) if prior_events else None
    body = {
        "event_version": "PO03-EVENT-v1",
        "task_id": task_id,
        "sequence": sequence,
        "state": state,
        "actor": actor,
        "observed_at": observed_at or utc_now(),
        "previous_event_sha256": previous_hash,
        "details": details or {},
    }
    body["event_sha256"] = sha256_bytes(canonical_json(body))
    destination = _event_directory(task_id) / f"{sequence:06d}-{state.lower()}.json"
    return destination, body


def hash_chain_event(
    task_id: str,
    state: str,
    *,
    actor: str,
    details: dict[str, Any] | None = None,
    observed_at: str | None = None,
) -> Path:
    """Append one immutable event. Use ``advance_task`` for fenced custody."""
    destination, body = _event_payload(
        task_id,
        state,
        actor=actor,
        details=details,
        observed_at=observed_at,
    )
    write_once(destination, canonical_json(body))
    return destination


def verify_chain(task_id: str) -> list[str]:
    errors: list[str] = []
    events = _event_files(task_id)
    previous_hash: str | None = None
    for expected_sequence, path in enumerate(events, start=1):
        try:
            event = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: unreadable event: {exc}")
            continue
        if event.get("sequence") != expected_sequence:
            errors.append(f"{repo_relative(path)}: non-monotonic sequence")
        if event.get("previous_event_sha256") != previous_hash:
            errors.append(f"{repo_relative(path)}: previous hash mismatch")
        claimed = event.pop("event_sha256", None)
        computed = sha256_bytes(canonical_json(event))
        if claimed != computed:
            errors.append(f"{repo_relative(path)}: event hash mismatch")
        previous_hash = sha256_file(path)
    if not events:
        errors.append(f"task {task_id}: no events")
    return errors


def task_events(task_id: str) -> list[dict[str, Any]]:
    errors = verify_chain(task_id)
    if errors:
        raise FactoryError("; ".join(errors))
    return [read_json(path) for path in _event_files(task_id)]


def task_capsule(
    *,
    task_id: str,
    head_sha: str,
    run_id: str,
    model: str,
    reasoning: str,
    hypothesis: str,
    prompt: str,
    owned_paths: list[str],
    result_slot: str,
    acceptance: dict[str, Any],
    lease_seconds: int,
    fence_token: int,
    nonce: str | None = None,
    function: str | None = None,
) -> dict[str, str]:
    """Freeze a task input, acceptance contract, and initial created state."""
    if not TASK_ID_RE.fullmatch(task_id):
        raise FactoryError(f"invalid task id: {task_id}")
    if not owned_paths or any(not allowed_path(path.replace("**", "").rstrip("/")) for path in owned_paths):
        raise FactoryError("owned paths must be non-empty PO-03 paths")
    if not allowed_path(result_slot):
        raise FactoryError("result slot is outside the PO-03 allowlist")
    if fence_token < 1 or lease_seconds < 1:
        raise FactoryError("lease and fence token must be positive")
    task_directory = CONTROL_ROOT / "tasks" / task_id
    acceptance_bytes = canonical_json(acceptance)
    acceptance_hash = sha256_bytes(acceptance_bytes)
    input_document = {
        "task_capsule_version": "PO03-TASK-CAPSULE-v1",
        "task_id": task_id,
        "commission_id": COMMISSION_ID,
        "controller_head_sha": head_sha,
        "controller_run_id": run_id,
        "function": function or ("transactional-route-canary" if nonce else "wave-a-work-unit"),
        "falsifiable_hypothesis": hypothesis,
        "task_prompt": prompt,
        "source_hashes": {
            "commission_sha256": sha256_file(PO03_ROOT / "COMMISSION.md"),
            "transaction_schema_sha256": sha256_file(PO03_ROOT / "contracts" / "transactional-result.schema.json"),
            "acceptance_contract_sha256": acceptance_hash,
        },
        "runtime": {
            "provider": "Cursor",
            "route": "Subagent isolated worktree/cloud agent",
            "exact_model": model,
            "reasoning_control": reasoning,
            "context_policy": "bounded task capsule plus immutable repository head",
            "tools": ["git", "python", "repository file tools"],
        },
        "ownership": {
            "owned_paths": owned_paths,
            "read_only_paths": ["** except owned_paths"],
            "result_slot": result_slot,
            "branch_requirement": f"po03/{task_id}",
        },
        "transaction": {
            "idempotency_key": f"{COMMISSION_ID}:{task_id}:attempt-1",
            "lease_id": f"lease-{task_id}-1",
            "lease_seconds": lease_seconds,
            "fence_token": fence_token,
            "attempt_number": 1,
            "provider_run_id": "PENDING_PROVIDER_ASSIGNMENT",
        },
        "canary_nonce": nonce,
        "created_at": utc_now(),
        "decision_changed": [],
    }
    input_bytes = canonical_json(input_document)
    input_hash = sha256_bytes(input_bytes)
    initial_result = {
        "protocol_version": PROTOCOL_VERSION,
        "task_id": task_id,
        "commission_id": COMMISSION_ID,
        "immutable_input_manifest_sha256": input_hash,
        "acceptance_contract_sha256": acceptance_hash,
        "provider_state": "QUEUED",
        "obzio_state": "CREATED",
        "attempt": {
            "attempt_id": f"{task_id}-attempt-1",
            "idempotency_key": input_document["transaction"]["idempotency_key"],
            "lease_id": input_document["transaction"]["lease_id"],
            "fence_token": fence_token,
            "provider_run_id": "PENDING_PROVIDER_ASSIGNMENT",
            "worker_id": "PENDING_WORKER_ASSIGNMENT",
            "heartbeat_at": None,
            "checkpoint_seq": 0,
        },
        "result_transaction": {
            "result_txn_id": f"result-{task_id}-1",
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
        "independent_acceptance": {
            "state": "NOT_TESTED",
            "reviewer_id": None,
            "receipt_uri": None,
        },
    }
    write_once(task_directory / "input.json", input_bytes)
    write_once(task_directory / "acceptance.json", acceptance_bytes)
    write_once(task_directory / "transaction-created.json", canonical_json(initial_result))
    event = hash_chain_event(
        task_id,
        "CREATED",
        actor="integration-controller",
        details={
            "input_sha256": input_hash,
            "acceptance_sha256": acceptance_hash,
            "result_slot": result_slot,
            "fence_token": fence_token,
        },
    )
    return {
        "task_id": task_id,
        "input_path": repo_relative(task_directory / "input.json"),
        "input_sha256": input_hash,
        "acceptance_path": repo_relative(task_directory / "acceptance.json"),
        "acceptance_sha256": acceptance_hash,
        "created_transaction_path": repo_relative(task_directory / "transaction-created.json"),
        "created_event_path": repo_relative(event),
        "created_event_sha256": sha256_file(event),
        "result_slot": result_slot,
    }


def _latest_fence(events: list[dict[str, Any]], fallback: int) -> int:
    for event in reversed(events):
        candidate = event.get("details", {}).get("fence_token")
        if isinstance(candidate, int):
            return candidate
    return fallback


def _lease_owner(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        if event["state"] == "LEASED":
            owner = event.get("details", {}).get("worker_id")
            return owner if isinstance(owner, str) and owner else None
    return None


def _provider_projection(state: str) -> str:
    if state == "CREATED":
        return "NOT_DISPATCHED"
    if state in {
        "RESULT_STAGING",
        "RESULT_STAGED",
        "RESULT_VERIFIED",
        "RESULT_COMMITTED",
        "PARENT_INGESTED",
        "COMPLETED",
        "PROVIDER_COMPLETED_UNCOMMITTED",
    }:
        return "COMPLETED"
    if state == "FAILED_TERMINAL":
        return "FAILED"
    if state == "CANCELLED":
        return "CANCELLED"
    return "RUNNING"


def _recovery_action(state: str) -> str:
    if state in {"PROVIDER_COMPLETED_UNCOMMITTED", "RECOVERY_REQUIRED", "RETRY_SCHEDULED"}:
        return "RERUN_OR_RECONCILE"
    if state == "PARENT_INGESTED":
        return "AWAIT_COORDINATOR_COMPLETION_AND_INDEPENDENT_REVIEW"
    if state in TERMINAL_STATES:
        return "NONE"
    return "MONITOR"


def _update_recovery_projection(
    task_id: str,
    *,
    state: str,
    fence_token: int,
    event_path: Path,
    details: dict[str, Any],
) -> None:
    path = CONTROL_ROOT / "recovery-state.json"
    if path.exists():
        projection = read_json(path)
    else:
        projection = {
            "recovery_version": "PO03-RECOVERY-STATE-v1",
            "scan_state": "ACTIVE",
            "units": {},
            "false_completion_count": 0,
            "orphan_count": 0,
            "duplicate_callback_count": 0,
            "collision_count": 0,
            "decision_changed": [],
        }
    units = projection.setdefault("units", {})
    units[task_id] = {
        "obzio_state": state,
        "provider_state": _provider_projection(state),
        "latest_event_sequence": len(_event_files(task_id)),
        "latest_event_sha256": sha256_file(event_path),
        "fence_token": fence_token,
        "result_commit_id": details.get("result_commit_id"),
        "recovery_action": _recovery_action(state),
    }
    replace_atomic(path, canonical_json(projection))


def advance_task(
    task_id: str,
    *,
    state: str,
    actor: str,
    fence_token: int,
    details: dict[str, Any] | None = None,
) -> Path:
    """Perform a fenced, monotonic custody transition and emit an event.

    Callers must use a provider-independent logical worker identifier.  A
    callback replay with an already-recorded idempotency key is harmless when
    it names the same target state and event payload.
    """
    if state not in ALLOWED_TRANSITIONS:
        raise FactoryError(f"unsupported state: {state}")
    if not isinstance(fence_token, int) or fence_token < 1:
        raise FactoryError("fence token must be a positive integer")
    events = task_events(task_id)
    prior = events[-1]
    prior_state = prior["state"]
    if prior_state in TERMINAL_STATES:
        raise FactoryError(f"terminal task cannot transition: {task_id} is {prior_state}")
    if state not in ALLOWED_TRANSITIONS[prior_state]:
        raise FactoryError(f"invalid transition: {prior_state} -> {state}")
    input_document = read_json(CONTROL_ROOT / "tasks" / task_id / "input.json")
    current_fence = _latest_fence(events, int(input_document["transaction"]["fence_token"]))
    if state == "LEASED":
        first_lease = prior_state == "CREATED"
        valid_fence = fence_token == current_fence if first_lease else fence_token > current_fence
        if actor != "integration-controller" or not valid_fence:
            raise FactoryError("lease requires controller and the current or a higher valid fence token")
        if not (details or {}).get("worker_id") or not (details or {}).get("provider_run_id"):
            raise FactoryError("lease must identify worker and provider run")
    else:
        if fence_token != current_fence:
            raise FactoryError(f"stale fence token {fence_token}; current is {current_fence}")
    owner = _lease_owner(events)
    if state in PRODUCER_STATES and actor != owner:
        controller_pre_dispatch = (
            state == "RUNNING"
            and actor == "integration-controller"
            and bool((details or {}).get("controller_pre_dispatch"))
        )
        if not controller_pre_dispatch:
            raise FactoryError("only the active leased worker may advance producer states")
    if state in CONTROLLER_STATES and actor != "integration-controller":
        raise FactoryError("only integration-controller may advance custody and recovery states")
    event_details = dict(details or {})
    event_details.setdefault("fence_token", fence_token)
    event_details.setdefault("prior_state", prior_state)
    event_path = hash_chain_event(task_id, state, actor=actor, details=event_details)
    append_jsonl(
        CONTROL_ROOT / "work-unit-registry.jsonl",
        {
            "registry_event_version": "PO03-REGISTRY-EVENT-v1",
            "task_id": task_id,
            "state": state,
            "event_path": repo_relative(event_path),
            "event_sha256": sha256_file(event_path),
            "fence_token": fence_token,
            "recorded_at": utc_now(),
        },
    )
    _update_recovery_projection(
        task_id,
        state=state,
        fence_token=fence_token,
        event_path=event_path,
        details=event_details,
    )
    return event_path


def recovery_scan() -> list[dict[str, Any]]:
    """Expose all nonterminal units without converting a callback to completion."""
    findings: list[dict[str, Any]] = []
    for task_directory in sorted((CONTROL_ROOT / "tasks").glob("*")):
        if not task_directory.is_dir():
            continue
        task_id = task_directory.name
        events = task_events(task_id)
        latest = events[-1]
        if latest["state"] not in TERMINAL_STATES:
            input_document = read_json(task_directory / "input.json")
            findings.append(
                {
                    "task_id": task_id,
                    "state": latest["state"],
                    "fence_token": _latest_fence(events, int(input_document["transaction"]["fence_token"])),
                    "last_event_sha256": sha256_file(_event_files(task_id)[-1]),
                }
            )
    return findings


def source_lock(head_sha: str) -> dict[str, Any]:
    paths = (
        "workstreams/po03/COMMISSION.md",
        "workstreams/po03/contracts/transactional-result.schema.json",
        "workstreams/po03/contracts/wave-compounding.schema.json",
        "workstreams/po03/tools/validate_contracts.py",
        "workstreams/po03/tests/test_validate_contracts.py",
        ".github/workflows/po03-contracts.yml",
    )
    return {
        "source_lock_version": "PO03-SOURCE-LOCK-v1",
        "repository": "github.com/asibrahim336-hash/obzio-ai-coordination-temp",
        "branch": "po03/repository-engineering-portable-runtime-20260822-v001",
        "head_sha": head_sha,
        "sources": [
            {
                "path": path,
                "git_blob_sha": git("rev-parse", f"{head_sha}:{path}"),
                "sha256": sha256_file(REPO_ROOT / path),
                "bytes": (REPO_ROOT / path).stat().st_size,
            }
            for path in paths
        ],
        "producer_narratives_read_for_acceptance": False,
        "decision_changed": [],
    }


def criteria_freeze(head_sha: str) -> dict[str, Any]:
    return {
        "criteria_version": "PO03-WAVE-A-CRITERIA-v1",
        "frozen_against_head": head_sha,
        "commission_id": COMMISSION_ID,
        "counted_unit": {
            "requires": [
                "distinct falsifiable hypothesis or executable acceptance decision",
                "durable artifact manifest with hashes and byte counts",
                "tests or reproduction evidence",
                "provider and Obzio state separated",
                "immutable result commit read back by a different process",
                "independent disposition by a non-producer",
            ],
            "excludes": [
                "renamed clone",
                "inventory",
                "plan",
                "idle session",
                "duplicated summary",
                "provider completion without a durable commit",
            ],
        },
        "wave_a_minimum_attempts": 64,
        "research_minimums": {
            "current_method_hypotheses": 12,
            "obzio_reproductions": 6,
            "tested_changes_or_rejections": 2,
        },
        "hard_guardrails": {
            "out_of_allowlist_writes": 0,
            "po01_contacts_or_mutations": 0,
            "protected_acts": 0,
            "false_completion": 0,
            "critical_correctness_assertions": "100_PERCENT",
        },
        "decision_changed": [],
    }


def model_register(run_id: str, parent_model: str) -> dict[str, Any]:
    return {
        "register_version": "PO03-MODEL-CAPABILITY-v1",
        "observed_at": utc_now(),
        "cursor_run_id": run_id,
        "parent_model_exact": parent_model,
        "parent_reasoning_control": "provider-exposed",
        "exposure_evidence": [
            {
                "family": "gpt-5.6-sol",
                "exact_configuration": parent_model,
                "state": "OBSERVED_CURRENT_RUN",
                "source": "cursor-cloud/run-info",
            },
            {
                "family": "gpt-5.6-sol",
                "exact_configuration": "gpt-5.6-sol-xhigh-fast",
                "state": "SUBAGENT_TOOL_EXPOSED",
                "source": "Subagent model enumeration",
            },
            {
                "family": "claude-opus-5",
                "exact_configuration": "claude-opus-5-thinking-high-fast",
                "state": "SUBAGENT_TOOL_EXPOSED",
                "source": "Subagent model enumeration",
            },
            {
                "family": "gemini-3.1-pro",
                "exact_configuration": None,
                "state": "NOT_SUPPORTED",
                "source": "absent from current Subagent model enumeration",
            },
            {
                "family": "composer-2.5",
                "exact_configuration": None,
                "state": "NOT_SUPPORTED",
                "source": "absent from current Subagent model enumeration",
            },
        ],
        "allocation_policy": {
            "lead": parent_model,
            "independent_frontiers": [
                "gpt-5.6-sol-xhigh-fast",
                "claude-opus-5-thinking-high-fast",
            ],
            "fallback": "record NOT_SUPPORTED; never manufacture diversity",
            "auto_model_selection": False,
        },
        "limitations": [
            "Tool enumeration establishes selectable configurations, not successful execution.",
            "Per-attempt provider admission and returned model identity must be recorded separately.",
        ],
        "decision_changed": [],
    }


def activate(args: argparse.Namespace) -> int:
    """Activate one pre-dispatch canary route; material work remains prohibited."""
    actual_head = git("rev-parse", "HEAD")
    if actual_head != args.head_sha:
        raise FactoryError(f"head changed: expected {args.head_sha}, observed {actual_head}")
    require_git_object_id(args.head_sha, "head_sha")
    source_path = PO03_ROOT / "evidence" / "source-lock.json"
    criteria_path = PO03_ROOT / "evidence" / "criteria-freeze.json"
    model_path = CONTROL_ROOT / "model-capability-register.json"
    write_once(source_path, canonical_json(source_lock(args.head_sha)))
    write_once(criteria_path, canonical_json(criteria_freeze(args.head_sha)))
    write_once(model_path, canonical_json(model_register(args.run_id, args.parent_model)))

    nonce = sha256_bytes(f"{args.head_sha}:{args.run_id}:po03-canary-001".encode("utf-8"))
    acceptance = {
        "acceptance_version": "PO03-CANARY-ACCEPTANCE-v1",
        "criteria": [
            "write canary.json only inside the owned result slot",
            "canary.json contains the exact nonce and its SHA-256",
            "worker reads bytes back and records matching hash and byte count",
            "worker commits the artifact and pushes an isolated remote branch",
            "worker returns READY_TO_COMMIT, branch, and immutable commit SHA",
            "worker does not set Obzio COMPLETED or self-accept",
        ],
        "forbidden": [
            "writes outside owned_paths",
            "PO-01 contact or mutation",
            "PR #8 mutation",
            "merge or promotion",
        ],
        "decision_changed": [],
    }
    canary = task_capsule(
        task_id="po03-canary-001",
        head_sha=args.head_sha,
        run_id=args.run_id,
        model=args.canary_model,
        reasoning=args.canary_reasoning,
        hypothesis="The selected subordinate route can durably write, commit, push, and independently read back an exact canary without path collision.",
        prompt="Execute the immutable canary contract. Write only the owned result slot; commit and push exact bytes; read them back; return READY_TO_COMMIT with branch and SHA.",
        owned_paths=["workstreams/po03/attempts/canary/po03-canary-001/**"],
        result_slot="workstreams/po03/attempts/canary/po03-canary-001",
        acceptance=acceptance,
        lease_seconds=1800,
        fence_token=1,
        nonce=nonce,
    )
    write_once(CONTROL_ROOT / "work-unit-registry.jsonl", canonical_json(canary))
    write_once(PO03_ROOT / "metrics" / "work-unit-runs.jsonl", b"")
    replace_atomic(
        CONTROL_ROOT / "path-ownership.json",
        canonical_json(
            {
                "ownership_version": "PO03-PATH-OWNERSHIP-v1",
                "controller": {"run_id": args.run_id, "owned_paths": ["workstreams/po03/control/**"]},
                "subordinates": [
                    {
                        "task_id": canary["task_id"],
                        "provider_run_id": "PENDING_PROVIDER_ASSIGNMENT",
                        "owned_paths": ["workstreams/po03/attempts/canary/po03-canary-001/**"],
                        "fence_token": 1,
                    }
                ],
                "collision_policy": "FAIL_CLOSED",
                "decision_changed": [],
            }
        ),
    )
    replace_atomic(
        CONTROL_ROOT / "recovery-state.json",
        canonical_json(
            {
                "recovery_version": "PO03-RECOVERY-STATE-v1",
                "controller_run_id": args.run_id,
                "controller_head_sha": args.head_sha,
                "scan_state": "ACTIVE",
                "units": {
                    canary["task_id"]: {
                        "obzio_state": "CREATED",
                        "provider_state": "NOT_DISPATCHED",
                        "latest_event_sequence": 1,
                        "fence_token": 1,
                        "result_commit_id": None,
                        "recovery_action": "DISPATCH_CANARY",
                    }
                },
                "false_completion_count": 0,
                "orphan_count": 0,
                "duplicate_callback_count": 0,
                "collision_count": 0,
                "decision_changed": [],
            }
        ),
    )
    activation = {
        "receipt_id": "RCP-PO03-AMENDMENT-ACTIVATION-20260822-v001",
        "commission_id": COMMISSION_ID,
        "commission_continuation": True,
        "strategy_restarted": False,
        "decision_changed": [],
        "repository": "github.com/asibrahim336-hash/obzio-ai-coordination-temp",
        "branch": git("branch", "--show-current"),
        "activation_head_sha": args.head_sha,
        "cursor_run_id": args.run_id,
        "parent_model_exact": args.parent_model,
        "source_lock": {"path": repo_relative(source_path), "sha256": sha256_file(source_path)},
        "criteria_freeze": {"path": repo_relative(criteria_path), "sha256": sha256_file(criteria_path)},
        "model_register": {"path": repo_relative(model_path), "sha256": sha256_file(model_path)},
        "canary_task": canary,
        "transactional_dispatch_state": "CANARY_CREATED_NOT_DISPATCHED",
        "material_subordinate_dispatch_authorized": False,
        "po01_non_interference": True,
        "pr8_untouched": True,
        "created_at": utc_now(),
    }
    write_once(RECEIPT_ROOT / "amendment-activation.json", canonical_json(activation))
    print(json.dumps(activation, indent=2, sort_keys=True))
    return 0


def verify(args: argparse.Namespace) -> int:
    task_directory = CONTROL_ROOT / "tasks" / args.task_id
    errors: list[str] = []
    for name in ("input.json", "acceptance.json", "transaction-created.json"):
        if not (task_directory / name).is_file():
            errors.append(f"missing {repo_relative(task_directory / name)}")
    if not errors:
        transaction = read_json(task_directory / "transaction-created.json")
        if sha256_file(task_directory / "input.json") != transaction.get("immutable_input_manifest_sha256"):
            errors.append("immutable input hash mismatch")
        if sha256_file(task_directory / "acceptance.json") != transaction.get("acceptance_contract_sha256"):
            errors.append("acceptance contract hash mismatch")
    errors.extend(verify_chain(args.task_id))
    if errors:
        for error in errors:
            print(f"INVALID: {error}")
        return 1
    print(f"VALID task={args.task_id}")
    return 0


def _json_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("must be a JSON object")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    activate_parser = subparsers.add_parser("activate")
    activate_parser.add_argument("--head-sha", required=True)
    activate_parser.add_argument("--run-id", required=True)
    activate_parser.add_argument("--parent-model", required=True)
    activate_parser.add_argument("--canary-model", required=True)
    activate_parser.add_argument("--canary-reasoning", required=True)
    activate_parser.set_defaults(handler=activate)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("task_id")
    verify_parser.set_defaults(handler=verify)
    advance_parser = subparsers.add_parser("advance")
    advance_parser.add_argument("task_id")
    advance_parser.add_argument("--state", required=True)
    advance_parser.add_argument("--actor", required=True)
    advance_parser.add_argument("--fence-token", required=True, type=int)
    advance_parser.add_argument("--details", default={}, type=_json_object)
    advance_parser.set_defaults(
        handler=lambda args: (print(advance_task(args.task_id, state=args.state, actor=args.actor, fence_token=args.fence_token, details=args.details)) or 0)
    )
    scan_parser = subparsers.add_parser("scan-recovery")
    scan_parser.set_defaults(handler=lambda args: (print(json.dumps(recovery_scan(), sort_keys=True)) or 0))
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return args.handler(args)
    except (OSError, ValueError, FileExistsError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
