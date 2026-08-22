#!/usr/bin/env python3
"""Build complete digest and byte accounting for this owned unit subtree."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


UNIT_ROOT = Path(__file__).parents[1]
OUTPUT = UNIT_ROOT / "result" / "artifact-manifest.json"
EXCLUDED = {
    "result/artifact-manifest.json",
    "result/artifact-manifest.json.tmp",
    "result/ready-to-commit.json",
}


def media_type(path: Path) -> str:
    return {
        ".json": "application/json",
        ".md": "text/markdown; charset=utf-8",
        ".py": "text/x-python; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
    }.get(path.suffix, "application/octet-stream")


def build() -> dict:
    artifacts = []
    for path in sorted(UNIT_ROOT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        logical_name = path.relative_to(UNIT_ROOT).as_posix()
        if logical_name in EXCLUDED:
            continue
        payload = path.read_bytes()
        artifacts.append(
            {
                "bytes": len(payload),
                "logical_name": logical_name,
                "media_type": media_type(path),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return {
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "attempt_id": "PO03-WA-019-A02",
        "coverage": (
            "Every file in the owned subtree except this manifest, which cannot "
            "hash itself, and ready-to-commit.json, which is written in the "
            "distinct return commit after the immutable result commit exists."
        ),
        "excluded": [
            {
                "logical_name": "result/artifact-manifest.json",
                "reason": "a manifest cannot contain its own digest",
            },
            {
                "logical_name": "result/ready-to-commit.json",
                "reason": "written after the immutable result commit and digested in the return receipt",
            },
        ],
        "hash_algorithm": "sha256",
        "immutable_input_sha256": "5a8ce310381627a6d3b803390b4344742a80ddeb09b3ed3bc0526f1ae3229039",
        "owned_subtree": "workstreams/po03/wave-a/units/wa-019",
        "protocol_version": "OBZIO-ARTIFACT-MANIFEST-v1",
        "source_base": "4e4641e96cc0ad6e48f58e06140d33b0410e6072",
        "task_id": "PO03-WA-019",
        "total_bytes": sum(artifact["bytes"] for artifact in artifacts),
    }


def main() -> int:
    document = build()
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(OUTPUT)
    print(
        f"WROTE {OUTPUT.relative_to(UNIT_ROOT)} "
        f"artifacts={document['artifact_count']} bytes={document['total_bytes']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
