#!/usr/bin/env python3
"""Repair candidate for the three fencing gaps found by this unit.

Staged inside this unit's subtree only.  The live mechanism is not modified by
this file; a coordinator would have to adopt it deliberately.

Gap 1 — allocation is a read-modify-write.  `allocate_fence` reads the counter,
adds one and replaces the file.  Two allocators that interleave inside that
window receive the same token, so fencing can no longer tell two live workers
apart.  The candidate allocates by exclusively creating a per-token file, which
makes uniqueness a property of the filesystem rather than of timing.

Gap 2 — `assert_fence_current` only rejects a token lower than the active
fence, so a token that was never allocated at all passes.  The candidate
requires exact equality with the active lease.

Gap 3 — `lease_seconds` and `granted_at` are recorded and never read again, so
an expired holder is still accepted.  The candidate enforces the recorded
lifetime against an explicit observation time.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TOKEN_DIRECTORY = "fence-tokens"


class ForgedFenceError(RuntimeError):
    """Raised when a worker presents a fence token that is not the active one."""


class LeaseExpiredError(RuntimeError):
    """Raised when a holder's recorded lease lifetime has elapsed."""


def allocate_fence_exclusive(module, *, attempts: int = 4096) -> int:
    """Allocate a unique token by exclusive file creation instead of read-modify-write."""
    directory = module.CONTROL_ROOT / TOKEN_DIRECTORY
    module.assert_allowed_path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    existing = [int(path.stem) for path in directory.glob("*.token") if path.stem.isdigit()]
    candidate = max(existing, default=0) + 1
    for _ in range(attempts):
        path = directory / f"{candidate:012d}.token"
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            candidate += 1
            continue
        try:
            os.write(descriptor, module.canonical_json({"fence_token": candidate}))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return candidate
    raise RuntimeError("fence allocation exhausted its attempt budget")


def assert_fence_exact(module, task_id: str, fence_token: Any) -> None:
    """Accept only the fence token of the lease that is actually held."""
    active = module.current_fence(task_id)
    if active == 0:
        raise ForgedFenceError(f"{task_id}: no lease is held, so no fence token is valid")
    if not isinstance(fence_token, int) or fence_token != active:
        raise ForgedFenceError(
            f"{task_id}: fence {fence_token!r} is not the active fence {active}"
        )


def lease_document(module, task_id: str) -> dict[str, Any] | None:
    path = module.CONTROL_ROOT / "leases" / f"{task_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def lease_expiry(lease: dict[str, Any]) -> datetime:
    granted = datetime.fromisoformat(lease["granted_at"].replace("Z", "+00:00"))
    return granted + timedelta(seconds=int(lease["lease_seconds"]))


def assert_lease_live(module, task_id: str, *, observed_at: datetime | None = None) -> None:
    """Enforce the lifetime the lease already records."""
    lease = lease_document(module, task_id)
    if lease is None:
        raise LeaseExpiredError(f"{task_id}: no lease document exists")
    now = observed_at or datetime.now(timezone.utc)
    expires_at = lease_expiry(lease)
    if now >= expires_at:
        raise LeaseExpiredError(
            f"{task_id}: lease {lease['lease_id']} expired at {expires_at.isoformat()}"
        )


def guarded_ingest(
    module,
    task_id: str,
    document: dict[str, Any],
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Apply exact fencing and lease-lifetime checks before the live ingestion."""
    attempt = document.get("attempt", {}) if isinstance(document.get("attempt"), dict) else {}
    try:
        assert_fence_exact(module, task_id, attempt.get("fence_token"))
        assert_lease_live(module, task_id, observed_at=observed_at)
    except (ForgedFenceError, LeaseExpiredError) as exc:
        return {
            "obzio_state": "RECOVERY_REQUIRED",
            "errors": [str(exc)],
            "refused_before_live_ingestion": True,
        }
    ingestion = module.ingest_result(task_id, document)
    ingestion["refused_before_live_ingestion"] = False
    return ingestion
