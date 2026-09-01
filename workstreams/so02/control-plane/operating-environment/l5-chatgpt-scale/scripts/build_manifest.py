#!/usr/bin/env python3
"""Build the delivery MANIFEST.json for lane OE-L5-CHATGPT-SCALE.

Lists every file this lane produced with path, size_bytes and sha256, plus
entry_count and bundle_sha256, where bundle_sha256 is the sha256 of
json.dumps(entries, sort_keys=True, separators=(",",":")).

The manifest excludes itself, because a file cannot contain its own hash.

Run from the repository root:
    python3 workstreams/.../l5-chatgpt-scale/scripts/build_manifest.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

LANE = "workstreams/so02/control-plane/operating-environment/l5-chatgpt-scale"
RECEIPTS = "receipts/so02/2026-08-22/oe-l5-chatgpt-scale"
MANIFEST = f"{RECEIPTS}/MANIFEST.json"

SKIP_DIRS = {"__pycache__", ".git"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(root: pathlib.Path, rel: str) -> list[pathlib.Path]:
    base = root / rel
    if not base.exists():
        return []
    out = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix in SKIP_SUFFIXES:
            continue
        if p.relative_to(root).as_posix() == MANIFEST:
            continue
        out.append(p)
    return out


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[6]
    if not (root / ".git").exists():
        print(f"not a repository root: {root}", file=sys.stderr)
        return 1

    files = collect(root, LANE) + collect(root, RECEIPTS)
    entries = []
    for p in files:
        entries.append({
            "path": p.relative_to(root).as_posix(),
            "size_bytes": p.stat().st_size,
            "sha256": sha256_file(p),
        })
    entries.sort(key=lambda e: e["path"])

    bundle = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    manifest = {
        "manifest_id": "OE-L5-CHATGPT-SCALE-DELIVERY-20260822-v001",
        "lane": "OE-L5-CHATGPT-SCALE",
        "commission": "COM-CUR-ENV-01-20260822-v001",
        "branch": "cursor/oe-l5-chatgpt-scale-696d",
        "immutable_source_sha": "fe0a595206e5986de7eaac6cabc619215a1eb81b",
        "built_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "state": "READY_TO_COMMIT",
        "namespaces_written": [LANE + "/**", RECEIPTS + "/**"],
        "bundle_sha256_definition":
            'sha256 of json.dumps(entries, sort_keys=True, separators=(",",":"))',
        "manifest_excludes_itself": True,
        "entry_count": len(entries),
        "bundle_sha256": bundle,
        "entries": entries,
    }

    out = root / MANIFEST
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"entry_count   : {len(entries)}")
    print(f"bundle_sha256 : {bundle}")
    print(f"written       : {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
