#!/usr/bin/env python3
"""Dispatch precondition: can a frozen task input still be resolved?

Recovery from an immutable task input is only possible if the pointers inside
that input resolve in the repository the recovering worker actually has.  A
commit-shaped string is not the same thing as a reachable commit, and nothing in
the seeded controls checks the difference.

This module reads only.  It never writes to the frozen inputs it inspects.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .seeded import SEEDED_RELS, PINNED_DIGEST_KEYS, repository_root, sha256_file

WAVE_A_INPUT_DIR = "workstreams/po03/control/inputs/wave-a"

# source_base keys that name a git object and must therefore be reachable.
COMMIT_POINTER_KEYS = ("commission_commit", "minimum_protocol_ancestor")


def git_available(repo: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-dir"],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def object_type(repo: Path, oid: str) -> str | None:
    """Return the git object type for ``oid``, or None if it does not resolve."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-t", oid],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def check_input(path: Path, repo: Path, *, have_git: bool) -> dict[str, Any]:
    """Resolve every pointer and digest one frozen input depends on."""
    document = json.loads(path.read_text(encoding="utf-8"))
    source_base = document.get("source_base", {})
    findings: list[dict[str, Any]] = []

    for key in COMMIT_POINTER_KEYS:
        value = source_base.get(key)
        if not isinstance(value, str) or not value:
            findings.append({"pointer": key, "value": value, "disposition": "MISSING"})
            continue
        if not have_git:
            findings.append({"pointer": key, "value": value, "disposition": "NOT_SUPPORTED", "reason": "git unavailable"})
            continue
        resolved = object_type(repo, value)
        if resolved == "commit":
            findings.append({"pointer": key, "value": value, "disposition": "RESOLVES"})
            continue
        abbreviated = object_type(repo, value[:7]) if len(value) >= 7 else None
        findings.append(
            {
                "pointer": key,
                "value": value,
                "disposition": "UNRESOLVABLE",
                "abbreviated_prefix": value[:7],
                "abbreviated_resolves_to": abbreviated,
            }
        )

    for name, digest_key in sorted(PINNED_DIGEST_KEYS.items()):
        pinned = source_base.get(digest_key)
        target = repo / SEEDED_RELS[name]
        if not isinstance(pinned, str) or not pinned:
            findings.append({"pointer": digest_key, "disposition": "MISSING"})
            continue
        if not target.exists():
            findings.append({"pointer": digest_key, "disposition": "UNRESOLVABLE", "reason": "target missing"})
            continue
        observed = sha256_file(target)
        findings.append(
            {
                "pointer": digest_key,
                "disposition": "RESOLVES" if observed == pinned else "DRIFTED",
                "observed_sha256": observed,
                "pinned_sha256": pinned,
            }
        )

    unresolvable = [f for f in findings if f["disposition"] in {"UNRESOLVABLE", "MISSING", "DRIFTED"}]
    return {
        "input_path": str(path.relative_to(repo)),
        "task_id": document.get("task_id"),
        "input_sha256": sha256_file(path),
        "findings": findings,
        "unresolvable_count": len(unresolvable),
        "resumable_from_immutable_input": not unresolvable,
    }


def check_wave_a(repo: Path | None = None) -> dict[str, Any]:
    """Apply the precondition to every frozen Wave A input."""
    base = repo or repository_root()
    have_git = git_available(base)
    directory = base / WAVE_A_INPUT_DIR
    inputs = sorted(directory.glob("*.json")) if directory.exists() else []
    rows = [check_input(path, base, have_git=have_git) for path in inputs]
    failing = [r for r in rows if not r["resumable_from_immutable_input"]]
    pointer_failures: dict[str, int] = {}
    for row in rows:
        for finding in row["findings"]:
            if finding["disposition"] in {"UNRESOLVABLE", "MISSING", "DRIFTED"}:
                pointer_failures[finding["pointer"]] = pointer_failures.get(finding["pointer"], 0) + 1
    return {
        "repository_root": str(base),
        "git_available": have_git,
        "input_count": len(rows),
        "resumable_count": len(rows) - len(failing),
        "non_resumable_count": len(failing),
        "pointer_failure_counts": pointer_failures,
        "rows": rows,
    }


def gate(repo: Path | None = None) -> tuple[bool, dict[str, Any]]:
    """Precondition gate: True only when every frozen input is resolvable."""
    report = check_wave_a(repo)
    return report["non_resumable_count"] == 0, report
