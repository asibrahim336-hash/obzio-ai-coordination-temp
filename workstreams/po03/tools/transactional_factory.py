#!/usr/bin/env python3
"""PO-03 transactional work-unit custody and Wave A activation.

The module is dependency-free so the same controls run in a clean clone.  It
creates immutable task/acceptance capsules, an append-only event ledger,
exclusive path ownership, canary challenges, and deterministic result slots
before any material work is delegated.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COMMISSION_ID = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
PROTOCOL_VERSION = "OBZIO-TRANSACTIONAL-RESULT-v1"
WAVE_ID = "PO03-WAVE-A-20260822"
ALLOWED_PREFIXES = (
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

ROUTES = (
    ("route-01", "claude-opus-5-thinking-high", "transactional-custody"),
    ("route-02", "gpt-5.6-sol-xhigh", "source-compilation"),
    ("route-03", "claude-opus-5-thinking-high", "portable-runtime"),
    ("route-04", "gpt-5.6-sol-xhigh", "pack-qualification"),
    ("route-05", "claude-opus-5-thinking-high", "provenance-and-paths"),
    ("route-06", "gpt-5.6-sol-xhigh", "research-reproduction"),
    ("route-07", "claude-opus-5-thinking-high", "evaluation-and-semantics"),
    ("route-08", "gpt-5.6-sol-xhigh", "successor-and-measurement"),
)

# Each entry is a distinct falsifiable attempt, not a request for a report.
WORK_UNITS = (
    ("transactional-custody", "State transitions reject skipped or reversed custody states."),
    ("transactional-custody", "A stale fence token cannot stage or commit a result."),
    ("transactional-custody", "Duplicate callbacks are idempotent and create one result transaction."),
    ("transactional-custody", "A lost callback is recovered from the durable outbox."),
    ("transactional-custody", "A partial artifact write cannot reach RESULT_STAGED."),
    ("transactional-custody", "Post-commit process loss is recovered without rerunning external effects."),
    ("transactional-custody", "Provider completion without a durable commit is reclassified automatically."),
    ("transactional-custody", "A recovery scan deterministically resumes every nonterminal task."),
    ("source-compilation", "A compiler resolves the one current source from pointer and disposition evidence."),
    ("source-compilation", "Hash mismatch in a selected current source fails closed."),
    ("source-compilation", "A superseded filename cannot become active through naming similarity."),
    ("source-compilation", "Pointer cycles are detected with a machine-readable failure trace."),
    ("source-compilation", "Missing selected source bytes are distinguished from superseded evidence."),
    ("source-compilation", "Chronology and standing conflicts produce deterministic precedence."),
    ("source-compilation", "Compiled source capsules contain only measured admitted context."),
    ("source-compilation", "A clean clone reproduces identical current-source compilation hashes."),
    ("portable-runtime", "The PO-03 suite runs from a clean clone without /tmp state."),
    ("portable-runtime", "The runtime rejects dependencies on uncommitted files."),
    ("portable-runtime", "Absolute workstation paths are detected before execution."),
    ("portable-runtime", "A declared runtime manifest is sufficient to invoke every PO-03 tool."),
    ("portable-runtime", "Missing optional provider metadata produces NOT_SUPPORTED rather than fabrication."),
    ("portable-runtime", "Locale and timezone variation do not alter canonical result hashes."),
    ("portable-runtime", "Interrupted execution resumes from a monotonic checkpoint in a fresh process."),
    ("portable-runtime", "GitHub Actions and local isolated execution produce equivalent dispositions."),
    ("pack-qualification", "Qualification fails when a claimed pack file is absent at its pinned commit."),
    ("pack-qualification", "Qualification detects manifest omissions and undeclared pack files."),
    ("pack-qualification", "Qualification rejects traversal and repository-escape paths."),
    ("pack-qualification", "Qualification detects process-boundary reliance on producer memory."),
    ("pack-qualification", "PO-01 claims are reproduced from immutable commits without branch mutation."),
    ("pack-qualification", "Producer narrative cannot satisfy an executable qualification assertion."),
    ("pack-qualification", "A sanitized fixture reproduces the lost PO-02 Code-2 custody defect."),
    ("pack-qualification", "Independent qualification emits a portable evidence bundle and exact hashes."),
    ("provenance-and-paths", "A changed-path guard rejects one deliberate out-of-allowlist mutation."),
    ("provenance-and-paths", "Symlink indirection cannot bypass the PO-03 write allowlist."),
    ("provenance-and-paths", "Renames are checked on both source and destination paths."),
    ("provenance-and-paths", "Every manifested artifact hash and byte count is independently reconciled."),
    ("provenance-and-paths", "Repository disposition detects transport debris without deleting evidence."),
    ("provenance-and-paths", "Generated artifacts retain source, tool, configuration, and parent lineage."),
    ("provenance-and-paths", "Concurrent writers with disjoint ownership cannot collide silently."),
    ("provenance-and-paths", "A shared-path write without controller identity fails before commit."),
    ("research-reproduction", "Content-addressed task capsules reduce callback-loss ambiguity on an Obzio fixture."),
    ("research-reproduction", "Transactional outbox replay recovers a lost-return Obzio fixture."),
    ("research-reproduction", "Lease fencing prevents a delayed worker from overwriting transferred ownership."),
    ("research-reproduction", "Hermetic test execution exposes hidden-state dependence in a sanitized pack."),
    ("research-reproduction", "Property-generated transition sequences find an invariant breach or pass a frozen bound."),
    ("research-reproduction", "Mutation testing demonstrates whether custody tests detect false completion."),
    ("research-reproduction", "Metamorphic path variants expose portability defects missed by example tests."),
    ("research-reproduction", "Differential local/clean-clone execution reveals environment-coupled behavior."),
    ("evaluation-and-semantics", "Frozen evaluators distinguish provider, Obzio, and acceptance completion."),
    ("evaluation-and-semantics", "A producer cannot self-accept through identity aliasing."),
    ("evaluation-and-semantics", "Hidden cases cover every legal state transition and every prohibited skip."),
    ("evaluation-and-semantics", "Ontology checks separate function, appointment, runtime, and provider identity."),
    ("evaluation-and-semantics", "Unknown metric values remain NOT_SUPPORTED through aggregation."),
    ("evaluation-and-semantics", "Blind review ordering prevents producer conclusions from changing criteria."),
    ("evaluation-and-semantics", "Three independent candidates are rankable by a frozen executable rubric."),
    ("evaluation-and-semantics", "Adversarial corrupt manifests never produce a false PASS."),
    ("successor-and-measurement", "Every counted unit has one immutable result locator and terminal disposition."),
    ("successor-and-measurement", "G0 is executable from immutable pre-amendment source rather than narrative."),
    ("successor-and-measurement", "G1 measures recovery and coordination overhead without invented values."),
    ("successor-and-measurement", "Three accepted G1 lessons compile into executable G2 route changes."),
    ("successor-and-measurement", "Evaluator-held novel cases prevent successor overfit to the public suite."),
    ("successor-and-measurement", "Generation comparison refuses lift when critical correctness regresses."),
    ("successor-and-measurement", "Per-model disagreement and accepted contribution are traceable per unit."),
    ("successor-and-measurement", "The successor reproduces from a fresh checkout with zero founder relay."),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n")


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab", buffering=0) as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.write(canonical_bytes(value))
        os.fsync(stream.fileno())
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def git(repo: Path, *arguments: str) -> str:
    return subprocess.check_output(("git", *arguments), cwd=repo, text=True).strip()


def relative(repo: Path, path: Path) -> str:
    return path.relative_to(repo).as_posix()


def source_record(repo: Path, source: str) -> dict[str, Any]:
    path = repo / source
    return {
        "path": source,
        "git_blob_sha": git(repo, "hash-object", source),
        "sha256": digest_file(path),
        "bytes": path.stat().st_size,
    }


def acceptance_for(task_id: str, function: str, hypothesis: str) -> dict[str, Any]:
    return {
        "contract_version": "PO03-WAVE-A-ACCEPTANCE-v1",
        "task_id": task_id,
        "function": function,
        "frozen_hypothesis": hypothesis,
        "required": [
            "an executable component, reproduction, adversarial case, or acceptance decision",
            "commands and observed results",
            "complete artifact manifest with SHA-256 and byte counts",
            "limitations and explicit PASS, FAIL, NOT_YET, NOT_SUPPORTED, or OWNER_BLOCKED disposition",
            "no writes outside the assigned owned subtree",
            "subordinate terminal report is READY_TO_COMMIT, never COMPLETED or ACCEPTED",
        ],
        "prohibited": [
            "plan-only or inventory-only return",
            "producer self-acceptance",
            "unhashed artifacts",
            "PO-01 mutation or contact",
            "protected action, merge, promotion, or PR #8 mutation",
        ],
        "decision_changed": [],
    }


def activate(repo: Path, controller_run_id: str, parent_head: str, branch: str) -> None:
    po03 = repo / "workstreams/po03"
    control = po03 / "control"
    activation_path = control / "protocol-activation.json"
    if activation_path.exists():
        existing = json.loads(activation_path.read_text())
        if existing.get("controller_run_id") != controller_run_id:
            raise RuntimeError("protocol already activated by a different controller")
        print(f"ALREADY_ACTIVE sha256={digest_file(activation_path)}")
        return

    observed_head = git(repo, "rev-parse", "HEAD")
    if observed_head != parent_head:
        raise RuntimeError(f"immutable head mismatch: expected {parent_head}, observed {observed_head}")
    if git(repo, "status", "--porcelain"):
        # This script itself is expected to be the sole uncommitted activation change.
        changed = git(repo, "status", "--porcelain").splitlines()
        expected_suffix = "workstreams/po03/tools/transactional_factory.py"
        if any(not line.endswith(expected_suffix) for line in changed):
            raise RuntimeError(f"unexpected pre-activation changes: {changed}")

    source_paths = (
        "workstreams/po03/COMMISSION.md",
        "workstreams/po03/LAUNCH-NOW.md",
        "workstreams/po03/contracts/transactional-result.schema.json",
        "workstreams/po03/contracts/wave-compounding.schema.json",
        "workstreams/po03/tools/validate_contracts.py",
        "workstreams/po03/tests/test_validate_contracts.py",
        ".github/workflows/po03-contracts.yml",
        "workstreams/po03/evidence/so02-operating-correction.json",
        "receipts/po03/2026-08-22/appointment-seed.json",
    )
    source_lock = {
        "lock_id": "PO03-SOURCE-LOCK-WAVE-A-v1",
        "commission_id": COMMISSION_ID,
        "immutable_parent_head": parent_head,
        "parent_tree": git(repo, "rev-parse", f"{parent_head}^{{tree}}"),
        "branch_at_activation": branch,
        "sources": [source_record(repo, path) for path in source_paths],
        "producer_narratives_admitted": [],
        "decision_changed": [],
    }
    source_lock_path = po03 / "evidence/source-lock.json"
    write_json(source_lock_path, source_lock)
    source_lock_sha = digest_file(source_lock_path)

    criteria = {
        "criteria_id": "PO03-WAVE-A-CRITERIA-FREEZE-v1",
        "frozen_before_material_delegation": True,
        "source_lock_sha256": source_lock_sha,
        "counted_unit_rule": "Distinct falsifiable hypothesis plus executable durable result and terminal disposition.",
        "hard_guardrails": {
            "out_of_allowlist_writes": 0,
            "po01_contact_or_mutation": 0,
            "false_completion": 0,
            "critical_correctness_required_percent": 100,
            "founder_relay_required": 0,
        },
        "first_return_minimums": {
            "current_method_hypotheses": 12,
            "obzio_reproductions": 6,
            "independently_tested_changes_or_rejections": 2,
        },
        "allowed_dispositions": ["PASS", "FAIL", "NOT_YET", "NOT_SUPPORTED", "OWNER_BLOCKED"],
        "decision_changed": [],
    }
    criteria_path = po03 / "evidence/criteria-freeze.json"
    write_json(criteria_path, criteria)
    criteria_sha = digest_file(criteria_path)

    model_register = {
        "register_version": "PO03-MODEL-CAPABILITY-v1",
        "observed_at": utc_now(),
        "controller": {
            "run_id": controller_run_id,
            "exact_model": "gpt-5.6-sol-max-fast",
            "source": "cursor-cloud run-info",
        },
        "delegation_configurations_exposed": [
            {"model": "claude-opus-5-thinking-high", "family": "claude-opus-5", "use": "lead, challenger, engineering"},
            {"model": "gpt-5.6-sol-xhigh", "family": "gpt-5.6-sol", "use": "chief challenger, engineering, reproduction"},
        ],
        "required_family_observations": [
            {"family": "claude-opus-5", "state": "SUPPORTED", "evidence": "task model selector"},
            {"family": "gpt-5.6-sol", "state": "SUPPORTED", "evidence": "task model selector and controller run-info"},
            {"family": "gemini-3.1-pro", "state": "NOT_SUPPORTED", "evidence": "absent from task model selector"},
            {"family": "composer-2.5", "state": "NOT_SUPPORTED", "evidence": "absent from task model selector"},
        ],
        "active_environment_observation": {
            "running_top_level_agents": 8,
            "interpretation": "observed active population, not yet a proven provider ceiling",
        },
        "auto_model_selection_used": False,
        "decision_changed": [],
    }
    write_json(control / "model-capability-register.json", model_register)

    path_ownership: dict[str, Any] = {
        "version": "PO03-PATH-OWNERSHIP-v1",
        "controller_run_id": controller_run_id,
        "controller_shared_paths": [
            "workstreams/po03/control/**",
            "workstreams/po03/metrics/**",
            "workstreams/po03/evidence/**",
            "workstreams/po03/successor/**",
            "receipts/po03/**",
            ".github/workflows/po03-*.yml",
        ],
        "routes": [],
        "allowlist": list(ALLOWED_PREFIXES),
        "decision_changed": [],
    }
    for route_id, model, function in ROUTES:
        path_ownership["routes"].append(
            {
                "route_id": route_id,
                "model": model,
                "function": function,
                "owned_subtree": f"workstreams/po03/runs/wave-a/{route_id}/**",
                "canary_response": f"workstreams/po03/control/canaries/{route_id}/response.json",
                "shared_path_write": "PROHIBITED",
            }
        )
    write_json(control / "path-ownership.json", path_ownership)

    canary_status = {"version": "PO03-CANARY-STATUS-v1", "routes": [], "all_verified": False}
    for route_id, model, function in ROUTES:
        payload = f"{WAVE_ID}:{parent_head}:{route_id}:durable-readback"
        challenge = {
            "protocol_version": PROTOCOL_VERSION,
            "route_id": route_id,
            "model": model,
            "function": function,
            "payload": payload,
            "payload_sha256": digest_bytes(payload.encode()),
            "required_response_path": f"workstreams/po03/control/canaries/{route_id}/response.json",
            "required_worker_state": "CANARY_READY_TO_COMMIT",
            "material_work_authorized": False,
            "decision_changed": [],
        }
        challenge_path = control / f"canaries/{route_id}/challenge.json"
        write_json(challenge_path, challenge)
        canary_status["routes"].append(
            {
                "route_id": route_id,
                "challenge_sha256": digest_file(challenge_path),
                "state": "CHALLENGE_COMMITTED_PENDING_CHILD_READBACK",
                "worker_commit": None,
                "parent_readback_at": None,
            }
        )
    write_json(control / "canaries/status.json", canary_status)

    registry_path = control / "work-unit-registry.jsonl"
    task_index: list[dict[str, Any]] = []
    for index, (function, hypothesis) in enumerate(WORK_UNITS, start=1):
        route_index = (index - 1) // 8
        route_id, model, route_function = ROUTES[route_index]
        if function != route_function:
            raise AssertionError(f"unit {index} function does not match route")
        task_id = f"PO03-WA-{index:03d}"
        result_slot = f"workstreams/po03/runs/wave-a/{route_id}/{task_id}/"
        acceptance = acceptance_for(task_id, function, hypothesis)
        acceptance_bytes = canonical_bytes(acceptance)
        acceptance_path = control / f"tasks/{task_id}/acceptance.json"
        atomic_write(acceptance_path, acceptance_bytes)
        acceptance_sha = digest_file(acceptance_path)
        immutable_input = {
            "protocol_version": PROTOCOL_VERSION,
            "wave_id": WAVE_ID,
            "task_id": task_id,
            "parent_task_id": f"{WAVE_ID}:{route_id}",
            "commission_id": COMMISSION_ID,
            "function": function,
            "frozen_hypothesis": hypothesis,
            "source_lock_uri": relative(repo, source_lock_path),
            "immutable_input_manifest_sha256": source_lock_sha,
            "acceptance_contract_uri": relative(repo, acceptance_path),
            "acceptance_contract_sha256": acceptance_sha,
            "exact_model_configuration": model,
            "owned_paths": [f"{result_slot}**"],
            "result_slot": result_slot,
            "idempotency_key": f"{WAVE_ID}:{task_id}:attempt-1",
            "lease": {
                "lease_id": f"lease-{task_id}-1",
                "fence_token": 1,
                "duration_seconds": 3600,
                "state": "NOT_GRANTED_CANARY_PENDING",
            },
            "attempt": 1,
            "initial_obzio_state": "CREATED",
            "subordinate_terminal_state": "READY_TO_COMMIT",
            "decision_changed": [],
        }
        input_path = control / f"tasks/{task_id}/input.json"
        write_json(input_path, immutable_input)
        input_sha = digest_file(input_path)
        record = {
            "task_id": task_id,
            "route_id": route_id,
            "function": function,
            "hypothesis": hypothesis,
            "model": model,
            "input_uri": relative(repo, input_path),
            "input_sha256": input_sha,
            "acceptance_uri": relative(repo, acceptance_path),
            "acceptance_sha256": acceptance_sha,
            "owned_path": result_slot,
            "idempotency_key": immutable_input["idempotency_key"],
            "lease_id": immutable_input["lease"]["lease_id"],
            "fence_token": 1,
            "obzio_state": "CREATED",
            "provider_state": "NOT_DISPATCHED",
            "result_commit_id": None,
            "parent_ingested_at": None,
            "independent_disposition": "NOT_TESTED",
        }
        append_jsonl(registry_path, record)
        task_index.append(record)

    recovery = {
        "version": "PO03-RECOVERY-STATE-v1",
        "wave_id": WAVE_ID,
        "controller_run_id": controller_run_id,
        "last_event_seq": 1,
        "counts": {"CREATED": 64},
        "recoverable_tasks": [record["task_id"] for record in task_index],
        "orphan_count": 0,
        "duplicate_count": 0,
        "collision_count": 0,
        "false_complete_count": 0,
        "lost_po02_code2_fixture": {
            "provider_state": "COMPLETED",
            "obzio_state": "PROVIDER_COMPLETED_UNCOMMITTED",
            "recovery": "UNRECOVERED_AFTER_FOUR_REPORTED_ROUTES",
            "acceptance": "NOT_ACCEPTED",
        },
    }
    write_json(control / "recovery-state.json", recovery)

    metric_definitions = {
        "version": "PO03-METRICS-v1",
        "one_row_per_counted_unit": True,
        "unknown_value": "NOT_SUPPORTED",
        "fields": [
            "task_id", "parent_task_id", "function", "runtime", "exact_model", "reasoning",
            "prompt_sha256", "source_sha256", "context_sha256", "available_tokens", "cost",
            "queue_seconds", "active_seconds", "wall_seconds", "review_seconds", "tools", "effects",
            "checkpoints", "retries", "result_commit_id", "readback", "first_pass_outcome",
            "independent_disposition", "defects", "rework", "founder_action", "provider_block",
            "collision_events", "recovery_events",
        ],
        "aggregate_metrics": [
            "independently_accepted_throughput", "first_pass_acceptance", "false_green_rate",
            "cycle_time", "recovery_time", "coordination_overhead", "founder_interventions",
            "context_waste", "orphan_count", "duplicate_count", "collision_count",
            "false_complete_count", "research_to_reproduction_conversion",
            "lesson_to_live_change_conversion", "per_model_contribution", "successor_lift",
        ],
    }
    write_json(po03 / "metrics/metric-definitions.json", metric_definitions)
    atomic_write(po03 / "metrics/work-unit-runs.jsonl", b"")

    activation = {
        "protocol_version": "PO03-TRANSACTIONAL-FACTORY-ACTIVATION-v1",
        "commission_id": COMMISSION_ID,
        "wave_id": WAVE_ID,
        "controller_run_id": controller_run_id,
        "immutable_parent_head": parent_head,
        "activation_branch": branch,
        "activated_at": utc_now(),
        "source_lock_sha256": source_lock_sha,
        "criteria_freeze_sha256": criteria_sha,
        "work_units_created": 64,
        "routes_created": 8,
        "material_dispatch_state": "BLOCKED_PENDING_CHILD_CANARY_READBACK",
        "append_only_ledger": "workstreams/po03/control/events/events.jsonl",
        "transactional_outbox": "workstreams/po03/control/outbox.jsonl",
        "recovery_scanner": "workstreams/po03/tools/transactional_factory.py scan",
        "decision_changed": [],
    }
    write_json(activation_path, activation)
    append_jsonl(
        control / "events/events.jsonl",
        {
            "event_seq": 1,
            "event_id": f"{WAVE_ID}:ACTIVATED",
            "at": activation["activated_at"],
            "actor": controller_run_id,
            "state": "CREATED",
            "action": "PROTOCOL_ACTIVATED",
            "task_count": 64,
            "source_lock_sha256": source_lock_sha,
            "criteria_freeze_sha256": criteria_sha,
        },
    )
    atomic_write(control / "outbox.jsonl", b"")

    receipt = {
        "receipt_id": "RCP-PO03-AMENDMENT-ACTIVATION-20260822-v1",
        "commission_id": COMMISSION_ID,
        "controller_run_id": controller_run_id,
        "immutable_parent_head": parent_head,
        "branch": branch,
        "protocol_state": "ACTIVE_CANARY_PENDING",
        "work_units_created": 64,
        "route_count": 8,
        "source_lock_sha256": source_lock_sha,
        "criteria_freeze_sha256": criteria_sha,
        "provider_active_population_observed": 8,
        "provider_safe_ceiling": "NOT_YET_PROVEN",
        "po01_non_interference": True,
        "pr8_mutated": False,
        "merge_or_promotion": False,
        "decision_changed": [],
    }
    write_json(repo / "receipts/po03/2026-08-22/amendment-activation.json", receipt)
    print(f"ACTIVATED units=64 routes=8 source_lock_sha256={source_lock_sha}")


def scan(repo: Path) -> int:
    registry_path = repo / "workstreams/po03/control/work-unit-registry.jsonl"
    records = [json.loads(line) for line in registry_path.read_text().splitlines() if line]
    false_completed = [
        record["task_id"]
        for record in records
        if record["obzio_state"] == "COMPLETED" and not record.get("result_commit_id")
    ]
    duplicate_ids = sorted(
        task_id
        for task_id in {record["task_id"] for record in records}
        if sum(record["task_id"] == task_id for record in records) > 1
    )
    result = {
        "scanned_at": utc_now(),
        "records": len(records),
        "false_completed": false_completed,
        "duplicate_task_ids": duplicate_ids,
        "state": "PASS" if not false_completed and not duplicate_ids else "FAIL",
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["state"] == "PASS" else 1


def verify_canary(repo: Path, route_id: str, response: Path) -> int:
    challenge_path = repo / f"workstreams/po03/control/canaries/{route_id}/challenge.json"
    challenge = json.loads(challenge_path.read_text())
    value = json.loads(response.read_text())
    errors = []
    if value.get("route_id") != route_id:
        errors.append("route_id")
    if value.get("challenge_sha256") != digest_file(challenge_path):
        errors.append("challenge_sha256")
    if value.get("observed_payload") != challenge["payload"]:
        errors.append("observed_payload")
    if value.get("observed_payload_sha256") != challenge["payload_sha256"]:
        errors.append("observed_payload_sha256")
    if value.get("state") != "CANARY_READY_TO_COMMIT":
        errors.append("state")
    if errors:
        print(f"CANARY_INVALID route={route_id} fields={','.join(errors)}")
        return 1
    print(f"CANARY_VALID route={route_id} response_sha256={digest_file(response)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    activation = commands.add_parser("activate")
    activation.add_argument("--controller-run-id", required=True)
    activation.add_argument("--parent-head", required=True)
    activation.add_argument("--branch", required=True)
    commands.add_parser("scan")
    canary = commands.add_parser("verify-canary")
    canary.add_argument("--route-id", required=True)
    canary.add_argument("--response", type=Path, required=True)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    if args.command == "activate":
        activate(repo, args.controller_run_id, args.parent_head, args.branch)
        return 0
    if args.command == "scan":
        return scan(repo)
    if args.command == "verify-canary":
        return verify_canary(repo, args.route_id, args.response)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
