#!/usr/bin/env python3
"""Inject a lost return message and observe whether the result survives.

The fault is the exact failure that cost the PO-02 Code-2 return: a worker
durably commits its result and then the return message never reaches the
coordinator.  The question this component answers is narrow and falsifiable —
does the live recovery scanner find the committed bytes from durable evidence
alone, or does it prescribe an action that discards a committed result?

Run directly to print the observation as JSON:

    python3 -I lost_callback_injector.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


KIT_PATH = Path(__file__).resolve().parent / "fault_kit.py"
_SPEC = importlib.util.spec_from_file_location("po03_c6_042_fault_kit", KIT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"cannot load {KIT_PATH}")
kit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(kit)

TASK_ID = "po03-c6-042-sandbox-unit"
SLOT = f"workstreams/po03/attempts/{TASK_ID}"
ARTIFACT_PATH = f"{SLOT}/component.json"
RESULT_PATH = f"{SLOT}/result.json"


def stage_committed_result(module, sandbox: Path) -> dict[str, Any]:
    """Drive one unit to a durably committed result, then drop the callback."""
    kit.init_repository(sandbox)
    kit.seed_capsule(
        module,
        TASK_ID,
        hypothesis="a committed result survives a lost return message",
    )
    lease = module.grant_lease(TASK_ID, holder="worker-a", lease_seconds=60, attempt=1)
    module.hash_chain_event(TASK_ID, "RUNNING", actor="worker-a", details={"phase": "compute"})

    artifact = sandbox / ARTIFACT_PATH
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(module.canonical_json({"component": TASK_ID, "computed": True}))
    artifact_commit = kit.commit_all(sandbox, "po03: sandbox worker artifact")

    module.hash_chain_event(TASK_ID, "RESULT_STAGED", actor="worker-a", details={"commit": artifact_commit})
    document = kit.build_result_document(
        module,
        task_id=TASK_ID,
        commit=artifact_commit,
        paths=[ARTIFACT_PATH],
        fence_token=lease["fence_token"],
        worker_id="worker-a",
    )
    (sandbox / RESULT_PATH).write_bytes(module.canonical_json(document))
    result_commit = kit.commit_all(sandbox, "po03: sandbox worker result")
    module.hash_chain_event(
        TASK_ID, "RESULT_COMMITTED", actor="worker-a", details={"commit": result_commit}
    )
    # The callback dies here.  No ingest_result call is ever made.
    return {
        "task_id": TASK_ID,
        "result_slot": SLOT,
        "artifact_commit": artifact_commit,
        "result_commit": result_commit,
        "fence_token": lease["fence_token"],
        "result_document_sha256": module.sha256_bytes(module.canonical_json(document)),
        "callback_delivered": False,
    }


def observe_recovery(module, staged: dict[str, Any]) -> dict[str, Any]:
    """Ask the live scanner what it knows and what it would do."""
    state = module.scan_recovery("c6-sandbox", "0" * 40)
    unit = state["units"][TASK_ID]
    serialized = json.dumps(state, sort_keys=True)
    ingestions = sorted((module.CONTROL_ROOT / "tasks" / TASK_ID).glob("ingestion-*.json"))
    committed_bytes_visible = staged["result_commit"] in serialized or staged["artifact_commit"] in serialized
    return {
        "scanner_recovery_action": unit["recovery_action"],
        "scanner_obzio_state": unit["obzio_state"],
        "scanner_ingested_flag": unit["ingested"],
        "false_completion_count": state["false_completion_count"],
        "orphan_count": state["orphan_count"],
        "ingestion_records": len(ingestions),
        "committed_result_referenced_by_scanner": committed_bytes_visible,
        "committed_bytes_still_readable_by_object_id": len(
            module.read_object_bytes(f"git:{staged['result_commit']}:{RESULT_PATH}")
        ),
        "event_chain_errors": module.verify_chain(TASK_ID),
    }


def inject(sandbox: Path) -> dict[str, Any]:
    module = kit.bind_sandbox(kit.load_factory("042_inject"), sandbox)
    staged = stage_committed_result(module, sandbox)
    observed = observe_recovery(module, staged)
    committed_result_recovered = observed["scanner_ingested_flag"] or observed["ingestion_records"] > 0
    rerun_would_discard = (
        observed["scanner_recovery_action"] == "RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT"
        and not committed_result_recovered
    )
    return {
        "injection": "LOST_RETURN_MESSAGE_AFTER_DURABLE_RESULT_COMMIT",
        "injected_at_state": "RESULT_COMMITTED",
        "staged": staged,
        "observed": observed,
        "committed_result_recovered_by_live_scanner": committed_result_recovered,
        "prescribed_action_discards_committed_result": rerun_would_discard,
        "false_completion_observed": observed["false_completion_count"] != 0,
        "verdict": "FAIL" if rerun_would_discard else "PASS",
        "verdict_basis": (
            "the live scan_recovery reconciles only control-plane events and ingestion records; "
            "it never enumerates committed result documents, so a lost callback leaves durable "
            "committed bytes invisible and prescribes a rerun"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox", default=None, help="reuse a directory instead of a temporary one")
    args = parser.parse_args(argv)
    if args.sandbox:
        report = inject(Path(args.sandbox).resolve())
    else:
        with tempfile.TemporaryDirectory() as temporary:
            report = inject(Path(temporary) / "repository")
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
