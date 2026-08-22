#!/usr/bin/env python3
"""Qualify manifest declarations directly from an immutable Git commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import PurePosixPath
from typing import Any


def git_bytes(repo: str, *args: str) -> bytes:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True
    ).stdout


def blob(repo: str, commit: str, path: str) -> bytes | None:
    proc = subprocess.run(
        ("git", "cat-file", "blob", f"{commit}:{path}"),
        cwd=repo,
        check=False,
        capture_output=True,
    )
    return proc.stdout if proc.returncode == 0 else None


def declarations(manifest_path: str, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    pack_dir = PurePosixPath(manifest_path).parent
    rows: list[dict[str, Any]] = []
    files = manifest.get("files", {})
    if isinstance(files, dict):
        for name, expected in files.items():
            rows.append({"path": str(pack_dir / name), **expected})
    elif isinstance(files, list):
        for expected in files:
            path = expected["path"]
            if "/" not in path:
                path = str(pack_dir / path)
            rows.append({"path": path, **{k: v for k, v in expected.items() if k != "path"}})

    required = manifest.get("requires", {})
    required_files = required.get("files", {}) if isinstance(required, dict) else {}
    if isinstance(required_files, dict):
        spine_dir = required.get("spine_dir")
        if spine_dir:
            root = pack_dir.parent
            for name, expected in required_files.items():
                rows.append({"path": str(root / spine_dir / name), **expected})
    return rows


def qualify(repo: str, commit: str, manifest_path: str) -> dict[str, Any]:
    manifest_raw = blob(repo, commit, manifest_path)
    if manifest_raw is None:
        return {
            "commit": commit,
            "manifest_path": manifest_path,
            "verdict": "FAIL",
            "problem": "manifest_absent",
            "evidence_table": [],
        }
    manifest = json.loads(manifest_raw)
    table = []
    for expected in declarations(manifest_path, manifest):
        path = expected["path"]
        body = blob(repo, commit, path)
        observed_hash = hashlib.sha256(body).hexdigest() if body is not None else None
        observed_bytes = len(body) if body is not None else None
        hash_match = body is not None and observed_hash == expected.get("sha256")
        bytes_match = body is not None and observed_bytes == expected.get("bytes")
        table.append(
            {
                "path": path,
                "declared_sha256": expected.get("sha256"),
                "observed_sha256": observed_hash,
                "declared_bytes": expected.get("bytes"),
                "observed_bytes": observed_bytes,
                "present": body is not None,
                "hash_match": hash_match,
                "bytes_match": bytes_match,
                "status": "MATCH" if hash_match and bytes_match else "MISMATCH",
            }
        )
    passed = bool(table) and all(row["status"] == "MATCH" for row in table)
    return {
        "commit": commit,
        "commit_type": git_bytes(repo, "cat-file", "-t", commit).decode().strip(),
        "manifest_path": manifest_path,
        "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "manifest_bytes": len(manifest_raw),
        "declaration_count": len(table),
        "matched_count": sum(row["status"] == "MATCH" for row in table),
        "verdict": "PASS" if passed else "FAIL",
        "evidence_table": table,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    result = qualify(args.repo, args.commit, args.manifest)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
