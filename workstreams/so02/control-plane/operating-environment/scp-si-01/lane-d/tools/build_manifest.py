#!/usr/bin/env python3
"""Emit the SCP-SI-01 lane D receipt manifest over every file this lane wrote.

`bundle_sha256` is the sha256 of the canonical JSON encoding of the entry
list, so a third party can recompute it from the files alone without trusting
this script's own output. Standard library only. Runs under `python3 -I`.

Covers, by explicit list rather than a directory walk that could silently
drift: every path touched by this lane's own commits (`workstreams/so02/
control-plane/operating-environment/scp-si-01/lane-d/**` and the four
canonical test files this lane extended under the hard-boundary permission to
do so) plus every file already written under the receipt directory itself.
`MANIFEST.json` excludes itself -- a manifest cannot hash its own
still-being-written bytes -- and that exclusion is declared, not silent (see
`excluded_paths` below and the write declaration, which is a separate
artifact under `write-declarations/` and is not itself part of this
delivery's changed-file closure).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[7]
LANE_ROOT = REPO_ROOT / "workstreams/so02/control-plane/operating-environment/scp-si-01/lane-d"
RECEIPT_DIR = REPO_ROOT / "receipts/so02/2026-08-27/scp-d"
MANIFEST = RECEIPT_DIR / "MANIFEST.json"

EXTENDED_CANONICAL_TEST_FILES = [
    "workstreams/so02/control-plane/operating-environment/w10-provenance/tools/negative_tests_provctl.py",
    "workstreams/so02/control-plane/operating-environment/tools/test_write_admission.py",
    "workstreams/so02/control-plane/operating-environment/l1-cursor-baseline/proposed-cursor-config/dot-cursor/hooks/verify_hooks.py",
    "workstreams/so02/control-plane/operating-environment/l4-currentness-recovery/tests/test_currentctl.py",
]

def _entry(relative: str) -> dict[str, object]:
    target = REPO_ROOT / relative
    payload = target.read_bytes()
    return {
        "path": relative,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def main() -> int:
    entries: list[dict[str, object]] = []

    for path in sorted(LANE_ROOT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        entries.append(_entry(str(path.relative_to(REPO_ROOT))))

    for relative in EXTENDED_CANONICAL_TEST_FILES:
        entries.append(_entry(relative))

    for path in sorted(RECEIPT_DIR.rglob("*")):
        if not path.is_file() or path == MANIFEST or "__pycache__" in path.parts:
            continue
        entries.append(_entry(str(path.relative_to(REPO_ROOT))))

    seen: set[str] = set()
    deduped: list[dict[str, object]] = []
    for entry in entries:
        if entry["path"] in seen:
            continue
        seen.add(str(entry["path"]))
        deduped.append(entry)
    entries = sorted(deduped, key=lambda entry: entry["path"])

    bundle = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    manifest = {
        "manifest_id": "RCPT-SCP-SI-01-LANE-D-20260827-v001",
        "parent_id": "SCP-SI-01-LANE-D",
        "commission_id": "SCP-SI-01",
        "lane_id": "SCP-SI-01-lane-D",
        "branch": "cursor/scp-d-failure-to-learning-696d",
        "terminal_state": "READY_TO_COMMIT",
        "decision_changed": [],
        "excluded_paths": [
            {
                "path": "receipts/so02/2026-08-27/scp-d/MANIFEST.json",
                "reason": "this file; a manifest cannot hash its own still-being-written bytes",
                "declared_in": "the write declaration's target.paths, not this closure",
            }
        ],
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
