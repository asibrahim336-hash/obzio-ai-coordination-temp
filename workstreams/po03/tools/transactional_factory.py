#!/usr/bin/env python3
"""Durable task custody for the PO-03 work-unit factory.

The controller writes immutable task capsules and a hash-chained event log
before a provider receives work. Provider completion is transport evidence,
not Obzio completion: only a fenced controller transition following immutable
result commit and independent read-back can reach ``COMPLETED``.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Cursor and GitHub Actions use POSIX locks.
    fcntl = None


PO03_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PO03_ROOT.parents[1]
CONTROL_ROOT = PO03_ROOT / "control"
RECEIPT_ROOT = REPO_ROOT / "receipts" / "po03" / "2026-08-22"
COMMISSION_ID = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
PROTOCOL_VERSION = "OBZIO-TRANSACTIONAL-RESULT-v1"
TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,95}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_OBJECT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
EVENT_FILE_RE = re.compile(r"^(?P<sequence>[0-9]{6})-(?P<state>[a-z_]+)\.json$")

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


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


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


@contextlib.contextmanager
def _task_lock(task_id: str) -> Iterator[None]:
    """Serialize one task's capsule and state transitions without a lock file."""
    if not TASK_ID_RE.fullmatch(task_id):
        raise FactoryError(f"invalid task id: {task_id}")
    task_directory = CONTROL_ROOT / "tasks" / task_id
    assert_allowed_path(task_directory)
    task_directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(task_directory, os.O_RDONLY)
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


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
        _fsync_directory(path.parent)
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


def git_bytes(*arguments: str) -> bytes:
    result = subprocess.run(
        ("git", *arguments),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout


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
    previous_state: str | None = None
    lease_owner: str | None = None
    current_fence: int | None = None
    for expected_sequence, path in enumerate(events, start=1):
        try:
            event = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: unreadable event: {exc}")
            continue
        match = EVENT_FILE_RE.fullmatch(path.name)
        if match is None:
            errors.append(f"{repo_relative(path)}: non-canonical event filename")
        elif int(match["sequence"]) != expected_sequence:
            errors.append(f"{repo_relative(path)}: filename sequence mismatch")
        if event.get("event_version") != "PO03-EVENT-v1":
            errors.append(f"{repo_relative(path)}: unsupported event version")
        if event.get("task_id") != task_id:
            errors.append(f"{repo_relative(path)}: task ID mismatch")
        state = event.get("state")
        if not isinstance(state, str) or state not in ALLOWED_TRANSITIONS:
            errors.append(f"{repo_relative(path)}: unsupported state")
        elif match is not None and match["state"] != state.lower():
            errors.append(f"{repo_relative(path)}: filename state mismatch")
        if event.get("sequence") != expected_sequence:
            errors.append(f"{repo_relative(path)}: non-monotonic sequence")
        if event.get("previous_event_sha256") != previous_hash:
            errors.append(f"{repo_relative(path)}: previous hash mismatch")
        claimed = event.pop("event_sha256", None)
        computed = sha256_bytes(canonical_json(event))
        if claimed != computed:
            errors.append(f"{repo_relative(path)}: event hash mismatch")

        actor = event.get("actor")
        details = event.get("details")
        if not _nonempty(actor):
            errors.append(f"{repo_relative(path)}: actor must be non-empty")
        if not isinstance(details, dict):
            errors.append(f"{repo_relative(path)}: details must be an object")
            details = {}
        fence_token = details.get("fence_token")
        if not isinstance(fence_token, int) or fence_token < 1:
            errors.append(f"{repo_relative(path)}: invalid fence token")

        if previous_state is None:
            if state != "CREATED":
                errors.append(f"{repo_relative(path)}: first event must be CREATED")
            if actor != "integration-controller":
                errors.append(f"{repo_relative(path)}: only controller may create a task")
            if isinstance(fence_token, int) and fence_token >= 1:
                current_fence = fence_token
        else:
            if isinstance(state, str) and state in ALLOWED_TRANSITIONS and state not in ALLOWED_TRANSITIONS.get(previous_state, set()):
                errors.append(f"{repo_relative(path)}: invalid transition {previous_state} -> {state}")
            if details.get("prior_state") != previous_state:
                errors.append(f"{repo_relative(path)}: prior-state evidence mismatch")
            if state == "LEASED":
                first_lease = previous_state == "CREATED"
                valid_fence = (
                    isinstance(fence_token, int)
                    and current_fence is not None
                    and (fence_token == current_fence if first_lease else fence_token > current_fence)
                )
                if not valid_fence:
                    errors.append(f"{repo_relative(path)}: invalid lease fence")
                if actor != "integration-controller":
                    errors.append(f"{repo_relative(path)}: only controller may lease a task")
                if not _nonempty(details.get("worker_id")) or not _nonempty(details.get("provider_run_id")):
                    errors.append(f"{repo_relative(path)}: lease lacks worker or provider run")
                lease_owner = details.get("worker_id") if _nonempty(details.get("worker_id")) else None
                if isinstance(fence_token, int) and fence_token >= 1:
                    current_fence = fence_token
            elif current_fence is not None and fence_token != current_fence:
                errors.append(f"{repo_relative(path)}: stale or missing fence token")

        if isinstance(state, str) and state in PRODUCER_STATES:
            controller_pre_dispatch = (
                state == "RUNNING"
                and actor == "integration-controller"
                and details.get("controller_pre_dispatch") is True
                and _nonempty(details.get("provider_run_id"))
            )
            if actor != lease_owner and not controller_pre_dispatch:
                errors.append(f"{repo_relative(path)}: producer state has no active leased worker")
        if isinstance(state, str) and state in CONTROLLER_STATES and actor != "integration-controller":
            errors.append(f"{repo_relative(path)}: controller state has non-controller actor")

        previous_hash = sha256_file(path)
        previous_state = state if isinstance(state, str) else previous_state
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
    """Create or safely replay one immutable task capsule."""
    with _task_lock(task_id):
        return _task_capsule_locked(
            task_id=task_id,
            head_sha=head_sha,
            run_id=run_id,
            model=model,
            reasoning=reasoning,
            hypothesis=hypothesis,
            prompt=prompt,
            owned_paths=owned_paths,
            result_slot=result_slot,
            acceptance=acceptance,
            lease_seconds=lease_seconds,
            fence_token=fence_token,
            nonce=nonce,
            function=function,
        )


def _task_capsule_locked(
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
    input_path = task_directory / "input.json"
    existing_input = read_json(input_path) if input_path.exists() else None
    if existing_input is not None and not _nonempty(existing_input.get("created_at")):
        raise FactoryError(f"existing task capsule is missing created_at: {repo_relative(input_path)}")
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
        "created_at": existing_input["created_at"] if existing_input is not None else utc_now(),
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
    write_once(input_path, input_bytes)
    write_once(task_directory / "acceptance.json", acceptance_bytes)
    write_once(task_directory / "transaction-created.json", canonical_json(initial_result))
    events = _event_files(task_id)
    if events:
        errors = verify_chain(task_id)
        if errors:
            raise FactoryError("; ".join(errors))
        created = read_json(events[0])
        if created.get("state") != "CREATED":
            raise FactoryError(f"task capsule has no CREATED event: {task_id}")
        event = events[0]
    else:
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


def provider_state_from_events(events: list[dict[str, Any]]) -> str:
    """Preserve completed provider evidence when custody later needs recovery."""
    latest = events[-1] if events else {}
    latest_details = latest.get("details") if isinstance(latest, dict) else None
    if (
        latest.get("state") in {"RECOVERY_REQUIRED", "RETRY_SCHEDULED"}
        and isinstance(latest_details, dict)
        and latest_details.get("provider_dispatched") is False
    ):
        return "NOT_DISPATCHED"
    states = {event["state"] for event in events}
    if states & {
        "RESULT_STAGING",
        "RESULT_STAGED",
        "RESULT_VERIFIED",
        "RESULT_COMMITTED",
        "PARENT_INGESTED",
        "COMPLETED",
        "PROVIDER_COMPLETED_UNCOMMITTED",
    }:
        return "COMPLETED"
    if "FAILED_TERMINAL" in states:
        return "FAILED"
    if "CANCELLED" in states:
        return "CANCELLED"
    if states == {"CREATED"}:
        return "NOT_DISPATCHED"
    return "RUNNING"


def _latest_result_commit(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        candidate = event.get("details", {}).get("result_commit_id")
        if _nonempty(candidate):
            return candidate
    return None


def _recovery_action(state: str) -> str:
    if state in {"PROVIDER_COMPLETED_UNCOMMITTED", "RECOVERY_REQUIRED", "RETRY_SCHEDULED"}:
        return "RERUN_OR_RECONCILE"
    if state == "PARENT_INGESTED":
        return "AWAIT_COORDINATOR_COMPLETION_AND_INDEPENDENT_REVIEW"
    if state == "CREATED":
        return "NOT_DISPATCHED"
    if state in TERMINAL_STATES:
        return "NONE"
    return "MONITOR"


def _recovery_unit(task_id: str) -> dict[str, Any]:
    events = task_events(task_id)
    latest = events[-1]
    input_document = read_json(CONTROL_ROOT / "tasks" / task_id / "input.json")
    event_path = _event_files(task_id)[-1]
    return {
        "obzio_state": latest["state"],
        "provider_state": provider_state_from_events(events),
        "latest_event_sequence": latest["sequence"],
        "latest_event_sha256": sha256_file(event_path),
        "fence_token": _latest_fence(events, int(input_document["transaction"]["fence_token"])),
        "result_commit_id": _latest_result_commit(events),
        "recovery_action": _recovery_action(latest["state"]),
    }


def rebuild_recovery_state(*, run_id: str) -> dict[str, Any]:
    """Reconstruct the mutable recovery projection from immutable event chains."""
    path = CONTROL_ROOT / "recovery-state.json"
    projection = read_json(path) if path.exists() else {
        "recovery_version": "PO03-RECOVERY-STATE-v1",
        "scan_state": "ACTIVE",
        "false_completion_count": 0,
        "orphan_count": 0,
        "duplicate_callback_count": 0,
        "collision_count": 0,
        "decision_changed": [],
    }
    units: dict[str, dict[str, Any]] = {}
    for task_directory in sorted((CONTROL_ROOT / "tasks").glob("*")):
        if task_directory.is_dir():
            units[task_directory.name] = _recovery_unit(task_directory.name)
    projection["recovery_version"] = "PO03-RECOVERY-STATE-v1"
    projection["scan_state"] = "ACTIVE"
    projection["units"] = units
    projection["rebuilt_from_immutable_events"] = True
    projection["rebuilt_by_run_id"] = run_id
    replace_atomic(path, canonical_json(projection))
    return projection


def verify_recovery_state() -> list[str]:
    """Fail closed when the derived projection diverges from immutable custody."""
    path = CONTROL_ROOT / "recovery-state.json"
    if not path.exists():
        return [f"missing {repo_relative(path)}"]
    projection = read_json(path)
    units = projection.get("units")
    if not isinstance(units, dict):
        return [f"{repo_relative(path)}: units must be an object"]
    errors: list[str] = []
    observed: set[str] = set()
    for task_directory in sorted((CONTROL_ROOT / "tasks").glob("*")):
        if not task_directory.is_dir():
            continue
        task_id = task_directory.name
        observed.add(task_id)
        expected = _recovery_unit(task_id)
        actual = units.get(task_id)
        if not isinstance(actual, dict):
            errors.append(f"{repo_relative(path)}: missing unit {task_id}")
            continue
        for field, value in expected.items():
            if actual.get(field) != value:
                errors.append(f"{repo_relative(path)}: {task_id}.{field} diverges from immutable events")
    for task_id in sorted(set(units) - observed):
        errors.append(f"{repo_relative(path)}: orphaned projection unit {task_id}")
    return errors


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
    units[task_id] = _recovery_unit(task_id)
    replace_atomic(path, canonical_json(projection))


_RESULT_VALIDATOR: Any | None = None


def _result_validator() -> Any:
    global _RESULT_VALIDATOR
    if _RESULT_VALIDATOR is None:
        validator_path = PO03_ROOT / "tools" / "validate_contracts.py"
        specification = importlib.util.spec_from_file_location("po03_validate_contracts", validator_path)
        if specification is None or specification.loader is None:
            raise FactoryError(f"unable to load result validator: {repo_relative(validator_path)}")
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        _RESULT_VALIDATOR = module
    return _RESULT_VALIDATOR


def validate_ingested_result(task_id: str) -> list[str]:
    """Validate the immutable parent-ingestion record against a frozen task."""
    task_directory = CONTROL_ROOT / "tasks" / task_id
    result_path = task_directory / "transaction-ingested.json"
    if not result_path.is_file():
        return [f"missing {repo_relative(result_path)}"]
    try:
        result = read_json(result_path)
        created = read_json(task_directory / "transaction-created.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"{repo_relative(result_path)}: unreadable result record: {exc}"]
    errors = list(_result_validator().validate_result(result))
    if result.get("task_id") != task_id:
        errors.append("result task_id does not match custody task")
    if result.get("obzio_state") != "PARENT_INGESTED":
        errors.append("result record must remain PARENT_INGESTED before coordinator completion")
    for field in ("immutable_input_manifest_sha256", "acceptance_contract_sha256"):
        if result.get(field) != created.get(field):
            errors.append(f"result {field} does not match the frozen task")
    commit_id = result.get("result_transaction", {}).get("result_commit_id")
    if not isinstance(commit_id, str) or not GIT_OBJECT_RE.fullmatch(commit_id):
        errors.append("result transaction lacks a full immutable result commit ID")
    return errors


def _canonical_result_relative_path(value: Any) -> str:
    if not _nonempty(value) or "\\" in value or "\x00" in value:
        raise FactoryError("result artifact path must be a non-empty canonical relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or value == "."
        or path.as_posix() != value
    ):
        raise FactoryError(f"non-canonical result artifact path: {value!r}")
    return value


def _result_media_type(path: str) -> str:
    if path.endswith(".json"):
        return "application/json"
    if path.endswith(".jsonl"):
        return "application/x-ndjson"
    if path.endswith(".py"):
        return "text/x-python"
    if path.endswith(".md"):
        return "text/markdown"
    return "application/octet-stream"


def _resolve_result_commit(
    *,
    result_commit_id: str,
    result_base_commit_id: str,
    result_ref: str,
) -> str:
    require_git_object_id(result_commit_id, "result_commit_id")
    require_git_object_id(result_base_commit_id, "result_base_commit_id")
    if result_ref != "HEAD" and not (
        result_ref.startswith("origin/po03/") or result_ref.startswith("po03/")
    ):
        raise FactoryError("result_ref must be HEAD or a deterministic po03/* branch")
    try:
        git("cat-file", "-e", f"{result_commit_id}^{{commit}}")
        git("cat-file", "-e", f"{result_base_commit_id}^{{commit}}")
        git("merge-base", "--is-ancestor", result_base_commit_id, result_commit_id)
        visible_from = git("rev-parse", f"{result_ref}^{{commit}}")
        git("merge-base", "--is-ancestor", result_commit_id, visible_from)
    except subprocess.CalledProcessError as exc:
        raise FactoryError(
            "result commit must be immutable, descend from the declared result base, "
            "and be readable from the declared result ref"
        ) from exc
    return visible_from


def _result_manifest_artifacts(
    *,
    task_id: str,
    result_slot: str,
    result_commit_id: str,
    result_base_commit_id: str,
    result_ref: str,
) -> tuple[list[dict[str, Any]], str, int, str]:
    """Read and verify a producer manifest strictly from immutable Git bytes."""
    normalized_slot = result_slot.rstrip("/")
    manifest_path = f"{normalized_slot}/manifest.json"
    try:
        manifest_bytes = git_bytes("show", f"{result_commit_id}:{manifest_path}")
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        raise FactoryError("result manifest is not an immutable JSON object at the result commit") from exc
    if not isinstance(manifest, dict):
        raise FactoryError("result manifest must be an object")
    if manifest.get("task_id") != task_id:
        raise FactoryError("result manifest task_id does not match custody task")
    if str(manifest.get("result_slot", "")).rstrip("/") != normalized_slot:
        raise FactoryError("result manifest slot does not match frozen task ownership")
    declared = manifest.get("artifacts")
    if not isinstance(declared, list) or not declared:
        raise FactoryError("result manifest requires at least one declared artifact")
    if manifest.get("artifact_count") != len(declared):
        raise FactoryError("result manifest artifact_count does not match declared artifacts")

    artifacts: list[dict[str, Any]] = []
    expected_paths = {manifest_path}
    declared_bytes = 0
    seen_paths: set[str] = set()
    observed_at = utc_now()
    for index, item in enumerate(declared, start=1):
        if not isinstance(item, dict):
            raise FactoryError("result manifest artifact entries must be objects")
        relative = _canonical_result_relative_path(item.get("path"))
        if relative == "manifest.json" or relative in seen_paths:
            raise FactoryError("result manifest artifacts must be unique and exclude manifest.json")
        seen_paths.add(relative)
        repository_path = f"{normalized_slot}/{relative}"
        expected_paths.add(repository_path)
        try:
            content = git_bytes("show", f"{result_commit_id}:{repository_path}")
        except subprocess.CalledProcessError as exc:
            raise FactoryError(f"declared result artifact is absent from immutable commit: {relative}") from exc
        observed_sha256 = sha256_bytes(content)
        if item.get("sha256") != observed_sha256:
            raise FactoryError(f"declared result artifact hash does not match immutable bytes: {relative}")
        if item.get("bytes") != len(content):
            raise FactoryError(f"declared result artifact byte count does not match immutable bytes: {relative}")
        declared_bytes += len(content)
        artifacts.append(
            {
                "artifact_id": f"{task_id}-artifact-{index}",
                "logical_name": relative,
                "content_uri": f"git:{result_ref}@{result_commit_id}:{repository_path}",
                "sha256": observed_sha256,
                "bytes": len(content),
                "media_type": _result_media_type(relative),
                "readback_verified_at": observed_at,
            }
        )
    if manifest.get("total_artifact_bytes_excluding_manifest") != declared_bytes:
        raise FactoryError("result manifest total artifact bytes do not match immutable bytes")
    try:
        changed_paths = {
            path
            for path in git(
                "diff",
                "--name-only",
                "--no-renames",
                "--diff-filter=ACMRD",
                f"{result_base_commit_id}..{result_commit_id}",
            ).splitlines()
            if path
        }
    except subprocess.CalledProcessError as exc:
        raise FactoryError("unable to enumerate the immutable result commit range") from exc
    if changed_paths != expected_paths:
        raise FactoryError(
            "result commit range must change exactly the manifest and declared owned artifacts"
        )
    manifest_sha256 = sha256_bytes(manifest_bytes)
    artifacts.append(
        {
            "artifact_id": f"{task_id}-manifest",
            "logical_name": "manifest.json",
            "content_uri": f"git:{result_ref}@{result_commit_id}:{manifest_path}",
            "sha256": manifest_sha256,
            "bytes": len(manifest_bytes),
            "media_type": "application/json",
            "readback_verified_at": observed_at,
        }
    )
    return artifacts, manifest_sha256, declared_bytes + len(manifest_bytes), observed_at


def ingest_committed_result(
    task_id: str,
    *,
    result_commit_id: str,
    result_base_commit_id: str,
    result_ref: str = "HEAD",
    provider_run_id: str,
) -> dict[str, Any]:
    """Ingest one READY_TO_COMMIT return only after immutable Git read-back.

    The controller reconstructs the parent record from Git object bytes rather
    than trusting a worker summary. It intentionally stops at PARENT_INGESTED;
    a coordinator completion and independent review remain separate actions.
    """
    if not _nonempty(provider_run_id):
        raise FactoryError("provider_run_id must be non-empty")
    with _task_lock(task_id):
        events = task_events(task_id)
        latest = events[-1]
        if latest["state"] in {"PARENT_INGESTED", "COMPLETED"}:
            errors = validate_ingested_result(task_id)
            if errors:
                raise FactoryError("; ".join(errors))
            record = read_json(CONTROL_ROOT / "tasks" / task_id / "transaction-ingested.json")
            existing_commit = record["result_transaction"]["result_commit_id"]
            if existing_commit != result_commit_id:
                raise FactoryError("duplicate ingestion names a different immutable result commit")
            return {
                "task_id": task_id,
                "result_commit_id": result_commit_id,
                "status": "ALREADY_INGESTED",
            }
        if latest["state"] != "RUNNING":
            raise FactoryError(
                f"result ingestion requires RUNNING custody, found {latest['state']}"
            )

        task_directory = CONTROL_ROOT / "tasks" / task_id
        input_document = read_json(task_directory / "input.json")
        created = read_json(task_directory / "transaction-created.json")
        ownership = input_document.get("ownership")
        if not isinstance(ownership, dict) or not _nonempty(ownership.get("result_slot")):
            raise FactoryError("frozen task lacks an owned result slot")
        worker_id = _lease_owner(events)
        if not _nonempty(worker_id):
            raise FactoryError("result ingestion requires an active leased worker")
        visible_from = _resolve_result_commit(
            result_commit_id=result_commit_id,
            result_base_commit_id=result_base_commit_id,
            result_ref=result_ref,
        )
        artifacts, manifest_sha256, total_bytes, readback_at = _result_manifest_artifacts(
            task_id=task_id,
            result_slot=ownership["result_slot"],
            result_commit_id=result_commit_id,
            result_base_commit_id=result_base_commit_id,
            result_ref=result_ref,
        )
        committed_at = git("show", "-s", "--format=%aI", result_commit_id)
        result_record = {
            "protocol_version": PROTOCOL_VERSION,
            "task_id": task_id,
            "commission_id": created["commission_id"],
            "immutable_input_manifest_sha256": created["immutable_input_manifest_sha256"],
            "acceptance_contract_sha256": created["acceptance_contract_sha256"],
            "provider_state": "COMPLETED",
            "obzio_state": "PARENT_INGESTED",
            "attempt": {
                "attempt_id": created["attempt"]["attempt_id"],
                "idempotency_key": created["attempt"]["idempotency_key"],
                "lease_id": created["attempt"]["lease_id"],
                "fence_token": _latest_fence(events, created["attempt"]["fence_token"]),
                "provider_run_id": provider_run_id,
                "worker_id": worker_id,
                "heartbeat_at": None,
                "checkpoint_seq": sum(event["state"] == "CHECKPOINTED" for event in events),
            },
            "result_transaction": {
                "result_txn_id": created["result_transaction"]["result_txn_id"],
                "state": "INGESTED",
                "manifest_uri": (
                    f"git:{result_ref}@{result_commit_id}:"
                    f"{ownership['result_slot'].rstrip('/')}/manifest.json"
                ),
                "manifest_sha256": manifest_sha256,
                "artifact_count": len(artifacts),
                "total_bytes": total_bytes,
                "committed_at": committed_at,
                "verified_at": readback_at,
                "parent_ingested_at": readback_at,
                "result_commit_id": result_commit_id,
            },
            "artifacts": artifacts,
            "completion_actor": None,
            "independent_acceptance": {
                "state": "PENDING",
                "reviewer_id": None,
                "receipt_uri": None,
            },
        }
        errors = _result_validator().validate_result(result_record)
        if errors:
            raise FactoryError("invalid reconstructed result record: " + "; ".join(errors))
        fence_token = result_record["attempt"]["fence_token"]
        provenance = {
            "reported_by": "integration-controller",
            "provider_execution_id": provider_run_id,
            "result_base_commit_id": result_base_commit_id,
            "result_commit_id": result_commit_id,
            "result_ref": result_ref,
            "visible_from_commit_id": visible_from,
        }
        _advance_task_locked(
            task_id,
            state="RESULT_STAGING",
            actor=worker_id,
            fence_token=fence_token,
            details=provenance,
        )
        _advance_task_locked(
            task_id,
            state="RESULT_STAGED",
            actor=worker_id,
            fence_token=fence_token,
            details={
                **provenance,
                "manifest_sha256": manifest_sha256,
                "total_bytes": total_bytes,
            },
        )
        _advance_task_locked(
            task_id,
            state="RESULT_VERIFIED",
            actor=worker_id,
            fence_token=fence_token,
            details={
                **provenance,
                "verified_artifacts": len(artifacts),
                "parent_remote_readback": "PASS",
            },
        )
        _advance_task_locked(
            task_id,
            state="RESULT_COMMITTED",
            actor="integration-controller",
            fence_token=fence_token,
            details=provenance,
        )
        write_once(task_directory / "transaction-ingested.json", canonical_json(result_record))
        _advance_task_locked(
            task_id,
            state="PARENT_INGESTED",
            actor="integration-controller",
            fence_token=fence_token,
            details={**provenance, "parent_readback": "PASS"},
        )
        return {
            "task_id": task_id,
            "result_commit_id": result_commit_id,
            "artifact_count": len(artifacts),
            "total_bytes": total_bytes,
            "status": "PARENT_INGESTED",
        }


def _require_detail_sha256(details: dict[str, Any], name: str) -> None:
    if not isinstance(details.get(name), str) or not SHA256_RE.fullmatch(details[name]):
        raise FactoryError(f"{name} must be a lowercase SHA-256")


def _require_detail_positive_int(details: dict[str, Any], name: str) -> None:
    if not isinstance(details.get(name), int) or details[name] < 1:
        raise FactoryError(f"{name} must be an integer >= 1")


def _validate_transition_evidence(task_id: str, state: str, details: dict[str, Any]) -> None:
    if state == "RESULT_STAGED":
        _require_detail_sha256(details, "manifest_sha256")
        _require_detail_positive_int(details, "total_bytes")
    elif state == "RESULT_VERIFIED":
        _require_detail_positive_int(details, "verified_artifacts")
        if details.get("parent_remote_readback") != "PASS":
            raise FactoryError("RESULT_VERIFIED requires parent_remote_readback=PASS")
    elif state == "RESULT_COMMITTED":
        result_commit_id = details.get("result_commit_id")
        if not isinstance(result_commit_id, str) or not GIT_OBJECT_RE.fullmatch(result_commit_id):
            raise FactoryError("RESULT_COMMITTED requires a full immutable result commit ID")
    elif state in {"PARENT_INGESTED", "COMPLETED"}:
        if state == "PARENT_INGESTED" and details.get("parent_readback") != "PASS":
            raise FactoryError("PARENT_INGESTED requires parent_readback=PASS")
        errors = validate_ingested_result(task_id)
        if errors:
            raise FactoryError("; ".join(errors))
        result = read_json(CONTROL_ROOT / "tasks" / task_id / "transaction-ingested.json")
        result_commit_id = result["result_transaction"]["result_commit_id"]
        if details.get("result_commit_id") != result_commit_id:
            raise FactoryError("event result commit does not match immutable ingestion record")


def advance_task(
    task_id: str,
    *,
    state: str,
    actor: str,
    fence_token: int,
    details: dict[str, Any] | None = None,
) -> Path:
    """Serialize a fenced task transition before changing durable custody."""
    with _task_lock(task_id):
        return _advance_task_locked(
            task_id,
            state=state,
            actor=actor,
            fence_token=fence_token,
            details=details,
        )


def _advance_task_locked(
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
    _validate_transition_evidence(task_id, state, event_details)
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
            finding = _recovery_unit(task_id)
            finding["task_id"] = task_id
            findings.append(finding)
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
    sources: list[dict[str, Any]] = []
    for path in paths:
        blob = git_bytes("show", f"{head_sha}:{path}")
        sources.append(
            {
                "path": path,
                "git_blob_sha": git("rev-parse", f"{head_sha}:{path}"),
                "sha256": sha256_bytes(blob),
                "bytes": len(blob),
            }
        )
    return {
        "source_lock_version": "PO03-SOURCE-LOCK-v1",
        "repository": "github.com/asibrahim336-hash/obzio-ai-coordination-temp",
        "branch": "po03/repository-engineering-portable-runtime-20260822-v001",
        "head_sha": head_sha,
        "sources": sources,
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
    if not errors and task_events(args.task_id)[-1]["state"] in {"PARENT_INGESTED", "COMPLETED"}:
        errors.extend(validate_ingested_result(args.task_id))
    if errors:
        for error in errors:
            print(f"INVALID: {error}")
        return 1
    print(f"VALID task={args.task_id}")
    return 0


def rebuild_recovery(args: argparse.Namespace) -> int:
    projection = rebuild_recovery_state(run_id=args.run_id)
    print(json.dumps({"rebuilt_units": len(projection["units"]), "run_id": args.run_id}, sort_keys=True))
    return 0


def verify_recovery(args: argparse.Namespace) -> int:
    errors = verify_recovery_state()
    if errors:
        for error in errors:
            print(f"INVALID: {error}")
        return 1
    print("VALID recovery projection")
    return 0


def ingest_result(args: argparse.Namespace) -> int:
    result = ingest_committed_result(
        args.task_id,
        result_commit_id=args.result_commit,
        result_base_commit_id=args.result_base,
        result_ref=args.result_ref,
        provider_run_id=args.provider_run_id,
    )
    print(json.dumps(result, sort_keys=True))
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
    ingest_parser = subparsers.add_parser("ingest-result")
    ingest_parser.add_argument("task_id")
    ingest_parser.add_argument("--result-commit", required=True)
    ingest_parser.add_argument("--result-base", required=True)
    ingest_parser.add_argument("--result-ref", default="HEAD")
    ingest_parser.add_argument("--provider-run-id", required=True)
    ingest_parser.set_defaults(handler=ingest_result)
    scan_parser = subparsers.add_parser("scan-recovery")
    scan_parser.set_defaults(handler=lambda args: (print(json.dumps(recovery_scan(), sort_keys=True)) or 0))
    rebuild_parser = subparsers.add_parser("rebuild-recovery")
    rebuild_parser.add_argument("--run-id", required=True)
    rebuild_parser.set_defaults(handler=rebuild_recovery)
    verify_recovery_parser = subparsers.add_parser("verify-recovery")
    verify_recovery_parser.set_defaults(handler=verify_recovery)
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
