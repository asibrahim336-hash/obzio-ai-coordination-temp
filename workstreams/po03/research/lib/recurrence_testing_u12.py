"""a5-u12: helpers for independently recurrence-testing this worker's own
admitted mechanism changes (a5-u06, a5-u07).

Honest scope boundary (also recorded in sources.json's a5-u12 entry): the
frozen acceptance wording asks for recurrence testing "by a different
owner". This subagent cannot invoke another PO-03 worker (po03-worker-a6,
po03-worker-a10, ...) or the coordinator mid-unit; the recurrence actually
executed here is independent-PROCESS, independent-SEED re-execution by
this same worker -- a fresh Python interpreter with no shared in-memory
state, a different random seed where applicable, run against the
byte-identical committed artifacts. True different-owner replay is
recorded as NOT_YET with this exact boundary, not claimed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
PO03_ROOT = Path(__file__).resolve().parents[2]


def run_probe_subprocess(script_path: Path, seed: int, extra_args: list[str] | None = None) -> dict[str, Any]:
    """Runs a recurrence probe script in a genuinely fresh subprocess (own
    interpreter, own memory space) and parses its single JSON stdout line."""
    args = [sys.executable, "-I", str(script_path), "--seed", str(seed)]
    if extra_args:
        args.extend(extra_args)
    result = subprocess.run(args, capture_output=True, text=True, cwd=REPO_ROOT, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"probe {script_path} failed (exit {result.returncode}): {result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def run_permanent_test_subprocess(test_file_pattern: str) -> dict[str, Any]:
    """Runs one permanent test file via the real, standard gate invocation
    (unittest discover) in a fresh subprocess, and reports pass/fail."""
    args = [
        sys.executable,
        "-I",
        "-m",
        "unittest",
        "discover",
        "-s",
        "workstreams/po03/tests",
        "-p",
        test_file_pattern,
    ]
    result = subprocess.run(args, capture_output=True, text=True, cwd=REPO_ROOT, timeout=120)
    return {
        "command": " ".join(args),
        "returncode": result.returncode,
        "passed": result.returncode == 0,
        "stderr_tail": "\n".join(result.stderr.strip().splitlines()[-5:]),
    }


VALID_DISPOSITIONS = {"RETAIN", "DELETE", "SUPERSEDE", "RETEST", "REJECT"}


def determine_disposition(permanent_test_passed: bool, qualitative_match: bool) -> str:
    if permanent_test_passed and qualitative_match:
        return "RETAIN"
    if permanent_test_passed and not qualitative_match:
        return "RETEST"  # the pinned test still passes, but the broader finding did not replicate cleanly
    return "REJECT"  # the permanent test itself failed under independent re-execution
