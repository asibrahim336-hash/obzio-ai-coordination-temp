#!/usr/bin/env python3
"""Compile the WA-006 artifact manifest and verify it from an immutable commit.

Two modes, deliberately separated so the accounting is never hand-written:

``compile``  digest every payload artifact in the result slot and emit
             artifact-manifest.json with exact SHA-256 and byte counts.
``readback`` re-read every manifested artifact from a pinned commit in a fresh
             temporary clone of the pushed branch and compare bytes, so the
             verification is performed by a different process against the
             remote rather than against the working tree that produced it.
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


RESULT_SLOT = "workstreams/po03/wave-a/units/wa-006/result"
MANIFEST_NAME = "artifact-manifest.json"

# artifact-manifest.json cannot contain its own digest, and ready-to-commit.json
# is the return document that quotes the manifest, so it is manifested by the
# return commit rather than by the payload manifest it reports on.
SELF_EXCLUDED = (MANIFEST_NAME, "ready-to-commit.json")

MEDIA_TYPES = {
    ".py": "text/x-python; charset=utf-8",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _media_type(path: Path) -> str:
    return MEDIA_TYPES.get(path.suffix, "application/octet-stream")


def _artifact_id(relative: str) -> str:
    stem = relative.replace("/", "-").rsplit(".", 1)[0]
    return f"art-po03-wa-006-{stem}"


def _payload_paths(slot: Path) -> list[Path]:
    return sorted(
        path
        for path in slot.rglob("*")
        if path.is_file() and path.name not in SELF_EXCLUDED and "__pycache__" not in path.parts
    )


def compile_manifest(repo: Path) -> dict[str, Any]:
    slot = repo / RESULT_SLOT
    entries: list[dict[str, Any]] = []
    total = 0
    for path in _payload_paths(slot):
        payload = path.read_bytes()
        relative = path.relative_to(slot).as_posix()
        total += len(payload)
        entries.append(
            {
                "artifact_id": _artifact_id(relative),
                "logical_name": relative,
                "content_uri": f"{RESULT_SLOT}/{relative}",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "media_type": _media_type(path),
                "readback_verified_at": None,
            }
        )
    return {
        "protocol_version": "OBZIO-WA-006-ARTIFACT-MANIFEST-v1",
        "task_id": "PO03-WA-006",
        "attempt_id": "PO03-WA-006-A02",
        "result_slot": f"{RESULT_SLOT}/",
        "hash_algorithm": "sha256",
        "generated_at": _now(),
        "excluded": list(SELF_EXCLUDED),
        "excluded_reason": "artifact-manifest.json cannot contain its own digest, and ready-to-commit.json is the return document that quotes this manifest.",
        "artifact_count": len(entries),
        "total_bytes": total,
        "artifacts": entries,
        "decision_changed": [],
    }


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "--no-pager", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return completed.stdout


def readback(repo: Path, remote: str, branch: str, commit: str) -> dict[str, Any]:
    """Read every manifested artifact back from ``commit`` in a fresh clone."""
    manifest = json.loads((repo / RESULT_SLOT / MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest_bytes = (repo / RESULT_SLOT / MANIFEST_NAME).read_bytes()

    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="wa006-readback-") as scratch:
        fresh = Path(scratch) / "verify"
        fresh.mkdir()
        _git(fresh.parent, "init", "--quiet", "--bare", str(fresh))
        _git(fresh, "remote", "add", "origin", remote)
        _git(fresh, "fetch", "--quiet", "--force", "origin", f"refs/heads/{branch}:refs/wa006/readback")
        tip = _git(fresh, "rev-parse", "refs/wa006/readback").strip()

        def blob(path: str) -> bytes | None:
            completed = subprocess.run(
                ["git", "--no-pager", "-C", str(fresh), "cat-file", "blob", f"{commit}:{path}"],
                capture_output=True,
                check=False,
            )
            return completed.stdout if completed.returncode == 0 else None

        verified_at = _now()
        for entry in manifest["artifacts"]:
            payload = blob(entry["content_uri"])
            observed_sha = hashlib.sha256(payload).hexdigest() if payload is not None else None
            checks.append(
                {
                    "path": entry["content_uri"],
                    "sha256": entry["sha256"],
                    "bytes": entry["bytes"],
                    "observed_sha256": observed_sha,
                    "observed_bytes": len(payload) if payload is not None else None,
                    "matches": payload is not None
                    and observed_sha == entry["sha256"]
                    and len(payload) == entry["bytes"],
                }
            )

        manifest_blob = blob(f"{RESULT_SLOT}/{MANIFEST_NAME}")
        manifest_match = manifest_blob == manifest_bytes
        checks.append(
            {
                "path": f"{RESULT_SLOT}/{MANIFEST_NAME}",
                "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "bytes": len(manifest_bytes),
                "observed_sha256": hashlib.sha256(manifest_blob).hexdigest() if manifest_blob else None,
                "observed_bytes": len(manifest_blob) if manifest_blob else None,
                "matches": manifest_match,
            }
        )

    return {
        "method": "Fresh temporary bare repository, forced fetch of the pushed branch into a dedicated ref, then git cat-file blob <immutable-commit>:<path> with SHA-256 and byte comparison.",
        "remote_branch": branch,
        "commit": commit,
        "remote_tip_at_readback": tip,
        "verified_at": verified_at,
        "artifact_count": len(checks),
        "all_match": all(check["matches"] for check in checks),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest_bytes": len(manifest_bytes),
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("compile", "readback"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--remote")
    parser.add_argument("--branch")
    parser.add_argument("--commit")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    if args.mode == "compile":
        document = compile_manifest(args.repo)
        target = args.out or args.repo / RESULT_SLOT / MANIFEST_NAME
        target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"manifest artifacts={document['artifact_count']} bytes={document['total_bytes']}")
        return 0

    if not (args.remote and args.branch and args.commit):
        parser.error("readback requires --remote, --branch and --commit")
    report = readback(args.repo, args.remote, args.branch, args.commit)
    serialised = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(serialised, encoding="utf-8")
    else:
        sys.stdout.write(serialised)
    return 0 if report["all_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
