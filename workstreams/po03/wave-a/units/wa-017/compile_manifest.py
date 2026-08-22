#!/usr/bin/env python3
"""Compile deterministic SHA-256/byte accounting for the owned subtree."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


UNIT_ROOT = Path(__file__).resolve().parent
OWNED_PREFIX = "workstreams/po03/wave-a/units/wa-017/"
EXCLUDED = {
    "result/artifact-manifest.json",
    "result/ready-to-commit.json",
}


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def media_type(path: Path) -> str:
    if path.suffix == ".json":
        return "application/json"
    if path.suffix == ".py":
        return "text/x-python; charset=utf-8"
    if path.suffix == ".md":
        return "text/markdown; charset=utf-8"
    if path.suffix in {".txt", ".log"}:
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def build() -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    for path in sorted(UNIT_ROOT.rglob("*")):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or path.suffix == ".pyc"
        ):
            continue
        logical_name = path.relative_to(UNIT_ROOT).as_posix()
        if logical_name in EXCLUDED:
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        artifacts.append(
            {
                "artifact_id": f"PO03-WA-017-{digest[:16]}",
                "bytes": len(data),
                "content_uri": OWNED_PREFIX + logical_name,
                "logical_name": logical_name,
                "media_type": media_type(path),
                "sha256": digest,
            }
        )
    if not artifacts:
        raise ValueError("refusing to emit an empty manifest")
    names = [artifact["logical_name"] for artifact in artifacts]
    if len(names) != len(set(names)):
        raise ValueError("duplicate logical name")
    return {
        "acceptance_contract_sha256": (
            "b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a"
        ),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "attempt": {
            "attempt_id": "PO03-WA-017-A02",
            "fence_token": 2,
            "idempotency_key": "po03:100bc2079ced:wa-017:a02",
            "lease_id": "lease-po03-wa-017-a02",
        },
        "decision_changed": [],
        "hash_algorithm": "sha256",
        "hash_closure": {
            "excluded_envelopes": sorted(EXCLUDED),
            "rule": (
                "This manifest hashes every payload predecessor. "
                "ready-to-commit.json hashes this manifest; the immutable "
                "return commit and terminal report carry the ready-envelope "
                "hash because neither object can contain its own digest."
            ),
        },
        "immutable_input_manifest_sha256": (
            "3d1529efb460525d2a4a23750fdd189fbf3136e79decabe267e5b8b353e96da5"
        ),
        "protocol_version": "OBZIO-ARTIFACT-MANIFEST-v1",
        "source_base_commit": "ef81e041befe9654ced9390ffd6cc046d8cdd033",
        "task_id": "PO03-WA-017",
        "total_bytes": sum(artifact["bytes"] for artifact in artifacts),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=UNIT_ROOT / "result" / "artifact-manifest.json",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if output != UNIT_ROOT / "result" / "artifact-manifest.json":
        raise ValueError("manifest output path is fixed to the owned result slot")
    output.write_bytes(json_bytes(build()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
