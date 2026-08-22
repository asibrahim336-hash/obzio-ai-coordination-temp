#!/usr/bin/env python3
"""Compile deterministic SHA-256 accounting for the WA-009 payload."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


UNIT_RELATIVE = Path("workstreams/po03/wave-a/units/wa-009")
EXCLUDED_ENVELOPES = {
    "result/artifact-manifest.json",
    "result/ready-to-commit.json",
}
MEDIA_TYPES = {
    ".json": "application/json",
    ".md": "text/markdown; charset=utf-8",
    ".py": "text/x-python; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def compile_manifest(unit_root: Path) -> dict[str, Any]:
    unit_root = unit_root.resolve(strict=True)
    artifacts: list[dict[str, Any]] = []
    for path in sorted(unit_root.rglob("*")):
        relative = path.relative_to(unit_root).as_posix()
        if relative in EXCLUDED_ENVELOPES or path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"non-regular artifact: {relative}")
        if "__pycache__" in path.parts or path.name.endswith(".pyc"):
            raise ValueError(f"runtime debris in artifact set: {relative}")
        content = path.read_bytes()
        executable = bool(path.stat().st_mode & 0o111)
        artifacts.append(
            {
                "artifact_id": (
                    "art-po03-wa-009-"
                    + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:12]
                ),
                "bytes": len(content),
                "content_uri": (UNIT_RELATIVE / relative).as_posix(),
                "git_mode": "100755" if executable else "100644",
                "logical_name": relative,
                "media_type": MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return {
        "acceptance_contract_sha256": (
            "b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a"
        ),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "attempt": {
            "attempt_id": "PO03-WA-009-A02",
            "fence_token": 2,
            "idempotency_key": "po03:100bc2079ced:wa-009:a02",
            "lease_id": "lease-po03-wa-009-a02",
        },
        "commission_id": (
            "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
        ),
        "decision_changed": [],
        "hash_algorithm": "sha256",
        "hash_closure": {
            "excluded_envelopes": sorted(EXCLUDED_ENVELOPES),
            "rule": (
                "The manifest hashes every payload predecessor. ready-to-commit.json "
                "hashes this manifest; the immutable return commit and terminal "
                "report carry the ready-to-commit hash because neither object can "
                "contain its own digest."
            ),
        },
        "immutable_input_manifest_sha256": (
            "6915fd4bd8e3aa39ba86fbf238bfbb76bff2995506e06111d03c5bd17ab2e0d0"
        ),
        "protocol_version": "OBZIO-ARTIFACT-MANIFEST-v1",
        "source_base_commit": "affc82b35e6205010fda90f9914a97e467294a44",
        "task_id": "PO03-WA-009",
        "total_bytes": sum(artifact["bytes"] for artifact in artifacts),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit-root", type=Path, default=Path.cwd() / UNIT_RELATIVE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    manifest = compile_manifest(args.unit_root)
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
