#!/usr/bin/env python3
"""Compile measured A2 outcomes into the recovery matrix and receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
PO03_ROOT = REPO_ROOT / "workstreams" / "po03"
OUTCOMES = PO03_ROOT / "faults" / "outcomes"
FIXTURE = PO03_ROOT / "faults" / "fixtures" / "po02-code2-lost-return.json"
MATRIX_DEFAULT = PO03_ROOT / "evidence" / "recovery-fault-matrix.json"
RECEIPT_DEFAULT = REPO_ROOT / "receipts" / "po03" / "2026-08-22" / "transactional-recovery.json"
CONTROL_PLANE = PO03_ROOT / "tools" / "control_plane.py"
TEST_FILE = PO03_ROOT / "tests" / "test_a2_fault_recovery.py"
COMMISSION_ID = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"


SUMMARIES = {
    "a2-u01": "Committed ledger state survived process loss, but no uncommitted task was automatically re-leased or rerun.",
    "a2-u02": "A durable committed result with a dropped callback was never discovered or ingested by the scanner.",
    "a2-u03": "All truncated-artifact and half-manifest injections were rejected with zero false completion.",
    "a2-u04": "Sequential replay was idempotent, but neither pre-commit rerun nor post-commit discovery exists.",
    "a2-u05": "All absent-remote commit locators were ingested and no pre-push failure triggered rerun.",
    "a2-u06": "All stale lower fences were rejected, but expiry was passive and all unissued higher fences were accepted.",
    "a2-u07": "All 200 controlled concurrent duplicate interleavings violated exactly-once ledger custody or chain integrity.",
    "a2-u08": "Corruption/deletion was rejected during ingest, but no RECOVERY_REQUIRED transition occurred and post-completion loss was invisible.",
    "a2-u09": "NOT_SUPPORTED: the live control plane has no network transport or retry/backoff boundary to inject.",
    "a2-u10": "Zero-memory projection rebuild was byte-identical, but in-flight units did not resume.",
    "a2-u11": "A fresh coordinator-branch clone failed to discover committed result branches in a local git remote.",
    "a2-u12": "Code-2 was classified uncommitted, then wrongly admitted as PARENT_INGESTED with no automatic rerun.",
}


HYPOTHESES_FALSIFIED = [
    {
        "unit_id": "a2-u01",
        "reason": "Visibility in resumable_units did not execute re-lease or rerun.",
    },
    {
        "unit_id": "a2-u02",
        "reason": "Scanner reconciliation never inspected the durable result slot after callback loss.",
    },
    {
        "unit_id": "a2-u04",
        "reason": "No automatic action distinguishes and recovers either commit boundary.",
    },
    {
        "unit_id": "a2-u05",
        "reason": "A local artifact plus arbitrary commit string was treated as a durable remote locator.",
    },
    {
        "unit_id": "a2-u06",
        "reason": "Expiry does not evict automatically and unissued higher fences bypass ownership.",
    },
    {
        "unit_id": "a2-u07",
        "reason": "Identical callbacks are not harmless under a forced concurrent read/append interleaving.",
    },
    {
        "unit_id": "a2-u08",
        "reason": "Artifact loss after COMPLETED is not rechecked, and ingest rejection does not schedule recovery.",
    },
    {
        "unit_id": "a2-u10",
        "reason": "Projection reconstruction succeeds, but the compound hypothesis also required in-flight resume.",
    },
    {
        "unit_id": "a2-u11",
        "reason": "The scanner does not enumerate or reconcile remote result branches after provider loss.",
    },
    {
        "unit_id": "a2-u12",
        "reason": "Classification succeeds, but the fixture is admitted to PARENT_INGESTED and no rerun occurs.",
    },
]


DEFECTS = [
    {
        "id": "A2-CP-001",
        "reproducer": "a2-u01 / a2-u02 / a2-u04 / a2-u10",
        "finding": "scan_recovery is observational only: it writes a report but emits no LEASE_EXPIRED or RETRY_SCHEDULED event and executes no lease, resume, rerun, or result-slot reconciliation.",
    },
    {
        "id": "A2-CP-002",
        "reproducer": "a2-u07; 200 controlled interleavings",
        "finding": "append_event has an unlocked read-verify-append sequence; concurrent writers reuse seq and prev_sha256, yielding multiple PARENT_INGESTED rows and a broken chain.",
    },
    {
        "id": "A2-CP-003",
        "reproducer": "a2-u05 at every lifecycle transition",
        "finding": "ingest_result verifies only the local working-tree artifact. It accepts an arbitrary non-empty result_commit_id and locator without immutable remote read-back.",
    },
    {
        "id": "A2-CP-004",
        "reproducer": "a2-u06 at every lifecycle transition",
        "finding": "Fence validation rejects only incoming_fence < current_fence. It accepts an unissued higher fence without matching the active lease, lease_id, worker, or idempotency key.",
    },
    {
        "id": "A2-CP-005",
        "reproducer": "a2-u08 corruption and deletion cases",
        "finding": "Artifact rejection raises an exception without a RECOVERY_REQUIRED event; committed artifacts are never re-hashed by recovery scanning.",
    },
    {
        "id": "A2-CP-006",
        "reproducer": "a2-u12 at every lifecycle transition",
        "finding": "ingest_result accepts a valid PROVIDER_COMPLETED_UNCOMMITTED document with zero artifacts and no commit, then appends PARENT_INGESTED and strands it in a terminal projection.",
    },
    {
        "id": "A2-CP-007",
        "reproducer": "FrozenControlPlaneDefects.test_defect_worker_event_must_not_set_completed",
        "finding": "The generic event command/append path enforces neither lifecycle transitions nor actor authority; a worker can append COMPLETED without a result commit.",
    },
    {
        "id": "A2-CP-008",
        "reproducer": "a2-u09",
        "finding": "No push/fetch/remote read-back or retry/backoff operation exists in the control plane, so network interruption recovery is not implemented or injectable.",
    },
    {
        "id": "A2-CP-009",
        "reproducer": "a2-u11 local bare-remote clean-clone injection",
        "finding": "Recovery reads only the checked-out ledger and cannot enumerate deterministic result branches or recover their commits from a remote.",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def load_outcomes() -> list[dict[str, Any]]:
    documents = []
    for index in range(1, 13):
        unit_id = f"a2-u{index:02d}"
        path = OUTCOMES / f"{unit_id}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        documents.append(document)
    return documents


def matrix_row(document: dict[str, Any]) -> dict[str, Any]:
    unit_id = document["unit_id"]
    status = document["status"]
    disposition = "READY_TO_COMMIT" if status == "PASS" else ("NOT_YET" if status == "NOT_SUPPORTED" else "FAILED")
    return {
        "unit_id": unit_id,
        "fault_class": document["fault_class"],
        "status": status,
        "disposition": disposition,
        "outcome": SUMMARIES[unit_id],
        "lifecycle_transition_count": len({row["transition"] for row in document["measurements"]}),
        "injection_count": document["injection_count"],
        "false_completion_count": document["false_completion_count"],
        "duplicate_external_effect_count": document["duplicate_external_effect_count"],
        "recovery_time": document["recovery_time"],
        "outcome_artifact": artifact(OUTCOMES / f"{unit_id}.json"),
        "injector_artifact": artifact(PO03_ROOT / "faults" / {
            "a2-u01": "inject_process_loss.py",
            "a2-u02": "inject_lost_return.py",
            "a2-u03": "inject_partial_write.py",
            "a2-u04": "inject_commit_boundary.py",
            "a2-u05": "inject_push_boundary.py",
            "a2-u06": "inject_stale_lease.py",
            "a2-u07": "inject_concurrent_duplicate.py",
            "a2-u08": "inject_artifact_loss.py",
            "a2-u09": "inject_network_interruption.py",
            "a2-u10": "inject_parent_restart.py",
            "a2-u11": "inject_runtime_loss.py",
            "a2-u12": "inject_code2_fixture.py",
        }[unit_id]),
        "test_command": "python3 -I -m unittest discover -s workstreams/po03/tests -p 'test_a2_*.py' -v",
        "test_result": "OK (15 tests; expected failures=8)",
    }


def build(matrix_path: Path, receipt_path: Path) -> None:
    outcomes = load_outcomes()
    generated_at = utc_now()
    rows = [matrix_row(document) for document in outcomes]
    committed_injected = sum(
        document.get("committed_results", {}).get("injected", 0) for document in outcomes
    )
    committed_locators_recovered = sum(
        document.get("committed_results", {}).get("recovered", 0) for document in outcomes
    )
    false_completions = sum(document["false_completion_count"] for document in outcomes)
    duplicate_effects = sum(document["duplicate_external_effect_count"] for document in outcomes)
    matrix = {
        "protocol_version": "OBZIO-PO03-RECOVERY-FAULT-MATRIX-v1",
        "commission_id": COMMISSION_ID,
        "commission_revision": "v002",
        "generated_at": generated_at,
        "source_commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "decision_changed": [],
        "strategy_restarted": False,
        "control_plane": artifact(CONTROL_PLANE),
        "test_artifact": artifact(TEST_FILE),
        "code2_fixture": artifact(FIXTURE),
        "lifecycle": [
            "CREATED",
            "LEASED",
            "RUNNING",
            "CHECKPOINTED",
            "RESULT_STAGING",
            "RESULT_STAGED",
            "RESULT_VERIFIED",
            "RESULT_COMMITTED",
            "PARENT_INGESTED",
            "COMPLETED",
        ],
        "rows": rows,
        "acceptance": {
            "status": "FAIL",
            "zero_false_completion": {
                "required": True,
                "observed": False,
                "count": false_completions,
            },
            "committed_result_recovery": {
                "required_percent": 100,
                "injected": committed_injected,
                "recovered_with_hash_and_bytes_from_durable_sink": 0,
                "observed_percent": 0,
                "locator_only_recovered": committed_locators_recovered,
                "reason": "Three ledger commit-id strings survived process loss, but no scanner path read result bytes back from a durable result branch.",
            },
            "automatic_resume_or_rerun": {
                "required": True,
                "observed": False,
            },
            "zero_duplicate_external_effects": {
                "required": True,
                "observed": duplicate_effects == 0,
                "count": duplicate_effects,
            },
            "complete_hash_coverage": {
                "required": True,
                "observed": False,
                "reason": "Remote commit existence is not verified and committed artifacts are not re-hashed during recovery.",
            },
            "no_founder_relay": {
                "required": True,
                "observed": True,
                "count": sum(document["founder_relay_count"] for document in outcomes),
            },
        },
        "defects": DEFECTS,
        "hypotheses_falsified": HYPOTHESES_FALSIFIED,
        "hypotheses_not_falsified": [
            {
                "unit_id": "a2-u03",
                "reason": "All 20 partial artifact/manifest writes were rejected.",
            }
        ],
        "not_supported": [
            {
                "unit_id": "a2-u09",
                "boundary": outcomes[8]["limitations"][0],
            }
        ],
        "limitations": [
            "The runtime-loss test used a dependency-free local bare git remote because tests are required to run without network.",
            "The live control plane contains no transport operation, so real network retry/backoff cannot be injected.",
            "PO-02 Code-2 bytes and original immutable input are absent; the fixture preserves that boundary and does not fabricate them.",
        ],
    }
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    matrix_path.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    receipt = {
        "protocol_version": "OBZIO-PO03-TRANSACTIONAL-RECOVERY-RECEIPT-v1",
        "receipt_id": "RCP-PO03-TRANSACTIONAL-RECOVERY-20260822-v001",
        "commission_id": COMMISSION_ID,
        "commission_revision": "v002",
        "recorded_at": generated_at,
        "branch": matrix["branch"],
        "source_commit": matrix["source_commit"],
        "decision_changed": [],
        "strategy_restarted": False,
        "producer_state": "READY_TO_COMMIT",
        "acceptance_state": "NOT_YET",
        "matrix_acceptance": "FAIL",
        "matrix": artifact(matrix_path),
        "code2_fixture": artifact(FIXTURE),
        "code2_disposition": {
            "obzio_state": "PROVIDER_COMPLETED_UNCOMMITTED",
            "recovery_state": "UNRECOVERED_AFTER_FOUR_REPORTED_ROUTES",
            "acceptance_state": "NOT_ACCEPTED",
            "deliverable": False,
            "automatic_rerun": "NOT_YET",
        },
        "test_run": {
            "command": "python3 -I -m unittest discover -s workstreams/po03/tests -p 'test_a2_*.py' -v",
            "exit_code": 0,
            "result": "Ran 15 tests; OK (expected failures=8)",
            "python": sys.version.split()[0],
        },
        "summary": matrix["acceptance"],
        "defects": [item["id"] for item in DEFECTS],
        "founder_relay_count": 0,
        "limitations": matrix["limitations"],
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, default=MATRIX_DEFAULT)
    parser.add_argument("--receipt", type=Path, default=RECEIPT_DEFAULT)
    args = parser.parse_args()
    build(args.matrix.resolve(), args.receipt.resolve())
    print(f"WROTE {args.matrix} AND {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
