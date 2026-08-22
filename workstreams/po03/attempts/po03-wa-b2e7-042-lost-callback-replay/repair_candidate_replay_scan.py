#!/usr/bin/env python3
"""Repair candidate for the lost-callback gap found by this unit.

Staged inside this unit's subtree only.  The live mechanism is not modified by
this file; a coordinator would have to adopt it deliberately.

The gap: `scan_recovery` reconciles a unit against control-plane events and
ingestion records only.  A worker that committed a result and then lost its
return message leaves durable bytes that the scanner never enumerates, so the
prescribed action is a rerun that discards a committed result.

The candidate closes the gap by making the durable commit itself the source of
truth: enumerate every task's `result.json` inside its own result slot at a
given revision, and ingest each discovered result through the unmodified
`ingest_result`, which already refuses stale fences, verifies every artifact by
immutable object id and suppresses a replayed identical callback.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any


def committed_result_paths(module, revision: str = "HEAD") -> list[str]:
    """List every committed `result.json` under an attempts result slot."""
    listing = subprocess.run(
        ("git", "ls-tree", "-r", "--name-only", "-z", revision, "--", "workstreams/po03/attempts"),
        cwd=module.REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return sorted(path for path in listing.split("\0") if path.endswith("/result.json"))


def discover_committed_results(module, revision: str = "HEAD") -> list[dict[str, Any]]:
    """Recover result documents from durable commits, never from provider memory."""
    discovered: list[dict[str, Any]] = []
    for path in committed_result_paths(module, revision):
        body = module.read_object_bytes(f"git:{revision}:{path}")
        try:
            document = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            discovered.append({"path": path, "error": f"undecodable result document: {exc}"})
            continue
        if not isinstance(document, dict) or "task_id" not in document:
            discovered.append({"path": path, "error": "result document is not a task-bearing object"})
            continue
        discovered.append(
            {
                "path": path,
                "task_id": document["task_id"],
                "document": document,
                "document_sha256": module.sha256_bytes(body),
            }
        )
    return discovered


def already_ingested(module, task_id: str) -> bool:
    task_directory = module.CONTROL_ROOT / "tasks" / task_id
    if not task_directory.is_dir():
        return False
    return any(
        json.loads(path.read_text(encoding="utf-8")).get("obzio_state") == "PARENT_INGESTED"
        for path in sorted(task_directory.glob("ingestion-*.json"))
    )


def replay_scan(module, revision: str = "HEAD") -> dict[str, Any]:
    """Replay every committed-but-unreported result exactly once."""
    replayed: list[dict[str, Any]] = []
    for candidate in discover_committed_results(module, revision):
        if "error" in candidate:
            replayed.append({"path": candidate["path"], "outcome": "UNREADABLE", "detail": candidate["error"]})
            continue
        task_id = candidate["task_id"]
        if not (module.CONTROL_ROOT / "tasks" / task_id / "input.json").is_file():
            replayed.append({"task_id": task_id, "outcome": "NO_IMMUTABLE_CAPSULE"})
            continue
        if already_ingested(module, task_id):
            replayed.append({"task_id": task_id, "outcome": "ALREADY_INGESTED_NO_REPLAY"})
            continue
        ingestion = module.ingest_result(task_id, candidate["document"])
        replayed.append(
            {
                "task_id": task_id,
                "outcome": ingestion["obzio_state"],
                "duplicate_suppressed": bool(ingestion.get("duplicate_callback_suppressed")),
                "errors": ingestion["errors"],
            }
        )
    return {
        "replay_version": "PO03-C6-042-REPLAY-CANDIDATE-v1",
        "revision": revision,
        "candidates": len(replayed),
        "replayed": replayed,
        "adopted_by_live_mechanism": False,
    }
