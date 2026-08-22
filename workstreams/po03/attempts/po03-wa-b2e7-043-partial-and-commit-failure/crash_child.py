#!/usr/bin/env python3
"""A worker that really dies inside the custody mechanism.

The parent spawns this as `python -I crash_child.py --crash-point <point>` and
asserts the child was killed by SIGKILL, so the injected fault is an actual
uncatchable process death rather than an exception the mechanism could clean up
after.  The crash points sit at the exact instructions where a partial write or
a commit-boundary failure would be observable.
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
_SPEC = importlib.util.spec_from_file_location("po03_c6_043_child_kit", HERE / "fault_kit.py")
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load fault_kit.py")
kit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(kit)

CRASH_POINTS = (
    "WRITE_ONCE_BEFORE_LINK",
    "WRITE_ONCE_BEFORE_DIRECTORY_FSYNC",
    "REPLACE_ATOMIC_BEFORE_REPLACE",
    "PRE_COMMIT",
    "POST_COMMIT_BEFORE_CALLBACK",
    "MID_EVENT_CHAIN",
)
PAYLOAD_FILLER = "p" * (2 * 1024 * 1024)


def die() -> None:
    sys.stdout.flush()
    os.kill(os.getpid(), signal.SIGKILL)


def kill_on_link(module) -> None:
    def hook(source, destination, **_):
        die()

    module.os.link = hook


def kill_on_directory_open(module) -> None:
    real_open = module.os.open

    def hook(path, flags, *arguments, **keywords):
        if os.path.isdir(path):
            die()
        return real_open(path, flags, *arguments, **keywords)

    module.os.open = hook


def kill_on_replace(module) -> None:
    def hook(source, destination, **_):
        die()

    module.os.replace = hook


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox", required=True)
    parser.add_argument("--crash-point", required=True, choices=CRASH_POINTS)
    parser.add_argument("--task-id", required=True)
    arguments = parser.parse_args(argv)

    sandbox = Path(arguments.sandbox).resolve()
    module = kit.bind_sandbox(kit.load_factory("043_child"), sandbox)
    task_id = arguments.task_id
    slot = f"workstreams/po03/attempts/{task_id}"

    if arguments.crash_point == "REPLACE_ATOMIC_BEFORE_REPLACE":
        # A controller-owned derived file already holds a good version.
        module.replace_atomic(
            module.CONTROL_ROOT / "recovery-state.json",
            module.canonical_json({"recovery_version": "PO03-RECOVERY-STATE-v1", "generation": 1}),
        )
        kill_on_replace(module)
        module.replace_atomic(
            module.CONTROL_ROOT / "recovery-state.json",
            module.canonical_json({"recovery_version": "PO03-RECOVERY-STATE-v1", "generation": 2}),
        )
        return 0

    kit.init_repository(sandbox)
    kit.seed_capsule(module, task_id, hypothesis="a crash leaves a recoverable state")
    lease = module.grant_lease(task_id, holder="worker-a", lease_seconds=60, attempt=1)
    module.hash_chain_event(task_id, "RUNNING", actor="worker-a", details={"phase": "compute"})

    if arguments.crash_point == "WRITE_ONCE_BEFORE_LINK":
        kill_on_link(module)
        module.hash_chain_event(
            task_id, "CHECKPOINTED", actor="worker-a", details={"filler": PAYLOAD_FILLER}
        )
        return 0

    if arguments.crash_point == "WRITE_ONCE_BEFORE_DIRECTORY_FSYNC":
        kill_on_directory_open(module)
        module.hash_chain_event(
            task_id, "CHECKPOINTED", actor="worker-a", details={"phase": "linked-not-fsynced"}
        )
        return 0

    if arguments.crash_point == "MID_EVENT_CHAIN":
        module.hash_chain_event(task_id, "CHECKPOINTED", actor="worker-a", details={"sequence": 3})
        kill_on_link(module)
        module.hash_chain_event(task_id, "RESULT_STAGING", actor="worker-a", details={"sequence": 4})
        return 0

    artifact = sandbox / slot / "component.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(module.canonical_json({"component": task_id, "computed": True}))

    if arguments.crash_point == "PRE_COMMIT":
        module.hash_chain_event(task_id, "RESULT_STAGING", actor="worker-a", details={"staged": True})
        die()

    commit = kit.commit_all(sandbox, "po03: sandbox worker artifact")
    document = kit.build_result_document(
        module,
        task_id=task_id,
        commit=commit,
        paths=[f"{slot}/component.json"],
        fence_token=lease["fence_token"],
        worker_id="worker-a",
    )
    (sandbox / slot / "result.json").write_bytes(module.canonical_json(document))
    result_commit = kit.commit_all(sandbox, "po03: sandbox worker result")
    module.hash_chain_event(
        task_id, "RESULT_COMMITTED", actor="worker-a", details={"commit": result_commit}
    )
    print(json.dumps({"artifact_commit": commit, "result_commit": result_commit}))
    die()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
