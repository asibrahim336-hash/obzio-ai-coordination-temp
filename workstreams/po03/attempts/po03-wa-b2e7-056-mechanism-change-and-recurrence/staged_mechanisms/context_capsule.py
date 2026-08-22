"""Staged bounded and hash-verifiable context admission mechanism."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def build_capsule(
    full_context: Mapping[str, object],
    required_keys: Sequence[str],
    budget_fields: int,
) -> dict[str, object]:
    if len(set(required_keys)) != len(required_keys):
        raise ValueError("required_keys must be unique")
    if len(required_keys) > budget_fields:
        raise ValueError("required context exceeds admission budget")
    missing = [key for key in required_keys if key not in full_context]
    if missing:
        raise ValueError(f"missing required context: {missing}")
    payload = {key: full_context[key] for key in required_keys}
    return {"payload": payload, "sha256": hashlib.sha256(canonical(payload)).hexdigest()}


def verify_capsule(capsule: Mapping[str, object]) -> bool:
    payload = capsule.get("payload")
    digest = capsule.get("sha256")
    return isinstance(payload, dict) and isinstance(digest, str) and hashlib.sha256(canonical(payload)).hexdigest() == digest
