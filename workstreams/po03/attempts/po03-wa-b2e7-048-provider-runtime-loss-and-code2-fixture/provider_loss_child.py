#!/usr/bin/env python3
"""A worker whose entire runtime disappears after it reports completion.

The child records a provider-reported completion in the hash-chained event log
and is then killed with SIGKILL before any commit exists.  That is the exact
shape of the lost PO-02 Code-2 packaging return: the provider said it was done
and no durable result was ever written.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import signal
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("po03_c6_048_child_kit", HERE / "fault_kit.py")
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load fault_kit.py")
kit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(kit)

LOSS_POINTS = (
    "AFTER_PROVIDER_REPORTED_COMPLETION_BEFORE_ANY_COMMIT",
    "AFTER_STAGING_BEFORE_PROVIDER_REPORT",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--loss-point", choices=LOSS_POINTS, required=True)
    arguments = parser.parse_args(argv)

    sandbox = Path(arguments.sandbox).resolve()
    module = kit.bind_sandbox(kit.load_factory("048_child"), sandbox)
    task_id = arguments.task_id
    kit.init_repository(sandbox)
    kit.seed_capsule(module, task_id, hypothesis="a provider report is not a result")
    module.grant_lease(task_id, holder="worker-a", lease_seconds=600, attempt=1)
    module.hash_chain_event(task_id, "RUNNING", actor="worker-a", details={"phase": "packaging"})

    slot = f"workstreams/po03/attempts/{task_id}"
    staged = sandbox / slot / "packaging-work-in-progress.json"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(module.canonical_json({"unit": task_id, "state": "in-progress"}))

    if arguments.loss_point == "AFTER_STAGING_BEFORE_PROVIDER_REPORT":
        sys.stdout.flush()
        os.kill(os.getpid(), signal.SIGKILL)

    module.hash_chain_event(
        task_id,
        "PROVIDER_COMPLETED_UNCOMMITTED",
        actor="provider-callback",
        details={
            "provider_state": "COMPLETION_REPORTED_OR_LIVE_CONFLICT",
            "durable_result_commit_id": None,
            "artifacts": [],
        },
    )
    sys.stdout.flush()
    os.kill(os.getpid(), signal.SIGKILL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
