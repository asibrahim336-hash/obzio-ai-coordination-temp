#!/usr/bin/env python3
"""Execute recurrence tests against staged and deliberately reverted mechanisms."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def execute(mechanism_root: str) -> dict[str, object]:
    command = [sys.executable, "-I", "test_recurrence.py", mechanism_root]
    process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    return {
        "command": " ".join(command),
        "exit_code": process.returncode,
        "stdout": process.stdout,
        "stderr": process.stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "revert_proof.json")
    args = parser.parse_args()
    contract = json.loads((ROOT / "change_contract.json").read_text())
    staged = execute("staged_mechanisms")
    reverted = execute("reverted_mechanisms")
    passed = staged["exit_code"] == 0 and reverted["exit_code"] != 0
    result = {
        "protocol": contract["protocol"],
        "change_contract_sha256": hashlib.sha256(canonical(contract)).hexdigest(),
        "staged_run": staged,
        "reverted_run": reverted,
        "recurrence_sensitive_to_reversion": passed,
        "mechanism_changes_with_passing_recurrence_tests": 2 if passed else 0,
        "verdict": "PASS" if passed else "FAIL",
        "decision_changed": [],
    }
    args.output.write_bytes(canonical(result))
    print(json.dumps(result, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
