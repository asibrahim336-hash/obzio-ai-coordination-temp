#!/usr/bin/env python3
"""Frozen regression for the absent declared sibling runtime dependency."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

PINNED = "1e6f53c323f8326d12af213557082a3665991f19"
PACKS = (
    "06-browser-execution",
    "07-capability-manufacture",
    "08-knowledge-currentness",
    "09-infrastructure-operation",
    "10-economics-measurement",
)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack-root", required=True, type=Path)
    args = parser.parse_args()
    missing = []
    for pack in PACKS:
        manifest = json.loads((args.pack_root / pack / "MANIFEST.json").read_text())
        assert any(row.get("path") == "_spine.py" for row in manifest["files"])
        target = args.pack_root / pack / "_spine.py"
        if not target.is_file():
            missing.append(target.relative_to(args.pack_root).as_posix())
    assert not missing, f"{PINNED} missing declared runtime files: {missing}"
    print(json.dumps({"pinned": PINNED, "missing": missing, "verdict": "PASS"}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
