#!/usr/bin/env python3
"""Package one route-08 slot into a staged transactional result."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
from pathlib import Path


SOURCE_LOCK = "f66ba25343ceb8ce7810a7b241dd80b042b3b888ba498dcd61e48a29863c2f66"
COMMISSION = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(task_id: str, repo: Path, path: Path) -> dict:
    relative_repo = path.relative_to(repo).as_posix()
    slot = repo / f"workstreams/po03/runs/wave-a/route-08/{task_id}"
    logical = path.relative_to(slot).as_posix()
    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix == ".py":
        media = "text/x-python"
    return {
        "artifact_id": f"{task_id}:{logical}",
        "logical_name": logical,
        "content_uri": relative_repo,
        "sha256": digest(path),
        "bytes": path.stat().st_size,
        "media_type": media,
        "readback_verified_at": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--disposition", required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    slot = repo / f"workstreams/po03/runs/wave-a/route-08/{args.task_id}"
    acceptance = repo / f"workstreams/po03/control/tasks/{args.task_id}/acceptance.json"
    core = sorted(
        path
        for path in slot.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "result.json"}
        and "__pycache__" not in path.parts
    )
    entries = [artifact(args.task_id, repo, path) for path in core]
    manifest = {
        "manifest_version": "PO03-WA-ROUTE-08-ARTIFACT-MANIFEST-v1",
        "task_id": args.task_id,
        "artifacts": entries,
        "artifact_count": len(entries),
        "total_bytes": sum(row["bytes"] for row in entries),
        "acceptance_contract_sha256": digest(acceptance),
        "source_lock_sha256": SOURCE_LOCK,
        "disposition": args.disposition,
        "terminal_report": "READY_TO_COMMIT",
        "decision_changed": [],
    }
    manifest_path = slot / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    result_artifacts = entries + [artifact(args.task_id, repo, manifest_path)]
    result = {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": args.task_id,
        "commission_id": COMMISSION,
        "immutable_input_manifest_sha256": SOURCE_LOCK,
        "acceptance_contract_sha256": digest(acceptance),
        "provider_state": "RUNNING",
        "obzio_state": "RESULT_STAGED",
        "attempt": {
            "attempt_id": f"{args.task_id}-attempt-1",
            "idempotency_key": f"PO03-WAVE-A-20260822:{args.task_id}:attempt-1",
            "lease_id": f"lease-{args.task_id}-1",
            "fence_token": 1,
            "provider_run_id": "bc-aa38db59-c61c-4e29-9c26-4424b20f6e19",
            "worker_id": "route-08-material-worker",
            "heartbeat_at": None,
            "checkpoint_seq": 1,
        },
        "result_transaction": {
            "result_txn_id": f"rtxn-{args.task_id}-attempt-1",
            "state": "STAGED",
            "manifest_uri": manifest_path.relative_to(repo).as_posix(),
            "manifest_sha256": digest(manifest_path),
            "artifact_count": len(result_artifacts),
            "total_bytes": sum(row["bytes"] for row in result_artifacts),
            "committed_at": None,
            "verified_at": None,
            "parent_ingested_at": None,
            "result_commit_id": None,
        },
        "artifacts": result_artifacts,
        "completion_actor": None,
        "independent_acceptance": {
            "state": "NOT_TESTED",
            "reviewer_id": None,
            "receipt_uri": None,
        },
    }
    (slot / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "task_id": args.task_id,
                "disposition": args.disposition,
                "artifact_count": len(result_artifacts),
                "total_bytes": result["result_transaction"]["total_bytes"],
                "manifest_sha256": result["result_transaction"]["manifest_sha256"],
                "terminal_report": "READY_TO_COMMIT",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
