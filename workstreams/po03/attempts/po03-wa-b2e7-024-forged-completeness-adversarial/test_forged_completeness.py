#!/usr/bin/env python3
"""A forged COMPLETE status must not override contradictory payload bytes."""

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
            str(HERE / "qualify_forged.py"),
            "--pack-dir",
            str(HERE / "synthetic_forged_pack"),
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(proc.stdout)
    assert report["fixture_label"] == "SYNTHETIC_FORGED_COMPLETENESS_FIXTURE"
    assert report["self_reported_status"] == "COMPLETE"
    assert report["self_report_ignored"] is True
    assert report["qualification"] == "FAIL"
    assert report["evidence_table"][0]["present"] is True
    assert report["evidence_table"][0]["observed_bytes"] == 15
    assert report["evidence_table"][0]["declared_bytes"] == 15
    assert report["evidence_table"][0]["observed_sha256"] != report["evidence_table"][0]["declared_sha256"]
    print(proc.stdout, end="")
    print("test_forged_completeness: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
