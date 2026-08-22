#!/usr/bin/env python3
"""Classify transport/package files using explicit, read-only evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

DEBRIS_SUFFIXES = (
    ".bak",
    ".orig",
    ".partial",
    ".rej",
    ".stage",
    ".staging",
    ".swp",
    ".tmp",
)
DEBRIS_NAMES = frozenset({".ds_store", "thumbs.db"})
LIVE_MARKER = b"OBZIO-LIVE-SURFACE"
DEBRIS_MARKER = b"OBZIO-TRANSPORT-DEBRIS"


def _files(roots: Iterable[Path]) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    unavailable: list[str] = []
    for root in roots:
        if not root.exists():
            unavailable.append(root.as_posix())
        elif root.is_file():
            files.append(root)
        else:
            files.extend(path for path in root.rglob("*") if path.is_file())
    return sorted(set(files)), unavailable


def classify(path: Path, live_paths: set[str] | None = None) -> dict[str, object]:
    """Classify one file; ambiguous files remain unresolved."""

    body = path.read_bytes()
    normalized = path.as_posix()
    name = path.name.lower()
    if DEBRIS_MARKER in body or name in DEBRIS_NAMES or name.endswith(DEBRIS_SUFFIXES):
        classification, reason = "debris", "explicit debris marker or transient suffix"
    elif LIVE_MARKER in body or (live_paths and normalized in live_paths):
        classification, reason = "live", "explicit live marker or current-path evidence"
    else:
        classification, reason = "unresolved", "no live or debris evidence"
    return {
        "path": normalized,
        "classification": classification,
        "reason": reason,
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
    }


def scan(roots: Iterable[str | Path], live_paths: Iterable[str] = ()) -> dict[str, object]:
    paths, unavailable = _files([Path(root) for root in roots])
    live = {Path(path).as_posix() for path in live_paths}
    artifacts = [classify(path, live) for path in paths]
    return {
        "artifacts": artifacts,
        "unavailable_roots": unavailable,
        "counts": {
            kind: sum(item["classification"] == kind for item in artifacts)
            for kind in ("live", "debris", "unresolved")
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="+", type=Path)
    parser.add_argument("--live-path", action="append", default=[])
    args = parser.parse_args()
    print(json.dumps(scan(args.root, args.live_path), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
