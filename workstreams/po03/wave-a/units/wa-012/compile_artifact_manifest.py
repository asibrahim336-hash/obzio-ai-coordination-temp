#!/usr/bin/env python3
"""Compile WA-012's deterministic, non-recursive artifact manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
from pathlib import Path

from verify_artifacts import ENVELOPE_FILES, _eligible_paths


def compile_manifest(unit_dir: Path) -> dict:
    artifacts = []
    for index, path in enumerate(_eligible_paths(unit_dir), start=1):
        data = path.read_bytes()
        relative = path.relative_to(unit_dir).as_posix()
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        artifacts.append(
            {
                "artifact_id": f"PO03-WA-012-ART-{index:03d}",
                "bytes": len(data),
                "media_type": media_type,
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return {
        "protocol_version": "OBZIO-ARTIFACT-MANIFEST-v1",
        "task_id": "PO03-WA-012",
        "source_base_commit": "e56eda6e8e4a4e958795f7157839926d93272b30",
        "hash_algorithm": "SHA-256",
        "artifact_count": len(artifacts),
        "total_bytes": sum(item["bytes"] for item in artifacts),
        "artifacts": artifacts,
        "excluded_envelopes": sorted(ENVELOPE_FILES),
        "envelope_rule": (
            "artifact-manifest.json and ready-to-commit.json are excluded from "
            "the managed hash set to avoid recursive digest dependencies; "
            "ready-to-commit.json records the manifest digest and the immutable "
            "remote commit is verified out of band."
        ),
        "changed_path_coverage": {
            "allowed_prefix": "workstreams/po03/wave-a/units/wa-012/",
            "managed_artifacts": len(artifacts),
            "recursive_envelopes": len(ENVELOPE_FILES),
            "total_unit_files": len(artifacts) + len(ENVELOPE_FILES),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--unit-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("artifact-manifest.json"),
    )
    args = parser.parse_args()
    payload = json.dumps(
        compile_manifest(args.unit_dir.resolve()),
        indent=2,
        sort_keys=True,
    ) + "\n"
    args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
