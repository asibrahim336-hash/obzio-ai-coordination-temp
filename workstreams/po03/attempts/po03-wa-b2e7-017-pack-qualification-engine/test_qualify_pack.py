#!/usr/bin/env python3
"""Executable proof for the pinned repository-engineering pack manifest."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PINNED = "1e6f53c323f8326d12af213557082a3665991f19"
MANIFEST = "packs/repository-engineering/MANIFEST.json"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def main() -> int:
    proc = subprocess.run(
        (
            sys.executable,
            "-I",
            str(HERE / "qualify_pack.py"),
            "--repo",
            str(REPO),
            "--commit",
            PINNED,
            "--manifest",
            MANIFEST,
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(f"qualification failed:\n{proc.stdout}\n{proc.stderr}")
    report = json.loads(proc.stdout)
    assert report["commit"] == PINNED
    assert report["commit_type"] == "commit"
    assert report["manifest_path"] == MANIFEST
    assert report["manifest_sha256"] == (
        "3b1d6f1433cddc61648b1b9a65d6b32503d0a3e97ac51db722e18ee78d8e2c2e"
    )
    assert report["manifest_bytes"] == 2584
    assert report["declaration_count"] == 17
    assert report["matched_count"] == 17
    assert report["verdict"] == "PASS"
    assert all(row["present"] for row in report["evidence_table"])
    assert all(row["hash_match"] and row["bytes_match"] for row in report["evidence_table"])
    print(proc.stdout, end="")
    print("test_qualify_pack: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
