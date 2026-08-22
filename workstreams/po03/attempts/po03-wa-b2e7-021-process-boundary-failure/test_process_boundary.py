#!/usr/bin/env python3
"""The harness must expose a producer-only synthetic qualification."""

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
            str(HERE / "process_boundary_harness.py"),
            "--qualifier",
            str(HERE / "synthetic_stateful_qualifier.py"),
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(proc.stdout)
    assert report["fixture_label"] == "SYNTHETIC_PROCESS_MEMORY_QUALIFIER"
    assert report["in_process"]["qualified"] is True
    assert report["subprocess"]["qualified"] is False
    assert report["divergence_detected"] is True
    assert report["verdict"] == "FAIL_PROCESS_BOUNDARY"
    print(proc.stdout, end="")
    print("test_process_boundary: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
