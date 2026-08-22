"""Materialise a commit-pinned test fixture inside the PO-03 owned allowlist."""

from __future__ import annotations

import io
import re
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
SNAPSHOT_PARENT = Path("workstreams/po03/strategy")


@contextmanager
def materialize_commit(repo_root: Path, commit: str) -> Iterator[Path]:
    """Yield an isolated tree for ``commit`` using read-only git plumbing."""
    if not COMMIT_SHA.fullmatch(commit):
        raise ValueError(f"snapshot commit must be a full SHA-1: {commit!r}")
    completed = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    parent = repo_root / SNAPSHOT_PARENT
    with tempfile.TemporaryDirectory(prefix=".a9-git-snapshot-", dir=parent) as name:
        snapshot_root = Path(name)
        with tarfile.open(fileobj=io.BytesIO(completed.stdout), mode="r:") as archive:
            archive.extractall(snapshot_root, filter="data")
        yield snapshot_root
