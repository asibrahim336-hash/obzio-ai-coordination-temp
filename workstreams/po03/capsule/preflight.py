#!/usr/bin/env python3
"""Refuse dispatch unless every immutable capsule source is CURRENT."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any


GIT_CAPSULE_PATH = Path(__file__).with_name("git_capsule.py")
_SPEC = importlib.util.spec_from_file_location("po03_git_capsule", GIT_CAPSULE_PATH)
_CAPSULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_CAPSULE)

canonical_bytes = _CAPSULE.canonical_bytes
create_capsule = _CAPSULE.create_capsule
load_capsule = _CAPSULE.load_capsule
manifest_sha256 = _CAPSULE.manifest_sha256
validate_capsule = _CAPSULE.validate_capsule


class PreflightError(ValueError):
    """Raised when a preflight input cannot be resolved deterministically."""


def _git(repo: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise PreflightError(f"git {' '.join(args)} failed: {detail or exc}") from exc


def _full_commit(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()


def _current_blob(repo: Path, commit_sha: str, path: str) -> str | None:
    output = _git(repo, "ls-tree", "-z", commit_sha, "--", path)
    rows = [row for row in output.split(b"\x00") if row]
    if not rows:
        return None
    if len(rows) != 1:
        raise PreflightError(
            f"{path}: expected at most one current tree entry, found {len(rows)}"
        )
    try:
        metadata, observed_path = rows[0].split(b"\t", 1)
        _mode, object_type, object_id = metadata.decode("ascii").split(" ")
        decoded_path = observed_path.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise PreflightError(f"{path}: malformed git ls-tree output") from exc
    if decoded_path != path or object_type != "blob":
        raise PreflightError(f"{path}: current tree entry is not the expected blob")
    return object_id


def _blob_sha256(repo: Path, blob_sha: str) -> str:
    return hashlib.sha256(_git(repo, "cat-file", "blob", blob_sha)).hexdigest()


def classify_capsule(
    repo: Path, capsule: dict[str, Any], *, current_ref: str = "HEAD"
) -> dict[str, Any]:
    """Classify from git objects only; the worktree is never consulted."""
    capsule_errors = validate_capsule(repo, capsule)
    if capsule_errors:
        raise PreflightError("invalid capsule: " + "; ".join(capsule_errors))
    current_commit = _full_commit(repo, current_ref)
    rows: list[dict[str, Any]] = []
    counts = {"CURRENT": 0, "DRIFTED": 0, "MISSING": 0}
    for entry in capsule["entries"]:
        current_blob = _current_blob(repo, current_commit, entry["path"])
        if current_blob is None:
            state = "MISSING"
            current_sha256 = None
        else:
            state = "CURRENT" if current_blob == entry["blob_sha"] else "DRIFTED"
            current_sha256 = _blob_sha256(repo, current_blob)
        counts[state] += 1
        rows.append(
            {
                "path": entry["path"],
                "frozen_commit_sha": entry["commit_sha"],
                "frozen_blob_sha": entry["blob_sha"],
                "frozen_sha256": _blob_sha256(repo, entry["blob_sha"]),
                "current_commit_sha": current_commit,
                "current_blob_sha": current_blob,
                "current_sha256": current_sha256,
                "state": state,
            }
        )
    aggregate_state = (
        "MISSING"
        if counts["MISSING"]
        else "DRIFTED"
        if counts["DRIFTED"]
        else "CURRENT"
    )
    return {
        "protocol_version": "OBZIO-DISPATCH-CAPSULE-PREFLIGHT-v1",
        "capsule_id": capsule["capsule_id"],
        "capsule_version": capsule["version"],
        "capsule_manifest_sha256": manifest_sha256(capsule),
        "current_commit_sha": current_commit,
        "aggregate_state": aggregate_state,
        "summary": counts,
        "sources": rows,
    }


def strict_exit_code(report: dict[str, Any]) -> int:
    return {"CURRENT": 0, "DRIFTED": 3, "MISSING": 4}[report["aggregate_state"]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--capsule", type=Path, required=True)
    parser.add_argument("--current-ref", default="HEAD")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        capsule = load_capsule(args.capsule)
        report = classify_capsule(
            args.repo, capsule, current_ref=args.current_ref
        )
    except (_CAPSULE.CapsuleError, PreflightError) as exc:
        print(
            json.dumps(
                {
                    "protocol_version": "OBZIO-DISPATCH-CAPSULE-PREFLIGHT-v1",
                    "aggregate_state": "INVALID",
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        return 2
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return strict_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
