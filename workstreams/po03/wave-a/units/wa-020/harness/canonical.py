"""Canonical serialisation and digests.

Every digest in this unit is taken over the same canonical byte form, so a
digest recorded in one document can be recomputed from another without knowing
how the object was built.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    """Return the canonical UTF-8 bytes of a JSON-compatible value."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    """SHA-256 over the canonical byte form of a JSON-compatible value."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def digest_bytes(payload: bytes) -> str:
    """SHA-256 over exact bytes."""
    return hashlib.sha256(payload).hexdigest()


def write_json(path, value: Any) -> tuple[str, int]:
    """Write a document in a stable, readable form; return its digest and size."""
    payload = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return digest_bytes(payload), len(payload)
