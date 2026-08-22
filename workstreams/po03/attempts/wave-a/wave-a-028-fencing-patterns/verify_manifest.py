#!/usr/bin/env python3
"""Verify manifest completeness and artifact identities."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


UNIT_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = UNIT_ROOT / "manifest.json"


def git_blob_sha(payload: bytes) -> str:
    framed = f"blob {len(payload)}\0".encode("ascii") + payload
    return hashlib.sha1(framed).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    declared = {record["path"]: record for record in manifest["artifacts"]}
    actual = {
        path.relative_to(UNIT_ROOT).as_posix(): path
        for path in UNIT_ROOT.rglob("*")
        if path.is_file()
        and path != MANIFEST_PATH
        and "__pycache__" not in path.parts
    }
    errors: list[str] = []
    for missing in sorted(set(declared) - set(actual)):
        errors.append(f"missing:{missing}")
    for undeclared in sorted(set(actual) - set(declared)):
        errors.append(f"undeclared:{undeclared}")
    for relative_path in sorted(set(actual) & set(declared)):
        payload = actual[relative_path].read_bytes()
        expected = declared[relative_path]
        observations = {
            "bytes": len(payload),
            "git_blob_sha": git_blob_sha(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for field, observed in observations.items():
            if observed != expected[field]:
                errors.append(
                    f"mismatch:{relative_path}:{field}:"
                    f"{expected[field]}:{observed}"
                )
    report = {
        "actual_artifact_count": len(actual),
        "declared_artifact_count": len(declared),
        "errors": errors,
        "manifest_sha256": hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
        "status": "PASS" if not errors else "FAIL",
    }
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
