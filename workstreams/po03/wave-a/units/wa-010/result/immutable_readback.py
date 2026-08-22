#!/usr/bin/env python3
"""Read every WA-010 artifact back from an immutable remote commit and verify it.

Result custody requires that a *different* process reads every artifact back by
immutable SHA.  Reading the producer's own worktree would prove nothing, so this
verifier clones into a fresh temporary directory, fetches the branch by force,
resolves the pinned commit, and extracts each path with ``git show`` at that
commit.  A byte and SHA-256 comparison against the manifest follows.

Usage::

    python3 -I immutable_readback.py <remote-url> <branch> <commit> [--out FILE]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESULT_DIR = Path(__file__).resolve().parent
MANIFEST_NAME = "artifact-manifest.json"
UNIT_PREFIX = "workstreams/po03/wave-a/units/wa-010"


class VerificationError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path | None = None) -> bytes:
    completed = subprocess.run(args, cwd=None if cwd is None else str(cwd), capture_output=True)
    if completed.returncode != 0:
        raise VerificationError(
            f"command failed ({completed.returncode}): {' '.join(args[:4])}...\n"
            f"{completed.stderr.decode('utf-8', 'replace')}"
        )
    return completed.stdout


def load_manifest(path: Path) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("protocol_version") != "OBZIO-ARTIFACT-MANIFEST-v1":
        raise VerificationError("unsupported manifest protocol_version")
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise VerificationError("manifest carries no artifacts")
    if document.get("artifact_count") != len(artifacts):
        raise VerificationError("manifest artifact_count disagrees with its artifact list")
    total = sum(int(entry["bytes"]) for entry in artifacts)
    if document.get("total_bytes") != total:
        raise VerificationError("manifest total_bytes disagrees with its artifact list")
    return document


def verify_readback(
    remote: str, branch: str, commit: str, manifest_path: Path
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    manifest_bytes = Path(manifest_path).read_bytes()
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "readback"
        scratch.mkdir()
        _run(["git", "init", "-q", "--bare", str(scratch)])
        _run(
            [
                "git",
                "-C",
                str(scratch),
                "fetch",
                "--force",
                "--no-tags",
                remote,
                f"+refs/heads/{branch}:refs/heads/{branch}",
            ]
        )
        resolved = _run(["git", "-C", str(scratch), "rev-parse", commit]).decode().strip()
        if resolved != commit:
            raise VerificationError(f"commit {commit} resolved to {resolved}")
        tip = (
            _run(["git", "-C", str(scratch), "rev-parse", f"refs/heads/{branch}"])
            .decode()
            .strip()
        )
        commit_type = _run(["git", "-C", str(scratch), "cat-file", "-t", commit]).decode().strip()
        if commit_type != "commit":
            raise VerificationError(f"{commit} is a {commit_type}, not a commit")

        checks: list[dict[str, Any]] = []
        mismatches: list[str] = []

        def check(logical: str, path: str, expected_sha: str, expected_bytes: int) -> None:
            data = _run(
                ["git", "-C", str(scratch), "show", "--no-textconv", f"{commit}:{path}"]
            )
            digest = hashlib.sha256(data).hexdigest()
            matches = digest == expected_sha and len(data) == expected_bytes
            if not matches:
                mismatches.append(path)
            checks.append(
                {
                    "logical_name": logical,
                    "path": path,
                    "expected_sha256": expected_sha,
                    "observed_sha256": digest,
                    "expected_bytes": expected_bytes,
                    "observed_bytes": len(data),
                    "matches": matches,
                }
            )

        for entry in manifest["artifacts"]:
            check(
                entry["logical_name"],
                entry["content_uri"],
                entry["sha256"],
                int(entry["bytes"]),
            )
        check(
            f"result/{MANIFEST_NAME}",
            f"{UNIT_PREFIX}/result/{MANIFEST_NAME}",
            manifest_digest,
            len(manifest_bytes),
        )

        out_of_scope = [
            entry["content_uri"]
            for entry in manifest["artifacts"]
            if not entry["content_uri"].startswith(f"{UNIT_PREFIX}/")
        ]

        return {
            "protocol_version": "OBZIO-IMMUTABLE-READBACK-v1",
            "method": (
                "Fresh temporary bare repository, forced branch fetch, then "
                "'git show --no-textconv <immutable-commit>:<path>' with SHA-256 and byte comparison."
            ),
            "remote": remote,
            "branch": branch,
            "commit": commit,
            "commit_object_type": commit_type,
            "remote_branch_tip_at_readback": tip,
            "commit_is_branch_tip": tip == commit,
            "manifest_path": str(manifest_path).split("workstreams/")[-1],
            "manifest_sha256": manifest_digest,
            "manifest_bytes": len(manifest_bytes),
            "artifact_count": manifest["artifact_count"],
            "total_bytes": manifest["total_bytes"],
            "verified_paths": len(checks),
            "all_match": not mismatches,
            "mismatched_paths": mismatches,
            "out_of_scope_artifacts": out_of_scope,
            "verified_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "checks": checks,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("remote")
    parser.add_argument("branch")
    parser.add_argument("commit")
    parser.add_argument("--manifest", type=Path, default=RESULT_DIR / MANIFEST_NAME)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        record = verify_readback(args.remote, args.branch, args.commit, args.manifest)
    except VerificationError as exc:
        print(f"READBACK_FAILED: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8")
        print(
            json.dumps(
                {
                    "all_match": record["all_match"],
                    "verified_paths": record["verified_paths"],
                    "commit": record["commit"],
                    "out_of_scope_artifacts": record["out_of_scope_artifacts"],
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0 if record["all_match"] and not record["out_of_scope_artifacts"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
