#!/usr/bin/env python3
"""Verify every A2 result artifact from the pushed remote-tracking branch."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RESULTS = REPO_ROOT / "workstreams" / "po03" / "control" / "units" / "a2"


def git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def verify(path: Path) -> tuple[str, int]:
    document = json.loads(path.read_text(encoding="utf-8"))
    branch = None
    commit = None
    for artifact in document["artifacts"]:
        locator = artifact["content_uri"]
        prefix, relative = locator.rsplit(":", 1)
        branch_at_commit = prefix.removeprefix("git:")
        artifact_branch, artifact_commit = branch_at_commit.rsplit("@", 1)
        branch = branch or artifact_branch
        commit = commit or artifact_commit
        if branch != artifact_branch or commit != artifact_commit:
            raise RuntimeError(f"{path}: mixed artifact custody locators")
        remote_ref = f"origin/{artifact_branch}"
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", artifact_commit, remote_ref],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        )
        payload = git_bytes("cat-file", "blob", f"{remote_ref}:{relative}")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != artifact["sha256"]:
            raise RuntimeError(
                f"{document['task_id']}:{relative}: remote sha256 {digest} != {artifact['sha256']}"
            )
        if len(payload) != artifact["bytes"]:
            raise RuntimeError(
                f"{document['task_id']}:{relative}: remote bytes {len(payload)} != {artifact['bytes']}"
            )
    print(
        f"READBACK_OK {document['task_id']} artifacts={len(document['artifacts'])} "
        f"remote=origin/{branch} source_commit={commit}"
    )
    return document["task_id"], len(document["artifacts"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="*", type=Path)
    args = parser.parse_args()
    paths = args.results or sorted(DEFAULT_RESULTS.glob("a2-u*.json"))
    artifact_count = 0
    for path in paths:
        _, count = verify(path.resolve())
        artifact_count += count
    print(f"READBACK_COMPLETE results={len(paths)} artifacts={artifact_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
