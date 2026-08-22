#!/usr/bin/env python3
"""Fail-closed authorization for deletion of depended-upon evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class DeletionBlocked(PermissionError):
    """Raised when deletion would remove the only referenced evidence copy."""


@dataclass(frozen=True)
class DeletionDecision:
    allowed: bool
    path: str
    sha256: str
    hash_copies: int
    referenced: bool
    reason: str


def evaluate_deletion(
    candidate: str | Path,
    inventory: Iterable[str | Path],
    current_pointer_paths: Iterable[str | Path],
) -> DeletionDecision:
    """Authorize only when the candidate is not unique referenced evidence.

    This function only evaluates authorization.  It never unlinks or mutates a
    file, making callers responsible for a separately approved deletion step.
    """

    candidate_path = Path(candidate)
    paths = sorted({Path(path) for path in inventory}, key=lambda item: item.as_posix())
    if candidate_path not in paths:
        raise DeletionBlocked(f"candidate is absent from evidence inventory: {candidate_path}")
    candidate_bytes = candidate_path.read_bytes()
    digest = hashlib.sha256(candidate_bytes).hexdigest()
    copies = sum(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path in paths)
    referenced_paths = {Path(path).as_posix() for path in current_pointer_paths}
    referenced = candidate_path.as_posix() in referenced_paths
    allowed = not (copies == 1 and referenced)
    reason = (
        "unique content is referenced by a current pointer"
        if not allowed
        else "duplicate content or no current-pointer dependency"
    )
    return DeletionDecision(allowed, candidate_path.as_posix(), digest, copies, referenced, reason)


def assert_deletion_allowed(
    candidate: str | Path,
    inventory: Iterable[str | Path],
    current_pointer_paths: Iterable[str | Path],
) -> DeletionDecision:
    decision = evaluate_deletion(candidate, inventory, current_pointer_paths)
    if not decision.allowed:
        raise DeletionBlocked(decision.reason)
    return decision
