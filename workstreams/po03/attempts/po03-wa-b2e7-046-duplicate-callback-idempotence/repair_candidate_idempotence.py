#!/usr/bin/env python3
"""Repair candidate for the duplicate-callback gap found by this unit.

Staged inside this unit's subtree only.  The live mechanism is not modified by
this file; a coordinator would have to adopt it deliberately.

The gap: `ingest_result` suppresses a replayed callback by hashing the whole
result document and checking whether `ingestion-<hash>.json` already exists.
That makes suppression a property of the bytes rather than of the transaction,
so a retried callback whose timestamps were regenerated is a different hash and
is counted twice, and two callbacks racing through the check-then-write window
are both recorded.

The candidate keys suppression on the transaction identity the result already
carries — task, idempotency key, fence token, result commit and the set of
artifact hashes — and claims that identity by exclusively creating a claim file
before the live ingestion runs.  Exclusive creation is atomic, so the race
collapses to exactly one effect.
"""

from __future__ import annotations

import json
import os
from typing import Any


CLAIM_DIRECTORY = "ingestion-claims"


def identity_fields(document: dict[str, Any]) -> dict[str, Any]:
    """Extract the fields that identify the transaction rather than the message."""
    attempt = document.get("attempt", {}) if isinstance(document.get("attempt"), dict) else {}
    transaction = (
        document.get("result_transaction", {})
        if isinstance(document.get("result_transaction"), dict)
        else {}
    )
    artifacts = document.get("artifacts", [])
    return {
        "task_id": document.get("task_id"),
        "idempotency_key": attempt.get("idempotency_key"),
        "fence_token": attempt.get("fence_token"),
        "attempt_id": attempt.get("attempt_id"),
        "result_commit_id": transaction.get("result_commit_id"),
        "artifact_sha256": sorted(
            artifact.get("sha256")
            for artifact in artifacts
            if isinstance(artifact, dict)
        ),
    }


def identity_key(module, document: dict[str, Any]) -> str:
    return module.sha256_bytes(module.canonical_json(identity_fields(document)))


def claim_identity(module, task_id: str, key: str, document: dict[str, Any]) -> bool:
    """Claim a transaction identity exactly once; return False if already claimed."""
    directory = module.CONTROL_ROOT / "tasks" / task_id / CLAIM_DIRECTORY
    module.assert_allowed_path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{key}.json"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    try:
        os.write(descriptor, module.canonical_json(identity_fields(document)))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return True


def idempotent_ingest(module, task_id: str, document: dict[str, Any]) -> dict[str, Any]:
    """Ingest at most once per transaction identity, whatever the message bytes are."""
    key = identity_key(module, document)
    if not claim_identity(module, task_id, key, document):
        return {
            "outcome": "DUPLICATE_SUPPRESSED_BY_IDENTITY",
            "identity_key": key,
            "obzio_state": None,
            "errors": [],
        }
    ingestion = module.ingest_result(task_id, document)
    return {
        "outcome": "INGESTED",
        "identity_key": key,
        "obzio_state": ingestion["obzio_state"],
        "errors": ingestion["errors"],
    }


def registry_rows(module) -> list[dict[str, Any]]:
    registry = module.CONTROL_ROOT / "work-unit-registry.jsonl"
    if not registry.is_file():
        return []
    return [
        json.loads(line)
        for line in registry.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
