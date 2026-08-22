#!/usr/bin/env python3
"""Inventory every durable G0 result file except the manifest itself."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


UNIT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = UNIT_ROOT / "manifest.json"
RESULT_SLOT = "workstreams/po03/attempts/wave-a/wave-a-062-g0-baseline-executable"


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def git_blob_sha(content: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(content)).encode("ascii") + b"\0" + content
    ).hexdigest()


def durable_files() -> list[Path]:
    return sorted(
        (
            path
            for path in UNIT_ROOT.rglob("*")
            if path.is_file()
            and path != MANIFEST_PATH
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        ),
        key=lambda path: path.relative_to(UNIT_ROOT).as_posix(),
    )


def build() -> dict[str, Any]:
    artifacts = []
    for path in durable_files():
        content = path.read_bytes()
        artifacts.append(
            {
                "path": path.relative_to(UNIT_ROOT).as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
                "git_blob_sha": git_blob_sha(content),
            }
        )
    return {
        "task_id": "wave-a-062-g0-baseline-executable",
        "result_slot": RESULT_SLOT,
        "decision_changed": [],
        "artifact_count": len(artifacts),
        "total_artifact_bytes_excluding_manifest": sum(
            artifact["bytes"] for artifact in artifacts
        ),
        "artifacts": artifacts,
    }


def main() -> int:
    document = build()
    MANIFEST_PATH.write_bytes(canonical_json(document))
    print(
        f"MANIFEST_BUILD_PASS artifacts={document['artifact_count']} "
        f"bytes={document['total_artifact_bytes_excluding_manifest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
