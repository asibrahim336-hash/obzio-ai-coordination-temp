#!/usr/bin/env python3
"""Kill a worker session at every state transition and check what survives.

For each of the nine states in the live order, a real child worker reaches that
state, does the durable work that belongs to it, and is then killed with
SIGKILL.  The parent then asks two questions of the unmodified mechanism: did
the loss leave any false completion, and can the unit be resumed from its
immutable input?  Resumption is executed for real — a fresh lease, fresh bytes,
a fresh commit and a fresh ingestion — rather than inferred.

Run directly to print the observation as JSON:

    python3 -I session_loss_injector.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
CHILD = HERE / "session_loss_child.py"
_SPEC = importlib.util.spec_from_file_location("po03_c6_041_fault_kit", HERE / "fault_kit.py")
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
EXPECTED_ACTION = {
    "CREATED": "DISPATCH",
    "PARENT_INGESTED": "AWAIT_COORDINATOR_COMPLETION",
}
DEFAULT_ACTION = "RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT"


def run_child(sandbox: Path, task_id: str, kill_after: str) -> dict[str, Any]:
    sandbox.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            str(CHILD),
            "--sandbox",
            str(sandbox),
            "--task-id",
            task_id,
            "--kill-after",
            kill_after,
        ),
        capture_output=True,
        text=True,
    )
    reported = {}
    if completed.stdout.strip():
        reported = json.loads(completed.stdout.strip().splitlines()[-1])
    return {
        "kill_after": kill_after,
        "returncode": completed.returncode,
        "killed_by_sigkill": completed.returncode == -9,
        "child_report": reported,
        "stderr_tail": completed.stderr.strip()[-300:],
    }


def resume_from_immutable_input(module, sandbox: Path, task_id: str) -> dict[str, Any]:
    """A fresh worker picks the unit up using only the immutable capsule."""
    capsule_path = module.CONTROL_ROOT / "tasks" / task_id / "input.json"
    capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    slot = capsule["ownership"]["result_slot"]
    resumed_path = f"{slot}/component-resumed.json"
    target = sandbox / resumed_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        module.canonical_json(
            {
                "component": capsule["task_id"],
                "resumed_from": capsule["transaction"]["idempotency_key"],
                "attempt": 2,
            }
        )
    )
    commit = kit.commit_all(sandbox, "po03: resumed from immutable input")
    lease = module.grant_lease(task_id, holder="worker-b", lease_seconds=600, attempt=2)
    document = kit.build_result_document(
        module,
        task_id=task_id,
        commit=commit,
        paths=[resumed_path],
        fence_token=lease["fence_token"],
        worker_id="worker-b",
        timestamp="2026-08-22T09:00:00Z",
    )
    ingestion = module.ingest_result(task_id, document)
    return {
        "resumed_fence_token": lease["fence_token"],
        "resumed_commit": commit,
        "resumed_state": ingestion["obzio_state"],
        "resumed_errors": ingestion["errors"],
        "resumed_readback_match": [item["match"] for item in ingestion.get("artifact_readback", [])],
    }


def inject_session_loss(root: Path, kill_after: str) -> dict[str, Any]:
    task_id = f"po03-c6-041-{kill_after.lower().replace('_', '-')}"
    sandbox = root / kill_after.lower()
    crash = run_child(sandbox, task_id, kill_after)
    module = kit.bind_sandbox(kit.load_factory(f"041_{kill_after.lower()}"), sandbox)
    task_directory = module.CONTROL_ROOT / "tasks" / task_id
    events = sorted((module.CONTROL_ROOT / "events" / task_id).glob("*.json"))
    states = [json.loads(path.read_text(encoding="utf-8"))["state"] for path in events]
    before = module.scan_recovery("c6-sandbox", "0" * 40)
    unit = before["units"][task_id]
    capsule_path = task_directory / "input.json"
    observed = {
        "event_states": states,
        "last_state": states[-1] if states else None,
        "completed_event_present": "COMPLETED" in states,
        "completion_file_present": (task_directory / "transaction-completed.json").is_file(),
        "ingestion_records": len(sorted(task_directory.glob("ingestion-*.json"))),
        "recovery_action": unit["recovery_action"],
        "expected_recovery_action": EXPECTED_ACTION.get(kill_after, DEFAULT_ACTION),
        "false_completion_count": before["false_completion_count"],
        "orphan_count": before["orphan_count"],
        "event_chain_errors": module.verify_chain(task_id),
        "immutable_input_intact": capsule_path.is_file()
        and json.loads(capsule_path.read_text(encoding="utf-8"))["task_id"] == task_id,
        "immutable_input_sha256": module.sha256_file(capsule_path) if capsule_path.is_file() else None,
    }

    if kill_after == "PARENT_INGESTED":
        observed["resume_required"] = False
        observed["ingested_result_survived_the_loss"] = unit["ingested"]
        resumable = unit["ingested"]
    else:
        observed["resume_required"] = True
        resume = resume_from_immutable_input(module, sandbox, task_id)
        observed.update(resume)
        after = module.scan_recovery("c6-sandbox", "0" * 40)
        observed["recovery_action_after_resume"] = after["units"][task_id]["recovery_action"]
        observed["false_completion_count_after_resume"] = after["false_completion_count"]
        resumable = (
            resume["resumed_state"] == "PARENT_INGESTED"
            and resume["resumed_errors"] == []
            and all(resume["resumed_readback_match"])
        )

    passed = (
        crash["killed_by_sigkill"]
        and not observed["completed_event_present"]
        and not observed["completion_file_present"]
        and observed["false_completion_count"] == 0
        and observed["event_chain_errors"] == []
        and observed["immutable_input_intact"]
        and observed["recovery_action"] == observed["expected_recovery_action"]
        and resumable
    )
    return {
        "fault_class": f"SESSION_LOST_AFTER_{kill_after}",
        "injected_at_state_transition": f"{kill_after} -> (session gone)",
        "crash": crash,
        "observed": observed,
        "unit_resumable_from_immutable_input": resumable,
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_all(root: Path) -> dict[str, Any]:
    results = [inject_session_loss(root, state) for state in KILL_STATES]
    return {
        "unit": "po03-wa-b2e7-041-session-loss-injection",
        "fault_classes": len(results),
        "state_transitions_covered": list(KILL_STATES),
        "results": results,
        "false_completions_observed": sum(
            int(item["observed"].get("false_completion_count", 0) or 0)
            + int(item["observed"].get("false_completion_count_after_resume", 0) or 0)
            for item in results
        ),
        "units_resumable": sum(1 for item in results if item["unit_resumable_from_immutable_input"]),
        "verdict": "PASS" if all(item["verdict"] == "PASS" for item in results) else "FAIL",
        "verdict_basis": (
            "a session killed with SIGKILL at each of the nine states left no COMPLETED event and "
            "no completion file, kept the event chain verifiable and the immutable capsule intact, "
            "was classified for dispatch, resumption or coordinator completion as appropriate, and "
            "was then actually resumed to PARENT_INGESTED by a fresh worker from the capsule alone"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox-root", default=None)
    arguments = parser.parse_args(argv)
    if arguments.sandbox_root:
        report = inject_all(Path(arguments.sandbox_root).resolve())
    else:
        with tempfile.TemporaryDirectory() as temporary:
            report = inject_all(Path(temporary))
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
