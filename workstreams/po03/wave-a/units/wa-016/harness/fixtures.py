#!/usr/bin/env python3
"""Sanitized repository-native fixtures for the custody workload.

The primary payload is the isolation-canary blob that PO-03 already committed to
an immutable remote commit during route verification.  Reusing it means the
harness exercises real Obzio bytes with an independently recorded digest rather
than a synthetic placeholder, and the expectations below are falsifiable against
the repository.

Nothing here contains credentials, owner identifiers or third-party content.
"""

from __future__ import annotations

from typing import Any

from .durable_io import canonical_json

# Committed by PO03-WA-ISOLATION-CANARY-001 at remote commit
# 371e8da6ab306c2948e0fe1f47c884ae46b2e81f, path
# workstreams/po03/runs/bc-b1956656-b897-4889-aeab-82c4556c1a9f/units/
# wa-isolation-canary-001/result/canary.txt
CANARY_TEXT = b"PO03 isolated-worktree canary: PO03-ISOLATION-CANARY-b1956656-90d2288-001\n"
CANARY_SHA256 = "5fdeb53d88f287e7e82006277c55ab0b3359b3b1881f408929359285be95f31b"
CANARY_BYTES = 74
CANARY_COMMIT = "371e8da6ab306c2948e0fe1f47c884ae46b2e81f"
CANARY_PATH = (
    "workstreams/po03/runs/bc-b1956656-b897-4889-aeab-82c4556c1a9f/units/"
    "wa-isolation-canary-001/result/canary.txt"
)

TASK_ID = "PO03-WA-016"
ATTEMPT_ID = "PO03-WA-016-A01"
IDEMPOTENCY_KEY = "po03:100bc20:wa-016:a01"
LEASE_ID = "lease-po03-wa-016-a01"
COMMISSION_ID = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"


def unit_result_payload() -> bytes:
    """Small deterministic result document staged alongside the canary blob."""
    return canonical_json(
        {
            "task_id": TASK_ID,
            "hypothesis_id": "H-PO03-WA-016",
            "workload": "transition-fault-injection",
            "payload_kind": "sanitized-repository-native",
        }
    )


def default_payload() -> list[tuple[str, bytes]]:
    return [("canary.txt", CANARY_TEXT), ("unit-result.json", unit_result_payload())]


def immutable_input_stub(**overrides: Any) -> dict[str, Any]:
    """The subset of the frozen input a recovering worker needs to resume."""
    stub = {
        "task_id": TASK_ID,
        "attempt_id": ATTEMPT_ID,
        "idempotency_key": IDEMPOTENCY_KEY,
        "lease_id": LEASE_ID,
        "fence_token": 1,
        "commission_id": COMMISSION_ID,
    }
    stub.update(overrides)
    return stub
