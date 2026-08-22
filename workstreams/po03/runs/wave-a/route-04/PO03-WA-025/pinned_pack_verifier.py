#!/usr/bin/env python3
"""Verify every pack claim against bytes in its immutable Git commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )


def _safe_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def verify_claims(repo: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    commit = manifest.get("source_commit")
    entries = manifest.get("artifacts")
    defects: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []
    if not isinstance(commit, str) or len(commit) != 40:
        defects.append({"code": "INVALID_PINNED_COMMIT"})
        entries = []
    if not isinstance(entries, list) or not entries:
        defects.append({"code": "EMPTY_CLAIM_SET"})
        entries = []

    for index, claim in enumerate(entries):
        path = _safe_path(claim.get("path") if isinstance(claim, dict) else None)
        if path is None:
            defects.append({"code": "INVALID_CLAIM_PATH", "index": index})
            continue
        object_name = f"{commit}:{path}"
        presence = _git(repo, "cat-file", "-e", object_name, check=False)
        if presence.returncode:
            defects.append(
                {
                    "code": "CLAIMED_FILE_ABSENT_AT_PINNED_COMMIT",
                    "index": index,
                    "path": path,
                    "commit": commit,
                }
            )
            continue
        payload = _git(repo, "cat-file", "blob", object_name).stdout
        observed = {
            "path": path,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        observed["matched"] = (
            observed["bytes"] == claim.get("bytes")
            and observed["sha256"] == claim.get("sha256")
        )
        if not observed["matched"]:
            defects.append({"code": "PINNED_BYTES_MISMATCH", **observed})
        checked.append(observed)

    return {
        "criterion": "all claimed files exist with claimed bytes at the pinned commit",
        "pinned_commit": commit,
        "claims_declared": len(entries),
        "claims_checked": len(checked),
        "defects": defects,
        "disposition": "PASS" if entries and not defects else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    report = verify_claims(args.repo, json.loads(args.manifest.read_text(encoding="utf-8")))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["disposition"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
