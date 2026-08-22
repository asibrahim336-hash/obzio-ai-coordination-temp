#!/usr/bin/env python3
"""Read-only reproduction harness for scripts/check_operator_taxonomy.py.

FALSIFIABLE HYPOTHESIS (task po03-wa-b2e7-012-currentness-gate-reproduction):
    The repository currentness check is reproducible from an immutable
    commit and its verdict is stable.

This harness never checks out a pinned commit into the live worktree and
never modifies `scripts/check_operator_taxonomy.py` or any file it reads.
For each commit it is asked to reproduce, it:

  1. Runs `git archive <commit>` (read-only; does not touch the worktree
     index or working tree) and extracts the resulting tree into a
     throwaway temporary directory.
  2. Runs the *exact bytes* of `scripts/check_operator_taxonomy.py` that
     were committed at that commit, against that read-only snapshot, with
     `python3 -I`.
  3. Records the verdict line, exit code, and a SHA-256 of the captured
     stdout.
  4. Deletes the temporary directory. Nothing under the scratch directory
     is treated as durable evidence; the caller must persist the returned
     dict into a committed file.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_REL_PATH = "scripts/check_operator_taxonomy.py"


class ReproductionError(Exception):
    """Raised when a commit cannot be archived/read at all (fail-closed)."""


def archive_commit_to_tempdir(repo_root: Path, commit: str) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix=f"po03-repro-{commit[:12]}-"))
    try:
        completed = subprocess.run(
            ("git", "archive", commit),
            cwd=repo_root,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ReproductionError(f"git archive failed for {commit}: {exc.stderr!r}") from exc
    with tarfile.open(fileobj=io.BytesIO(completed.stdout)) as tar:
        tar.extractall(tmpdir)  # nosec B202 - content is our own immutable commit tree
    return tmpdir


def blob_sha(repo_root: Path, commit: str, path: str) -> str | None:
    completed = subprocess.run(
        ("git", "rev-parse", f"{commit}:{path}"),
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def run_taxonomy_check(snapshot_root: Path, script_rel_path: str = SCRIPT_REL_PATH) -> dict[str, Any]:
    script = snapshot_root / script_rel_path
    if not script.is_file():
        return {"script_found": False, "exit_code": None, "stdout_sha256": None, "verdict": "SCRIPT_MISSING"}
    completed = subprocess.run(
        (sys.executable, "-I", str(script)),
        cwd=snapshot_root,
        capture_output=True,
        text=True,
    )
    stdout_sha256 = hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest()
    if "OPERATOR TAXONOMY CHECK: PASS" in completed.stdout:
        verdict = "PASS"
    elif "OPERATOR TAXONOMY CHECK: FAIL" in completed.stdout:
        verdict = "FAIL"
    else:
        verdict = "UNKNOWN"
    return {
        "script_found": True,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "stdout_sha256": stdout_sha256,
        "verdict": verdict,
    }


def reproduce_at_commit(repo_root: Path, commit: str) -> dict[str, Any]:
    """Extract `commit` into a scratch snapshot, run its own
    check_operator_taxonomy.py against it, and clean up. Returns a
    self-contained, JSON-serialisable report."""
    repo_root = Path(repo_root)
    tmpdir = archive_commit_to_tempdir(repo_root, commit)
    try:
        result = run_taxonomy_check(tmpdir)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    result["commit"] = commit
    result["script_blob_sha"] = blob_sha(repo_root, commit, SCRIPT_REL_PATH)
    return result


def reproduce_many(repo_root: Path, commits: list[str]) -> list[dict[str, Any]]:
    return [reproduce_at_commit(repo_root, commit) for commit in commits]


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(default_root))
    parser.add_argument("--commit", action="append", dest="commits", required=True)
    args = parser.parse_args(argv)

    reports = []
    for commit in args.commits:
        try:
            reports.append(reproduce_at_commit(Path(args.repo_root), commit))
        except ReproductionError as exc:
            reports.append({"commit": commit, "error": str(exc)})

    print(json.dumps(reports, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
