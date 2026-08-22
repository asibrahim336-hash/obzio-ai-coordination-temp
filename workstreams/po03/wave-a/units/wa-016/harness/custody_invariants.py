#!/usr/bin/env python3
"""Additive strengthening layer over the seeded PO-03 result validator.

The seeded validator at ``workstreams/po03/tools/validate_contracts.py`` is an
active control and is read-only to this unit, so this module composes it rather
than replacing it: every seeded error is preserved and further invariants are
appended.

Each added invariant closes a gap the harness measured, meaning there exists a
document the seeded executable validator accepts while it still asserts a
completion that is not evidenced.  ``GAP_FIXTURES`` names them so the additions
stay falsifiable: if a gap is closed upstream, the paired test will say so.
"""

from __future__ import annotations

import copy
from typing import Any

from .seeded import load_validator

# Enum from contracts/transactional-result.schema.json.  The seeded *executable*
# validator never checks it, so an unknown transaction state passes today.
TXN_STATES = ("RESERVED", "STAGING", "STAGED", "VERIFIED", "COMMITTED", "INGESTED")

# Which transaction state each lifecycle state may present.
STATE_COHERENCE: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"RESERVED"}),
    "LEASED": frozenset({"RESERVED"}),
    "RUNNING": frozenset({"RESERVED", "STAGING"}),
    "CHECKPOINTED": frozenset({"RESERVED", "STAGING"}),
    "RESULT_STAGING": frozenset({"STAGING"}),
    "RESULT_STAGED": frozenset({"STAGED"}),
    "RESULT_VERIFIED": frozenset({"VERIFIED"}),
    "RESULT_COMMITTED": frozenset({"COMMITTED"}),
    "PARENT_INGESTED": frozenset({"INGESTED"}),
    "COMPLETED": frozenset({"INGESTED"}),
    "PROVIDER_COMPLETED_UNCOMMITTED": frozenset({"RESERVED", "STAGING", "STAGED", "VERIFIED"}),
    "RECOVERY_REQUIRED": frozenset(TXN_STATES),
    "RETRY_SCHEDULED": frozenset(TXN_STATES),
    "FAILED_TERMINAL": frozenset(TXN_STATES),
    "CANCELLED": frozenset(TXN_STATES),
}

COMMITTED_STATES = frozenset({"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"})


def _order_key(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _ordered(earlier: Any, later: Any) -> bool:
    """True unless both timestamps exist and run backwards."""
    first, second = _order_key(earlier), _order_key(later)
    if first is None or second is None:
        return True
    return first <= second


def added_invariants(doc: dict[str, Any]) -> list[str]:
    """Invariants this unit adds; the seeded validator checks none of them."""
    errors: list[str] = []
    txn = doc.get("result_transaction")
    artifacts = doc.get("artifacts")
    state = doc.get("obzio_state")
    if not isinstance(txn, dict) or not isinstance(artifacts, list):
        return ["$: strengthened layer requires result_transaction and artifacts"]

    # A1 -- the transaction state must be one the schema defines.
    if txn.get("state") not in TXN_STATES:
        errors.append(f"$.result_transaction.state: {txn.get('state')!r} is not a declared transaction state")

    # A2 -- the lifecycle state and the transaction state must agree.
    allowed = STATE_COHERENCE.get(state)
    if allowed is not None and txn.get("state") in TXN_STATES and txn.get("state") not in allowed:
        errors.append(
            f"$.result_transaction.state: {txn.get('state')} is incoherent with obzio_state {state}"
        )

    # A3 -- custody timestamps must not run backwards.  Nothing can be read back
    # from a commit that did not exist yet, and nothing can be ingested before
    # it was committed, so a receipt claiming otherwise is stale or copied.
    fully_readback = bool(artifacts) and all(
        isinstance(a, dict) and _order_key(a.get("readback_verified_at")) for a in artifacts
    )
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            continue
        if not _ordered(txn.get("committed_at"), artifact.get("readback_verified_at")):
            errors.append(f"$.artifacts[{index}].readback_verified_at: precedes committed_at")
    if fully_readback and not _ordered(txn.get("committed_at"), txn.get("verified_at")):
        errors.append("$.result_transaction.verified_at: fully read-back result verified before it was committed")
    if not _ordered(txn.get("committed_at"), txn.get("parent_ingested_at")):
        errors.append("$.result_transaction.parent_ingested_at: precedes committed_at")

    # A4 -- one logical name and one content URI per result.
    seen_names: set[str] = set()
    seen_uris: set[str] = set()
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            continue
        name = artifact.get("logical_name")
        uri = artifact.get("content_uri")
        if name in seen_names:
            errors.append(f"$.artifacts[{index}].logical_name: duplicate logical name {name!r}")
        if uri in seen_uris:
            errors.append(f"$.artifacts[{index}].content_uri: duplicate content uri {uri!r}")
        if isinstance(name, str):
            seen_names.add(name)
        if isinstance(uri, str):
            seen_uris.add(uri)

    # A5 -- a committed result must locate its artifacts at the commit it claims.
    if state in COMMITTED_STATES:
        commit_id = txn.get("result_commit_id")
        if isinstance(commit_id, str) and commit_id.strip():
            for index, artifact in enumerate(artifacts):
                uri = artifact.get("content_uri") if isinstance(artifact, dict) else None
                if isinstance(uri, str) and commit_id not in uri:
                    errors.append(
                        f"$.artifacts[{index}].content_uri: does not reference result_commit_id {commit_id}"
                    )

    # A6 -- a manifest digest is required as soon as a manifest URI is claimed.
    if _order_key(txn.get("manifest_uri")) and not _order_key(txn.get("manifest_sha256")):
        errors.append("$.result_transaction.manifest_sha256: required whenever manifest_uri is claimed")

    return errors


def validate_result_strict(doc: dict[str, Any], *, require_pin: bool = True) -> list[str]:
    """Seeded validator errors followed by this unit's added invariants."""
    validator = load_validator(require_pin=require_pin)
    errors = list(validator.validate_result(doc))
    errors.extend(added_invariants(doc))
    return errors


# --------------------------------------------------------------------- fixtures
def _committed_baseline() -> dict[str, Any]:
    """A document the seeded validator accepts, used as the mutation base."""
    digest = "a" * 64
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": "PO03-WA-016",
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "immutable_input_manifest_sha256": digest,
        "acceptance_contract_sha256": digest,
        "provider_state": "COMPLETED",
        "obzio_state": "COMPLETED",
        "attempt": {
            "attempt_id": "PO03-WA-016-A01",
            "idempotency_key": "po03:100bc20:wa-016:a01",
            "lease_id": "lease-po03-wa-016-a01",
            "fence_token": 1,
            "provider_run_id": "bc-b1956656-b897-4889-aeab-82c4556c1a9f",
            "worker_id": "producer-1",
            "heartbeat_at": "2026-08-22T07:20:00Z",
            "checkpoint_seq": 2,
        },
        "result_transaction": {
            "result_txn_id": "txn-po03-wa-016-a01",
            "state": "INGESTED",
            "manifest_uri": "refs/po03/po03-wa-016@commit1:artifact-manifest.json",
            "manifest_sha256": digest,
            "artifact_count": 1,
            "total_bytes": 74,
            "committed_at": "2026-08-22T07:21:00Z",
            "verified_at": "2026-08-22T07:22:00Z",
            "parent_ingested_at": "2026-08-22T07:23:00Z",
            "result_commit_id": "commit1",
        },
        "artifacts": [
            {
                "artifact_id": "art-1",
                "logical_name": "canary.txt",
                "content_uri": "refs/po03/po03-wa-016@commit1:canary.txt",
                "sha256": "5fdeb53d88f287e7e82006277c55ab0b3359b3b1881f408929359285be95f31b",
                "bytes": 74,
                "media_type": "text/plain; charset=utf-8",
                "readback_verified_at": "2026-08-22T07:22:30Z",
            }
        ],
        "completion_actor": "coordinator",
        "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
    }


def _gap_undeclared_txn_state() -> dict[str, Any]:
    doc = _committed_baseline()
    doc["result_transaction"]["state"] = "DEFINITELY_NOT_A_STATE"
    return doc


def _gap_incoherent_txn_state() -> dict[str, Any]:
    doc = _committed_baseline()
    doc["result_transaction"]["state"] = "RESERVED"
    return doc


def _gap_verification_before_commit() -> dict[str, Any]:
    doc = _committed_baseline()
    doc["result_transaction"]["verified_at"] = "2026-08-22T07:20:00Z"
    doc["artifacts"][0]["readback_verified_at"] = "2026-08-22T07:20:30Z"
    return doc


def _gap_duplicate_logical_name() -> dict[str, Any]:
    doc = _committed_baseline()
    clone = copy.deepcopy(doc["artifacts"][0])
    clone["artifact_id"] = "art-2"
    doc["artifacts"].append(clone)
    doc["result_transaction"]["artifact_count"] = 2
    doc["result_transaction"]["total_bytes"] = 148
    return doc


def _gap_artifact_at_wrong_commit() -> dict[str, Any]:
    doc = _committed_baseline()
    doc["artifacts"][0]["content_uri"] = "refs/po03/po03-wa-016@some-other-commit:canary.txt"
    return doc


def _gap_manifest_uri_without_digest() -> dict[str, Any]:
    doc = _committed_baseline()
    doc["obzio_state"] = "RESULT_VERIFIED"
    doc["provider_state"] = "RUNNING"
    doc["result_transaction"].update(
        state="VERIFIED",
        manifest_sha256=None,
        parent_ingested_at=None,
        committed_at=None,
        result_commit_id=None,
    )
    doc["completion_actor"] = None
    doc["artifacts"][0]["readback_verified_at"] = None
    doc["artifacts"][0]["content_uri"] = "refs/po03/po03-wa-016@STAGED:canary.txt"
    return doc


# Each fixture is a document the seeded validator admits and this layer rejects.
GAP_FIXTURES: tuple[tuple[str, Any, str], ...] = (
    (
        "GAP-1-UNDECLARED-TRANSACTION-STATE",
        _gap_undeclared_txn_state,
        "the seeded executable validator never compares result_transaction.state to the schema enum",
    ),
    (
        "GAP-2-INCOHERENT-TRANSACTION-STATE",
        _gap_incoherent_txn_state,
        "a COMPLETED result may claim a merely RESERVED transaction",
    ),
    (
        "GAP-3-VERIFICATION-BEFORE-COMMIT",
        _gap_verification_before_commit,
        "custody timestamps are checked for presence but never for order",
    ),
    (
        "GAP-4-DUPLICATE-LOGICAL-NAME",
        _gap_duplicate_logical_name,
        "only artifact_id uniqueness is enforced, so one path can be counted twice",
    ),
    (
        "GAP-5-ARTIFACT-AT-WRONG-COMMIT",
        _gap_artifact_at_wrong_commit,
        "artifact content URIs are never tied to the claimed result commit",
    ),
    (
        "GAP-6-MANIFEST-URI-WITHOUT-DIGEST",
        _gap_manifest_uri_without_digest,
        "a manifest may be located without any digest before the committed states",
    ),
)


def measure_gaps(*, require_pin: bool = True) -> list[dict[str, Any]]:
    """Report, per gap, what the seeded validator says and what this layer says."""
    validator = load_validator(require_pin=require_pin)
    rows: list[dict[str, Any]] = []
    for gap_id, builder, rationale in GAP_FIXTURES:
        doc = builder()
        seeded_errors = list(validator.validate_result(doc))
        added = added_invariants(doc)
        rows.append(
            {
                "gap_id": gap_id,
                "rationale": rationale,
                "seeded_validator_errors": seeded_errors,
                "seeded_validator_admits": not seeded_errors,
                "strengthened_errors": added,
                "strengthened_rejects": bool(added),
                "closes_gap": not seeded_errors and bool(added),
            }
        )
    return rows
