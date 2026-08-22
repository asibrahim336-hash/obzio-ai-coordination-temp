#!/usr/bin/env python3
"""Validate the immutable reproduction ledger and preserve its real output."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


EXPECTED_SHAS = {
    "1e6f53c323f8326d12af213557082a3665991f19",
    "37943ec2ff9f6702d72e127a3c8e56c81b0c3812",
    "4612fee16a0027ae41ed17d3b16b7bb18212ba6a",
    "62c29e1a641932b817592ddc970df11f89b6c0f7",
    "9696c325f0897b7c9e7ff2cd9d57fc7c4bb19e27",
    "8c52ef6d8f0d510cf1d2bfee48923a49ca19475d",
    "5db7affeb7f00763e148e6d98a33ee6b751f2def",
}
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def main() -> int:
    proc = subprocess.run(
        (
            sys.executable,
            "-I",
            str(HERE / "reproduce_claims.py"),
            "--repo",
            str(REPO),
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    ledger = json.loads(proc.stdout)
    assert ledger["overall_verdict"] == "PASS"
    assert ledger["po01_contact_or_mutation"] is False
    assert set(ledger["targets"].values()) == EXPECTED_SHAS
    assert ledger["claim_count"] == 9
    verdicts = [row["verdict"] for row in ledger["claims"]]
    assert "PASS" in verdicts
    assert "FAIL" in verdicts
    assert "NOT_YET" in verdicts
    assert "NOT_SUPPORTED" in verdicts
    aggregate = ledger["claims"][0]
    assert aggregate["verdict"] == "PASS"
    assert aggregate["observed"]["declared_mismatches"] == []
    assert aggregate["observed"]["tree_not_hash_declared"] == ["packs/MANIFEST_ALL.json"]
    runtime = ledger["claims"][1]
    assert runtime["verdict"] == "FAIL"
    assert len(runtime["observed"]["missing_declared_runtime_files"]) == 5
    print(proc.stdout, end="")
    print("test_reproduce_claims: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
