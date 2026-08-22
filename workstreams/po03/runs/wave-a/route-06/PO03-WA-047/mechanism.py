#!/usr/bin/env python3
"""Metamorphic canonical-path portability mechanism."""
import hashlib
import json
import tempfile
from pathlib import Path


def baseline_identity(configured_path):
    return hashlib.sha256(configured_path.encode()).hexdigest()


def portable_identity(root, configured_path):
    root = Path(root).resolve(strict=True)
    configured = Path(configured_path)
    if configured.is_absolute():
        raise ValueError("absolute paths are not portable")
    target = (root / configured).resolve(strict=True)
    relative = target.relative_to(root)
    payload_digest = hashlib.sha256(target.read_bytes()).hexdigest()
    identity = hashlib.sha256((relative.as_posix() + "\0" + payload_digest).encode()).hexdigest()
    return {"relative_path": relative.as_posix(), "content_sha256": payload_digest, "identity": identity}


def exercise():
    variants = ["pack/data.json", "./pack/data.json", "pack/../pack/data.json"]
    with tempfile.TemporaryDirectory(prefix="obzio path ") as tmp:
        root = Path(tmp)
        (root / "pack").mkdir()
        (root / "pack/data.json").write_text('{"fixture":"sanitized"}\n')
        baseline_ids = [baseline_identity(path) for path in variants]
        portable = [portable_identity(root, path) for path in variants]
        try:
            portable_identity(root, "../escape.json")
            escape_state = "UNEXPECTED_PASS"
        except (ValueError, FileNotFoundError):
            escape_state = "REJECTED"
    return {
        "variants": variants,
        "baseline_unique_identities": len(set(baseline_ids)),
        "portable_unique_identities": len({row["identity"] for row in portable}),
        "canonical_relative_paths": sorted({row["relative_path"] for row in portable}),
        "escape_state": escape_state,
        "disposition": "PASS",
    }


if __name__ == "__main__":
    print(json.dumps(exercise(), indent=2, sort_keys=True))
