#!/usr/bin/env python3
"""Dependency-free validators for PO-03 result custody and wave compounding.

JSON Schema files document the complete wire format.  This executable enforces
the invariants that must hold even in clean runtimes without third-party
packages.  A producer cannot turn provider completion into Obzio completion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

RESULT_STATES = {
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
    "PROVIDER_COMPLETED_UNCOMMITTED",
    "RECOVERY_REQUIRED",
    "RETRY_SCHEDULED",
    "FAILED_TERMINAL",
    "CANCELLED",
}

TERMINAL_RESULT_STATES = {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"}
PROVIDER_STATES = {"QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "UNKNOWN"}
TRANSACTION_STATES = {"RESERVED", "STAGING", "STAGED", "VERIFIED", "COMMITTED", "INGESTED"}
EXPECTED_TRANSACTION_STATES = {
    "CREATED": {"RESERVED"},
    "LEASED": {"RESERVED"},
    "RUNNING": {"RESERVED"},
    "CHECKPOINTED": {"RESERVED"},
    "RESULT_STAGING": {"STAGING"},
    "RESULT_STAGED": {"STAGED"},
    "RESULT_VERIFIED": {"VERIFIED"},
    "RESULT_COMMITTED": {"COMMITTED"},
    "PARENT_INGESTED": {"INGESTED"},
    "COMPLETED": {"INGESTED"},
    "PROVIDER_COMPLETED_UNCOMMITTED": {"RESERVED"},
    "RECOVERY_REQUIRED": {"RESERVED", "STAGING", "STAGED", "VERIFIED", "COMMITTED", "INGESTED"},
    "RETRY_SCHEDULED": {"RESERVED"},
    "FAILED_TERMINAL": {"RESERVED", "STAGING", "STAGED", "VERIFIED", "COMMITTED", "INGESTED"},
    "CANCELLED": {"RESERVED"},
}


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _required(obj: dict[str, Any], names: tuple[str, ...], prefix: str) -> list[str]:
    return [f"{prefix}.{name}: missing" for name in names if name not in obj]


def _unexpected(obj: dict[str, Any], names: set[str], prefix: str) -> list[str]:
    return [f"{prefix}.{name}: unexpected" for name in sorted(set(obj) - names)]


def validate_result(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = (
        "protocol_version",
        "task_id",
        "commission_id",
        "immutable_input_manifest_sha256",
        "acceptance_contract_sha256",
        "provider_state",
        "obzio_state",
        "attempt",
        "result_transaction",
        "artifacts",
        "completion_actor",
        "independent_acceptance",
    )
    errors.extend(_required(doc, required, "$"))
    errors.extend(_unexpected(doc, set(required), "$"))
    if errors:
        return errors

    if doc["protocol_version"] != "OBZIO-TRANSACTIONAL-RESULT-v1":
        errors.append("$.protocol_version: unsupported")
    for field in ("task_id", "commission_id"):
        if not _nonempty(doc[field]):
            errors.append(f"$.{field}: must be a non-empty string")
    for field in ("immutable_input_manifest_sha256", "acceptance_contract_sha256"):
        if not _sha256(doc[field]):
            errors.append(f"$.{field}: must be a lowercase SHA-256")

    state = doc["obzio_state"]
    provider_state = doc["provider_state"]
    if state not in RESULT_STATES:
        errors.append("$.obzio_state: invalid")
    if provider_state not in PROVIDER_STATES:
        errors.append("$.provider_state: invalid")

    attempt = doc["attempt"]
    if not isinstance(attempt, dict):
        errors.append("$.attempt: must be an object")
        return errors
    errors.extend(
        _required(
            attempt,
            (
                "attempt_id",
                "idempotency_key",
                "lease_id",
                "fence_token",
                "provider_run_id",
                "worker_id",
                "checkpoint_seq",
            ),
            "$.attempt",
        )
    )
    errors.extend(
        _unexpected(
            attempt,
            {
                "attempt_id",
                "idempotency_key",
                "lease_id",
                "fence_token",
                "provider_run_id",
                "worker_id",
                "heartbeat_at",
                "checkpoint_seq",
            },
            "$.attempt",
        )
    )
    if errors:
        return errors
    for field in ("attempt_id", "idempotency_key", "lease_id", "provider_run_id", "worker_id"):
        if not _nonempty(attempt[field]):
            errors.append(f"$.attempt.{field}: must be non-empty")
    if not isinstance(attempt["fence_token"], int) or attempt["fence_token"] < 1:
        errors.append("$.attempt.fence_token: must be an integer >= 1")
    if not isinstance(attempt["checkpoint_seq"], int) or attempt["checkpoint_seq"] < 0:
        errors.append("$.attempt.checkpoint_seq: must be an integer >= 0")

    txn = doc["result_transaction"]
    if not isinstance(txn, dict):
        errors.append("$.result_transaction: must be an object")
        return errors
    txn_required = (
        "result_txn_id",
        "state",
        "manifest_uri",
        "manifest_sha256",
        "artifact_count",
        "total_bytes",
        "committed_at",
        "verified_at",
        "parent_ingested_at",
        "result_commit_id",
    )
    errors.extend(_required(txn, txn_required, "$.result_transaction"))
    errors.extend(_unexpected(txn, set(txn_required), "$.result_transaction"))
    if errors:
        return errors
    if txn["state"] not in TRANSACTION_STATES:
        errors.append("$.result_transaction.state: invalid")
    elif state in EXPECTED_TRANSACTION_STATES and txn["state"] not in EXPECTED_TRANSACTION_STATES[state]:
        errors.append("$.result_transaction.state: incompatible with $.obzio_state")

    artifacts = doc["artifacts"]
    if not isinstance(artifacts, list):
        errors.append("$.artifacts: must be an array")
        return errors
    if txn["artifact_count"] != len(artifacts):
        errors.append("$.result_transaction.artifact_count: does not match artifacts")
    byte_sum = 0
    artifact_ids: set[str] = set()
    for index, artifact in enumerate(artifacts):
        prefix = f"$.artifacts[{index}]"
        if not isinstance(artifact, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        errors.extend(
            _required(
                artifact,
                ("artifact_id", "logical_name", "content_uri", "sha256", "bytes", "media_type", "readback_verified_at"),
                prefix,
            )
        )
        if any(name not in artifact for name in ("artifact_id", "logical_name", "content_uri", "sha256", "bytes", "media_type", "readback_verified_at")):
            continue
        errors.extend(
            _unexpected(
                artifact,
                {"artifact_id", "logical_name", "content_uri", "sha256", "bytes", "media_type", "readback_verified_at"},
                prefix,
            )
        )
        if artifact["artifact_id"] in artifact_ids:
            errors.append(f"{prefix}.artifact_id: duplicate")
        artifact_ids.add(artifact["artifact_id"])
        for field in ("artifact_id", "logical_name", "content_uri", "media_type"):
            if not _nonempty(artifact[field]):
                errors.append(f"{prefix}.{field}: must be non-empty")
        if not _sha256(artifact["sha256"]):
            errors.append(f"{prefix}.sha256: must be a lowercase SHA-256")
        if not isinstance(artifact["bytes"], int) or artifact["bytes"] < 0:
            errors.append(f"{prefix}.bytes: must be an integer >= 0")
        else:
            byte_sum += artifact["bytes"]
    if txn["total_bytes"] != byte_sum:
        errors.append("$.result_transaction.total_bytes: does not match artifact bytes")

    committed = state in TERMINAL_RESULT_STATES
    uncommitted_states = {"CREATED", "LEASED", "RUNNING", "CHECKPOINTED", "RETRY_SCHEDULED", "CANCELLED"}
    if state in uncommitted_states:
        if txn["result_commit_id"] is not None or txn["committed_at"] is not None:
            errors.append("$.result_transaction: uncommitted state cannot claim a result commit")
        if artifacts:
            errors.append("$.artifacts: uncommitted state cannot expose committed artifacts")
    if committed:
        for field in ("manifest_uri", "manifest_sha256", "committed_at", "verified_at", "result_commit_id"):
            if not _nonempty(txn[field]):
                errors.append(f"$.result_transaction.{field}: required after result commit")
        if txn["manifest_sha256"] is not None and not _sha256(txn["manifest_sha256"]):
            errors.append("$.result_transaction.manifest_sha256: invalid")
        if not artifacts:
            errors.append("$.artifacts: committed result requires at least one artifact")
        for index, artifact in enumerate(artifacts):
            if isinstance(artifact, dict) and not _nonempty(artifact.get("readback_verified_at")):
                errors.append(f"$.artifacts[{index}].readback_verified_at: required after result commit")

    if state in {"PARENT_INGESTED", "COMPLETED"} and not _nonempty(txn["parent_ingested_at"]):
        errors.append("$.result_transaction.parent_ingested_at: required after parent ingestion")
    if state in {
        "RESULT_STAGING",
        "RESULT_STAGED",
        "RESULT_VERIFIED",
        "RESULT_COMMITTED",
        "PARENT_INGESTED",
        "COMPLETED",
        "PROVIDER_COMPLETED_UNCOMMITTED",
    } and provider_state != "COMPLETED":
        errors.append("$.provider_state: custody after provider completion requires COMPLETED")
    if state == "PARENT_INGESTED" and doc["completion_actor"] is not None:
        errors.append("$.completion_actor: parent ingestion is not coordinator completion")
    if state == "COMPLETED" and doc["completion_actor"] != "coordinator":
        errors.append("$.completion_actor: only coordinator may set COMPLETED")
    if provider_state == "COMPLETED" and not _nonempty(txn["result_commit_id"]):
        if state != "PROVIDER_COMPLETED_UNCOMMITTED":
            errors.append(
                "$.obzio_state: provider completion without result commit must be PROVIDER_COMPLETED_UNCOMMITTED"
            )

    acceptance = doc["independent_acceptance"]
    if not isinstance(acceptance, dict):
        errors.append("$.independent_acceptance: must be an object")
    else:
        errors.extend(_required(acceptance, ("state", "reviewer_id", "receipt_uri"), "$.independent_acceptance"))
        errors.extend(
            _unexpected(
                acceptance,
                {"state", "reviewer_id", "receipt_uri"},
                "$.independent_acceptance",
            )
        )
        if acceptance.get("state") not in {"NOT_TESTED", "PENDING", "ACCEPTED", "REJECTED"}:
            errors.append("$.independent_acceptance.state: invalid")
        if acceptance.get("state") in {"ACCEPTED", "REJECTED"}:
            if not _nonempty(acceptance.get("reviewer_id")) or not _nonempty(acceptance.get("receipt_uri")):
                errors.append("$.independent_acceptance: terminal review requires reviewer_id and receipt_uri")
            if state != "COMPLETED":
                errors.append("$.independent_acceptance: terminal review requires COMPLETED result")
            if acceptance.get("reviewer_id") == attempt.get("worker_id"):
                errors.append("$.independent_acceptance.reviewer_id: producer cannot self-accept")

    return errors


def validate_wave(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = (
        "protocol_version",
        "wave_id",
        "baseline",
        "observations",
        "challenges",
        "external_hypotheses",
        "reproductions",
        "live_mechanism_changes",
        "independent_tests",
        "dispositions",
        "successor_manifest_uri",
        "decision_changed",
    )
    errors.extend(_required(doc, required, "$"))
    errors.extend(_unexpected(doc, set(required), "$"))
    if errors:
        return errors
    if doc["protocol_version"] != "OBZIO-WAVE-COMPOUNDING-v1":
        errors.append("$.protocol_version: unsupported")
    if not _nonempty(doc["wave_id"]) or not _nonempty(doc["successor_manifest_uri"]):
        errors.append("$.wave_id and $.successor_manifest_uri must be non-empty")
    if doc["decision_changed"] != []:
        errors.append("$.decision_changed: founder correction requires []")
    baseline = doc["baseline"]
    if not isinstance(baseline, dict) or not _nonempty(baseline.get("metrics_uri")) or not _sha256(baseline.get("sha256")):
        errors.append("$.baseline: requires metrics_uri and lowercase SHA-256")
    for field in (
        "observations",
        "challenges",
        "external_hypotheses",
        "reproductions",
        "live_mechanism_changes",
        "independent_tests",
        "dispositions",
    ):
        if not isinstance(doc[field], list) or not doc[field]:
            errors.append(f"$.{field}: must be a non-empty array")
    return errors


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("root must be a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("result", "wave"))
    parser.add_argument("document", type=Path)
    args = parser.parse_args(argv)
    try:
        doc = _load(args.document)
        errors = validate_result(doc) if args.kind == "result" else validate_wave(doc)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}")
        return 2
    if errors:
        for error in errors:
            print(f"INVALID: {error}")
        return 1
    digest = hashlib.sha256(args.document.read_bytes()).hexdigest()
    print(f"VALID {args.kind} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
