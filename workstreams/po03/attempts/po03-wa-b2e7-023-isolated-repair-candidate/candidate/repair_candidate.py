#!/usr/bin/env python3
"""Integration candidate: restore manifest-pinned sibling spine bytes."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

PINNED = "1e6f53c323f8326d12af213557082a3665991f19"
EXPECTED_SPINE_SHA256 = "431773539ced6556fdd9a631fc80d42404aa2f30846a1d127826dd099a01f182"
PACKS = (
    "06-browser-execution",
    "07-capability-manufacture",
    "08-knowledge-currentness",
    "09-infrastructure-operation",
    "10-economics-measurement",
)

def repair(pack_root: Path) -> list[str]:
    source = pack_root / "_shared" / "_spine.py"
    body = source.read_bytes()
    observed = hashlib.sha256(body).hexdigest()
    if observed != EXPECTED_SPINE_SHA256:
        raise ValueError(f"shared spine hash mismatch: {observed}")
    written = []
    for pack in PACKS:
        manifest = json.loads((pack_root / pack / "MANIFEST.json").read_text())
        declaration = next(row for row in manifest["files"] if row.get("path") == "_spine.py")
        if declaration["sha256"] != observed or declaration["bytes"] != len(body):
            raise ValueError(f"{pack} declaration does not match shared spine")
        target = pack_root / pack / "_spine.py"
        if not target.exists():
            target.write_bytes(body)
            written.append(target.relative_to(pack_root).as_posix())
    return written

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack-root", required=True, type=Path)
    args = parser.parse_args()
    written = repair(args.pack_root)
    print(json.dumps({"pinned": PINNED, "written": written, "verdict": "REPAIR_CANDIDATE_APPLIED_TO_COPY"}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
