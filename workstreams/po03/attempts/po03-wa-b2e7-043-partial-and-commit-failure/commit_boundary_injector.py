#!/usr/bin/env python3
"""Inject partial writes and commit-boundary failures, then classify what survived.

Each fault class kills a real worker process with SIGKILL at a precise point and
then inspects the durable state the mechanism left behind: whether an immutable
file was ever observable half-written, whether the previous generation of a
controller-owned file survived, how the recovery scanner classifies the unit, and
whether any false completion appeared.

Run directly to print the observation as JSON:

    python3 -I commit_boundary_injector.py
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
CHILD = HERE / "crash_child.py"
_SPEC = importlib.util.spec_from_file_location("po03_c6_043_fault_kit", HERE / "fault_kit.py")
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load fault_kit.py")
kit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(kit)

SIGKILL_RETURNCODE = -9


def run_crash(sandbox: Path, crash_point: str, task_id: str) -> dict[str, Any]:
    """Run the child worker and require that it died from an uncatchable signal."""
    sandbox.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            str(CHILD),
            "--sandbox",
            str(sandbox),
            "--crash-point",
            crash_point,
            "--task-id",
            task_id,
        ),
        capture_output=True,
        text=True,
    )
    return {
        "crash_point": crash_point,
        "returncode": completed.returncode,
        "killed_by_sigkill": completed.returncode == SIGKILL_RETURNCODE,
        "stdout": completed.stdout.strip(),
        "stderr_tail": completed.stderr.strip()[-400:],
    }


def event_files(module, task_id: str) -> list[Path]:
    directory = module.CONTROL_ROOT / "events" / task_id
    return sorted(directory.glob("*.json")) if directory.is_dir() else []


def directory_entries(module, task_id: str) -> list[str]:
    directory = module.CONTROL_ROOT / "events" / task_id
    return sorted(item.name for item in directory.iterdir()) if directory.is_dir() else []


def bind(sandbox: Path, instance: str):
    return kit.bind_sandbox(kit.load_factory(instance), sandbox)


def inject_partial_write(root: Path) -> dict[str, Any]:
    """Kill the worker after the payload is fsynced but before the atomic link."""
    task_id = "po03-c6-043-partial-write"
    sandbox = root / "partial-write"
    crash = run_crash(sandbox, "WRITE_ONCE_BEFORE_LINK", task_id)
    module = bind(sandbox, "043_partial")
    events = event_files(module, task_id)
    entries = directory_entries(module, task_id)
    stray = [name for name in entries if not name.endswith(".json")]
    observed = {
        "durable_event_files": [path.name for path in events],
        "half_written_immutable_file_visible": any("checkpointed" in path.name for path in events),
        "stray_temporary_entries": stray,
        "stray_entries_ignored_by_mechanism": all(name not in {path.name for path in events} for name in stray),
        "event_chain_errors": module.verify_chain(task_id),
        "recovery_action": module.scan_recovery("c6-sandbox", "0" * 40)["units"][task_id]["recovery_action"],
        "false_completion_count": module.scan_recovery("c6-sandbox", "0" * 40)["false_completion_count"],
    }
    passed = (
        crash["killed_by_sigkill"]
        and not observed["half_written_immutable_file_visible"]
        and observed["stray_entries_ignored_by_mechanism"]
        and observed["event_chain_errors"] == []
        and observed["false_completion_count"] == 0
        and observed["recovery_action"] == "RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT"
    )
    return {
        "fault_class": "PARTIAL_WRITE_KILLED_BEFORE_ATOMIC_LINK",
        "injected_at_state_transition": "RUNNING -> CHECKPOINTED",
        "crash": crash,
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_link_without_fsync(root: Path) -> dict[str, Any]:
    """Kill the worker after the link but before the directory fsync."""
    task_id = "po03-c6-043-link-no-fsync"
    sandbox = root / "link-no-fsync"
    crash = run_crash(sandbox, "WRITE_ONCE_BEFORE_DIRECTORY_FSYNC", task_id)
    module = bind(sandbox, "043_linked")
    events = event_files(module, task_id)
    checkpoint = [path for path in events if "checkpointed" in path.name]
    body = json.loads(checkpoint[0].read_text(encoding="utf-8")) if checkpoint else None
    recomputed = None
    if body is not None:
        claimed = dict(body)
        claimed.pop("event_sha256", None)
        recomputed = module.sha256_bytes(module.canonical_json(claimed)) == body["event_sha256"]
    observed = {
        "durable_event_files": [path.name for path in events],
        "checkpoint_file_present": bool(checkpoint),
        "checkpoint_content_self_consistent": recomputed,
        "event_chain_errors": module.verify_chain(task_id),
        "false_completion_count": module.scan_recovery("c6-sandbox", "0" * 40)["false_completion_count"],
    }
    passed = (
        crash["killed_by_sigkill"]
        and observed["checkpoint_file_present"]
        and observed["checkpoint_content_self_consistent"] is True
        and observed["event_chain_errors"] == []
        and observed["false_completion_count"] == 0
    )
    return {
        "fault_class": "LINKED_BUT_UNFSYNCED_DIRECTORY_ENTRY",
        "injected_at_state_transition": "RUNNING -> CHECKPOINTED",
        "crash": crash,
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_replace_atomic_crash(root: Path) -> dict[str, Any]:
    """Kill the worker mid-replacement of a controller-owned derived file."""
    sandbox = root / "replace-atomic"
    crash = run_crash(sandbox, "REPLACE_ATOMIC_BEFORE_REPLACE", "po03-c6-043-replace-atomic")
    module = bind(sandbox, "043_replace")
    target = module.CONTROL_ROOT / "recovery-state.json"
    body = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else None
    strays = sorted(
        item.name for item in module.CONTROL_ROOT.iterdir() if item.name.startswith(".recovery-state.json.")
    )
    observed = {
        "previous_generation_intact": body == {"recovery_version": "PO03-RECOVERY-STATE-v1", "generation": 1},
        "observed_generation": None if body is None else body.get("generation"),
        "stray_temporary_entries": strays,
        "target_is_valid_json": body is not None,
    }
    passed = crash["killed_by_sigkill"] and observed["previous_generation_intact"]
    return {
        "fault_class": "CRASH_MID_REPLACEMENT_OF_DERIVED_STATE",
        "injected_at_state_transition": "controller recovery-state regeneration",
        "crash": crash,
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_mid_event_chain(root: Path) -> dict[str, Any]:
    """Kill the worker between two hash-chained events."""
    task_id = "po03-c6-043-mid-chain"
    sandbox = root / "mid-chain"
    crash = run_crash(sandbox, "MID_EVENT_CHAIN", task_id)
    module = bind(sandbox, "043_chain")
    events = event_files(module, task_id)
    observed = {
        "durable_event_files": [path.name for path in events],
        "event_chain_errors": module.verify_chain(task_id),
        "last_state": json.loads(events[-1].read_text(encoding="utf-8"))["state"] if events else None,
        "next_event_sequence_is_contiguous": len(events) == max(
            (json.loads(path.read_text(encoding="utf-8"))["sequence"] for path in events), default=0
        ),
        "false_completion_count": module.scan_recovery("c6-sandbox", "0" * 40)["false_completion_count"],
    }
    passed = (
        crash["killed_by_sigkill"]
        and observed["event_chain_errors"] == []
        and observed["next_event_sequence_is_contiguous"]
        and observed["false_completion_count"] == 0
    )
    return {
        "fault_class": "CRASH_BETWEEN_HASH_CHAINED_EVENTS",
        "injected_at_state_transition": "CHECKPOINTED -> RESULT_STAGING",
        "crash": crash,
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_pre_commit_failure(root: Path) -> dict[str, Any]:
    """Kill the worker after staging bytes in the worktree but before any commit."""
    task_id = "po03-c6-043-pre-commit"
    sandbox = root / "pre-commit"
    crash = run_crash(sandbox, "PRE_COMMIT", task_id)
    module = bind(sandbox, "043_precommit")
    slot = f"workstreams/po03/attempts/{task_id}"
    listing = kit.git(sandbox, "ls-tree", "-r", "--name-only", "HEAD", "--", slot)
    worktree_file = sandbox / slot / "component.json"
    head = kit.git(sandbox, "rev-parse", "HEAD")
    claim = None
    ingestion = None
    if worktree_file.is_file():
        body = worktree_file.read_bytes()
        claim = {
            "task_id": task_id,
            "claimed_sha256": module.sha256_bytes(body),
            "claimed_bytes": len(body),
        }
        # The controller is handed a result that points at HEAD, where the bytes
        # were never committed.  Ingestion must refuse it.
        candidate = {
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "task_id": task_id,
            "commission_id": module.COMMISSION_ID,
            "immutable_input_manifest_sha256": module.sha256_file(
                module.CONTROL_ROOT / "tasks" / task_id / "input.json"
            ),
            "acceptance_contract_sha256": module.sha256_file(
                module.CONTROL_ROOT / "tasks" / task_id / "acceptance.json"
            ),
            "provider_state": "COMPLETED",
            "obzio_state": "RESULT_COMMITTED",
            "attempt": {
                "attempt_id": f"{task_id}-attempt-1",
                "idempotency_key": f"{module.COMMISSION_ID}:{task_id}:attempt-1",
                "lease_id": f"lease-{task_id}-1",
                "fence_token": module.current_fence(task_id),
                "provider_run_id": "sandbox-provider-run-1",
                "worker_id": "worker-a",
                "heartbeat_at": "2026-08-22T07:00:00Z",
                "checkpoint_seq": 1,
            },
            "result_transaction": {
                "result_txn_id": f"result-{task_id}-1",
                "state": "COMMITTED",
                "manifest_uri": f"git:{head}:{slot}/component.json",
                "manifest_sha256": module.sha256_bytes(body),
                "artifact_count": 1,
                "total_bytes": len(body),
                "committed_at": "2026-08-22T07:00:00Z",
                "verified_at": "2026-08-22T07:00:00Z",
                "parent_ingested_at": None,
                "result_commit_id": head,
            },
            "artifacts": [
                {
                    "artifact_id": f"{task_id}-artifact-001",
                    "logical_name": "component.json",
                    "content_uri": f"git:{head}:{slot}/component.json",
                    "sha256": module.sha256_bytes(body),
                    "bytes": len(body),
                    "media_type": "application/json",
                    "readback_verified_at": "2026-08-22T07:00:00Z",
                }
            ],
            "completion_actor": None,
            "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
        }
        ingestion = module.ingest_result(task_id, candidate)
    state = module.scan_recovery("c6-sandbox", "0" * 40)
    observed = {
        "bytes_present_in_worktree": worktree_file.is_file(),
        "bytes_present_in_commit": [item for item in listing.split("\n") if item],
        "uncommitted_claim": claim,
        "ingestion_state": None if ingestion is None else ingestion["obzio_state"],
        "ingestion_errors": [] if ingestion is None else ingestion["errors"],
        "recovery_action": state["units"][task_id]["recovery_action"],
        "false_completion_count": state["false_completion_count"],
        "event_chain_errors": module.verify_chain(task_id),
    }
    passed = (
        crash["killed_by_sigkill"]
        and observed["bytes_present_in_commit"] == []
        and observed["ingestion_state"] == "RECOVERY_REQUIRED"
        and observed["false_completion_count"] == 0
    )
    return {
        "fault_class": "PRE_COMMIT_FAILURE_WITH_UNCOMMITTED_BYTES",
        "injected_at_state_transition": "RESULT_STAGING -> (no commit)",
        "crash": crash,
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_post_commit_failure(root: Path) -> dict[str, Any]:
    """Kill the worker after the durable commit but before the callback."""
    task_id = "po03-c6-043-post-commit"
    sandbox = root / "post-commit"
    crash = run_crash(sandbox, "POST_COMMIT_BEFORE_CALLBACK", task_id)
    module = bind(sandbox, "043_postcommit")
    commits = json.loads(crash["stdout"]) if crash["stdout"] else {}
    slot = f"workstreams/po03/attempts/{task_id}"
    readable = None
    if commits:
        readable = len(module.read_object_bytes(f"git:{commits['result_commit']}:{slot}/result.json"))
    state = module.scan_recovery("c6-sandbox", "0" * 40)
    unit = state["units"][task_id]
    observed = {
        "committed_result_bytes_readable": readable,
        "recovery_action": unit["recovery_action"],
        "scanner_sees_ingested_result": unit["ingested"],
        "ingestion_records": len(sorted((module.CONTROL_ROOT / "tasks" / task_id).glob("ingestion-*.json"))),
        "false_completion_count": state["false_completion_count"],
        "event_chain_errors": module.verify_chain(task_id),
        "immutable_input_available_for_rerun": (module.CONTROL_ROOT / "tasks" / task_id / "input.json").is_file(),
    }
    recoverable_state = bool(readable) and observed["immutable_input_available_for_rerun"]
    passed = crash["killed_by_sigkill"] and recoverable_state and observed["false_completion_count"] == 0
    return {
        "fault_class": "POST_COMMIT_FAILURE_BEFORE_CALLBACK",
        "injected_at_state_transition": "RESULT_COMMITTED -> (no callback)",
        "crash": crash,
        "observed": observed,
        "state_is_recoverable": recoverable_state,
        "automatic_recovery_by_live_scanner": observed["scanner_sees_ingested_result"],
        "verdict": "PASS" if passed else "FAIL",
        "cross_reference": (
            "the committed bytes survive and no false completion appears, but the live scanner "
            "still prescribes a rerun rather than replaying the commit; that gap is recorded as "
            "DEF-PO03-C6-042-LOST-CALLBACK-NOT-REPLAYED"
        ),
    }


def inject_immutable_overwrite(root: Path) -> dict[str, Any]:
    """Rewrite an immutable file with different bytes; the mechanism must refuse."""
    task_id = "po03-c6-043-immutable"
    sandbox = root / "immutable"
    sandbox.mkdir(parents=True, exist_ok=True)
    module = bind(sandbox, "043_immutable")
    kit.init_repository(sandbox)
    kit.seed_capsule(module, task_id, hypothesis="an immutable file cannot be rewritten")
    capsule = module.CONTROL_ROOT / "tasks" / task_id / "input.json"
    original = capsule.read_bytes()
    refused = False
    try:
        module.write_once(capsule, original + b"tamper\n")
    except FileExistsError:
        refused = True
    identical_accepted = True
    try:
        module.write_once(capsule, original)
    except FileExistsError:
        identical_accepted = False
    observed = {
        "differing_payload_refused": refused,
        "identical_payload_is_a_noop": identical_accepted,
        "bytes_unchanged": capsule.read_bytes() == original,
    }
    passed = all(observed.values())
    return {
        "fault_class": "IMMUTABLE_FILE_REWRITE_ATTEMPT",
        "injected_at_state_transition": "CREATED (immutable capsule)",
        "crash": {"crash_point": "NONE_IN_PROCESS_ATTEMPT", "killed_by_sigkill": False},
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


INJECTIONS = (
    inject_partial_write,
    inject_link_without_fsync,
    inject_replace_atomic_crash,
    inject_mid_event_chain,
    inject_pre_commit_failure,
    inject_post_commit_failure,
    inject_immutable_overwrite,
)


def inject_all(root: Path) -> dict[str, Any]:
    results = [injection(root) for injection in INJECTIONS]
    false_completions = sum(
        int(item["observed"].get("false_completion_count", 0) or 0) for item in results
    )
    return {
        "unit": "po03-wa-b2e7-043-partial-and-commit-failure",
        "fault_classes": len(results),
        "results": results,
        "false_completions_observed": false_completions,
        "verdict": "PASS" if all(item["verdict"] == "PASS" for item in results) else "FAIL",
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
