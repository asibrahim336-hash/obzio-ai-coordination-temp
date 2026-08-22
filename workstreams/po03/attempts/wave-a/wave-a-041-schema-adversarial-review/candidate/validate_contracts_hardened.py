#!/usr/bin/env python3
"""Candidate hardened result-custody validator for PO-03 (wave-a-041, unapplied).

This module is an isolated repair candidate produced by an independent adversarial
review.  It is a modified copy of `workstreams/po03/tools/validate_contracts.py`
and lives entirely inside the reviewing unit's owned subtree.  The shared control
is untouched; the integration controller decides whether to adopt this.

Each change is marked `HARDENING Hn` and maps to a confirmed exploit case in
`../adversarial-cases.json`:

  H1  unknown-key rejection at every object level ......... C15
  H2  identity comparison under Unicode normalisation ...... C08, C09, C10
  H3  reserved institutional actor names .................. C11
  H4  evidence obligations keyed on the transaction state .. C02, C03
  H5  commit identity must be object-id shaped ............ C04
  H6  timestamps must parse and respect custody order ..... C04, C05
  H7  the manifest must be a read-back artifact ........... C06
  H8  logical name and content locator uniqueness ......... C07
  H9  attempt identity must bind to the task ............. C13
  H10 acceptance receipt must leave producer custody ...... C14
  H11 provider loss after staging is representable ....... U01
  H12 a zero-byte artifact is representable ............. U02
  H13 ledger-level custody, fence and checkpoint order ... C01, C12

H13 is the structural finding: a validator that sees one document can never
enforce an ordered custody chain or a fencing rule.  `validate_result` keeps its
single-document signature for drop-in use, and `validate_result_sequence` adds
the ledger-level gate the commission's fencing and monotonicity requirements
actually need.
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
# HARDENING H5: a git object id, full or abbreviated to at least 7 nibbles.
COMMIT_ID_RE = re.compile(r"^[0-9a-f]{7,64}$")

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

# HARDENING H4: these transaction states assert that a durable commit exists, so
# they carry the post-commit evidence obligations no matter what obzio_state says.
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
    # HARDENING H11: provider completion may be observed at any pre-commit point,
    # so the truthful staged-then-lost state is expressible without discarding
    # the staging evidence or misreporting provider_state.
    "PROVIDER_COMPLETED_UNCOMMITTED": {"RESERVED", "STAGING", "STAGED", "VERIFIED"},
    "RECOVERY_REQUIRED": {"RESERVED", "STAGING", "STAGED", "VERIFIED", "COMMITTED", "INGESTED"},
    "RETRY_SCHEDULED": {"RESERVED"},
    "FAILED_TERMINAL": {"RESERVED", "STAGING", "STAGED", "VERIFIED", "COMMITTED", "INGESTED"},
    "CANCELLED": {"RESERVED"},
}

# HARDENING H13: the mandated custody ladder, used only by the ledger validator.
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

# HARDENING H3: institutional functions a producing worker may not occupy.
RESERVED_ACTOR_IDENTITIES = {"coordinator", "reviewer", "acceptor", "controller", "founder"}

ALLOWED_KEYS: dict[str, set[str]] = {
    "$": {
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
    },
    "$.attempt": {
        "attempt_id",
        "idempotency_key",
        "lease_id",
        "fence_token",
        "provider_run_id",
        "worker_id",
        "heartbeat_at",
        "checkpoint_seq",
    },
    "$.result_transaction": {
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
    },
    "$.artifacts[]": {
        "artifact_id",
        "logical_name",
        "content_uri",
        "sha256",
        "bytes",
        "media_type",
        "readback_verified_at",
    },
    "$.independent_acceptance": {"state", "reviewer_id", "receipt_uri"},
}

MANIFEST_LOGICAL_NAMES = {"manifest.json", "manifest"}


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _required(obj: dict[str, Any], names: tuple[str, ...], prefix: str) -> list[str]:
    return [f"{prefix}.{name}: missing" for name in names if name not in obj]


def _unknown(obj: dict[str, Any], prefix: str, key: str | None = None) -> list[str]:
    """HARDENING H1: reject undeclared properties, matching additionalProperties false."""
    allowed = ALLOWED_KEYS[key or prefix]
    return [f"{prefix}.{name}: undeclared property" for name in sorted(obj) if name not in allowed]


def normalise_identity(value: Any) -> str | None:
    """HARDENING H2: fold ids to a comparison form.

    Trailing spaces, zero-width and other format characters, case differences and
    canonically equivalent Unicode all denote the same principal to a human
    reader, so they must denote the same principal to the separation-of-duties
    check.
    """
    if not isinstance(value, str):
        return None
    folded = unicodedata.normalize("NFKC", value)
    folded = "".join(ch for ch in folded if unicodedata.category(ch) not in {"Cf", "Zs", "Zl", "Zp"})
    folded = "".join(ch for ch in folded if not ch.isspace())
    folded = unicodedata.normalize("NFKC", folded).casefold()
    return folded or None


def _parse_timestamp(value: Any) -> datetime | None:
    """HARDENING H6: only a real RFC 3339 instant counts as a custody timestamp."""
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
    """Validate one result document.

    `context` is optional controller-supplied information that a single document
    cannot carry honestly about itself:
      producer_path_prefix -- the producer's owned result slot (HARDENING H10)
      reviewer_roster      -- identities entitled to accept (HARDENING H10)
    """
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
    if errors:
        return errors
    errors.extend(_unknown(doc, "$"))

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
    # HARDENING H14: bail only on this object's own missing fields.  The shipped
    # control returns on any previously accumulated error here, so a single early
    # defect suppresses every later finding in the same document.
    missing = _required(
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
    errors.extend(missing)
    if missing:
        return errors
    errors.extend(_unknown(attempt, "$.attempt"))
    for field in ("attempt_id", "idempotency_key", "lease_id", "provider_run_id", "worker_id"):
        if not _nonempty(attempt[field]):
            errors.append(f"$.attempt.{field}: must be non-empty")
    if not isinstance(attempt["fence_token"], int) or isinstance(attempt["fence_token"], bool) or attempt["fence_token"] < 1:
        errors.append("$.attempt.fence_token: must be an integer >= 1")
    if not isinstance(attempt["checkpoint_seq"], int) or isinstance(attempt["checkpoint_seq"], bool) or attempt["checkpoint_seq"] < 0:
        errors.append("$.attempt.checkpoint_seq: must be an integer >= 0")

    # HARDENING H3: a producing worker may not occupy a reserved institutional name.
    worker_identity = normalise_identity(attempt["worker_id"])
    if worker_identity in RESERVED_ACTOR_IDENTITIES:
        errors.append("$.attempt.worker_id: may not occupy the reserved identity " f"{worker_identity!r}")

    # HARDENING H9: attempt identity must bind to the task it claims to serve.
    key = attempt["idempotency_key"]
    if isinstance(key, str):
        segments = key.split(":")
        if doc["task_id"] not in segments:
            errors.append("$.attempt.idempotency_key: must contain $.task_id as a segment")
        if doc["commission_id"] not in segments:
            errors.append("$.attempt.idempotency_key: must contain $.commission_id as a segment")
    if isinstance(attempt["attempt_id"], str) and doc["task_id"] not in attempt["attempt_id"]:
        errors.append("$.attempt.attempt_id: must reference $.task_id")

    # HARDENING H6: a heartbeat that cannot be parsed is not a heartbeat.
    if attempt.get("heartbeat_at") is not None and _parse_timestamp(attempt.get("heartbeat_at")) is None:
        errors.append("$.attempt.heartbeat_at: must be an RFC 3339 instant with an offset or null")

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
    # HARDENING H14: see above; bail only on this object's own missing fields.
    missing = _required(txn, txn_required, "$.result_transaction")
    errors.extend(missing)
    if missing:
        return errors
    errors.extend(_unknown(txn, "$.result_transaction"))
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
        artifact_fields = (
            "artifact_id",
            "logical_name",
            "content_uri",
            "sha256",
            "bytes",
            "media_type",
            "readback_verified_at",
        )
        errors.extend(_required(artifact, artifact_fields, prefix))
        if any(name not in artifact for name in artifact_fields):
            continue
        errors.extend(_unknown(artifact, prefix, key="$.artifacts[]"))
        if artifact["artifact_id"] in artifact_ids:
            errors.append(f"{prefix}.artifact_id: duplicate")
        artifact_ids.add(artifact["artifact_id"])
        # HARDENING H8: evidence resolved by name or locator must be unambiguous.
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
        # HARDENING H12: an empty durable artifact is real and must be manifestable.
        if not isinstance(artifact["bytes"], int) or isinstance(artifact["bytes"], bool) or artifact["bytes"] < 0:
            errors.append(f"{prefix}.bytes: must be an integer >= 0")
        else:
            byte_sum += artifact["bytes"]
    if txn["total_bytes"] != byte_sum:
        errors.append("$.result_transaction.total_bytes: does not match artifact bytes")

    # HARDENING H4: the obligation follows the transaction state, not the label.
    committed = state in TERMINAL_RESULT_STATES or txn["state"] in EVIDENCE_BEARING_TRANSACTION_STATES
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
        # HARDENING H5: the commit identity must be capable of denoting a commit.
        if _nonempty(txn["result_commit_id"]) and not COMMIT_ID_RE.fullmatch(txn["result_commit_id"].strip()):
            errors.append("$.result_transaction.result_commit_id: must be a lowercase object id of 7 to 64 hex digits")
        if not artifacts:
            errors.append("$.artifacts: committed result requires at least one artifact")
        for index, artifact in enumerate(artifacts):
            if isinstance(artifact, dict) and not _nonempty(artifact.get("readback_verified_at")):
                errors.append(f"$.artifacts[{index}].readback_verified_at: required after result commit")
        # HARDENING H7: the manifest must itself be a read-back artifact of the
        # transaction, bound to manifest_sha256, or it covers nothing verifiable.
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
        # HARDENING H6: custody order must be causally possible.
        committed_at = _parse_timestamp(txn["committed_at"])
        verified_at = _parse_timestamp(txn["verified_at"])
        if committed_at is None:
            errors.append("$.result_transaction.committed_at: must be an RFC 3339 instant with an offset")
        if verified_at is None:
            errors.append("$.result_transaction.verified_at: must be an RFC 3339 instant with an offset")
        if committed_at and verified_at and verified_at < committed_at:
            errors.append("$.result_transaction.verified_at: must not precede committed_at")
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                continue
            readback = _parse_timestamp(artifact.get("readback_verified_at"))
            if artifact.get("readback_verified_at") is not None and readback is None:
                errors.append(f"$.artifacts[{index}].readback_verified_at: must be an RFC 3339 instant with an offset")
            elif readback and committed_at and readback < committed_at:
                errors.append(f"$.artifacts[{index}].readback_verified_at: must not precede committed_at")

    if state in {"PARENT_INGESTED", "COMPLETED"}:
        if not _nonempty(txn["parent_ingested_at"]):
            errors.append("$.result_transaction.parent_ingested_at: required after parent ingestion")
        else:
            ingested_at = _parse_timestamp(txn["parent_ingested_at"])
            verified_at = _parse_timestamp(txn["verified_at"])
            if ingested_at is None:
                errors.append("$.result_transaction.parent_ingested_at: must be an RFC 3339 instant with an offset")
            elif verified_at and ingested_at < verified_at:
                errors.append("$.result_transaction.parent_ingested_at: must not precede verified_at")
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
        errors.extend(_unknown(acceptance, "$.independent_acceptance"))
        if acceptance.get("state") in {"ACCEPTED", "REJECTED"}:
            if not _nonempty(acceptance.get("reviewer_id")) or not _nonempty(acceptance.get("receipt_uri")):
                errors.append("$.independent_acceptance: terminal review requires reviewer_id and receipt_uri")
            if state != "COMPLETED":
                errors.append("$.independent_acceptance: terminal review requires COMPLETED result")
            # HARDENING H2: compare normalised identities, not raw bytes.
            reviewer_identity = normalise_identity(acceptance.get("reviewer_id"))
            if reviewer_identity is not None and reviewer_identity == worker_identity:
                errors.append("$.independent_acceptance.reviewer_id: producer cannot self-accept")
            # HARDENING H10: acceptance evidence must leave producer custody.
            prefix = context.get("producer_path_prefix")
            receipt = acceptance.get("receipt_uri")
            if prefix and isinstance(receipt, str) and prefix in receipt:
                errors.append(
                    "$.independent_acceptance.receipt_uri: acceptance receipt must not reside in the producer's owned slot"
                )
            roster = context.get("reviewer_roster")
            if roster is not None:
                allowed = {normalise_identity(name) for name in roster}
                if reviewer_identity not in allowed:
                    errors.append("$.independent_acceptance.reviewer_id: not an entitled reviewer")

    return errors


def validate_result_sequence(
    documents: list[dict[str, Any]], context: dict[str, Any] | None = None
) -> list[str]:
    """HARDENING H13: validate an append-only ledger, not an isolated snapshot.

    A snapshot validator cannot see custody skipping, fence staleness or
    non-monotonic checkpoints, because every one of those defects is a relation
    between successive entries.  Documents are supplied in ledger append order.
    """
    errors: list[str] = []
    for index, doc in enumerate(documents):
        errors.extend(f"[{index}]{error[1:]}" if error.startswith("$") else error for error in validate_result(doc, context))
    if errors:
        return errors

    by_task: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, doc in enumerate(documents):
        by_task.setdefault(doc["task_id"], []).append((index, doc))

    for task_id, entries in by_task.items():
        highest_fence = 0
        highest_rank = -1
        commit_by_key: dict[str, tuple[str, str]] = {}
        checkpoint_by_attempt: dict[str, int] = {}
        for index, doc in entries:
            where = f"[{index}] task {task_id}"
            attempt = doc["attempt"]
            txn = doc["result_transaction"]
            state = doc["obzio_state"]
            fence = attempt["fence_token"]

            # Duplicate and replayed callbacks must be harmless, so repeated
            # entries under one idempotency key are expected as the attempt
            # advances.  What must never diverge under one key is the identity of
            # the transaction and of the commit it produced.
            if txn["result_commit_id"] is not None:
                identity = (txn["result_txn_id"], txn["result_commit_id"])
                previous = commit_by_key.get(attempt["idempotency_key"])
                if previous is not None and previous != identity:
                    errors.append(
                        f"{where}: idempotency key {attempt['idempotency_key']!r} already bound to "
                        f"{previous}, cannot also produce {identity}"
                    )
                commit_by_key[attempt["idempotency_key"]] = identity

            evidence_bearing = (
                txn["state"] in EVIDENCE_BEARING_TRANSACTION_STATES or state in TERMINAL_RESULT_STATES
            )
            if fence < highest_fence and evidence_bearing:
                errors.append(
                    f"{where}: stale fence {fence} below current fence {highest_fence} "
                    "may not commit or complete a result"
                )
            highest_fence = max(highest_fence, fence)

            last_checkpoint = checkpoint_by_attempt.get(attempt["attempt_id"])
            if last_checkpoint is not None and attempt["checkpoint_seq"] < last_checkpoint:
                errors.append(
                    f"{where}: checkpoint_seq {attempt['checkpoint_seq']} regressed below {last_checkpoint}"
                )
            checkpoint_by_attempt[attempt["attempt_id"]] = max(
                attempt["checkpoint_seq"], last_checkpoint if last_checkpoint is not None else 0
            )

            if state in OFF_LADDER_STATES:
                continue
            rank = CUSTODY_LADDER.index(state)
            if highest_rank < 0:
                if rank != 0:
                    errors.append(f"{where}: ledger must open at CREATED, not {state}")
            elif rank < highest_rank:
                errors.append(f"{where}: custody state {state} regressed below the recorded position")
            elif rank > highest_rank + 1:
                errors.append(
                    f"{where}: custody state {state} skips "
                    f"{CUSTODY_LADDER[highest_rank + 1:rank]} without a recorded transition"
                )
            highest_rank = max(highest_rank, rank)

        if highest_rank == CUSTODY_LADDER.index("COMPLETED"):
            commit_ids = {
                doc["result_transaction"]["result_commit_id"]
                for _, doc in entries
                if doc["obzio_state"] in TERMINAL_RESULT_STATES
            }
            if len(commit_ids) != 1:
                errors.append(f"task {task_id}: completion requires exactly one result commit id, saw {sorted(commit_ids)}")

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


def _load(path: Path) -> Any:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data


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
