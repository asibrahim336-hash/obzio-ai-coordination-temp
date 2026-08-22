#!/usr/bin/env python3
"""Repair candidate for the push-boundary gap found by this unit.

Staged inside this unit's subtree only.  The live mechanism is not modified by
this file; a coordinator would have to adopt it deliberately.

The gap: `ingest_result` reads every artifact with `git cat-file` inside the
coordinator's own repository and never reaches for the remote.  A result that
was pushed but never reported therefore fails ingestion with exactly the same
error as a result that was never pushed at all, so the coordinator can neither
distinguish the two nor recover the durable one.

The candidate adds two things and changes nothing else: a classifier that asks
the remote whether the object exists, and a recovery step that fetches the
object before re-ingesting through the unmodified `ingest_result`.
"""

from __future__ import annotations

import subprocess
from typing import Any


ABSENT_EVERYWHERE = "ABSENT_EVERYWHERE"
PRESENT_LOCALLY = "PRESENT_LOCALLY"
PRESENT_ON_REMOTE_NOT_FETCHED = "PRESENT_ON_REMOTE_NOT_FETCHED"


def _git(repo, *arguments: str) -> dict[str, Any]:
    completed = subprocess.run(("git", *arguments), cwd=repo, capture_output=True, text=True)
    return {"returncode": completed.returncode, "stdout": completed.stdout.strip()}


def object_present_locally(module, commit: str) -> bool:
    return _git(module.REPO_ROOT, "cat-file", "-e", f"{commit}^{{commit}}")["returncode"] == 0


def object_present_on_remote(module, remote: str, commit: str) -> bool:
    """Ask the remote directly instead of guessing from a local failure."""
    if _git(module.REPO_ROOT, "fetch", "--quiet", remote, commit)["returncode"] == 0:
        return _git(module.REPO_ROOT, "cat-file", "-e", f"{commit}^{{commit}}")["returncode"] == 0
    return False


def classify_missing_result(module, remote: str, commit: str) -> str:
    """Distinguish a result that was never pushed from one the coordinator has not fetched."""
    if object_present_locally(module, commit):
        return PRESENT_LOCALLY
    if object_present_on_remote(module, remote, commit):
        return PRESENT_ON_REMOTE_NOT_FETCHED
    return ABSENT_EVERYWHERE


def recover_from_remote(module, task_id: str, document: dict[str, Any], remote: str) -> dict[str, Any]:
    """Fetch a pushed-but-unfetched result, then ingest it through the live path."""
    commit = document.get("result_transaction", {}).get("result_commit_id")
    if not isinstance(commit, str) or not commit:
        return {"classification": "NO_RESULT_COMMIT_ID", "ingestion": None}
    classification = classify_missing_result(module, remote, commit)
    if classification == ABSENT_EVERYWHERE:
        return {"classification": classification, "ingestion": None}
    ingestion = module.ingest_result(task_id, document)
    return {
        "classification": classification,
        "ingestion": ingestion,
        "obzio_state": ingestion["obzio_state"],
        "errors": ingestion["errors"],
    }
