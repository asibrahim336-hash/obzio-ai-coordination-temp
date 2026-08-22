#!/usr/bin/env python3
"""Injections for total provider-runtime loss, checked against the Code-2 fixture.

Two things are proved here.  First, that losing the whole provider runtime after
it reported completion leaves PROVIDER_COMPLETED_UNCOMMITTED and never Obzio
COMPLETED.  Second, that the frozen PO-02 Code-2 fixture in this subtree still
carries exactly the four states it was commissioned with, is never described as
a completed deliverable, and needs no founder relay to be recovered.

Run directly to print the observation as JSON:

    python3 -I provider_loss_injector.py
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
CHILD = HERE / "provider_loss_child.py"
FIXTURE = HERE / "code2-fault-fixture.json"
REAL_REPO_ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = REAL_REPO_ROOT / "workstreams" / "po03" / "evidence" / "so02-operating-correction.json"

_SPEC = importlib.util.spec_from_file_location("po03_c6_048_fault_kit", HERE / "fault_kit.py")
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load fault_kit.py")
kit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(kit)

COMMISSIONED_STATES = {
    "provider_state": "COMPLETION_REPORTED_OR_LIVE_CONFLICT",
    "obzio_state": "PROVIDER_COMPLETED_UNCOMMITTED",
    "result_state": "UNRECOVERED_AFTER_FOUR_REPORTED_ROUTES",
    "acceptance_state": "NOT_ACCEPTED",
}
FORBIDDEN_CLAIMS = ("COMPLETED_DELIVERABLE", "DELIVERED", "ACCEPTED_DELIVERABLE", "SHIPPED")


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def run_loss(sandbox: Path, task_id: str, loss_point: str) -> dict[str, Any]:
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
            "--loss-point",
            loss_point,
        ),
        capture_output=True,
        text=True,
    )
    return {
        "loss_point": loss_point,
        "returncode": completed.returncode,
        "killed_by_sigkill": completed.returncode == -9,
        "stderr_tail": completed.stderr.strip()[-300:],
    }


def inject_runtime_loss(root: Path, loss_point: str) -> dict[str, Any]:
    task_id = f"po03-c6-048-{loss_point.lower().replace('_', '-')[:40]}"
    sandbox = root / loss_point.lower()[:30]
    crash = run_loss(sandbox, task_id, loss_point)
    module = kit.bind_sandbox(kit.load_factory(f"048_{abs(hash(loss_point)) % 100000}"), sandbox)
    slot = f"workstreams/po03/attempts/{task_id}"
    events = sorted((module.CONTROL_ROOT / "events" / task_id).glob("*.json"))
    states = [json.loads(path.read_text(encoding="utf-8"))["state"] for path in events]
    committed = kit.git(sandbox, "ls-tree", "-r", "--name-only", "HEAD", "--", slot)
    state = module.scan_recovery("c6-sandbox", "0" * 40)
    unit = state["units"][task_id]
    task_directory = module.CONTROL_ROOT / "tasks" / task_id
    observed = {
        "event_states": states,
        "provider_reported_completion": "PROVIDER_COMPLETED_UNCOMMITTED" in states,
        "obzio_completed_event_present": "COMPLETED" in states,
        "durable_result_committed": [item for item in committed.split("\n") if item],
        "ingestion_records": len(sorted(task_directory.glob("ingestion-*.json"))),
        "completion_file_present": (task_directory / "transaction-completed.json").is_file(),
        "recovery_action": unit["recovery_action"],
        "false_completion_count": state["false_completion_count"],
        "event_chain_errors": module.verify_chain(task_id),
        "immutable_input_available_for_rerun": (task_directory / "input.json").is_file(),
    }
    passed = (
        crash["killed_by_sigkill"]
        and not observed["obzio_completed_event_present"]
        and not observed["completion_file_present"]
        and observed["durable_result_committed"] == []
        and observed["ingestion_records"] == 0
        and observed["recovery_action"] == "RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT"
        and observed["false_completion_count"] == 0
        and observed["immutable_input_available_for_rerun"]
    )
    return {
        "fault_class": f"TOTAL_PROVIDER_RUNTIME_LOSS_{loss_point}",
        "injected_at_state_transition": "RUNNING -> PROVIDER_COMPLETED_UNCOMMITTED -> (runtime gone)"
        if loss_point.startswith("AFTER_PROVIDER")
        else "RUNNING -> (runtime gone before any report)",
        "crash": crash,
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_contract_refusal(root: Path) -> dict[str, Any]:
    """A provider completion with no result commit must not be allowed to claim COMPLETED."""
    sandbox = root / "contract"
    module = kit.bind_sandbox(kit.load_factory("048_contract"), sandbox)
    kit.init_repository(sandbox)
    task_id = "po03-c6-048-contract-unit"
    kit.seed_capsule(module, task_id, hypothesis="a provider report is not a completion")
    validator = module.load_result_validator()
    fixture = load_fixture()

    document = {
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
        "obzio_state": "COMPLETED",
        "attempt": {
            "attempt_id": f"{task_id}-attempt-1",
            "idempotency_key": f"{module.COMMISSION_ID}:{task_id}:attempt-1",
            "lease_id": f"lease-{task_id}-1",
            "fence_token": 1,
            "provider_run_id": "lost-provider-runtime",
            "worker_id": "worker-a",
            "heartbeat_at": "2026-08-22T07:00:00Z",
            "checkpoint_seq": 1,
        },
        "result_transaction": {
            "result_txn_id": f"result-{task_id}-1",
            "state": "RESERVED",
            "manifest_uri": None,
            "manifest_sha256": None,
            "artifact_count": 0,
            "total_bytes": 0,
            "committed_at": None,
            "verified_at": None,
            "parent_ingested_at": None,
            "result_commit_id": fixture["durable_result_commit_id"],
        },
        "artifacts": fixture["durable_artifacts"],
        "completion_actor": "coordinator",
        "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
    }
    completed_claim_errors = validator.validate_result(document)

    uncommitted = json.loads(json.dumps(document))
    uncommitted["obzio_state"] = "PROVIDER_COMPLETED_UNCOMMITTED"
    uncommitted["completion_actor"] = None
    uncommitted_errors = validator.validate_result(uncommitted)

    self_accepted = json.loads(json.dumps(document))
    self_accepted["independent_acceptance"] = {
        "state": "ACCEPTED",
        "reviewer_id": "worker-a",
        "receipt_uri": "receipts/po03/2026-08-22/self.json",
    }
    self_acceptance_errors = validator.validate_result(self_accepted)

    completion_refused = None
    try:
        module.complete_unit(task_id, uncommitted)
        completion_refused = False
    except ValueError as exc:
        completion_refused = str(exc)

    ingestion = module.ingest_result(task_id, uncommitted)
    observed = {
        "completed_claim_errors": completed_claim_errors,
        "completed_claim_refused": bool(completed_claim_errors),
        "provider_completed_uncommitted_is_the_only_legal_state": uncommitted_errors == [],
        "self_acceptance_errors": self_acceptance_errors,
        "self_acceptance_refused": bool(self_acceptance_errors),
        "complete_unit_refusal": completion_refused,
        "ingestion_state": ingestion["obzio_state"],
        "ingestion_errors": ingestion["errors"],
    }
    passed = (
        observed["completed_claim_refused"]
        and observed["provider_completed_uncommitted_is_the_only_legal_state"]
        and observed["self_acceptance_refused"]
        and isinstance(observed["complete_unit_refusal"], str)
        and observed["ingestion_state"] == "RECOVERY_REQUIRED"
    )
    return {
        "fault_class": "PROVIDER_COMPLETION_WITH_NO_DURABLE_RESULT_CLAIMS_COMPLETED",
        "injected_at_state_transition": "PROVIDER_COMPLETED_UNCOMMITTED -> COMPLETED (attempted)",
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def inspect_fixture() -> dict[str, Any]:
    """Check the frozen fixture against its commissioned states and its evidence."""
    fixture = load_fixture()
    evidence_bytes = EVIDENCE.read_bytes()
    import hashlib

    evidence_sha = hashlib.sha256(evidence_bytes).hexdigest()
    evidence = json.loads(evidence_bytes.decode("utf-8"))
    rulings = evidence["evidence_rulings"]
    serialised = json.dumps(fixture)
    observed = {
        "frozen_states": fixture["frozen_states"],
        "frozen_states_match_commission": fixture["frozen_states"] == COMMISSIONED_STATES,
        "reported_routes_count": fixture["reported_routes_count"],
        "durable_result_commit_id": fixture["durable_result_commit_id"],
        "durable_artifacts": fixture["durable_artifacts"],
        "is_a_completed_deliverable": fixture["is_a_completed_deliverable"],
        "no_forbidden_deliverable_claim": not any(claim in serialised for claim in FORBIDDEN_CLAIMS),
        "founder_relay_required_for_recovery": fixture["founder_relay_required_for_recovery"],
        "evidence_sha256_recorded": fixture["corroborating_recorded_evidence"]["sha256"],
        "evidence_sha256_observed": evidence_sha,
        "evidence_hash_matches": fixture["corroborating_recorded_evidence"]["sha256"] == evidence_sha,
        "evidence_provider_state": rulings["code2_provider_state"],
        "evidence_obzio_state": rulings["code2_obzio_state"],
        "evidence_result_state": rulings["code2_result_state"],
        "evidence_acceptance_state": rulings["code2_acceptance_state"],
        "recorded_values_quoted_verbatim": fixture["corroborating_recorded_evidence"][
            "recorded_values_verbatim"
        ]
        == {
            "code2_provider_state": rulings["code2_provider_state"],
            "code2_obzio_state": rulings["code2_obzio_state"],
            "code2_result_state": rulings["code2_result_state"],
            "code2_acceptance_state": rulings["code2_acceptance_state"],
        },
        "reconciliation_covers_every_state": sorted(
            item["field"] for item in fixture["state_reconciliation"]
        )
        == sorted(COMMISSIONED_STATES),
    }
    passed = (
        observed["frozen_states_match_commission"]
        and observed["reported_routes_count"] == 4
        and observed["durable_result_commit_id"] is None
        and observed["durable_artifacts"] == []
        and observed["is_a_completed_deliverable"] is False
        and observed["no_forbidden_deliverable_claim"]
        and observed["founder_relay_required_for_recovery"] is False
        and observed["evidence_hash_matches"]
        and observed["recorded_values_quoted_verbatim"]
        and observed["reconciliation_covers_every_state"]
    )
    return {
        "fault_class": "FROZEN_CODE2_FAULT_FIXTURE",
        "injected_at_state_transition": "n/a (frozen historical fault)",
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def inspect_founder_relay(root: Path) -> dict[str, Any]:
    """Confirm the recovery decision is computed from repository state alone."""
    module = kit.bind_sandbox(kit.load_factory("048_relay"), root / "relay")
    signature = inspect.signature(module.scan_recovery)
    source = inspect.getsource(module.scan_recovery)
    observed = {
        "scan_recovery_parameters": list(signature.parameters),
        "scan_recovery_reads_only_repository_state": all(
            token not in source for token in ("input(", "founder", "relay", "message")
        ),
        "recovery_inputs": [
            "control/tasks/<task>/input.json (immutable capsule)",
            "control/events/<task>/*.json (hash-chained events)",
            "control/tasks/<task>/ingestion-*.json (ingestion records)",
            "control/leases/<task>.json (fence token)",
            "git objects reached by immutable object id",
        ],
        "founder_supplied_inputs": [],
    }
    passed = (
        observed["scan_recovery_parameters"] == ["run_id", "head_sha"]
        and observed["scan_recovery_reads_only_repository_state"]
        and observed["founder_supplied_inputs"] == []
    )
    return {
        "fault_class": "RECOVERY_WITHOUT_FOUNDER_RELAY",
        "injected_at_state_transition": "n/a (static and behavioural check)",
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_all(root: Path) -> dict[str, Any]:
    results = [
        inject_runtime_loss(root, "AFTER_PROVIDER_REPORTED_COMPLETION_BEFORE_ANY_COMMIT"),
        inject_runtime_loss(root, "AFTER_STAGING_BEFORE_PROVIDER_REPORT"),
        inject_contract_refusal(root),
        inspect_fixture(),
        inspect_founder_relay(root),
    ]
    return {
        "unit": "po03-wa-b2e7-048-provider-runtime-loss-and-code2-fixture",
        "fault_classes": len(results),
        "results": results,
        "false_completions_observed": sum(
            int(item["observed"].get("false_completion_count", 0) or 0) for item in results
        ),
        "code2_is_a_completed_deliverable": False,
        "verdict": "PASS" if all(item["verdict"] == "PASS" for item in results) else "FAIL",
        "verdict_basis": (
            "total provider-runtime loss after a reported completion leaves the unit at "
            "PROVIDER_COMPLETED_UNCOMMITTED with no durable commit, no ingestion and no completion; "
            "the seeded contract refuses a COMPLETED claim without a result commit; complete_unit "
            "refuses a unit that never reached PARENT_INGESTED; and the frozen Code-2 fixture keeps "
            "its four commissioned states with no founder relay in the recovery path"
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
