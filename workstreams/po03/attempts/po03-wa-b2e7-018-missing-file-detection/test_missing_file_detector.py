#!/usr/bin/env python3
"""Prove absence detection on both pinned and labelled synthetic inputs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PINNED = "1e6f53c323f8326d12af213557082a3665991f19"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
PROGRAM = HERE / "missing_file_detector.py"


def run(*args: str) -> dict:
    proc = subprocess.run(
        (sys.executable, "-I", str(PROGRAM), *args),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def main() -> int:
    pinned = run(
        "--repo",
        str(REPO),
        "--commit",
        PINNED,
        "--manifest",
        "packs/repository-engineering/MANIFEST.json",
    )
    assert pinned["verdict"] == "PASS"
    assert pinned["declared_count"] == 8
    assert pinned["missing"] == []

    synthetic = run("--pack-dir", str(HERE / "synthetic_pack"))
    assert synthetic["fixture_label"] == "SYNTHETIC_MISSING_FILE_FIXTURE"
    assert synthetic["verdict"] == "FAIL"
    assert synthetic["declared_count"] == 2
    assert synthetic["missing"] == ["missing.txt"]
    print(json.dumps({"pinned": pinned, "synthetic": synthetic}, indent=2, sort_keys=True))
    print("test_missing_file_detector: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
