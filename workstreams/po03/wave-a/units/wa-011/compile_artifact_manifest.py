#!/usr/bin/env python3
"""Compile deterministic SHA-256 accounting for the WA-011 result payload."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


UNIT_RELATIVE = Path("workstreams/po03/wave-a/units/wa-011")
EXCLUDED_ENVELOPES = {
    "result/artifact-manifest.json",
    "result/ready-to-commit.json",
}
MEDIA_TYPES = {
    ".env": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".md": "text/markdown; charset=utf-8",
    ".py": "text/x-python; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def _load_generator(unit_root: Path) -> Any:
    path = unit_root / "manifest_generator.py"
    specification = importlib.util.spec_from_file_location(
        "wa011_artifact_manifest_generator", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"could not load generator from {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def compile_artifact_manifest(unit_root: Path) -> dict[str, Any]:
    unit_root = unit_root.resolve(strict=True)
    generator = _load_generator(unit_root)
    paths = [
        path
        for path in generator.discover_paths(unit_root)
        if path not in EXCLUDED_ENVELOPES
    ]
    content_manifest = generator.compile_manifest(unit_root, paths)

    artifacts = []
    for item in content_manifest["artifacts"]:
        relative = item["path"]
        artifacts.append(
            {
                "artifact_id": (
                    "art-po03-wa-011-"
                    + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:12]
                ),
                "bytes": item["bytes"],
                "content_uri": (UNIT_RELATIVE / relative).as_posix(),
                "logical_name": relative,
                "media_type": MEDIA_TYPES.get(
                    Path(relative).suffix, "application/octet-stream"
                ),
                "sha256": item["sha256"],
            }
        )

    return {
        "acceptance_contract_sha256": (
            "b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a"
        ),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "attempt": {
            "attempt_id": "PO03-WA-011-A02",
            "fence_token": 2,
            "idempotency_key": "po03:100bc2079ced:wa-011:a02",
            "lease_id": "lease-po03-wa-011-a02",
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
                "report carry the ready envelope hash because neither object can "
                "contain its own digest."
            ),
        },
        "immutable_input_manifest_sha256": (
            "15f090e1c0618e5b7ffbf17f47c33d856bd5204d536737270ab9850de6f74fb3"
        ),
        "manifest_content_tree_sha256": content_manifest["tree_sha256"],
        "protocol_version": "OBZIO-ARTIFACT-MANIFEST-v1",
        "source_base_commit": "6d9fd4bde38da22b70ee503a0b9497c7279e32e4",
        "task_id": "PO03-WA-011",
        "total_bytes": sum(artifact["bytes"] for artifact in artifacts),
    }


def canonical_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit-root", type=Path, default=Path.cwd() / UNIT_RELATIVE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = canonical_bytes(compile_artifact_manifest(args.unit_root))
        if args.check:
            if args.output is None:
                raise ValueError("--check requires --output")
            if args.output.read_bytes() != payload:
                raise ValueError(f"stale artifact manifest: {args.output}")
        elif args.output is None:
            sys.stdout.buffer.write(payload)
        else:
            generator = _load_generator(args.unit_root.resolve(strict=True))
            generator._atomic_write(args.output, payload)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
