#!/usr/bin/env python3
"""Build the factory-compatible artifact manifest for this attempt's result slot.

Every durable file in the slot is declared except the manifest itself. Paths are
canonical slot-relative POSIX paths. Byte counts and SHA-256 values are computed
from the file bytes; the Git blob SHA-1 is recorded as an optional cross-check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


SLOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SLOT.parents[4]
TASK_ID = "wave-a-043-path-scope-adversarial-review"
RESULT_SLOT = "workstreams/po03/attempts/wave-a/wave-a-043-path-scope-adversarial-review"
MANIFEST_NAME = "manifest.json"


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def collect() -> list[dict]:
    artifacts = []
    for path in sorted(SLOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(SLOT).as_posix()
        if relative == MANIFEST_NAME:
            continue
        if "__pycache__" in relative:
            continue
        data = path.read_bytes()
        artifacts.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "git_blob_sha1": git_blob_sha1(data),
            }
        )
    return artifacts


def build() -> dict:
    artifacts = collect()
    return {
        "task_id": TASK_ID,
        "result_slot": RESULT_SLOT,
        "decision_changed": [],
        "artifact_count": len(artifacts),
        "total_artifact_bytes_excluding_manifest": sum(a["bytes"] for a in artifacts),
        "artifacts": artifacts,
        "manifest_version": "PO03-WAVE-A-043-MANIFEST-v1",
        "algorithm": "sha256",
        "path_convention": "canonical slot-relative POSIX path",
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "manifest_excluded_from_artifacts": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(SLOT / MANIFEST_NAME))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    document = build()
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    target = Path(args.out)
    if args.check:
        if not target.exists():
            print("MANIFEST_MISSING")
            return 1
        if target.read_text(encoding="utf-8") != text:
            print("MANIFEST_DRIFT: manifest.json does not describe the current slot contents")
            return 1
        print(
            f"MANIFEST_CURRENT artifact_count={document['artifact_count']} "
            f"bytes={document['total_artifact_bytes_excluding_manifest']}"
        )
        return 0
    target.write_text(text, encoding="utf-8")
    print(
        f"wrote {target} artifact_count={document['artifact_count']} "
        f"bytes={document['total_artifact_bytes_excluding_manifest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
