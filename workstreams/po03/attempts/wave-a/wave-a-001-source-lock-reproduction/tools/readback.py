#!/usr/bin/env python3
"""Read every manifested artifact back out of an immutable commit and a pushed ref.

This is deliberately a separate process from the one that produced the artifacts: it
trusts nothing in the working tree and reads only from Git object storage, so a
partial write, a lost file or a ref that never reached the remote is caught.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

UNIT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UNIT_ROOT / "tools"))

import source_lock  # noqa: E402


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ("git", "-C", str(repo), *args), check=True, capture_output=True
    ).stdout


def read_from(repo: Path, revision: str, path: str) -> bytes:
    return git(repo, "show", f"{revision}:{path}")


def check(repo: Path, revision: str, prefix: str, entries: list[dict]) -> dict:
    """Recompute every manifested digest from blobs stored under one revision."""
    mismatches: list[dict[str, object]] = []
    total = 0
    for entry in entries:
        path = str(PurePosixPath(prefix) / entry["path"])
        try:
            payload = read_from(repo, revision, path)
        except subprocess.CalledProcessError:
            mismatches.append({"kind": "UNREADABLE", "path": entry["path"], "revision": revision})
            continue
        total += len(payload)
        observed = {
            "bytes": len(payload),
            "git_blob_sha": source_lock.git_blob_sha1(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for field, value in observed.items():
            if value != entry[field]:
                mismatches.append(
                    {
                        "actual": value,
                        "expected": entry[field],
                        "kind": f"{field.upper()}_MISMATCH",
                        "path": entry["path"],
                        "revision": revision,
                    }
                )
    return {
        "artifacts_read": len(entries),
        "bytes_read": total,
        "mismatches": mismatches,
        "revision": revision,
        "status": "FAIL" if mismatches else "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--remote-ref", required=True)
    parser.add_argument("--unit-prefix", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    try:
        manifest_path = str(PurePosixPath(args.unit_prefix) / "manifest.json")
        manifest_bytes = read_from(args.repo, args.commit, manifest_path)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        entries = manifest["sources"]

        remote_sha = git(args.repo, "rev-parse", args.remote_ref).decode().strip()
        from_commit = check(args.repo, args.commit, args.unit_prefix, entries)
        from_remote = check(args.repo, args.remote_ref, args.unit_prefix, entries)

        document = {
            "commit": args.commit,
            "from_commit": from_commit,
            "from_remote_ref": from_remote,
            "manifest_self": {
                "bytes": len(manifest_bytes),
                "git_blob_sha": source_lock.git_blob_sha1(manifest_bytes),
                "note": "manifest.json cannot list its own digest; it is verified here instead",
                "path": manifest_path,
                "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            },
            "readback_version": "PO03-READBACK-v1",
            "remote_ref": args.remote_ref,
            "remote_ref_sha": remote_sha,
            "remote_ref_matches_commit": remote_sha == args.commit,
            "status": (
                "PASS"
                if from_commit["status"] == "PASS"
                and from_remote["status"] == "PASS"
                and remote_sha == args.commit
                else "FAIL"
            ),
        }
        text = source_lock.canonical_json(document)
        if args.out is None:
            sys.stdout.write(text)
        else:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"PO03_READBACK_ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        f"PO03_READBACK_{document['status']} "
        f"artifacts={from_commit['artifacts_read']} "
        f"bytes={from_commit['bytes_read']} "
        f"ref_matches_commit={document['remote_ref_matches_commit']}"
    )
    return 0 if document["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
