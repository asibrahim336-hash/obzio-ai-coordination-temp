#!/usr/bin/env python3
"""Package G1 — the current transactional factory — for successor/g1/.

The package is a copy plus a manifest, and the manifest is only worth reading if
the copy is provably the same bytes as the live tool.  So the packager reads the
live file's blob out of Git rather than trusting the working tree, records the
blob id and digest, and refuses to report a package as intact when the copy and
the blob disagree.

This unit does not write successor/g1/ itself.  It stages the package inside its
own subtree for the controller to ingest, which is the boundary a subordinate
producer is allowed to touch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PACKAGE_VERSION = "PO03-G1-PACKAGE-v1"
FACTORY_PATH = "workstreams/po03/tools/transactional_factory.py"
CONTRACT_PATHS = (
    "workstreams/po03/contracts/transactional-result.schema.json",
    "workstreams/po03/contracts/wave-compounding.schema.json",
    "workstreams/po03/tools/validate_contracts.py",
)
STAGED_FOR = "successor/g1/"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_bytes(repo: Path, *arguments: str) -> bytes:
    return subprocess.run(("git", *arguments), cwd=repo, check=True, capture_output=True).stdout


def git_text(repo: Path, *arguments: str) -> str:
    return git_bytes(repo, *arguments).decode("utf-8", "replace").strip()


def dependency_record(repo: Path, relative: str) -> dict[str, Any]:
    payload = (repo / relative).read_bytes()
    return {
        "path": relative,
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
        "blob_id": git_text(repo, "rev-parse", f"HEAD:{relative}"),
        "role": "read at runtime by the packaged factory; not copied into the package",
    }


def build(repo: Path, destination: Path, *, write: bool) -> dict[str, Any]:
    head = git_text(repo, "rev-parse", "HEAD")
    blob_id = git_text(repo, "rev-parse", f"HEAD:{FACTORY_PATH}")
    blob = git_bytes(repo, "cat-file", "blob", blob_id)
    working = (repo / FACTORY_PATH).read_bytes()

    if write:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(blob)

    copied = destination.read_bytes() if destination.is_file() else b""
    return {
        "package_version": PACKAGE_VERSION,
        "generation": "G1",
        "definition": "the current transactional factory at this checkout, copied from its committed blob",
        "packaged_at": utc_now(),
        "staged_for_controller_path": STAGED_FOR,
        "staged_note": "this unit stages the package in its own subtree; the controller owns successor/g1/",
        "source": {
            "path": FACTORY_PATH,
            "commit": head,
            "blob_id": blob_id,
            "sha256": sha256_bytes(blob),
            "bytes": len(blob),
            "retrieved_with": f"git cat-file blob {blob_id}",
            # A dirty working tree would silently package something that is not
            # in any commit, so the two are compared rather than assumed equal.
            "working_tree_matches_blob": working == blob,
        },
        "package": {
            "path": destination.as_posix(),
            "present": destination.is_file(),
            "sha256": sha256_bytes(copied) if copied else None,
            "bytes": len(copied),
            "byte_exact_with_blob": copied == blob,
        },
        "runtime_dependencies": [dependency_record(repo, relative) for relative in CONTRACT_PATHS],
        "entry_points": {
            "cli": "python3 -I transactional_factory.py --help",
            "importable": "importlib loads the file directly; module-level REPO_ROOT resolves from the file location",
        },
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--destination", required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    record = build(repo, Path(args.destination).resolve(), write=args.write)
    Path(args.out).write_bytes(canonical(record))
    print(json.dumps(record, indent=2, sort_keys=True))
    if not record["package"]["byte_exact_with_blob"]:
        print("PACKAGING FAILED: the package is not byte-exact with the committed factory blob", file=sys.stderr)
        return 1
    if not record["source"]["working_tree_matches_blob"]:
        print("PACKAGING FAILED: the working tree factory differs from its committed blob", file=sys.stderr)
        return 1
    print("PACKAGE VERIFIED: byte-exact with blob " + record["source"]["blob_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
