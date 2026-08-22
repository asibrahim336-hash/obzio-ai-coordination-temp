#!/usr/bin/env python3
"""Create Wave A's 64 immutable task capsules without dispatching workers."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
factory = _load_module("po03_transactional_factory", HERE / "transactional_factory.py")
catalog = _load_module("po03_wave_a_catalog", HERE / "seed_wave_a.py")

WAVE_ID = "PO03-WAVE-A-20260822"


def _write_once(path: Path, document: dict[str, Any]) -> None:
    factory.write_once(path, factory.canonical_json(document))


def _registry_task_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict) and isinstance(row.get("task_id"), str):
            ids.add(row["task_id"])
    return ids


def _merge_ownership(run_id: str, task_rows: list[dict[str, Any]]) -> None:
    path = factory.CONTROL_ROOT / "path-ownership.json"
    ownership = factory.read_json(path) if path.exists() else {
        "ownership_version": "PO03-PATH-OWNERSHIP-v1",
        "controller": {"run_id": run_id, "owned_paths": ["workstreams/po03/control/**"]},
        "subordinates": [],
        "collision_policy": "FAIL_CLOSED",
        "decision_changed": [],
    }
    known = {entry["task_id"] for entry in ownership.get("subordinates", []) if "task_id" in entry}
    for row in task_rows:
        if row["task_id"] not in known:
            ownership.setdefault("subordinates", []).append(
                {
                    "task_id": row["task_id"],
                    "provider_run_id": "PENDING_PROVIDER_ASSIGNMENT",
                    "owned_paths": [row["result_slot"] + "/**"],
                    "fence_token": 1,
                }
            )
    factory.replace_atomic(path, factory.canonical_json(ownership))


def _merge_recovery(_head_sha: str, run_id: str, _task_rows: list[dict[str, Any]]) -> None:
    """Refresh every task projection from its immutable event chain."""
    factory.rebuild_recovery_state(run_id=run_id)


def register(repo_root: Path, *, head_sha: str, run_id: str) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if len(catalog.TASKS) != 64 or len({task["id"] for task in catalog.TASKS}) != 64:
        raise factory.FactoryError("Wave A catalog must contain exactly 64 unique work units")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip() != head_sha:
        raise factory.FactoryError("head changed before task registration")

    factory.REPO_ROOT = repo_root
    factory.PO03_ROOT = repo_root / "workstreams" / "po03"
    factory.CONTROL_ROOT = factory.PO03_ROOT / "control"
    factory.RECEIPT_ROOT = repo_root / "receipts" / "po03" / "2026-08-22"

    _write_once(
        factory.PO03_ROOT / "evidence" / "scale-ladder.json",
        {
            "schema_version": "PO03-SCALE-LADDER-v1",
            "wave_a": {
                "required_substantive_attempts": 64,
                "registered_attempts": 64,
                "state": "REGISTERED_AWAITING_CANARY",
            },
            "wave_b": {"required_substantive_attempts": 128, "state": "NOT_YET"},
            "decision_changed": [],
        },
    )
    _write_once(
        factory.PO03_ROOT / "evidence" / "recovery-fault-matrix.json",
        {
            "schema_version": "PO03-RECOVERY-FAULT-MATRIX-v1",
            "required_faults": [
                "process_or_session_loss",
                "lost_return_message",
                "partial_write",
                "pre_commit_failure",
                "post_commit_failure",
                "pre_push_failure",
                "post_push_failure",
                "stale_lease",
                "duplicate_callback",
                "corrupt_or_missing_artifact",
                "network_interruption",
                "parent_restart",
                "provider_runtime_loss",
            ],
            "state": "REGISTERED_FOR_EXECUTION",
            "decision_changed": [],
        },
    )
    _write_once(
        factory.PO03_ROOT / "evidence" / "model-allocation-and-exceptions.json",
        {
            "schema_version": "PO03-MODEL-ALLOCATION-v1",
            "wave_id": WAVE_ID,
            "allocation": [
                {
                    "task_id": task["id"],
                    "model": catalog._model_for(index)[0],
                    "reasoning": catalog._model_for(index)[1],
                }
                for index, task in enumerate(catalog.TASKS, start=1)
            ],
            "exceptions": [
                {
                    "family": "gemini-3.1-pro",
                    "state": "NOT_SUPPORTED",
                    "evidence": "not exposed by the current native subordinate selector",
                },
                {
                    "family": "composer-2.5",
                    "state": "NOT_SUPPORTED",
                    "evidence": "not exposed by the current native subordinate selector",
                },
            ],
            "decision_changed": [],
        },
    )
    _write_once(
        factory.CONTROL_ROOT / "runtime-observations" / f"{run_id}.json",
        {
            "schema_version": "PO03-RUNTIME-OBSERVATION-v1",
            "controller_run_id": run_id,
            "controller_model": "gpt-5.6-terra-max-fast",
            "subordinate_models": [
                "claude-opus-5-thinking-high",
                "gpt-5.6-sol-xhigh",
            ],
            "unavailable_families": ["gemini-3.1-pro", "composer-2.5"],
            "decision_changed": [],
        },
    )

    registry = factory.CONTROL_ROOT / "work-unit-registry.jsonl"
    registered = _registry_task_ids(registry)
    rows: list[dict[str, Any]] = []
    hypotheses: list[dict[str, Any]] = []
    for index, task in enumerate(catalog.TASKS, start=1):
        task_id = task["id"]
        model, reasoning = catalog._model_for(index)
        result_slot = f"workstreams/po03/attempts/wave-a/{task_id}"
        acceptance = {
            "acceptance_version": "PO03-WAVE-A-ACCEPTANCE-v1",
            "task_id": task_id,
            "criteria": [
                "distinct falsifiable hypothesis",
                "owned-path-only durable artifacts",
                "manifested SHA-256 values and byte counts",
                "reproducible test or controlled reproduction output",
                "explicit limitations and negative outcomes",
                "READY_TO_COMMIT only after commit, push, and immutable read-back",
            ],
            "forbidden": [
                "out-of-allowlist writes",
                "PO-01 contact or mutation",
                "PR #8 modification",
                "Obzio completion or self-acceptance",
                "external outreach, spend, secret, permission, protected, or strategy-binding action",
            ],
            "decision_changed": [],
        }
        if task_id not in registered:
            row = factory.task_capsule(
                task_id=task_id,
                head_sha=head_sha,
                run_id=run_id,
                model=model,
                reasoning=reasoning,
                hypothesis=task["hypothesis"],
                prompt=task["request"],
                owned_paths=[result_slot + "/**"],
                result_slot=result_slot,
                acceptance=acceptance,
                lease_seconds=1800,
                fence_token=1,
                function=task["function"],
            )
            factory.append_jsonl(
                registry,
                {
                    "registry_event_version": "PO03-REGISTRY-CREATED-v1",
                    "wave_id": WAVE_ID,
                    "function": task["function"],
                    "model": model,
                    "reasoning": reasoning,
                    **row,
                },
            )
            registered.add(task_id)
        else:
            task_directory = factory.CONTROL_ROOT / "tasks" / task_id
            row = {
                "task_id": task_id,
                "result_slot": result_slot,
                "input_path": factory.repo_relative(task_directory / "input.json"),
                "input_sha256": factory.sha256_file(task_directory / "input.json"),
                "acceptance_path": factory.repo_relative(task_directory / "acceptance.json"),
                "acceptance_sha256": factory.sha256_file(task_directory / "acceptance.json"),
            }
        rows.append(row)
        hypotheses.append(
            {
                "hypothesis_id": task_id,
                "wave_id": WAVE_ID,
                "function": task["function"],
                "claim": task["hypothesis"],
                "state": "FROZEN_FOR_EXECUTION",
                "input_sha256": row["input_sha256"],
                "decision_changed": [],
            }
        )

    _merge_ownership(run_id, rows)
    _merge_recovery(head_sha, run_id, rows)
    hypotheses_path = factory.PO03_ROOT / "research" / "hypotheses.jsonl"
    if not hypotheses_path.exists():
        factory.write_once(
            hypotheses_path,
            b"".join(factory.canonical_json(hypothesis) for hypothesis in hypotheses),
        )
    _write_once(
        factory.RECEIPT_ROOT / "wave-a-registration.json",
        {
            "receipt_version": "PO03-WAVE-A-REGISTRATION-v1",
            "commission_id": factory.COMMISSION_ID,
            "wave_id": WAVE_ID,
            "registration_head_sha": head_sha,
            "controller_run_id": run_id,
            "registered_count": len(rows),
            "dispatch_state": "AWAITING_INDEPENDENT_CANARY_READBACK",
            "decision_changed": [],
        },
    )
    return {"wave_id": WAVE_ID, "registered_count": len(rows)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--head-sha")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    head_sha = args.head_sha or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
    ).strip()
    try:
        result = register(repo_root, head_sha=head_sha, run_id=args.run_id)
    except (factory.FactoryError, OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}")
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
