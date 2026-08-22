#!/usr/bin/env python3
"""Independently verify and ingest a staged PO-03 route result.

Producer artifacts remain byte-identical.  The controller writes separate
PARENT_INGESTED transaction receipts, updates the current work-unit registry,
and records one metrics row per counted unit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(("git", *args), cwd=repo, text=True).strip()


def verify_bytes(path: Path, expected_sha: str, expected_bytes: int) -> None:
    data = path.read_bytes()
    if len(data) != expected_bytes:
        raise ValueError(f"{path}: bytes {len(data)} != {expected_bytes}")
    observed = digest(data)
    if observed != expected_sha:
        raise ValueError(f"{path}: sha256 {observed} != {expected_sha}")


def committed_path_sha(repo: Path, commit: str, path: str) -> str:
    data = subprocess.check_output(("git", "show", f"{commit}:{path}"), cwd=repo)
    return digest(data)


def ingest(
    repo: Path,
    route_id: str,
    producer_branch: str,
    producer_tip: str,
    ingested_at: str,
) -> None:
    route = repo / f"workstreams/po03/runs/wave-a/{route_id}"
    nested_route_metadata = (route / "_route/route-manifest.json").exists()
    metadata_root = route / "_route" if nested_route_metadata else route
    route_manifest_path = metadata_root / "route-manifest.json"
    execution_receipt_path = metadata_root / "execution-receipt.json"
    route_manifest = read_json(route_manifest_path)
    execution = read_json(execution_receipt_path)

    if execution.get("route_id") != route_id:
        raise ValueError("execution receipt route mismatch")
    producer_state = (
        execution.get("states", {}).get("producer_terminal_report")
        if nested_route_metadata
        else execution.get("state")
    )
    staged_state = (
        execution.get("states", {}).get("obzio_state_per_task")
        if nested_route_metadata
        else execution.get("result_custody", {}).get("task_obzio_state")
    )
    acceptance_claimed = (
        execution.get("states", {}).get("independent_acceptance_claimed")
        if nested_route_metadata
        else execution.get("result_custody", {}).get("independent_acceptance_claimed")
    )
    if producer_state != "READY_TO_COMMIT":
        raise ValueError("producer did not return READY_TO_COMMIT")
    if staged_state != "RESULT_STAGED":
        raise ValueError("producer result is not staged")
    if acceptance_claimed:
        raise ValueError("producer claimed independent acceptance")
    if execution.get("decision_changed") != []:
        raise ValueError("decision_changed must remain []")
    if git(repo, "rev-parse", f"origin/{producer_branch}") != producer_tip:
        raise ValueError("producer remote tip mismatch")
    producer_base = execution.get("immutable_base_commit", execution.get("base_commit"))
    if not producer_base:
        raise ValueError("producer base commit missing")
    changed_paths = git(repo, "diff", "--name-only", f"{producer_base}..{producer_tip}").splitlines()
    owned_prefix = f"workstreams/po03/runs/wave-a/{route_id}/"
    outside = [path for path in changed_paths if not path.startswith(owned_prefix)]
    if outside:
        raise ValueError(f"producer wrote outside route ownership: {outside}")

    expected_route_sha = execution["route_manifest"]["sha256"]
    expected_route_bytes = execution["route_manifest"]["bytes"]
    verify_bytes(route_manifest_path, expected_route_sha, expected_route_bytes)
    if nested_route_metadata:
        tasks = route_manifest.get("tasks")
        if not isinstance(tasks, list) or route_manifest.get("task_count") != len(tasks):
            raise ValueError("route task count mismatch")
        artifacts = [
            {
                "path": item["repository_uri"],
                "sha256": item["sha256"],
                "bytes": item["bytes"],
            }
            for task in tasks
            for item in task["files"]
        ]
        expected_artifact_count = route_manifest.get("file_count")
    else:
        artifacts = route_manifest.get("artifacts")
        tasks = execution.get("tasks")
        expected_artifact_count = route_manifest.get("artifact_count")
    if not isinstance(artifacts, list) or expected_artifact_count != len(artifacts):
        raise ValueError("route artifact count mismatch")
    if not isinstance(tasks, list):
        raise ValueError("route task records missing")
    seen_paths: set[str] = set()
    for artifact in artifacts:
        path_text = artifact["path"]
        if path_text in seen_paths:
            raise ValueError(f"duplicate route artifact: {path_text}")
        seen_paths.add(path_text)
        if not path_text.startswith(f"workstreams/po03/runs/wave-a/{route_id}/"):
            raise ValueError(f"artifact outside route ownership: {path_text}")
        path = repo / path_text
        verify_bytes(path, artifact["sha256"], artifact["bytes"])
        if artifact.get("git_blob_sha") and git(repo, "hash-object", path_text) != artifact["git_blob_sha"]:
            raise ValueError(f"{path_text}: git blob mismatch")

    registry_path = repo / "workstreams/po03/control/work-unit-registry.jsonl"
    registry = [json.loads(line) for line in registry_path.read_text().splitlines() if line]
    registry_by_id = {record["task_id"]: record for record in registry}
    if len(registry_by_id) != len(registry):
        raise ValueError("work-unit registry contains duplicate task ids")

    metrics_path = repo / "workstreams/po03/metrics/work-unit-runs.jsonl"
    metrics = [json.loads(line) for line in metrics_path.read_text().splitlines() if line]
    metric_ids = {row["task_id"] for row in metrics}
    new_metrics: list[dict[str, Any]] = []
    generated: list[dict[str, Any]] = []
    route_function = execution.get("function", "research-reproduction")
    exact_model = execution["exact_model_configuration"]
    reasoning = "high" if exact_model.startswith("claude-") else "xhigh"
    route_collision_events = execution.get("collision_events", execution.get("execution_collision_events", []))
    route_recovery_events = execution.get("recovery_events", execution.get("execution_recovery_events", []))

    for task in tasks:
        task_id = task["task_id"]
        if task_id not in registry_by_id:
            raise ValueError(f"{task_id}: missing registry record")
        task_dir = route / task_id
        staged_path = task_dir / "result.json"
        staged = read_json(staged_path)
        if staged.get("task_id") != task_id or staged.get("obzio_state") != "RESULT_STAGED":
            raise ValueError(f"{task_id}: invalid staged result")
        if staged.get("independent_acceptance", {}).get("state") != "NOT_TESTED":
            raise ValueError(f"{task_id}: producer acceptance state is not NOT_TESTED")
        verify_bytes(staged_path, task["result_sha256"], task["result_bytes"])

        evidence_commit = task["result_commit_id"] if nested_route_metadata else task["evidence_commit"]
        git(repo, "cat-file", "-e", f"{evidence_commit}^{{commit}}")
        result_path_text = staged_path.relative_to(repo).as_posix()
        if committed_path_sha(repo, evidence_commit, result_path_text) != task["result_sha256"]:
            raise ValueError(f"{task_id}: evidence commit does not contain staged result")

        task_manifest_path = task_dir / ("manifest.json" if nested_route_metadata else "artifact-manifest.json")
        task_manifest = read_json(task_manifest_path)
        verify_bytes(
            task_manifest_path,
            task["manifest_sha256"] if nested_route_metadata else task["artifact_manifest_sha256"],
            task["manifest_bytes"] if nested_route_metadata else task["artifact_manifest_bytes"],
        )
        manifest_artifacts = task_manifest.get("artifacts")
        if not isinstance(manifest_artifacts, list):
            raise ValueError(f"{task_id}: artifact manifest has no artifacts")
        for item in manifest_artifacts:
            manifest_uri = item.get("repository_uri", item.get("content_uri"))
            if not manifest_uri:
                raise ValueError(f"{task_id}: artifact has no repository URI")
            verify_bytes(repo / manifest_uri, item["sha256"], item["bytes"])

        parent_artifacts = []
        for artifact in staged["artifacts"]:
            verify_bytes(repo / artifact["content_uri"], artifact["sha256"], artifact["bytes"])
            verified = dict(artifact)
            verified["readback_verified_at"] = ingested_at
            parent_artifacts.append(verified)

        committed_at = git(repo, "show", "-s", "--format=%cI", evidence_commit)
        parent_result = {
            **staged,
            "provider_state": "COMPLETED",
            "obzio_state": "PARENT_INGESTED",
            "artifacts": parent_artifacts,
            "result_transaction": {
                **staged["result_transaction"],
                "state": "INGESTED",
                "committed_at": committed_at,
                "verified_at": ingested_at,
                "parent_ingested_at": ingested_at,
                "result_commit_id": evidence_commit,
            },
            "independent_acceptance": {
                "state": "PENDING",
                "reviewer_id": None,
                "receipt_uri": None,
            },
        }
        output_path = repo / f"workstreams/po03/control/results/{task_id}.json"
        atomic_json(output_path, parent_result)
        generated.append(
            {
                "task_id": task_id,
                "receipt_uri": output_path.relative_to(repo).as_posix(),
                "receipt_sha256": digest(output_path.read_bytes()),
                "result_commit_id": evidence_commit,
            }
        )

        registry_record = registry_by_id[task_id]
        registry_record.update(
            {
                "obzio_state": "PARENT_INGESTED",
                "provider_state": "COMPLETED",
                "result_commit_id": evidence_commit,
                "parent_ingested_at": ingested_at,
                "independent_disposition": "PENDING",
            }
        )

        if task_id not in metric_ids:
            source_path = task_dir / ("manifest.json" if nested_route_metadata else "source.json")
            new_metrics.append(
                {
                    "task_id": task_id,
                    "parent_task_id": staged["attempt"]["attempt_id"],
                    "function": route_function,
                    "runtime": "Cursor Cloud",
                    "exact_model": exact_model,
                    "reasoning": reasoning,
                    "prompt_sha256": registry_record["input_sha256"],
                    "source_sha256": digest(source_path.read_bytes()),
                    "context_sha256": staged["immutable_input_manifest_sha256"],
                    "available_tokens": "NOT_SUPPORTED",
                    "cost": "NOT_SUPPORTED",
                    "queue_seconds": "NOT_SUPPORTED",
                    "active_seconds": "NOT_SUPPORTED",
                    "wall_seconds": "NOT_SUPPORTED",
                    "review_seconds": "NOT_SUPPORTED",
                    "tools": ["git", "python3", "standard-library"],
                    "effects": [],
                    "checkpoints": staged["attempt"]["checkpoint_seq"],
                    "retries": 0,
                    "result_commit_id": evidence_commit,
                    "readback": True,
                    "first_pass_outcome": task.get("mechanism_disposition", task.get("disposition")),
                    "independent_disposition": "PENDING",
                    "defects": [],
                    "rework": 0,
                    "founder_action": "NONE",
                    "provider_block": "NONE",
                    "collision_events": route_collision_events,
                    "recovery_events": route_recovery_events,
                }
            )

    atomic_json(
        repo / f"workstreams/po03/control/results/{route_id}-ingestion.json",
        {
            "ingestion_version": "PO03-ROUTE-INGESTION-v1",
            "route_id": route_id,
            "producer_branch": producer_branch,
            "producer_tip": producer_tip,
            "producer_base": producer_base,
            "producer_changed_path_count": len(changed_paths),
            "route_manifest_sha256": expected_route_sha,
            "execution_receipt_sha256": digest(execution_receipt_path.read_bytes()),
            "parent_readback_at": ingested_at,
            "artifact_readback_count": len(artifacts),
            "task_results": generated,
            "state": "PARENT_INGESTED_PENDING_INDEPENDENT_ACCEPTANCE",
            "decision_changed": [],
        },
    )
    registry_path.write_bytes(b"".join(canonical(record) for record in registry))
    if new_metrics:
        with metrics_path.open("ab") as stream:
            for row in new_metrics:
                stream.write(canonical(row))
            stream.flush()
            os.fsync(stream.fileno())
    print(
        f"INGESTED route={route_id} tasks={len(generated)} "
        f"artifacts={len(artifacts)} metrics={len(new_metrics)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--route-id", required=True)
    parser.add_argument("--producer-branch", required=True)
    parser.add_argument("--producer-tip", required=True)
    parser.add_argument("--ingested-at")
    args = parser.parse_args()
    ingested_at = args.ingested_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    ingest(
        args.repo.resolve(),
        args.route_id,
        args.producer_branch,
        args.producer_tip,
        ingested_at,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
