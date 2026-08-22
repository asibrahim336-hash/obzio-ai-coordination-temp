#!/usr/bin/env python3
"""Build the wave-a-003 attempt manifest over every owned artifact.

The manifest excludes itself, covers the whole owned subtree, and records the
SHA-256, byte count and Git blob identity of each artifact so the controller
can verify the result from immutable Git bytes alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MANIFEST_VERSION = "PO03-ATTEMPT-MANIFEST-v1"
TASK_ID = "wave-a-003-currentness-compiler"
UNIT_ROOT = Path(__file__).resolve().parents[1]
UNIT_RELATIVE = "workstreams/po03/attempts/wave-a/wave-a-003-currentness-compiler"
SELF_EXCLUDED = "manifest.json"


DEBRIS_SUFFIXES = (".pyc", ".pyo", ".orig", ".rej")
DEBRIS_DIRECTORIES = ("__pycache__", ".pytest_cache", ".ipynb_checkpoints")


def _is_debris(relative: str) -> bool:
    """Keep interpreter and merge debris out of the result manifest."""
    parts = relative.split("/")
    return relative.endswith(DEBRIS_SUFFIXES) or any(part in DEBRIS_DIRECTORIES for part in parts)


def git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload).hexdigest()


def build(unit_root: Path = UNIT_ROOT) -> dict[str, object]:
    sources = []
    for path in sorted(unit_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(unit_root).as_posix()
        if relative == SELF_EXCLUDED or _is_debris(relative):
            continue
        payload = path.read_bytes()
        sources.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "git_blob_sha": git_blob_sha(payload),
            }
        )
    return {
        "manifest_version": MANIFEST_VERSION,
        "task_id": TASK_ID,
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "repository": "github.com/asibrahim336-hash/obzio-ai-coordination-temp",
        "branch": f"po03/{TASK_ID}",
        "unit_root": UNIT_RELATIVE,
        "self_excluded": SELF_EXCLUDED,
        "artifact_count": len(sources),
        "total_bytes": sum(int(item["bytes"]) for item in sources),
        "sources": sources,
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the wave-a-003 attempt manifest.")
    parser.add_argument("--out", default=str(UNIT_ROOT / SELF_EXCLUDED))
    arguments = parser.parse_args(argv)
    manifest = build()
    Path(arguments.out).write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    print(f"MANIFEST artifacts={manifest['artifact_count']} bytes={manifest['total_bytes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
