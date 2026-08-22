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
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_OBJECT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

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
EVIDENCE_BEARING_TRANSACTION_STATES = {"COMMITTED", "INGESTED"}
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
    "PROVIDER_COMPLETED_UNCOMMITTED": {"RESERVED", "STAGING", "STAGED", "VERIFIED"},
    "RECOVERY_REQUIRED": {"RESERVED", "STAGING", "STAGED", "VERIFIED", "COMMITTED", "INGESTED"},
    "RETRY_SCHEDULED": {"RESERVED"},
    "FAILED_TERMINAL": {"RESERVED", "STAGING", "STAGED", "VERIFIED", "COMMITTED", "INGESTED"},
    "CANCELLED": {"RESERVED"},
}
CUSTODY_LADDER = [
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
]
OFF_LADDER_STATES = {
    "PROVIDER_COMPLETED_UNCOMMITTED",
    "RECOVERY_REQUIRED",
    "RETRY_SCHEDULED",
    "FAILED_TERMINAL",
    "CANCELLED",
}
RESERVED_ACTOR_IDENTITIES = {"coordinator", "reviewer", "acceptor", "controller", "founder"}
MANIFEST_LOGICAL_NAMES = {"manifest.json", "manifest"}


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _required(obj: dict[str, Any], names: tuple[str, ...], prefix: str) -> list[str]:
    return [f"{prefix}.{name}: missing" for name in names if name not in obj]


def _unexpected(obj: dict[str, Any], names: set[str], prefix: str) -> list[str]:
    return [f"{prefix}.{name}: undeclared property" for name in sorted(set(obj) - names)]


def normalise_identity(value: Any) -> str | None:
    """Return a conservative comparison form for institutional identities."""
    if not isinstance(value, str):
        return None
    folded = unicodedata.normalize("NFKC", value)
    folded = "".join(
        character
        for character in folded
        if unicodedata.category(character) not in {"Cf", "Zs", "Zl", "Zp"}
        and not character.isspace()
    )
    folded = unicodedata.normalize("NFKC", folded).casefold()
    return folded or None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def validate_result(doc: dict[str, Any], context: dict[str, Any] | None = None) -> list[str]:
    context = context or {}
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
    missing_attempt = _required(
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
    errors.extend(missing_attempt)
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
    if missing_attempt:
        return errors
    for field in ("attempt_id", "idempotency_key", "lease_id", "provider_run_id", "worker_id"):
        if not _nonempty(attempt[field]):
            errors.append(f"$.attempt.{field}: must be non-empty")
    if (
        not isinstance(attempt["fence_token"], int)
        or isinstance(attempt["fence_token"], bool)
        or attempt["fence_token"] < 1
    ):
        errors.append("$.attempt.fence_token: must be an integer >= 1")
    if (
        not isinstance(attempt["checkpoint_seq"], int)
        or isinstance(attempt["checkpoint_seq"], bool)
        or attempt["checkpoint_seq"] < 0
    ):
        errors.append("$.attempt.checkpoint_seq: must be an integer >= 0")
    worker_identity = normalise_identity(attempt["worker_id"])
    if worker_identity in RESERVED_ACTOR_IDENTITIES:
        errors.append(
            f"$.attempt.worker_id: may not occupy the reserved identity {worker_identity!r}"
        )
    key = attempt["idempotency_key"]
    if isinstance(key, str):
        segments = key.split(":")
        if doc["task_id"] not in segments:
            errors.append("$.attempt.idempotency_key: must contain $.task_id as a segment")
        if doc["commission_id"] not in segments:
            errors.append("$.attempt.idempotency_key: must contain $.commission_id as a segment")
    if isinstance(attempt["attempt_id"], str) and doc["task_id"] not in attempt["attempt_id"]:
        errors.append("$.attempt.attempt_id: must reference $.task_id")
    if (
        attempt.get("heartbeat_at") is not None
        and _parse_timestamp(attempt.get("heartbeat_at")) is None
    ):
        errors.append(
            "$.attempt.heartbeat_at: must be an RFC 3339 instant with an offset or null"
        )

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
    missing_transaction = _required(txn, txn_required, "$.result_transaction")
    errors.extend(missing_transaction)
    errors.extend(_unexpected(txn, set(txn_required), "$.result_transaction"))
    if missing_transaction:
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
    logical_names: set[str] = set()
    content_uris: set[str] = set()
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
        if artifact["logical_name"] in logical_names:
            errors.append(f"{prefix}.logical_name: duplicate")
        logical_names.add(artifact["logical_name"])
        if artifact["content_uri"] in content_uris:
            errors.append(f"{prefix}.content_uri: duplicate")
        content_uris.add(artifact["content_uri"])
        for field in ("artifact_id", "logical_name", "content_uri", "media_type"):
            if not _nonempty(artifact[field]):
                errors.append(f"{prefix}.{field}: must be non-empty")
        if not _sha256(artifact["sha256"]):
            errors.append(f"{prefix}.sha256: must be a lowercase SHA-256")
        if (
            not isinstance(artifact["bytes"], int)
            or isinstance(artifact["bytes"], bool)
            or artifact["bytes"] < 0
        ):
            errors.append(f"{prefix}.bytes: must be an integer >= 0")
        else:
            byte_sum += artifact["bytes"]
    if txn["total_bytes"] != byte_sum:
        errors.append("$.result_transaction.total_bytes: does not match artifact bytes")

    committed = (
        state in TERMINAL_RESULT_STATES
        or txn["state"] in EVIDENCE_BEARING_TRANSACTION_STATES
    )
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
        if _nonempty(txn["result_commit_id"]) and not GIT_OBJECT_RE.fullmatch(
            txn["result_commit_id"].strip()
        ):
            errors.append(
                "$.result_transaction.result_commit_id: must be a lowercase object id "
                "with exactly 40 or 64 hex digits"
            )
        if not artifacts:
            errors.append("$.artifacts: committed result requires at least one artifact")
        for index, artifact in enumerate(artifacts):
            if isinstance(artifact, dict) and not _nonempty(artifact.get("readback_verified_at")):
                errors.append(f"$.artifacts[{index}].readback_verified_at: required after result commit")
        manifest_bound = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, dict)
            and artifact.get("sha256") == txn["manifest_sha256"]
            and artifact.get("logical_name") in MANIFEST_LOGICAL_NAMES
        ]
        if len(manifest_bound) != 1:
            errors.append(
                "$.result_transaction.manifest_sha256: exactly one artifact named manifest.json "
                "must carry this digest so the manifest is itself read back"
            )
        committed_at = _parse_timestamp(txn["committed_at"])
        verified_at = _parse_timestamp(txn["verified_at"])
        if committed_at is None:
            errors.append(
                "$.result_transaction.committed_at: must be an RFC 3339 instant with an offset"
            )
        if verified_at is None:
            errors.append(
                "$.result_transaction.verified_at: must be an RFC 3339 instant with an offset"
            )
        if committed_at and verified_at and verified_at < committed_at:
            errors.append(
                "$.result_transaction.verified_at: must not precede committed_at"
            )
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                continue
            readback = _parse_timestamp(artifact.get("readback_verified_at"))
            if artifact.get("readback_verified_at") is not None and readback is None:
                errors.append(
                    f"$.artifacts[{index}].readback_verified_at: "
                    "must be an RFC 3339 instant with an offset"
                )
            elif readback and committed_at and readback < committed_at:
                errors.append(
                    f"$.artifacts[{index}].readback_verified_at: must not precede committed_at"
                )

    if state in {"PARENT_INGESTED", "COMPLETED"}:
        if not _nonempty(txn["parent_ingested_at"]):
            errors.append("$.result_transaction.parent_ingested_at: required after parent ingestion")
        else:
            ingested_at = _parse_timestamp(txn["parent_ingested_at"])
            verified_at = _parse_timestamp(txn["verified_at"])
            if ingested_at is None:
                errors.append(
                    "$.result_transaction.parent_ingested_at: "
                    "must be an RFC 3339 instant with an offset"
                )
            elif verified_at and ingested_at < verified_at:
                errors.append(
                    "$.result_transaction.parent_ingested_at: must not precede verified_at"
                )
    if state in {
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
            reviewer_identity = normalise_identity(acceptance.get("reviewer_id"))
            if reviewer_identity is not None and reviewer_identity == worker_identity:
                errors.append("$.independent_acceptance.reviewer_id: producer cannot self-accept")
            producer_path_prefix = context.get("producer_path_prefix")
            receipt_uri = acceptance.get("receipt_uri")
            if (
                _nonempty(producer_path_prefix)
                and isinstance(receipt_uri, str)
                and producer_path_prefix.rstrip("/") + "/" in receipt_uri
            ):
                errors.append(
                    "$.independent_acceptance.receipt_uri: acceptance receipt must not "
                    "reside in the producer's owned slot"
                )
            reviewer_roster = context.get("reviewer_roster")
            if reviewer_roster is not None:
                allowed = {normalise_identity(identity) for identity in reviewer_roster}
                if reviewer_identity not in allowed:
                    errors.append(
                        "$.independent_acceptance.reviewer_id: not an entitled reviewer"
                    )

    return errors


def validate_result_sequence(
    documents: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> list[str]:
    """Validate ordered custody, fencing, checkpoints and idempotent commit identity."""
    errors: list[str] = []
    for index, document in enumerate(documents):
        errors.extend(
            f"[{index}]{error[1:]}" if error.startswith("$") else error
            for error in validate_result(document, context)
        )
    if errors:
        return errors

    by_task: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, document in enumerate(documents):
        by_task.setdefault(document["task_id"], []).append((index, document))

    for task_id, entries in by_task.items():
        highest_fence = 0
        highest_rank = -1
        commit_by_key: dict[str, tuple[str, str]] = {}
        checkpoint_by_attempt: dict[str, int] = {}
        for index, document in entries:
            where = f"[{index}] task {task_id}"
            attempt = document["attempt"]
            transaction = document["result_transaction"]
            state = document["obzio_state"]
            fence = attempt["fence_token"]

            if transaction["result_commit_id"] is not None:
                identity = (
                    transaction["result_txn_id"],
                    transaction["result_commit_id"],
                )
                previous = commit_by_key.get(attempt["idempotency_key"])
                if previous is not None and previous != identity:
                    errors.append(
                        f"{where}: idempotency key {attempt['idempotency_key']!r} "
                        f"already bound to {previous}, cannot also produce {identity}"
                    )
                commit_by_key[attempt["idempotency_key"]] = identity

            evidence_bearing = (
                transaction["state"] in EVIDENCE_BEARING_TRANSACTION_STATES
                or state in TERMINAL_RESULT_STATES
            )
            if fence < highest_fence and evidence_bearing:
                errors.append(
                    f"{where}: stale fence {fence} below current fence {highest_fence} "
                    "may not commit or complete a result"
                )
            highest_fence = max(highest_fence, fence)

            last_checkpoint = checkpoint_by_attempt.get(attempt["attempt_id"])
            if (
                last_checkpoint is not None
                and attempt["checkpoint_seq"] < last_checkpoint
            ):
                errors.append(
                    f"{where}: checkpoint_seq {attempt['checkpoint_seq']} "
                    f"regressed below {last_checkpoint}"
                )
            checkpoint_by_attempt[attempt["attempt_id"]] = max(
                attempt["checkpoint_seq"],
                last_checkpoint if last_checkpoint is not None else 0,
            )

            if state in OFF_LADDER_STATES:
                continue
            rank = CUSTODY_LADDER.index(state)
            if highest_rank < 0:
                if rank != 0:
                    errors.append(f"{where}: ledger must open at CREATED, not {state}")
            elif rank < highest_rank:
                errors.append(
                    f"{where}: custody state {state} regressed below the recorded position"
                )
            elif rank > highest_rank + 1:
                errors.append(
                    f"{where}: custody state {state} skips "
                    f"{CUSTODY_LADDER[highest_rank + 1:rank]} without a recorded transition"
                )
            highest_rank = max(highest_rank, rank)

        if highest_rank == CUSTODY_LADDER.index("COMPLETED"):
            commit_ids = {
                document["result_transaction"]["result_commit_id"]
                for _, document in entries
                if document["obzio_state"] in TERMINAL_RESULT_STATES
            }
            if len(commit_ids) != 1:
                errors.append(
                    f"task {task_id}: completion requires exactly one result commit id, "
                    f"saw {sorted(commit_ids)}"
                )

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


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("result", "ledger", "wave"))
    parser.add_argument("document", type=Path)
    args = parser.parse_args(argv)
    try:
        doc = _load(args.document)
        if args.kind == "ledger":
            if not isinstance(doc, list):
                raise ValueError("ledger must be a JSON array of result documents")
            errors = validate_result_sequence(doc)
        else:
            if not isinstance(doc, dict):
                raise ValueError("root must be a JSON object")
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
