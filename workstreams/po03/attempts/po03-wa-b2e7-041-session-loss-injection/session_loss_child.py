#!/usr/bin/env python3
"""A worker session that dies at a chosen state transition.

The child drives one unit forward through the live state order, recording each
transition in the hash-chained event log and doing the real durable work that
belongs to it, and then loses its session to SIGKILL at the requested state.
SIGKILL is used deliberately: a session that is lost gets no chance to tidy up,
mark itself failed, or report anything.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("po03_c6_041_child_kit", HERE / "fault_kit.py")
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load fault_kit.py")
kit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(kit)

KILL_STATES = (
    "CREATED",
    "LEASED",
    "RUNNING",
    "CHECKPOINTED",
    "RESULT_STAGING",
    "RESULT_STAGED",
    "RESULT_VERIFIED",
    "RESULT_COMMITTED",
    "PARENT_INGESTED",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--kill-after", choices=KILL_STATES, required=True)
    arguments = parser.parse_args(argv)

    sandbox = Path(arguments.sandbox).resolve()
    module = kit.bind_sandbox(kit.load_factory("041_child"), sandbox)
    task_id = arguments.task_id
    kill_after = arguments.kill_after
    slot = f"workstreams/po03/attempts/{task_id}"
    artifact_path = f"{slot}/component.json"
    reached: list[str] = []
    payload: dict[str, object] = {"task_id": task_id, "kill_after": kill_after}

    def die() -> None:
        payload["reached"] = reached
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()
        os.kill(os.getpid(), signal.SIGKILL)

    kit.init_repository(sandbox)
    kit.seed_capsule(module, task_id, hypothesis="a lost session leaves no false completion")
    reached.append("CREATED")
    if kill_after == "CREATED":
        die()

    lease = module.grant_lease(task_id, holder="worker-a", lease_seconds=600, attempt=1)
    reached.append("LEASED")
    payload["fence_token"] = lease["fence_token"]
    if kill_after == "LEASED":
        die()

    module.hash_chain_event(task_id, "RUNNING", actor="worker-a", details={"phase": "compute"})
    reached.append("RUNNING")
    if kill_after == "RUNNING":
        die()

    module.hash_chain_event(task_id, "CHECKPOINTED", actor="worker-a", details={"checkpoint_seq": 1})
    reached.append("CHECKPOINTED")
    if kill_after == "CHECKPOINTED":
        die()

    module.hash_chain_event(task_id, "RESULT_STAGING", actor="worker-a", details={"slot": slot})
    target = sandbox / artifact_path
    target.parent.mkdir(parents=True, exist_ok=True)
    body = module.canonical_json({"component": task_id, "computed": True})
    target.write_bytes(body)
    reached.append("RESULT_STAGING")
    if kill_after == "RESULT_STAGING":
        die()

    module.hash_chain_event(
        task_id, "RESULT_STAGED", actor="worker-a", details={"staged_bytes": len(body)}
    )
    reached.append("RESULT_STAGED")
    if kill_after == "RESULT_STAGED":
        die()

    module.hash_chain_event(
        task_id,
        "RESULT_VERIFIED",
        actor="worker-a",
        details={"sha256": module.sha256_bytes(body), "bytes": len(body)},
    )
    reached.append("RESULT_VERIFIED")
    if kill_after == "RESULT_VERIFIED":
        die()

    commit = kit.commit_all(sandbox, "po03: sandbox worker artifact")
    module.hash_chain_event(task_id, "RESULT_COMMITTED", actor="worker-a", details={"commit": commit})
    reached.append("RESULT_COMMITTED")
    payload["artifact_commit"] = commit
    payload["artifact_path"] = artifact_path
    if kill_after == "RESULT_COMMITTED":
        die()

    document = kit.build_result_document(
        module,
        task_id=task_id,
        commit=commit,
        paths=[artifact_path],
        fence_token=lease["fence_token"],
        worker_id="worker-a",
    )
    ingestion = module.ingest_result(task_id, document)
    reached.append("PARENT_INGESTED")
    payload["ingestion_state"] = ingestion["obzio_state"]
    payload["ingestion_errors"] = ingestion["errors"]
    die()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
