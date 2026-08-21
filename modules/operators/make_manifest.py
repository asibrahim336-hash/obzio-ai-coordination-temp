#!/usr/bin/env python3
"""Build MANIFEST.json for a pack directory: every file, byte count, sha256.

MANIFEST.json cannot contain its own hash; it is excluded from `files` and
that exclusion is recorded explicitly in the manifest itself.

    python3 make_manifest.py <pack_dir> [...]
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

EXCLUDE_NAMES = {"MANIFEST.json"}
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache"}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build(pack_dir: Path) -> dict:
    files = []
    for p in sorted(pack_dir.rglob("*")):
        if not p.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        if p.name in EXCLUDE_NAMES:
            continue
        files.append({
            "path": str(p.relative_to(pack_dir)),
            "bytes": p.stat().st_size,
            "sha256": sha256_file(p),
        })
    return {
        "pack": pack_dir.name,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hash_algorithm": "sha256",
        "excluded": sorted(EXCLUDE_NAMES),
        "excluded_reason": "MANIFEST.json cannot contain its own digest",
        "file_count": len(files),
        "total_bytes": sum(f["bytes"] for f in files),
        "files": files,
    }


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    for d in argv[1:]:
        pd = Path(d).resolve()
        man = build(pd)
        out = pd / "MANIFEST.json"
        out.write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")
        print(f"{pd.name}: {man['file_count']} files, {man['total_bytes']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
