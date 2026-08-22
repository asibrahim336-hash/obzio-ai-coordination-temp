#!/usr/bin/env python3
"""Build or verify the immutable Wave A result manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath


TASK_ID = "wave-a-002-clean-clone-smoke"
RESULT_SLOT = (
    "workstreams/po03/attempts/wave-a/"
    "wave-a-002-clean-clone-smoke"
)
ARTIFACT_PATHS = (
    "build_manifest.py",
    "clean_clone_smoke.py",
    "fixtures/hidden-checkout-state.json",
    "frozen-criteria.json",
    "limitations.json",
    "observed-results.json",
    "owned-harness-results.json",
    "result.json",
    "runtime-binding.json",
    "test_clean_clone_smoke.py",
)


def _canonical(path: str) -> str:
    value = PurePosixPath(path)
    if (
        not path
        or "\\" in path
        or "\x00" in path
        or value.is_absolute()
        or ".." in value.parts
        or value.as_posix() != path
    ):
        raise ValueError(f"non-canonical artifact path: {path!r}")
    return path


def build(root: Path) -> dict[str, object]:
    artifacts: list[dict[str, object]] = []
    for relative in ARTIFACT_PATHS:
        relative = _canonical(relative)
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"artifact must be a regular non-symlink file: {relative}")
        payload = path.read_bytes()
        artifacts.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
        )
    return {
        "manifest_version": "PO03-WAVE-A-RESULT-MANIFEST-v1",
        "task_id": TASK_ID,
        "result_slot": RESULT_SLOT,
        "artifact_count": len(artifacts),
        "total_artifact_bytes_excluding_manifest": sum(
            int(artifact["bytes"]) for artifact in artifacts
        ),
        "artifacts": artifacts,
        "self_excluded": "manifest.json",
        "decision_changed": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest_path = root / "manifest.json"
    expected = (
        json.dumps(build(root), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    if args.check:
        if not manifest_path.is_file() or manifest_path.read_bytes() != expected:
            print("MANIFEST_INVALID")
            return 1
        print(
            "MANIFEST_VALID "
            f"sha256={hashlib.sha256(expected).hexdigest()} "
            f"bytes={len(expected)}"
        )
        return 0

    temporary = manifest_path.with_name(f".{manifest_path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(expected)
        os.replace(temporary, manifest_path)
    finally:
        temporary.unlink(missing_ok=True)
    print(
        "MANIFEST_WRITTEN "
        f"sha256={hashlib.sha256(expected).hexdigest()} "
        f"bytes={len(expected)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
