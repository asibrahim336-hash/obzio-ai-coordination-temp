#!/usr/bin/env python3
"""Route-01 manifest and execution receipt builder.

Reconciles every committed task result against the immutable git object store:
each artifact recorded in a task manifest is re-read from the *committed blob*
rather than from the working tree, and its SHA-256 and byte count are compared
against the declaration.  A working-tree-only check would not detect a file that
was staged but never committed, which is precisely the custody gap PO-03 exists
to close.

Standard library plus ``git`` only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROUTE_ID = "route-01"
WAVE_ID = "PO03-WAVE-A-20260822"
ROUTE_SLOT = "workstreams/po03/runs/wave-a/route-01"
COMMISSION_ID = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
TASK_IDS = tuple(f"PO03-WA-{index:03d}" for index in range(1, 9))


def git(repo: Path, *arguments: str) -> str:
    return subprocess.check_output(("git", *arguments), cwd=repo, text=True).rstrip("\n")


def git_bytes(repo: Path, *arguments: str) -> bytes:
    return subprocess.check_output(("git", *arguments), cwd=repo)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: Path, value: Any) -> str:
    data = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"
    atomic_write(path, data)
    return digest(data)


def task_commit(repo: Path, task_id: str, branch: str) -> str:
    """The commit that introduced this task's result slot."""
    output = git(repo, "log", "--format=%H", branch, "--", f"{ROUTE_SLOT}/{task_id}/")
    return output.splitlines()[-1] if output else ""


def verify_task(repo: Path, task_id: str, commit: str) -> dict[str, Any]:
    """Re-read every declared artifact from the committed blob and reconcile."""
    manifest_path = f"{ROUTE_SLOT}/{task_id}/manifest.json"
    result_path = f"{ROUTE_SLOT}/{task_id}/result.json"
    manifest_bytes = git_bytes(repo, "show", f"{commit}:{manifest_path}")
    result_bytes = git_bytes(repo, "show", f"{commit}:{result_path}")
    manifest = json.loads(manifest_bytes)
    result = json.loads(result_bytes)

    mismatches: list[dict[str, Any]] = []
    for artifact in manifest["artifacts"]:
        blob_path = f"{ROUTE_SLOT}/{task_id}/{artifact['logical_name']}"
        try:
            payload = git_bytes(repo, "show", f"{commit}:{blob_path}")
        except subprocess.CalledProcessError:
            mismatches.append({"logical_name": artifact["logical_name"], "reason": "BLOB_ABSENT_AT_COMMIT"})
            continue
        observed_sha = digest(payload)
        if observed_sha != artifact["sha256"] or len(payload) != artifact["bytes"]:
            mismatches.append(
                {
                    "logical_name": artifact["logical_name"],
                    "reason": "BLOB_MISMATCH",
                    "declared_sha256": artifact["sha256"],
                    "observed_sha256": observed_sha,
                    "declared_bytes": artifact["bytes"],
                    "observed_bytes": len(payload),
                }
            )

    declared_manifest_sha = result["result_transaction"]["manifest_sha256"]
    if digest(manifest_bytes) != declared_manifest_sha:
        mismatches.append(
            {
                "logical_name": "manifest.json",
                "reason": "MANIFEST_HASH_MISMATCH",
                "declared_sha256": declared_manifest_sha,
                "observed_sha256": digest(manifest_bytes),
            }
        )

    return {
        "task_id": task_id,
        "frozen_hypothesis": manifest["frozen_hypothesis"],
        "disposition": manifest["disposition"],
        "obzio_state": result["obzio_state"],
        "provider_state": result["provider_state"],
        "independent_acceptance": result["independent_acceptance"]["state"],
        "completion_actor": result["completion_actor"],
        "result_commit_id": commit,
        "result_uri": f"{ROUTE_SLOT}/{task_id}/result.json",
        "result_sha256": digest(result_bytes),
        "manifest_uri": f"{ROUTE_SLOT}/{task_id}/manifest.json",
        "manifest_sha256": digest(manifest_bytes),
        "manifest_bytes": len(manifest_bytes),
        "artifact_count": manifest["artifact_count"],
        "total_bytes": manifest["total_bytes"],
        "commands": manifest["commands"],
        "limitations": manifest["limitations"],
        "blob_verification": "PASS" if not mismatches else "FAIL",
        "blob_mismatches": mismatches,
    }


def build(repo: Path, branch: str, base_commit: str, test_summary_path: Path | None) -> dict[str, Any]:
    tasks = []
    for task_id in TASK_IDS:
        commit = task_commit(repo, task_id, branch)
        if not commit:
            raise SystemExit(f"no commit found for {task_id}")
        tasks.append(verify_task(repo, task_id, commit))

    ordered_commits = [task["result_commit_id"] for task in tasks]
    manifest = {
        "manifest_version": "PO03-ROUTE-01-MANIFEST-v1",
        "wave_id": WAVE_ID,
        "route_id": ROUTE_ID,
        "commission_id": COMMISSION_ID,
        "function": "transactional-custody",
        "exact_model_configuration": "claude-opus-5-thinking-high",
        "immutable_base_commit": base_commit,
        "branch": branch,
        "lease": {
            "lease_batch_id": f"{WAVE_ID}:{ROUTE_ID}:lease-1",
            "fence_token": 1,
            "owned_subtree": f"{ROUTE_SLOT}/",
            "result_state_ceiling": "READY_TO_COMMIT",
        },
        "canary_commit": "00b3988bad3e2b74ba5c2d7a50dc8ab9883fc24e",
        "task_count": len(tasks),
        "ordered_result_commits": ordered_commits,
        "tasks": tasks,
        "all_blobs_verified": all(task["blob_verification"] == "PASS" for task in tasks),
        "dispositions": sorted({task["disposition"] for task in tasks}),
        "producer_terminal_report": "READY_TO_COMMIT",
        "independent_acceptance": "NOT_TESTED",
        "generated_at": utc_now(),
        "decision_changed": [],
    }
    if test_summary_path and test_summary_path.exists():
        payload = test_summary_path.read_bytes()
        manifest["test_summary"] = {
            "uri": f"{ROUTE_SLOT}/evidence/{test_summary_path.name}",
            "sha256": digest(payload),
            "bytes": len(payload),
        }

    manifest_sha = write_json(repo / ROUTE_SLOT / "MANIFEST.json", manifest)
    print(f"ROUTE_MANIFEST sha256={manifest_sha} tasks={len(tasks)} verified={manifest['all_blobs_verified']}")
    return {"manifest": manifest, "manifest_sha256": manifest_sha}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--branch", required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--test-summary", type=Path, default=None)
    args = parser.parse_args(argv)
    build(args.repo.resolve(), args.branch, args.base_commit, args.test_summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
