#!/usr/bin/env python3
"""Verify WA-012's non-recursive artifact manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ENVELOPE_FILES = {"artifact-manifest.json", "ready-to-commit.json"}


def _eligible_paths(unit_dir: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in unit_dir.rglob("*")
            if path.is_file()
            and path.name not in ENVELOPE_FILES
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        ),
        key=lambda path: path.relative_to(unit_dir).as_posix(),
    )


def verify(unit_dir: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        return ["$.artifacts must be an array"]

    expected_paths = [
        path.relative_to(unit_dir).as_posix() for path in _eligible_paths(unit_dir)
    ]
    declared_paths = [entry.get("path") for entry in entries if isinstance(entry, dict)]
    if declared_paths != expected_paths:
        errors.append("artifact path inventory is incomplete or not sorted")

    observed_total = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"$.artifacts[{index}] must be an object")
            continue
        relative = entry.get("path")
        if not isinstance(relative, str):
            errors.append(f"$.artifacts[{index}].path must be a string")
            continue
        path = unit_dir / relative
        if not path.is_file():
            errors.append(f"{relative}: missing")
            continue
        data = path.read_bytes()
        observed_total += len(data)
        if entry.get("bytes") != len(data):
            errors.append(f"{relative}: byte count mismatch")
        if entry.get("sha256") != hashlib.sha256(data).hexdigest():
            errors.append(f"{relative}: SHA-256 mismatch")

    if manifest.get("artifact_count") != len(entries):
        errors.append("$.artifact_count does not match artifacts")
    if manifest.get("total_bytes") != observed_total:
        errors.append("$.total_bytes does not match artifact bytes")
    if manifest.get("excluded_envelopes") != sorted(ENVELOPE_FILES):
        errors.append("$.excluded_envelopes must declare the recursive envelopes")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "manifest",
        type=Path,
        nargs="?",
        default=Path(__file__).with_name("artifact-manifest.json"),
    )
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        errors = verify(manifest_path.parent, manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}")
        return 2
    if errors:
        for error in errors:
            print(f"INVALID: {error}")
        return 1
    print(
        "VALID "
        f"artifact_count={manifest['artifact_count']} "
        f"total_bytes={manifest['total_bytes']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
