#!/usr/bin/env python3
"""Coordinator-only transition from PARENT_INGESTED to COMPLETED.

Independent acceptance remains PENDING and must be supplied by a different
producer.  This command cannot accept or reject a result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected object")
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


def complete(repo: Path, route_id: str, completed_at: str) -> int:
    ingestion_path = repo / f"workstreams/po03/control/results/{route_id}-ingestion.json"
    ingestion = read_json(ingestion_path)
    if ingestion.get("state") not in {
        "PARENT_INGESTED_PENDING_INDEPENDENT_ACCEPTANCE",
        "COMPLETED_PENDING_INDEPENDENT_ACCEPTANCE",
    }:
        raise ValueError(f"{route_id}: invalid ingestion state")

    registry_path = repo / "workstreams/po03/control/work-unit-registry.jsonl"
    registry = [json.loads(line) for line in registry_path.read_text().splitlines() if line]
    registry_by_id = {record["task_id"]: record for record in registry}
    if len(registry_by_id) != len(registry):
        raise ValueError("duplicate task ids in registry")

    completed_results: list[dict[str, Any]] = []
    for task in ingestion["task_results"]:
        task_id = task["task_id"]
        result_path = repo / task["receipt_uri"]
        result = read_json(result_path)
        old_sha = sha256(result_path)
        parent_ingested_sha = task["receipt_sha256"]
        if result.get("provider_state") != "COMPLETED":
            raise ValueError(f"{task_id}: provider result is not complete")
        if result.get("obzio_state") not in {"PARENT_INGESTED", "COMPLETED"}:
            raise ValueError(f"{task_id}: result is not parent-ingested")
        if result.get("result_transaction", {}).get("state") != "INGESTED":
            raise ValueError(f"{task_id}: transaction is not ingested")
        for field in ("result_commit_id", "committed_at", "verified_at", "parent_ingested_at"):
            if not result["result_transaction"].get(field):
                raise ValueError(f"{task_id}: transaction missing {field}")
        if any(not artifact.get("readback_verified_at") for artifact in result["artifacts"]):
            raise ValueError(f"{task_id}: artifact readback is incomplete")
        acceptance = result.get("independent_acceptance", {})
        if acceptance.get("state") != "PENDING":
            raise ValueError(f"{task_id}: acceptance must remain PENDING")
        if acceptance.get("reviewer_id") is not None or acceptance.get("receipt_uri") is not None:
            raise ValueError(f"{task_id}: premature reviewer or acceptance receipt")
        if result["obzio_state"] == "PARENT_INGESTED" and old_sha != parent_ingested_sha:
            raise ValueError(f"{task_id}: parent-ingested receipt hash mismatch")

        result["obzio_state"] = "COMPLETED"
        result["completion_actor"] = "coordinator"
        atomic_json(result_path, result)
        new_sha = sha256(result_path)
        registry_by_id[task_id].update(
            {
                "obzio_state": "COMPLETED",
                "completion_actor": "coordinator",
                "completed_at": completed_at,
                "independent_disposition": "PENDING",
            }
        )
        completed_results.append(
            {
                "task_id": task_id,
                "result_uri": task["receipt_uri"],
                "parent_ingested_receipt_sha256": parent_ingested_sha,
                "completed_receipt_sha256": new_sha,
                "result_commit_id": result["result_transaction"]["result_commit_id"],
            }
        )

    ingestion["state"] = "COMPLETED_PENDING_INDEPENDENT_ACCEPTANCE"
    ingestion["coordinator_completed_at"] = completed_at
    ingestion["coordinator_completion_actor"] = "coordinator"
    ingestion["coordinator_completion_receipt_uri"] = (
        f"workstreams/po03/control/completions/{route_id}.json"
    )
    atomic_json(ingestion_path, ingestion)
    registry_path.write_bytes(b"".join(canonical(record) for record in registry))

    receipt_path = repo / f"workstreams/po03/control/completions/{route_id}.json"
    atomic_json(
        receipt_path,
        {
            "completion_version": "PO03-COORDINATOR-COMPLETION-v1",
            "route_id": route_id,
            "completion_actor": "coordinator",
            "completed_at": completed_at,
            "task_results": completed_results,
            "independent_acceptance": "PENDING",
            "state": "COMPLETED_PENDING_INDEPENDENT_ACCEPTANCE",
            "decision_changed": [],
        },
    )
    print(f"COMPLETED route={route_id} tasks={len(completed_results)} acceptance=PENDING")
    return len(completed_results)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--route-id", action="append", required=True)
    parser.add_argument("--completed-at")
    args = parser.parse_args()
    completed_at = args.completed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    total = 0
    for route_id in args.route_id:
        total += complete(args.repo.resolve(), route_id, completed_at)
    print(f"COORDINATOR_COMPLETION_TOTAL tasks={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
