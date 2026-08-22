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
RESULT_SCHEMA_PATH = Path(__file__).parents[1] / "contracts" / "transactional-result.schema.json"
RESULT_SCHEMA = json.loads(RESULT_SCHEMA_PATH.read_text(encoding="utf-8"))
SUPPORTED_SCHEMA_KEYWORDS = {
    "$ref",
    "additionalProperties",
    "anyOf",
    "const",
    "enum",
    "items",
    "minimum",
    "minLength",
    "pattern",
    "properties",
    "required",
    "type",
}

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


def _json_equal(left: Any, right: Any) -> bool:
    """Compare values using JSON rather than Python's bool/int equality."""
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def _json_type_matches(value: Any, expected: str) -> bool:
    checks = {
        "array": lambda item: isinstance(item, list),
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "null": lambda item: item is None,
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "object": lambda item: isinstance(item, dict),
        "string": lambda item: isinstance(item, str),
    }
    return expected in checks and checks[expected](value)


def _resolve_local_ref(root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported non-local schema reference: {reference}")
    target: Any = root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        target = target[part]
    if not isinstance(target, dict):
        raise ValueError(f"schema reference does not resolve to an object: {reference}")
    return target


def _schema_errors(
    value: Any,
    schema: dict[str, Any],
    *,
    root: dict[str, Any],
    path: str = "$",
) -> list[str]:
    """Validate the transactional schema keywords without third-party packages."""
    if "$ref" in schema:
        return _schema_errors(value, _resolve_local_ref(root, schema["$ref"]), root=root, path=path)

    if "anyOf" in schema:
        if not any(
            not _schema_errors(value, alternative, root=root, path=path)
            for alternative in schema["anyOf"]
        ):
            return [f"{path}: does not match any allowed schema"]

    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        expected_types = [expected] if isinstance(expected, str) else expected
        if not any(_json_type_matches(value, item) for item in expected_types):
            return [f"{path}: expected type {' or '.join(expected_types)}"]

    if "const" in schema and not _json_equal(value, schema["const"]):
        errors.append(f"{path}: must equal declared constant")
    if "enum" in schema and not any(_json_equal(value, item) for item in schema["enum"]):
        errors.append(f"{path}: value is outside declared enum")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}.{name}: missing")
        if schema.get("additionalProperties") is False:
            for name in sorted(set(value) - set(properties)):
                errors.append(f"{path}.{name}: undeclared field")
        for name, child_schema in properties.items():
            if name in value:
                errors.extend(
                    _schema_errors(
                        value[name],
                        child_schema,
                        root=root,
                        path=f"{path}.{name}",
                    )
                )

    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            errors.extend(
                _schema_errors(
                    item,
                    schema["items"],
                    root=root,
                    path=f"{path}[{index}]",
                )
            )

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: does not match declared pattern")

    if (
        "minimum" in schema
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value < schema["minimum"]
    ):
        errors.append(f"{path}: below minimum {schema['minimum']}")
    return errors


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _required(obj: dict[str, Any], names: tuple[str, ...], prefix: str) -> list[str]:
    return [f"{prefix}.{name}: missing" for name in names if name not in obj]


def validate_result(doc: dict[str, Any]) -> list[str]:
    errors = _schema_errors(doc, RESULT_SCHEMA, root=RESULT_SCHEMA)
    if errors:
        return errors
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
