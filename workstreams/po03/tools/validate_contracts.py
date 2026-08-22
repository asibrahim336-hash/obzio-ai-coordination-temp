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

RESULT_TOP_LEVEL_KEYS = frozenset({
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
})

ATTEMPT_KEYS = frozenset({
    "attempt_id",
    "idempotency_key",
    "lease_id",
    "fence_token",
    "provider_run_id",
    "worker_id",
    "heartbeat_at",
    "checkpoint_seq",
})

RESULT_TRANSACTION_KEYS = frozenset({
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
})

ARTIFACT_KEYS = frozenset({
    "artifact_id",
    "logical_name",
    "content_uri",
    "sha256",
    "bytes",
    "media_type",
    "readback_verified_at",
})

ACCEPTANCE_KEYS = frozenset({"state", "reviewer_id", "receipt_uri"})

WAVE_TOP_LEVEL_KEYS = frozenset({
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
})


def _unexpected(obj: Any, allowed: frozenset[str], prefix: str) -> list[str]:
    if not isinstance(obj, dict):
        return []
    return [
        f"{prefix}.{name}: not permitted by the contract"
        for name in sorted(set(obj) - allowed)
    ]


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _required(obj: dict[str, Any], names: tuple[str, ...], prefix: str) -> list[str]:
    return [f"{prefix}.{name}: missing" for name in names if name not in obj]


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
    errors.extend(_unexpected(doc, RESULT_TOP_LEVEL_KEYS, "$"))
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
    errors.extend(_unexpected(attempt, ATTEMPT_KEYS, "$.attempt"))
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
    errors.extend(_unexpected(txn, RESULT_TRANSACTION_KEYS, "$.result_transaction"))
    if errors:
        return errors

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
        errors.extend(_unexpected(artifact, ARTIFACT_KEYS, prefix))
        if any(name not in artifact for name in ("artifact_id", "logical_name", "content_uri", "sha256", "bytes", "media_type", "readback_verified_at")):
            continue
        if artifact["artifact_id"] in artifact_ids:
            errors.append(f"{prefix}.artifact_id: duplicate")
        artifact_ids.add(artifact["artifact_id"])
        for field in ("artifact_id", "logical_name", "content_uri", "media_type"):
            if not _nonempty(artifact[field]):
                errors.append(f"{prefix}.{field}: must be non-empty")
        if not _sha256(artifact["sha256"]):
            errors.append(f"{prefix}.sha256: must be a lowercase SHA-256")
        if not isinstance(artifact["bytes"], int) or artifact["bytes"] < 1:
            errors.append(f"{prefix}.bytes: must be an integer >= 1")
        else:
            byte_sum += artifact["bytes"]
    if txn["total_bytes"] != byte_sum:
        errors.append("$.result_transaction.total_bytes: does not match artifact bytes")

    committed = state in TERMINAL_RESULT_STATES
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
        errors.extend(_unexpected(acceptance, ACCEPTANCE_KEYS, "$.independent_acceptance"))
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
    errors.extend(_unexpected(doc, WAVE_TOP_LEVEL_KEYS, "$"))
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


VALIDATORS = {"result": validate_result, "wave": validate_wave}

EXCLUDED_DIRECTORY_NAMES = frozenset({"__pycache__"})


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("root must be a JSON object")
    return data


def iter_json_documents(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob("*.json")
        if path.is_file() and not EXCLUDED_DIRECTORY_NAMES.intersection(path.parts)
    )


def validate_document(kind: str, path: Path) -> list[str]:
    try:
        return VALIDATORS[kind](_load(path))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"unreadable document: {exc}"]


def validate_directory(kind: str, directory: Path) -> list[tuple[Path, list[str]]]:
    return [(path, validate_document(kind, path)) for path in iter_json_documents(directory)]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate PO-03 custody documents.")
    modes = parser.add_subparsers(dest="mode", required=True)
    for kind in ("result", "wave"):
        single = modes.add_parser(kind, help=f"validate one {kind} document")
        single.add_argument("document", type=Path)
    directory = modes.add_parser(
        "validate-dir", help="validate every *.json document in a directory tree"
    )
    directory.add_argument("kind", choices=("result", "wave"))
    directory.add_argument("directory", type=Path)
    directory.add_argument(
        "--allow-empty",
        action="store_true",
        help="treat a directory with no documents as success instead of an error",
    )
    return parser


def _run_single(kind: str, document: Path) -> int:
    try:
        doc = _load(document)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}")
        return 2
    errors = VALIDATORS[kind](doc)
    if errors:
        for error in errors:
            print(f"INVALID: {error}")
        return 1
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    print(f"VALID {kind} sha256={digest}")
    return 0


def _run_directory(kind: str, directory: Path, allow_empty: bool) -> int:
    if not directory.is_dir():
        print(f"VALIDATE-DIR ERROR: not a directory: {directory}")
        return 2
    outcomes = validate_directory(kind, directory)
    if not outcomes:
        if allow_empty:
            print(f"VALIDATE-DIR {kind} {directory}: scanned=0 valid=0 invalid=0")
            return 0
        print(f"VALIDATE-DIR ERROR: no *.json documents under {directory}")
        return 2
    valid = 0
    invalid = 0
    for path, errors in outcomes:
        if errors:
            invalid += 1
            print(f"INVALID {path}: {errors[0]}")
        else:
            valid += 1
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            print(f"VALID {path} sha256={digest}")
    print(
        f"VALIDATE-DIR {kind} {directory}: "
        f"scanned={len(outcomes)} valid={valid} invalid={invalid}"
    )
    return 1 if invalid else 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.mode == "validate-dir":
        return _run_directory(args.kind, args.directory, args.allow_empty)
    return _run_single(args.mode, args.document)


if __name__ == "__main__":
    raise SystemExit(main())
