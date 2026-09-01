#!/usr/bin/env python3
"""Build the lane receipt manifest.

Lists every file this lane produced with path, size and sha256, then binds the
set with bundle_sha256 = sha256 of json.dumps(entries, sort_keys=True,
separators=(",",":")). The manifest excludes itself, since a file cannot contain
its own hash.

Run from the repository root:
    build_manifest.py <manifest-output-path> <root> [<root> ...]
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    out_path = sys.argv[1]
    roots = sys.argv[2:]
    out_abs = os.path.abspath(out_path)

    paths: list[str] = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                if os.path.abspath(full) == out_abs:
                    continue
                paths.append(full)
    paths.sort()

    entries = [
        {
            "path": p.replace(os.sep, "/"),
            "size_bytes": os.path.getsize(p),
            "sha256": sha256_file(p),
        }
        for p in paths
    ]

    bundle = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    bundle_sha256 = hashlib.sha256(bundle.encode("utf-8")).hexdigest()

    manifest = {
        "manifest_id": "OE-L2-RECEIPT-MANIFEST-20260822-v001",
        "lane": "OE-L2-CAPABILITY-RESEARCH",
        "commission_id": "COM-CUR-ENV-01-20260822-v001",
        "parent_fence_token": "d5e76252f0ea259d",
        "immutable_start_sha": "fe0a595206e5986de7eaac6cabc619215a1eb81b",
        "branch": "cursor/oe-l2-capability-research-696d",
        "lifecycle_state": "READY_TO_COMMIT",
        "built_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "roots": [r.replace(os.sep, "/") for r in roots],
        "bundle_sha256_definition": "sha256 of json.dumps(entries, sort_keys=True, separators=(\",\",\":\"))",
        "self_excluded": out_path.replace(os.sep, "/"),
        "entry_count": len(entries),
        "bundle_sha256": bundle_sha256,
        "entries": entries,
    }

    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    with open(out_abs, "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")

    print(f"entry_count={len(entries)} bundle_sha256={bundle_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
