#!/usr/bin/env python3
"""Emit the OE-L4 receipt manifest over every file this lane wrote.

`bundle_sha256` is the sha256 of the canonical JSON encoding of the entry list,
so a third party can recompute it from the files alone without trusting this
script's own output. Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

LANE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[6]
RECEIPT_DIR = REPO_ROOT / "receipts/so02/2026-08-22/oe-l4-currentness-recovery"
MANIFEST = RECEIPT_DIR / "MANIFEST.json"


def main() -> int:
    entries = []
    for path in sorted(LANE_ROOT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        payload = path.read_bytes()
        entries.append({
            "path": str(path.relative_to(REPO_ROOT)),
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    for path in sorted(RECEIPT_DIR.rglob("*")):
        if not path.is_file() or path == MANIFEST:
            continue
        payload = path.read_bytes()
        entries.append({
            "path": str(path.relative_to(REPO_ROOT)),
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    entries.sort(key=lambda entry: entry["path"])

    bundle = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    manifest = {
        "manifest_id": "RCPT-OE-L4-CURRENTNESS-RECOVERY-20260822-v001",
        "parent_id": "OE-L4-CURRENTNESS-RECOVERY",
        "commission_id": "COM-CUR-ENV-01-20260822-v001",
        "parent_fence_token": "b749f2eaa8cf6e1c",
        "immutable_start_sha": "fe0a595206e5986de7eaac6cabc619215a1eb81b",
        "branch": "cursor/oe-l4-currentness-recovery-696d",
        "terminal_state": "READY_TO_COMMIT",
        "decision_changed": [],
        "bundle_sha256_definition": "sha256 of json.dumps(entries, sort_keys=True, separators=(',',':'))",
        "entry_count": len(entries),
        "bundle_sha256": bundle,
        "entries": entries,
    }
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"entry_count   {len(entries)}")
    print(f"bundle_sha256 {bundle}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
