#!/usr/bin/env python3
"""Adversarial, non-mutating check for silent loss of unique evidence."""

from __future__ import annotations

import hashlib
from typing import Mapping


class SilentDeletionDetected(RuntimeError):
    """Raised when a current unique evidence digest vanishes."""


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def detect_silent_deletions(
    before: Mapping[str, bytes],
    after: Mapping[str, bytes],
    current_pointer_paths: set[str] | frozenset[str],
) -> list[dict[str, str]]:
    """Find referenced, unique-before digests absent from the after snapshot."""

    before_counts: dict[str, int] = {}
    for body in before.values():
        digest = _digest(body)
        before_counts[digest] = before_counts.get(digest, 0) + 1
    after_digests = {_digest(body) for body in after.values()}
    violations = []
    for path in sorted(current_pointer_paths):
        if path not in before:
            continue
        digest = _digest(before[path])
        if before_counts[digest] == 1 and digest not in after_digests:
            violations.append({"path": path, "sha256": digest, "reason": "unique referenced evidence vanished"})
    return violations


def assert_no_silent_deletion(
    before: Mapping[str, bytes],
    after: Mapping[str, bytes],
    current_pointer_paths: set[str] | frozenset[str],
) -> None:
    violations = detect_silent_deletions(before, after, current_pointer_paths)
    if violations:
        raise SilentDeletionDetected(str(violations))
