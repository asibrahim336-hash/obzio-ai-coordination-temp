#!/usr/bin/env python3
"""Re-execute the regression suites the seeded chains name, and record the result.

A RERUN link asserts that a named regression test was actually re-executed and
what it returned. That assertion needs its own artifact, or the link is a claim
about a claim. This harness produces that artifact.

Note the invocation. `python3 -I` implies `-P`, so neither the script directory
nor the working directory is placed on `sys.path`; `python3 -I -m unittest
<module>` therefore fails to import the module at all and reports a load error
while still exiting 0 under a shell that swallows it. Every suite here is run as
a script, which is the form that actually works isolated, and the returncode is
read from the process rather than from the printed summary.

Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[7]

SUITES: tuple[dict[str, str], ...] = (
    {
        "suite_id": "SUITE-EVIDENCE-INTEGRITY",
        "path": "workstreams/so02/control-plane/operating-environment/tools/test_evidence_integrity.py",
        "covers_chains": "ICH-01-FORGED-READBACK, ICH-02-DENYLIST-CAPACITY, ICH-05-UNPARSEABLE-ARTIFACT",
    },
    {
        "suite_id": "SUITE-LANE-GUARD",
        "path": "workstreams/so02/control-plane/operating-environment/tools/test_lane_guard.py",
        "covers_chains": "ICH-03-SHARED-WORKTREE-COLLISION, ICH-04-SILENT-PUSH-NO-OP",
    },
    {
        "suite_id": "SUITE-IMPROVEMENT-CHAIN",
        "path": "workstreams/so02/control-plane/operating-environment/scp-si-01/lane-b/"
                "tests/test_improvement_chain.py",
        "covers_chains": "the chain mechanism itself, and the seeded state of all eight",
    },
    {
        "suite_id": "SUITE-SCCTL",
        "path": "workstreams/so02/control-plane/tests/test_scctl.py",
        "covers_chains": "the canonical seed validator, which is what catches a broken "
                         "hash chain after the append",
    },
)

COUNT_RE = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)


def run_suite(suite: dict[str, str]) -> dict[str, Any]:
    target = REPO_ROOT / suite["path"]
    done = subprocess.run(
        [sys.executable, "-I", str(target)],
        cwd=str(target.parent), capture_output=True, text=True, check=False,
    )
    combined = done.stdout + done.stderr
    match = COUNT_RE.search(combined)
    return {
        **suite,
        "argv": ["python3", "-I", suite["path"]],
        "cwd": str(target.parent.relative_to(REPO_ROOT)),
        "exit_code": done.returncode,
        "tests_run": int(match.group(1)) if match else None,
        "result": "OK" if done.returncode == 0 and "\nOK" in combined else "FAILED",
        "summary_tail": combined.strip().splitlines()[-1] if combined.strip() else "",
        "evidence_label": "DIRECTLY_REPRODUCED",
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out = argv[0] if argv else None
    results = [run_suite(suite) for suite in SUITES]
    report = {
        "report_id": "SCP-B-REGRESSION-RERUN",
        "produced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "decision_changed": [],
        "invocation_note": (
            "python3 -I implies -P, so `python3 -I -m unittest <module>` cannot import a suite "
            "from the current directory and reports a load error. Each suite is run as a script."
        ),
        "suites": results,
        "total_tests_run": sum(item["tests_run"] or 0 for item in results),
        "all_passed": all(item["exit_code"] == 0 and item["result"] == "OK" for item in results),
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        print(f"wrote {out}")
        print(f"total_tests_run={report['total_tests_run']} all_passed={report['all_passed']}")
    else:
        print(text, end="")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
