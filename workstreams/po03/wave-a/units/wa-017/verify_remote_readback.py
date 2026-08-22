#!/usr/bin/env python3
"""Verify a manifest and every payload artifact through immutable git-show."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_MANIFEST = (
    "workstreams/po03/wave-a/units/wa-017/result/artifact-manifest.json"
)


def git(repository: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repository), *args])


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify(
    repository: Path,
    commit: str,
    manifest_path: str,
    expected_manifest_sha256: str | None,
) -> dict[str, Any]:
    resolved = git(repository, "rev-parse", "--verify", f"{commit}^{{commit}}")
    resolved_commit = resolved.decode("ascii").strip()
    if not FULL_SHA.fullmatch(commit) or resolved_commit != commit:
        raise ValueError("commit must resolve exactly as a full immutable SHA")
    manifest_bytes = git(repository, "show", f"{commit}:{manifest_path}")
    manifest_sha = sha256(manifest_bytes)
    if (
        expected_manifest_sha256 is not None
        and manifest_sha != expected_manifest_sha256
    ):
        raise ValueError("manifest SHA-256 differs from the expected digest")
    manifest = json.loads(manifest_bytes)
    if manifest["artifact_count"] != len(manifest["artifacts"]):
        raise ValueError("manifest artifact_count differs")
    rows: list[dict[str, Any]] = []
    for artifact in manifest["artifacts"]:
        path = artifact["content_uri"]
        data = git(repository, "show", f"{commit}:{path}")
        observed = {"bytes": len(data), "sha256": sha256(data)}
        matches = (
            observed["bytes"] == artifact["bytes"]
            and observed["sha256"] == artifact["sha256"]
        )
        rows.append(
            {
                "bytes": observed["bytes"],
                "logical_name": artifact["logical_name"],
                "matches": matches,
                "sha256": observed["sha256"],
            }
        )
    total = sum(row["bytes"] for row in rows)
    all_match = (
        all(row["matches"] for row in rows)
        and len(rows) == manifest["artifact_count"]
        and total == manifest["total_bytes"]
    )
    return {
        "all_match": all_match,
        "artifact_count": len(rows),
        "artifacts": rows,
        "commit": commit,
        "manifest_bytes": len(manifest_bytes),
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha,
        "method": (
            "git show <immutable-commit>:<path> from a separately supplied "
            "repository for the manifest and every declared artifact"
        ),
        "total_bytes": total,
    }


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--manifest-path", default=DEFAULT_MANIFEST)
    parser.add_argument("--expected-manifest-sha256")
    args = parser.parse_args()
    try:
        result = verify(
            args.repository.resolve(),
            args.commit,
            args.manifest_path,
            args.expected_manifest_sha256,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"REFUSED: {exc}")
        return 2
    print(json_bytes(result).decode("utf-8"), end="")
    return 0 if result["all_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
