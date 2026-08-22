#!/usr/bin/env python3
"""Read a WA-007 payload back from an immutable commit in a fresh repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import PurePosixPath
from typing import Sequence


OBJECT_ID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _validate_repo_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe repository path: {value!r}")
    return path.as_posix()


def _git(repo: str, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", repo, *arguments],
        check=False,
        capture_output=True,
    )


def _git_bytes(repo: str, commit: str, path: str) -> bytes:
    process = _git(repo, "show", "--no-textconv", f"{commit}:{path}")
    if process.returncode:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git show failed for {path}: {detail}")
    return process.stdout


def _parse_extra(value: str) -> tuple[str, str, int]:
    try:
        path, digest, size_text = value.rsplit("|", 2)
        size = int(size_text)
    except (ValueError, TypeError) as exc:
        raise ValueError("extra must be PATH|SHA256|BYTES") from exc
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("extra SHA-256 must be lowercase hexadecimal")
    if size < 0:
        raise ValueError("extra byte count must be non-negative")
    return _validate_repo_path(path), digest, size


def verify(
    *,
    remote: str,
    branch: str,
    commit: str,
    manifest_path: str,
    manifest_sha256: str,
    manifest_bytes: int,
    extra_specs: Sequence[str] = (),
) -> dict[str, object]:
    if not remote:
        raise ValueError("remote must be non-empty")
    if not branch or branch.startswith("-") or any(char.isspace() for char in branch):
        raise ValueError("branch must be a safe non-empty ref component")
    if not OBJECT_ID_RE.fullmatch(commit):
        raise ValueError("commit must be a full lowercase Git object ID")
    manifest_path = _validate_repo_path(manifest_path)
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        raise ValueError("manifest SHA-256 must be lowercase hexadecimal")
    if manifest_bytes < 1:
        raise ValueError("manifest byte count must be positive")
    extras = [_parse_extra(value) for value in extra_specs]

    with tempfile.TemporaryDirectory(prefix="po03-wa007-readback-") as temporary:
        initial = _git(temporary, "init", "-q")
        if initial.returncode:
            raise ValueError(initial.stderr.decode("utf-8", errors="replace"))
        fetch = _git(
            temporary,
            "fetch",
            "--force",
            "--no-tags",
            "--depth=1",
            remote,
            f"+refs/heads/{branch}:refs/remotes/readback/{branch}",
        )
        if fetch.returncode:
            detail = fetch.stderr.decode("utf-8", errors="replace").strip()
            raise ValueError(f"fetch failed: {detail}")
        tip_process = _git(
            temporary,
            "rev-parse",
            "--verify",
            f"refs/remotes/readback/{branch}^{{commit}}",
        )
        if tip_process.returncode:
            raise ValueError("fetched branch tip is not a commit")
        remote_tip = tip_process.stdout.decode("ascii").strip()
        if remote_tip != commit:
            raise ValueError(
                f"remote branch tip mismatch: expected {commit}, observed {remote_tip}"
            )

        manifest_data = _git_bytes(temporary, commit, manifest_path)
        manifest_digest = hashlib.sha256(manifest_data).hexdigest()
        if manifest_digest != manifest_sha256 or len(manifest_data) != manifest_bytes:
            raise ValueError("manifest digest or byte count mismatch")
        try:
            manifest = json.loads(manifest_data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"manifest is not UTF-8 JSON: {exc}") from exc
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise ValueError("manifest artifacts must be an array")

        expected: list[tuple[str, str, int, str]] = []
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                raise ValueError(f"manifest artifact {index} is not an object")
            path = _validate_repo_path(str(artifact.get("content_uri", "")))
            digest = artifact.get("sha256")
            size = artifact.get("bytes")
            if not isinstance(digest, str) or not re.fullmatch(
                r"[0-9a-f]{64}", digest
            ):
                raise ValueError(f"manifest artifact {index} has invalid SHA-256")
            if not isinstance(size, int) or size < 1:
                raise ValueError(f"manifest artifact {index} has invalid bytes")
            expected.append((path, digest, size, "payload"))
        expected.append(
            (manifest_path, manifest_sha256, manifest_bytes, "manifest")
        )
        expected.extend(
            (path, digest, size, "extra") for path, digest, size in extras
        )

        checks: list[dict[str, object]] = []
        seen: set[str] = set()
        for path, digest, size, role in expected:
            if path in seen:
                raise ValueError(f"duplicate readback path: {path}")
            seen.add(path)
            data = _git_bytes(temporary, commit, path)
            observed_digest = hashlib.sha256(data).hexdigest()
            matches = observed_digest == digest and len(data) == size
            checks.append(
                {
                    "path": path,
                    "role": role,
                    "sha256": observed_digest,
                    "bytes": len(data),
                    "matches": matches,
                }
            )
        all_match = all(bool(check["matches"]) for check in checks)
        return {
            "protocol_version": "OBZIO-IMMUTABLE-REMOTE-READBACK-v1",
            "branch": branch,
            "commit": commit,
            "remote_tip": remote_tip,
            "artifact_count": len(checks),
            "all_match": all_match,
            "checks": checks,
            "decision_changed": [],
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--manifest-bytes", type=int, required=True)
    parser.add_argument("--extra", action="append", default=[])
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = verify(
            remote=args.remote,
            branch=args.branch,
            commit=args.commit,
            manifest_path=args.manifest,
            manifest_sha256=args.manifest_sha256,
            manifest_bytes=args.manifest_bytes,
            extra_specs=args.extra,
        )
    except ValueError as exc:
        print(f"READBACK_ERROR: {exc}", file=sys.stderr)
        return 2
    json.dump(
        result,
        sys.stdout,
        indent=2 if args.pretty else None,
        sort_keys=True,
        separators=None if args.pretty else (",", ":"),
    )
    sys.stdout.write("\n")
    return 0 if result["all_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
