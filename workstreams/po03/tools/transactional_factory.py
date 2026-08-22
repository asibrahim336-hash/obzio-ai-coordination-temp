#!/usr/bin/env python3
"""Durable task custody for the PO-03 work-unit factory.

The controller writes immutable task capsules and hash-chained event files
before a provider receives work.  Mutable provider callbacks are observations;
only an ingested, read-back result can advance to Obzio COMPLETED.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def assert_allowed_path(path: Path) -> None:
    relative = repo_relative(path)
    if not any(relative.startswith(prefix) for prefix in ALLOWED_WRITE_PREFIXES):
        raise ValueError(f"write outside PO-03 allowlist: {relative}")


def write_once(path: Path, payload: bytes) -> None:
    """Atomically create an immutable file and fsync its directory."""
    assert_allowed_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_bytes()
        if existing != payload:
            raise FileExistsError(f"immutable file differs: {repo_relative(path)}")
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def replace_atomic(path: Path, payload: bytes) -> None:
    """Atomically replace controller-owned derived state."""
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
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


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
        raise ValueError(f"{field} must be a full lowercase Git object ID")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{repo_relative(path)} must contain an object")
    return value


def hash_chain_event(
    task_id: str,
    state: str,
    *,
    actor: str,
    details: dict[str, Any] | None = None,
    observed_at: str | None = None,
) -> Path:
    if state not in STATE_ORDER and state not in {
        "PROVIDER_COMPLETED_UNCOMMITTED",
        "RECOVERY_REQUIRED",
        "RETRY_SCHEDULED",
        "FAILED_TERMINAL",
        "CANCELLED",
        "ACCEPTED",
        "REJECTED",
    }:
        raise ValueError(f"unsupported event state: {state}")
    event_directory = CONTROL_ROOT / "events" / task_id
    prior_events = sorted(event_directory.glob("*.json")) if event_directory.exists() else []
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
    destination = event_directory / f"{sequence:06d}-{state.lower()}.json"
    write_once(destination, canonical_json(body))
    return destination


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
        "parent_reasoning_control": "encoded_by_provider_as_max-fast",
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
                "family": "claude-sonnet-5",
                "exact_configuration": "claude-sonnet-5-thinking-xhigh",
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
    if not TASK_ID_RE.fullmatch(task_id):
        raise ValueError(f"invalid task id: {task_id}")
    if not owned_paths or any(not path.startswith("workstreams/po03/") for path in owned_paths):
        raise ValueError("owned paths must be non-empty PO-03 paths")
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


def activate(args: argparse.Namespace) -> int:
    actual_head = git("rev-parse", "HEAD")
    if actual_head != args.head_sha:
        raise ValueError(f"head changed: expected {args.head_sha}, observed {actual_head}")
    require_git_object_id(args.head_sha, "head_sha")

    source_document = source_lock(args.head_sha)
    criteria_document = criteria_freeze(args.head_sha)
    model_document = model_register(args.run_id, args.parent_model)
    source_path = PO03_ROOT / "evidence" / "source-lock.json"
    criteria_path = PO03_ROOT / "evidence" / "criteria-freeze.json"
    model_path = CONTROL_ROOT / "model-capability-register.json"
    write_once(source_path, canonical_json(source_document))
    write_once(criteria_path, canonical_json(criteria_document))
    write_once(model_path, canonical_json(model_document))

    nonce_seed = f"{args.head_sha}:{args.run_id}:po03-canary-001".encode("utf-8")
    nonce = sha256_bytes(nonce_seed)
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
        prompt=(
            "Execute the immutable canary contract in this task capsule. Write only the owned result slot; "
            "commit and push the exact artifact; independently read it back from the immutable commit; "
            "return READY_TO_COMMIT with branch and SHA. Never claim COMPLETED or ACCEPTED."
        ),
        owned_paths=["workstreams/po03/attempts/canary/po03-canary-001/**"],
        result_slot="workstreams/po03/attempts/canary/po03-canary-001",
        acceptance=acceptance,
        lease_seconds=1800,
        fence_token=1,
        nonce=nonce,
    )

    ownership = {
        "ownership_version": "PO03-PATH-OWNERSHIP-v1",
        "controller": {
            "run_id": args.run_id,
            "owned_paths": [
                "workstreams/po03/control/**",
                "workstreams/po03/evidence/**",
                "workstreams/po03/metrics/**",
                "workstreams/po03/successor/**",
                "receipts/po03/**",
                ".github/workflows/po03-*.yml",
            ],
        },
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
    recovery = {
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
    metrics = {
        "metrics_version": "PO03-METRIC-DEFINITIONS-v1",
        "unit_of_observation": "one counted work-unit attempt",
        "required_fields": [
            "task_id",
            "parent_id",
            "function",
            "runtime",
            "exact_model",
            "reasoning",
            "prompt_sha256",
            "source_sha256",
            "context_sha256",
            "available_tokens",
            "available_cost",
            "queue_ms",
            "active_ms",
            "wall_ms",
            "review_ms",
            "checkpoint_count",
            "retry_count",
            "result_commit_id",
            "readback_state",
            "first_pass_outcome",
            "independent_disposition",
            "defect_count",
            "rework_count",
            "founder_action_count",
            "provider_block",
            "collision_count",
            "recovery_events",
        ],
        "unsupported_value": "NOT_SUPPORTED",
        "derived_metrics": [
            "independently_accepted_throughput",
            "first_pass_acceptance_rate",
            "false_green_rate",
            "recovery_rate",
            "research_to_reproduction_conversion",
            "lesson_to_live_change_conversion",
            "successor_lift",
        ],
        "decision_changed": [],
    }
    replace_atomic(CONTROL_ROOT / "path-ownership.json", canonical_json(ownership))
    replace_atomic(CONTROL_ROOT / "recovery-state.json", canonical_json(recovery))
    write_once(PO03_ROOT / "metrics" / "metric-definitions.json", canonical_json(metrics))
    write_once(PO03_ROOT / "metrics" / "work-unit-runs.jsonl", b"")
    write_once(CONTROL_ROOT / "work-unit-registry.jsonl", canonical_json(canary))

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


def verify_chain(task_id: str) -> list[str]:
    errors: list[str] = []
    events = sorted((CONTROL_ROOT / "events" / task_id).glob("*.json"))
    previous_hash: str | None = None
    for expected_sequence, path in enumerate(events, start=1):
        event = read_json(path)
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


class StaleFenceError(RuntimeError):
    """Raised when a superseded worker attempts to commit after ownership moved."""


def append_registry(entry: dict[str, Any]) -> str:
    """Append one durable line to the append-only work-unit registry."""
    registry = CONTROL_ROOT / "work-unit-registry.jsonl"
    assert_allowed_path(registry)
    registry.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(entry)
    with registry.open("ab") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return sha256_bytes(payload)


def allocate_fence() -> int:
    """Allocate a strictly monotonic fence token.

    The previous value survives a crash mid-allocation because the counter is
    replaced atomically rather than rewritten in place.
    """
    counter = CONTROL_ROOT / "fence-counter.json"
    current = read_json(counter)["fence_token"] if counter.is_file() else 0
    nxt = int(current) + 1
    replace_atomic(counter, canonical_json({"fence_token": nxt, "allocated_at": utc_now()}))
    return nxt


def _lease_path(task_id: str) -> Path:
    return CONTROL_ROOT / "leases" / f"{task_id}.json"


def grant_lease(task_id: str, *, holder: str, lease_seconds: int, attempt: int) -> dict[str, Any]:
    """Grant or transfer a lease, always advancing the fence token."""
    fence_token = allocate_fence()
    lease = {
        "lease_version": "PO03-LEASE-v1",
        "task_id": task_id,
        "lease_id": f"lease-{task_id}-{attempt}",
        "holder": holder,
        "attempt": attempt,
        "fence_token": fence_token,
        "granted_at": utc_now(),
        "lease_seconds": lease_seconds,
    }
    replace_atomic(_lease_path(task_id), canonical_json(lease))
    hash_chain_event(
        task_id,
        "LEASED",
        actor="integration-controller",
        details={"holder": holder, "fence_token": fence_token, "attempt": attempt},
    )
    return lease


def current_fence(task_id: str) -> int:
    lease = _lease_path(task_id)
    return int(read_json(lease)["fence_token"]) if lease.is_file() else 0


def assert_fence_current(task_id: str, fence_token: int) -> None:
    """Reject a write from a worker whose lease has been superseded."""
    active = current_fence(task_id)
    if active and int(fence_token) < active:
        raise StaleFenceError(
            f"{task_id}: fence {fence_token} is stale; active fence is {active}"
        )


REMOTE_LEASE_PREFIX = "refs/heads/po03/lease/"


def _claim_commit(payload: dict[str, Any]) -> str:
    """Build an unreferenced commit carrying an ownership claim."""
    claim_bytes = canonical_json(payload)
    blob = subprocess.run(
        ("git", "hash-object", "-w", "--stdin"),
        cwd=REPO_ROOT,
        input=claim_bytes,
        check=True,
        capture_output=True,
    ).stdout.decode().strip()
    tree = subprocess.run(
        ("git", "mktree"),
        cwd=REPO_ROOT,
        input=f"100644 blob {blob}\tclaim.json\n".encode("utf-8"),
        check=True,
        capture_output=True,
    ).stdout.decode().strip()
    return git("commit-tree", tree, "-m", f"po03 lease claim {payload['task_id']}")


def read_remote_claim(task_id: str, *, remote: str = "origin") -> dict[str, Any] | None:
    """Return the published ownership claim for a task, or None if unclaimed."""
    ref = REMOTE_LEASE_PREFIX + task_id
    listing = git("ls-remote", remote, ref)
    if not listing.strip():
        return None
    git("fetch", "--no-tags", remote, ref)
    head = git("rev-parse", "FETCH_HEAD")
    body = subprocess.run(
        ("git", "cat-file", "blob", f"{head}:claim.json"),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    claim = json.loads(body.decode("utf-8"))
    return claim if isinstance(claim, dict) else None


def acquire_remote_lease(
    task_id: str,
    controller_run_id: str,
    *,
    remote: str = "origin",
    attempt: int = 1,
) -> dict[str, Any]:
    """Atomically claim cross-controller ownership of a task.

    A local fence token cannot arbitrate between two controllers that inherited
    the same immutable capsule: both read the same frozen token and both believe
    they own the work.  Creating a remote ref is a compare-and-swap, so the first
    controller to publish a claim wins and every later controller is refused
    instead of colliding in the shared result slot.
    """
    existing = read_remote_claim(task_id, remote=remote)
    if existing is not None:
        state = "OWNED" if existing.get("controller_run_id") == controller_run_id else "REFUSED"
        return {"state": state, "owner": existing.get("controller_run_id"), "claim": existing}

    payload = {
        "claim_version": "PO03-REMOTE-LEASE-CLAIM-v1",
        "task_id": task_id,
        "controller_run_id": controller_run_id,
        "commission_id": COMMISSION_ID,
        "attempt": attempt,
        "claimed_at": utc_now(),
    }
    commit = _claim_commit(payload)
    try:
        git("push", remote, f"{commit}:{REMOTE_LEASE_PREFIX}{task_id}")
    except subprocess.CalledProcessError:
        # Another controller won the race between the check and the push.
        existing = read_remote_claim(task_id, remote=remote)
        return {
            "state": "REFUSED",
            "owner": existing.get("controller_run_id") if existing else "UNKNOWN",
            "claim": existing,
        }
    return {"state": "ACQUIRED", "owner": controller_run_id, "claim": payload}


def published_claims(remote: str = "origin") -> dict[str, dict[str, Any]]:
    """Read every published ownership claim in one batched round trip."""
    listing = git("ls-remote", "--heads", remote, f"{REMOTE_LEASE_PREFIX}*")
    task_ids = [
        line.split("\t")[1][len(REMOTE_LEASE_PREFIX) :]
        for line in listing.splitlines()
        if "\t" in line
    ]
    if not task_ids:
        return {}
    git("fetch", "--no-tags", "--force", remote, f"+{REMOTE_LEASE_PREFIX}*:refs/po03-claims/*")
    claims: dict[str, dict[str, Any]] = {}
    for task_id in task_ids:
        body = subprocess.run(
            ("git", "cat-file", "blob", f"refs/po03-claims/{task_id}:claim.json"),
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
        )
        if body.returncode != 0:
            continue
        try:
            claim = json.loads(body.stdout.decode("utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(claim, dict):
            claims[task_id] = claim
    return claims


def claim_wave(spec_path: Path, controller_run_id: str, *, remote: str = "origin") -> dict[str, Any]:
    """Claim every unclaimed unit in a wave with one batched compare-and-swap.

    Idempotent: a slot this controller already owns is reported as owned rather
    than re-pushed, and a slot another controller owns is reported as contended
    rather than overwritten.
    """
    spec = read_json(spec_path)
    existing = published_claims(remote)
    owned: list[str] = []
    contended: list[dict[str, str]] = []
    refspecs: list[str] = []
    for unit in spec["units"]:
        task_id = unit["task_id"]
        claim = existing.get(task_id)
        if claim is not None:
            if claim.get("controller_run_id") == controller_run_id:
                owned.append(task_id)
            else:
                contended.append({"task_id": task_id, "owner": claim.get("controller_run_id", "UNKNOWN")})
            continue
        payload = {
            "claim_version": "PO03-REMOTE-LEASE-CLAIM-v1",
            "task_id": task_id,
            "controller_run_id": controller_run_id,
            "commission_id": COMMISSION_ID,
            "attempt": 1,
            "claimed_at": utc_now(),
        }
        refspecs.append(f"{_claim_commit(payload)}:{REMOTE_LEASE_PREFIX}{task_id}")

    acquired: list[str] = []
    rejected: list[str] = []
    exit_code = 0
    if refspecs:
        completed = subprocess.run(
            ("git", "push", "--porcelain", remote, *refspecs),
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        exit_code = completed.returncode
        for line in completed.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            target = parts[1].split(":")[-1]
            if not target.startswith(REMOTE_LEASE_PREFIX):
                continue
            task_id = target[len(REMOTE_LEASE_PREFIX) :]
            (rejected if parts[0].startswith("!") else acquired).append(task_id)

    return {
        "claim_outcome_version": "PO03-WAVE-CLAIM-v1",
        "controller_run_id": controller_run_id,
        "remote": remote,
        "requested": len(spec["units"]),
        "already_owned": sorted(owned),
        "acquired": sorted(acquired),
        "rejected_at_push": sorted(rejected),
        "contended": sorted(contended, key=lambda item: item["task_id"]),
        "already_owned_count": len(owned),
        "acquired_count": len(acquired),
        "rejected_count": len(rejected),
        "contended_count": len(contended),
        "exclusive_ownership_complete": len(owned) + len(acquired) == len(spec["units"]),
        "push_exit_code": exit_code,
        "claimed_at": utc_now(),
    }


def find_published_result(
    slot: str,
    idempotency_key: str,
    *,
    remote: str = "origin",
    ref_glob: str = "refs/heads/po03/*",
) -> dict[str, Any] | None:
    """Locate an already-published result for one idempotency key.

    A duplicate dispatch of a key that has already produced a durable result must
    be a no-op that returns the existing result.  Without this the second producer
    is handed a worktree pinned before the first producer's commit, so it cannot
    observe the conflict until its push is refused, which is exactly how the
    po03-canary-001 collision was discovered.
    """
    listing = git("ls-remote", "--heads", remote, ref_glob)
    refs = [line.split("\t")[1] for line in listing.splitlines() if "\t" in line]
    if not refs:
        return None
    git("fetch", "--no-tags", "--force", remote, f"+{ref_glob}:refs/po03-scan/*")
    for ref in refs:
        local = "refs/po03-scan/" + ref[len("refs/heads/po03/") :]
        body = subprocess.run(
            ("git", "cat-file", "blob", f"{local}:{slot}/result.json"),
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
        )
        if body.returncode != 0:
            continue
        try:
            document = json.loads(body.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        attempt = document.get("attempt", {})
        if isinstance(attempt, dict) and attempt.get("idempotency_key") == idempotency_key:
            return {
                "ref": ref,
                "slot": slot,
                "idempotency_key": idempotency_key,
                "result": document,
                "result_commit_id": document.get("result_transaction", {}).get("result_commit_id"),
            }
    return None


def dispatch_precheck(task_id: str, *, remote: str = "origin") -> dict[str, Any]:
    """Decide whether a unit may be dispatched, or is already satisfied.

    Returns ALREADY_SATISFIED when this exact idempotency key has already left a
    durable published result, so the controller returns that result instead of
    handing a second producer a doomed worktree.
    """
    capsule = read_json(CONTROL_ROOT / "tasks" / task_id / "input.json")
    slot = capsule["ownership"]["result_slot"]
    idempotency_key = capsule["transaction"]["idempotency_key"]
    published = find_published_result(slot, idempotency_key, remote=remote)
    if published is not None:
        return {
            "state": "ALREADY_SATISFIED",
            "task_id": task_id,
            "slot": slot,
            "idempotency_key": idempotency_key,
            "existing_ref": published["ref"],
            "existing_result_commit_id": published["result_commit_id"],
            "action": "return the existing result; do not dispatch a second producer",
        }
    return {
        "state": "DISPATCHABLE",
        "task_id": task_id,
        "slot": slot,
        "idempotency_key": idempotency_key,
        "action": "acquire a remote ownership claim, then dispatch",
    }


def assert_remote_ownership(task_id: str, controller_run_id: str, *, remote: str = "origin") -> None:
    """Refuse to publish into a result slot this controller does not own."""
    claim = read_remote_claim(task_id, remote=remote)
    if claim is None:
        raise StaleFenceError(f"{task_id}: no published ownership claim; acquire a remote lease first")
    owner = claim.get("controller_run_id")
    if owner != controller_run_id:
        raise StaleFenceError(
            f"{task_id}: result slot is owned by controller {owner}, not {controller_run_id}"
        )


def read_object_bytes(locator: str) -> bytes:
    """Read committed bytes by immutable Git object id, never from the worktree."""
    if not locator.startswith("git:"):
        raise ValueError(f"non-durable artifact locator: {locator}")
    revision_path = locator[len("git:") :]
    result = subprocess.run(
        ("git", "cat-file", "blob", revision_path),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout


def load_result_validator():
    """Load the seeded validator without leaving bytecode in a shared path."""
    module_path = PO03_ROOT / "tools" / "validate_contracts.py"
    spec = importlib.util.spec_from_file_location("po03_validate_contracts", module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load contract validator: {repo_relative(module_path)}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def ingest_result(task_id: str, document: dict[str, Any]) -> dict[str, Any]:
    """Verify a subordinate result and record parent ingestion.

    Provider completion is only an observation.  A result advances only when the
    seeded contract validates it, every artifact is read back from an immutable
    object by this process, and the worker's fence is still current.  Re-ingesting
    the same result is harmless so a duplicated callback cannot double-count.
    """
    validator = load_result_validator()
    errors = list(validator.validate_result(document))
    attempt = document.get("attempt", {}) if isinstance(document.get("attempt"), dict) else {}

    if not errors:
        try:
            assert_fence_current(task_id, attempt.get("fence_token", 0))
        except StaleFenceError as exc:
            errors.append(str(exc))

    readback: list[dict[str, Any]] = []
    if not errors:
        for artifact in document["artifacts"]:
            try:
                observed = read_object_bytes(artifact["content_uri"])
            except (ValueError, subprocess.CalledProcessError) as exc:
                errors.append(f"artifact {artifact['artifact_id']}: read-back failed ({exc})")
                continue
            observed_sha = sha256_bytes(observed)
            matched = observed_sha == artifact["sha256"] and len(observed) == artifact["bytes"]
            if not matched:
                errors.append(
                    f"artifact {artifact['artifact_id']}: read-back mismatch "
                    f"sha256={observed_sha} bytes={len(observed)}"
                )
            readback.append(
                {
                    "artifact_id": artifact["artifact_id"],
                    "locator": artifact["content_uri"],
                    "expected_sha256": artifact["sha256"],
                    "observed_sha256": observed_sha,
                    "expected_bytes": artifact["bytes"],
                    "observed_bytes": len(observed),
                    "match": matched,
                }
            )
        if not document["artifacts"]:
            errors.append("result carries no artifacts; nothing durable to ingest")

    result_bytes = canonical_json(document)
    result_sha = sha256_bytes(result_bytes)
    task_directory = CONTROL_ROOT / "tasks" / task_id
    state = "PARENT_INGESTED" if not errors else "RECOVERY_REQUIRED"

    ingestion = {
        "ingestion_version": "PO03-INGESTION-v1",
        "task_id": task_id,
        "obzio_state": state,
        "result_sha256": result_sha,
        "idempotency_key": attempt.get("idempotency_key"),
        "fence_token": attempt.get("fence_token"),
        "worker_id": attempt.get("worker_id"),
        "provider_state": document.get("provider_state"),
        "result_commit_id": document.get("result_transaction", {}).get("result_commit_id"),
        "artifact_readback": readback,
        "errors": errors,
        "ingested_by": "coordinator",
        "ingested_at": utc_now(),
    }
    # write_once makes a replayed identical callback a no-op instead of a duplicate.
    destination = task_directory / f"ingestion-{result_sha[:16]}.json"
    ingestion_bytes = canonical_json(ingestion)
    if destination.is_file():
        ingestion["duplicate_callback_suppressed"] = True
        return ingestion
    write_once(task_directory / f"result-{result_sha[:16]}.json", result_bytes)
    write_once(destination, ingestion_bytes)
    hash_chain_event(
        task_id,
        state,
        actor="integration-controller",
        details={"result_sha256": result_sha, "readback_count": len(readback), "errors": errors},
    )
    append_registry(
        {
            "registry_event": "INGESTION",
            "task_id": task_id,
            "obzio_state": state,
            "result_sha256": result_sha,
            "fence_token": attempt.get("fence_token"),
            "worker_id": attempt.get("worker_id"),
            "artifact_count": len(readback),
            "errors": errors,
            "recorded_at": ingestion["ingested_at"],
        }
    )
    return ingestion


def find_ingestion(task_id: str, result_sha256: str) -> dict[str, Any] | None:
    candidate = CONTROL_ROOT / "tasks" / task_id / f"ingestion-{result_sha256[:16]}.json"
    return read_json(candidate) if candidate.is_file() else None


def complete_unit(task_id: str, document: dict[str, Any], *, reviewer_id: str | None = None) -> dict[str, Any]:
    """Set Obzio COMPLETED. Only the coordinator may call this, and only after ingestion.

    Parent ingestion is a fact the coordinator observes, never a field a producer
    supplies, so a pre-populated `parent_ingested_at` is treated as forgery and
    the timestamp is stamped from the controller's own ingestion record.
    """
    events = sorted((CONTROL_ROOT / "events" / task_id).glob("*.json"))
    ingested = any(read_json(path).get("state") == "PARENT_INGESTED" for path in events)
    if not ingested:
        raise ValueError(f"{task_id}: cannot complete before PARENT_INGESTED")

    if _nonempty_text(document.get("result_transaction", {}).get("parent_ingested_at")):
        raise ValueError(
            f"{task_id}: producer supplied parent_ingested_at; only the coordinator records ingestion"
        )
    ingestion = find_ingestion(task_id, sha256_bytes(canonical_json(document)))
    if ingestion is None:
        raise ValueError(f"{task_id}: no ingestion record matches this result document")
    if ingestion.get("errors"):
        raise ValueError(f"{task_id}: cannot complete a result that failed ingestion")

    completed = json.loads(json.dumps(document))
    completed["result_transaction"]["parent_ingested_at"] = ingestion["ingested_at"]
    completed["obzio_state"] = "COMPLETED"
    completed["completion_actor"] = "coordinator"
    completed["independent_acceptance"] = {
        "state": "PENDING",
        "reviewer_id": reviewer_id,
        "receipt_uri": None,
    }
    validator = load_result_validator()
    errors = validator.validate_result(completed)
    if errors:
        raise ValueError(f"{task_id}: completion rejected by contract: {errors}")
    write_once(CONTROL_ROOT / "tasks" / task_id / "transaction-completed.json", canonical_json(completed))
    hash_chain_event(
        task_id,
        "COMPLETED",
        actor="integration-controller",
        details={"completion_actor": "coordinator"},
    )
    append_registry(
        {
            "registry_event": "COMPLETED",
            "task_id": task_id,
            "obzio_state": "COMPLETED",
            "completion_actor": "coordinator",
            "recorded_at": utc_now(),
        }
    )
    return completed


def dispose_unit(
    task_id: str,
    *,
    reviewer_id: str,
    decision: str,
    receipt_uri: str,
    criteria_sha256: str,
    reviewer_model: str,
    notes: str,
) -> dict[str, Any]:
    """Record an independent disposition by a reviewer who is not the producer.

    Acceptance is only meaningful when a different actor renders it against
    criteria frozen before the producer's conclusions were visible, so both the
    reviewer identity and the frozen criteria hash are required here.
    """
    if decision not in {"ACCEPTED", "REJECTED"}:
        raise ValueError(f"{task_id}: disposition must be ACCEPTED or REJECTED")
    if not SHA256_RE.fullmatch(criteria_sha256):
        raise ValueError(f"{task_id}: frozen criteria hash must be a lowercase SHA-256")

    completed_path = CONTROL_ROOT / "tasks" / task_id / "transaction-completed.json"
    if not completed_path.is_file():
        raise ValueError(f"{task_id}: cannot dispose before coordinator completion")
    completed = read_json(completed_path)
    producer = completed.get("attempt", {}).get("worker_id")
    if reviewer_id == producer:
        raise ValueError(f"{task_id}: producer {producer} cannot render its own disposition")

    disposed = json.loads(json.dumps(completed))
    disposed["independent_acceptance"] = {
        "state": decision,
        "reviewer_id": reviewer_id,
        "receipt_uri": receipt_uri,
    }
    validator = load_result_validator()
    errors = validator.validate_result(disposed)
    if errors:
        raise ValueError(f"{task_id}: disposition rejected by contract: {errors}")

    write_once(CONTROL_ROOT / "tasks" / task_id / "transaction-disposed.json", canonical_json(disposed))
    hash_chain_event(
        task_id,
        decision,
        actor=reviewer_id,
        details={
            "reviewer_model": reviewer_model,
            "producer_worker_id": producer,
            "frozen_criteria_sha256": criteria_sha256,
            "receipt_uri": receipt_uri,
            "notes": notes,
        },
    )
    append_registry(
        {
            "registry_event": "DISPOSITION",
            "task_id": task_id,
            "independent_disposition": decision,
            "reviewer_id": reviewer_id,
            "reviewer_model": reviewer_model,
            "producer_worker_id": producer,
            "frozen_criteria_sha256": criteria_sha256,
            "recorded_at": utc_now(),
        }
    )
    return disposed


def scan_recovery(run_id: str, head_sha: str) -> dict[str, Any]:
    """Reconcile every known unit against durable evidence and write recovery state."""
    tasks_root = CONTROL_ROOT / "tasks"
    units: dict[str, Any] = {}
    false_completion = 0
    orphans = 0
    for task_directory in sorted(p for p in tasks_root.glob("*") if p.is_dir()):
        task_id = task_directory.name
        events = sorted((CONTROL_ROOT / "events" / task_id).glob("*.json"))
        states = [read_json(path).get("state") for path in events]
        latest = states[-1] if states else None
        ingestions = sorted(task_directory.glob("ingestion-*.json"))
        verified = any(
            read_json(path).get("obzio_state") == "PARENT_INGESTED" for path in ingestions
        )
        completed = (task_directory / "transaction-completed.json").is_file()
        if completed and not verified:
            false_completion += 1
        action = "NONE"
        if not events:
            action = "REDISPATCH_FROM_IMMUTABLE_INPUT"
            orphans += 1
        elif completed:
            action = "NONE"
        elif verified:
            action = "AWAIT_COORDINATOR_COMPLETION"
        elif latest in {"CREATED"}:
            action = "DISPATCH"
        else:
            action = "RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT"
        units[task_id] = {
            "obzio_state": "COMPLETED" if completed else (latest or "UNKNOWN"),
            "latest_event_sequence": len(events),
            "fence_token": current_fence(task_id),
            "ingested": verified,
            "recovery_action": action,
        }
    state = {
        "recovery_version": "PO03-RECOVERY-STATE-v1",
        "controller_run_id": run_id,
        "controller_head_sha": head_sha,
        "scan_state": "ACTIVE",
        "scanned_at": utc_now(),
        "units": units,
        "unit_count": len(units),
        "false_completion_count": false_completion,
        "orphan_count": orphans,
        "duplicate_callback_count": 0,
        "collision_count": 0,
        "decision_changed": [],
    }
    replace_atomic(CONTROL_ROOT / "recovery-state.json", canonical_json(state))
    return state


def detect_path_collisions() -> list[str]:
    """Fail closed if two subordinates claim overlapping owned subtrees."""
    ownership = read_json(CONTROL_ROOT / "path-ownership.json")
    claims: list[tuple[str, str]] = []
    for subordinate in ownership.get("subordinates", []):
        for path in subordinate.get("owned_paths", []):
            claims.append((subordinate["task_id"], path.rstrip("*").rstrip("/")))
    collisions: list[str] = []
    for index, (task_a, path_a) in enumerate(claims):
        for task_b, path_b in claims[index + 1 :]:
            if task_a == task_b:
                continue
            if path_a == path_b or path_a.startswith(path_b + "/") or path_b.startswith(path_a + "/"):
                collisions.append(f"{task_a}:{path_a} overlaps {task_b}:{path_b}")
    return sorted(set(collisions))


def create_units(args: argparse.Namespace) -> int:
    spec = read_json(Path(args.spec))
    head_sha = git("rev-parse", "HEAD")
    created: list[dict[str, str]] = []
    ownership = read_json(CONTROL_ROOT / "path-ownership.json")
    existing = {entry["task_id"] for entry in ownership.get("subordinates", [])}
    for unit in spec["units"]:
        fence_token = allocate_fence()
        capsule = task_capsule(
            task_id=unit["task_id"],
            head_sha=head_sha,
            run_id=spec["run_id"],
            model=unit["model"],
            reasoning=unit["reasoning"],
            hypothesis=unit["hypothesis"],
            prompt=unit["prompt"],
            owned_paths=unit["owned_paths"],
            result_slot=unit["result_slot"],
            acceptance=unit["acceptance"],
            lease_seconds=unit.get("lease_seconds", 10800),
            fence_token=fence_token,
            function=unit["function"],
        )
        capsule["function"] = unit["function"]
        capsule["exact_model"] = unit["model"]
        capsule["fence_token"] = str(fence_token)
        created.append(capsule)
        append_registry(
            {
                "registry_event": "CREATED",
                "wave": spec.get("wave", "A"),
                "task_id": unit["task_id"],
                "function": unit["function"],
                "exact_model": unit["model"],
                "fence_token": fence_token,
                "input_sha256": capsule["input_sha256"],
                "acceptance_sha256": capsule["acceptance_sha256"],
                "owned_paths": unit["owned_paths"],
                "result_slot": unit["result_slot"],
                "recorded_at": utc_now(),
            }
        )
        if unit["task_id"] not in existing:
            ownership["subordinates"].append(
                {
                    "task_id": unit["task_id"],
                    "provider_run_id": "PENDING_PROVIDER_ASSIGNMENT",
                    "owned_paths": unit["owned_paths"],
                    "fence_token": fence_token,
                }
            )
    ownership["controller"]["run_id"] = spec["run_id"]
    replace_atomic(CONTROL_ROOT / "path-ownership.json", canonical_json(ownership))
    collisions = detect_path_collisions()
    if collisions:
        raise ValueError(f"path collision detected: {collisions}")
    print(json.dumps({"created": len(created), "units": created, "collisions": []}, indent=2, sort_keys=True))
    return 0


def ingest(args: argparse.Namespace) -> int:
    document = read_json(Path(args.result))
    ingestion = ingest_result(args.task_id, document)
    print(json.dumps(ingestion, indent=2, sort_keys=True))
    return 0 if not ingestion["errors"] else 1


def complete(args: argparse.Namespace) -> int:
    document = read_json(Path(args.result))
    completed = complete_unit(args.task_id, document, reviewer_id=args.reviewer_id)
    print(json.dumps({"task_id": args.task_id, "obzio_state": completed["obzio_state"]}, indent=2))
    return 0


def dispose(args: argparse.Namespace) -> int:
    disposed = dispose_unit(
        args.task_id,
        reviewer_id=args.reviewer_id,
        decision=args.decision,
        receipt_uri=args.receipt_uri,
        criteria_sha256=args.criteria_sha256,
        reviewer_model=args.reviewer_model,
        notes=args.notes,
    )
    print(
        json.dumps(
            {
                "task_id": args.task_id,
                "independent_acceptance": disposed["independent_acceptance"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def recover(args: argparse.Namespace) -> int:
    state = scan_recovery(args.run_id, git("rev-parse", "HEAD"))
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


def collisions(args: argparse.Namespace) -> int:
    found = detect_path_collisions()
    for item in found:
        print(f"PO03_PATH_COLLISION: {item}")
    if not found:
        print("PO03_PATH_COLLISION_PASS")
    return 1 if found else 0


def claim(args: argparse.Namespace) -> int:
    outcome = claim_wave(Path(args.spec), args.run_id)
    if args.out:
        write_once(Path(args.out), canonical_json(outcome))
    print(json.dumps(outcome, indent=2, sort_keys=True))
    return 0 if outcome["exclusive_ownership_complete"] else 1


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

    create_parser = subparsers.add_parser("create-units")
    create_parser.add_argument("spec")
    create_parser.set_defaults(handler=create_units)

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("task_id")
    ingest_parser.add_argument("result")
    ingest_parser.set_defaults(handler=ingest)

    complete_parser = subparsers.add_parser("complete")
    complete_parser.add_argument("task_id")
    complete_parser.add_argument("result")
    complete_parser.add_argument("--reviewer-id", default=None)
    complete_parser.set_defaults(handler=complete)

    dispose_parser = subparsers.add_parser("dispose")
    dispose_parser.add_argument("task_id")
    dispose_parser.add_argument("--reviewer-id", required=True)
    dispose_parser.add_argument("--decision", required=True, choices=("ACCEPTED", "REJECTED"))
    dispose_parser.add_argument("--receipt-uri", required=True)
    dispose_parser.add_argument("--criteria-sha256", required=True)
    dispose_parser.add_argument("--reviewer-model", required=True)
    dispose_parser.add_argument("--notes", default="")
    dispose_parser.set_defaults(handler=dispose)

    recover_parser = subparsers.add_parser("recover")
    recover_parser.add_argument("--run-id", required=True)
    recover_parser.set_defaults(handler=recover)

    collision_parser = subparsers.add_parser("collisions")
    collision_parser.set_defaults(handler=collisions)

    claim_parser = subparsers.add_parser("claim-wave")
    claim_parser.add_argument("spec")
    claim_parser.add_argument("--run-id", required=True)
    claim_parser.add_argument("--out", default=None)
    claim_parser.set_defaults(handler=claim)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return args.handler(args)
    except (OSError, ValueError, FileExistsError, StaleFenceError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
