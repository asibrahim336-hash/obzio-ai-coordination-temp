#!/usr/bin/env python3
"""Shared test-support helper for asserting reproduction at an explicit,
immutable pin rather than against live, mutating shared state.

workstreams/po03/evidence/snapshot-coupling.json documents the defect class
this exists to prevent: a test that asserts a committed report equals a fresh
recomputation against *live* state (the ledger, another cohort's branch, the
unit population) is guaranteed to fail as the wave progresses, because the
measured state keeps changing after the report was committed. That failure
looks exactly like a regression and is not one -- a false red.

The fix used throughout workstreams/po03/tests/test_a7_*.py is to materialise
the exact subset of files this cohort's tools read, as those files existed at
an explicitly recorded, immutable commit, into a fresh temporary directory
that mirrors the repository's relative path layout, and recompute against
that directory instead of the live worktree. The recorded commit is chosen to
be the one whose committed artifact this cohort's own tool produced, so the
assertion is a genuine reproduction check (it still fails if the report, the
generator, or the pin itself is wrong or changes) without ever comparing
against a moving target.

Dependency-free standard-library Python 3.12.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def materialize_commit_subset(repo_root: Path, commit: str, relative_paths: list[str], dest: Path) -> None:
    """Write each of ``relative_paths`` into ``dest`` with the exact bytes it
    had at ``commit``. A path that does not exist at that commit is left
    absent in ``dest``, matching the semantics a live "file is absent" check
    would have seen at that same commit -- never invented, never skipped
    silently in a way that would change the result.
    """
    for relative in relative_paths:
        proc = subprocess.run(
            ["git", "cat-file", "blob", f"{commit}:{relative}"],
            cwd=str(repo_root),
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            continue
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(proc.stdout)
