#!/usr/bin/env python3
"""Exercise both directions of the synthetic manifest gap."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent


def main() -> int:
    proc = subprocess.run(
        (
            sys.executable,
            "-I",
            str(HERE / "manifest_gaps.py"),
            "--pack-dir",
            str(HERE / "synthetic_pack"),
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(proc.stdout)
    assert report["fixture_label"] == "SYNTHETIC_BIDIRECTIONAL_MANIFEST_GAP_FIXTURE"
    assert report["verdict"] == "FAIL"
    assert report["undeclared_present"] == ["extra-present.txt"]
    assert report["declared_unhashed"] == ["declared-unhashed.txt"]
    print(proc.stdout, end="")
    print("test_manifest_gaps: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
