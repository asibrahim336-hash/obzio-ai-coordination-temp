#!/usr/bin/env python3
"""Fetch a branch, detect tip movement, and verify pinned artifact bytes.

The verifier deliberately separates the mutable branch observation from
artifact identity.  A forced fetch updates one dedicated remote-tracking ref;
artifact bytes are always read from the caller's immutable commit with
``git show --no-textconv <commit>:<path>`` and checked against a frozen
SHA-256/byte manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


OBJECT_ID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_TRACKING_REF = "refs/remotes/immutable-readback/target"


class VerificationError(ValueError):
    """The request or repository state cannot support verification."""


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if check and completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise VerificationError(f"git {' '.join(args)} failed: {detail}")
    return completed


def _resolve_ref(repo: Path, ref: str) -> str | None:
    completed = _git(repo, "rev-parse", "--verify", ref, check=False)
    if completed.returncode:
        return None
    value = completed.stdout.decode("ascii").strip()
    return value if OBJECT_ID_RE.fullmatch(value) else None


def _normalize_branch(branch: str) -> str:
    value = branch.removeprefix("refs/heads/")
    if not value or value.startswith("-") or ".." in value or value.endswith("/"):
        raise VerificationError("branch must be a non-empty refs/heads-relative name")
    return value


def _validate_tracking_ref(tracking_ref: str) -> str:
    if not tracking_ref.startswith("refs/remotes/immutable-readback/"):
        raise VerificationError(
            "tracking_ref must stay below refs/remotes/immutable-readback/"
        )
    if tracking_ref.startswith("-") or ".." in tracking_ref or tracking_ref.endswith("/"):
        raise VerificationError("tracking_ref is not a safe ref name")
    return tracking_ref


def _validate_artifact(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise VerificationError(f"artifacts[{index}] must be an object")
    path_value = item.get("path", item.get("content_uri"))
    digest = item.get("sha256")
    byte_count = item.get("bytes")
    if not isinstance(path_value, str) or not path_value:
        raise VerificationError(f"artifacts[{index}].path must be non-empty")
    path = PurePosixPath(path_value)
    if path.is_absolute() or ".." in path.parts or path_value.startswith(":"):
        raise VerificationError(f"artifacts[{index}].path is not repository-relative")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise VerificationError(f"artifacts[{index}].sha256 is invalid")
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
        raise VerificationError(f"artifacts[{index}].bytes must be an integer >= 0")
    return {
        "path": path.as_posix(),
        "sha256": digest,
        "bytes": byte_count,
    }


def load_manifest(path: Path) -> list[dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot load manifest: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("artifacts"), list):
        raise VerificationError("manifest root must contain an artifacts array")
    artifacts = [
        _validate_artifact(item, index)
        for index, item in enumerate(document["artifacts"])
    ]
    if not artifacts:
        raise VerificationError("manifest must contain at least one artifact")
    paths = [item["path"] for item in artifacts]
    if len(paths) != len(set(paths)):
        raise VerificationError("manifest artifact paths must be unique")
    return artifacts


def verify_readback(
    *,
    repo: Path,
    remote: str,
    branch: str,
    expected_commit: str,
    artifacts: Sequence[dict[str, Any]],
    tracking_ref: str = DEFAULT_TRACKING_REF,
    require_branch_moved: bool = False,
) -> dict[str, Any]:
    """Run one fetch/readback transaction and return machine-readable evidence."""

    if not repo.is_dir():
        raise VerificationError("repo must be an existing Git repository directory")
    if not OBJECT_ID_RE.fullmatch(expected_commit):
        raise VerificationError("expected_commit must be a full SHA-1 or SHA-256 object ID")
    branch = _normalize_branch(branch)
    tracking_ref = _validate_tracking_ref(tracking_ref)
    normalized_artifacts = [
        _validate_artifact(item, index) for index, item in enumerate(artifacts)
    ]
    if not normalized_artifacts:
        raise VerificationError("at least one artifact is required")

    tracking_before = _resolve_ref(repo, tracking_ref)
    source_ref = f"refs/heads/{branch}"
    refspec = f"+{source_ref}:{tracking_ref}"
    fetch = _git(repo, "fetch", "--no-tags", "--force", remote, refspec)
    tracking_after = _resolve_ref(repo, tracking_ref)
    if tracking_after is None:
        raise VerificationError("fetch completed without resolving the tracking ref")

    commit_check = _git(
        repo, "cat-file", "-e", f"{expected_commit}^{{commit}}", check=False
    )
    if commit_check.returncode:
        raise VerificationError(
            "expected immutable commit is unavailable after fetch; "
            "it must be fetched while reachable before branch movement"
        )

    artifact_results: list[dict[str, Any]] = []
    for artifact in normalized_artifacts:
        object_spec = f"{expected_commit}:{artifact['path']}"
        object_type = _git(repo, "cat-file", "-t", object_spec).stdout.decode("ascii").strip()
        if object_type != "blob":
            raise VerificationError(f"{artifact['path']} resolves to {object_type}, not blob")
        content = _git(repo, "show", "--no-textconv", object_spec).stdout
        observed_digest = hashlib.sha256(content).hexdigest()
        observed_bytes = len(content)
        digest_matches = observed_digest == artifact["sha256"]
        bytes_match = observed_bytes == artifact["bytes"]
        artifact_results.append(
            {
                "path": artifact["path"],
                "expected_sha256": artifact["sha256"],
                "observed_sha256": observed_digest,
                "expected_bytes": artifact["bytes"],
                "observed_bytes": observed_bytes,
                "digest_matches": digest_matches,
                "bytes_match": bytes_match,
                "matches": digest_matches and bytes_match,
                "read_command": (
                    f"git show --no-textconv {expected_commit}:{artifact['path']}"
                ),
            }
        )

    branch_tip_moved = tracking_after != expected_commit
    all_artifacts_match = all(item["matches"] for item in artifact_results)
    movement_requirement_met = branch_tip_moved if require_branch_moved else True
    return {
        "protocol_version": "OBZIO-IMMUTABLE-READBACK-v1",
        "remote": remote,
        "branch_ref": source_ref,
        "tracking_ref": tracking_ref,
        "tracking_tip_before_fetch": tracking_before,
        "tracking_tip_after_fetch": tracking_after,
        "tracking_ref_moved_during_fetch": (
            tracking_before is not None and tracking_before != tracking_after
        ),
        "expected_commit": expected_commit,
        "branch_tip_moved_from_expected_commit": branch_tip_moved,
        "require_branch_moved": require_branch_moved,
        "movement_requirement_met": movement_requirement_met,
        "fetch_stderr": fetch.stderr.decode("utf-8", errors="replace").strip(),
        "artifacts": artifact_results,
        "all_artifacts_match": all_artifacts_match,
        "success": movement_requirement_met and all_artifacts_match,
    }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--remote", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--tracking-ref", default=DEFAULT_TRACKING_REF)
    parser.add_argument("--require-branch-moved", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        result = verify_readback(
            repo=args.repo,
            remote=args.remote,
            branch=args.branch,
            expected_commit=args.expected_commit,
            artifacts=load_manifest(args.manifest),
            tracking_ref=args.tracking_ref,
            require_branch_moved=args.require_branch_moved,
        )
    except VerificationError as exc:
        result = {
            "protocol_version": "OBZIO-IMMUTABLE-READBACK-v1",
            "success": False,
            "error": str(exc),
        }
        encoded = _json_bytes(result)
        if args.output:
            args.output.write_bytes(encoded)
        sys.stdout.buffer.write(encoded)
        return 2

    encoded = _json_bytes(result)
    if args.output:
        args.output.write_bytes(encoded)
    sys.stdout.buffer.write(encoded)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
