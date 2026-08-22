#!/usr/bin/env python3
"""Prove concrete non-portability findings in the pinned published pack."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PINNED = "1e6f53c323f8326d12af213557082a3665991f19"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def main() -> int:
    proc = subprocess.run(
        (
            sys.executable,
            "-I",
            str(HERE / "scan_nonportable.py"),
            "--repo",
            str(REPO),
            "--commit",
            PINNED,
            "--prefix",
            "packs",
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(proc.stdout)
    assert report["commit"] == PINNED
    assert report["files_scanned"] == 93
    assert report["qualification"] == "FAIL_NONPORTABLE"
    assert any(
        row["path"] == "packs/MANIFEST.json" and row["reference"].startswith("/tmp/packs")
        for row in report["absolute_paths"]
    )
    assert any(
        row["path"] == "packs/MANIFEST_ALL.json" and row["reference"] == "packs2/"
        for row in report["transport_assumptions"]
    )
    missing = {row["target"] for row in report["unresolved_internal_references"]}
    assert {
        "packs/06-browser-execution/_spine.py",
        "packs/07-capability-manufacture/_spine.py",
        "packs/08-knowledge-currentness/_spine.py",
        "packs/09-infrastructure-operation/_spine.py",
        "packs/10-economics-measurement/_spine.py",
    }.issubset(missing)
    print(proc.stdout, end="")
    print("test_scan_nonportable: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
