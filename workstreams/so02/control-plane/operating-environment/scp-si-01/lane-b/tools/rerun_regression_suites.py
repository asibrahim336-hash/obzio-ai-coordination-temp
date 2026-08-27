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

import hashlib
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
)

#: Run and recorded, but deliberately NOT in the cited report.
#:
#: These two suites test the chain mechanism itself. A RERUN link citing a report
#: that contains the verdict of the suite testing that very link is circular
#: evidence: the artifact's contents depend on whether the link is valid, and the
#: link's validity depends on the artifact's digest. Tried it. It does not
#: converge — re-anchor and rebuild oscillate between a passing and a failing
#: digest forever, because each state produces the other. The cycle is the
#: symptom; the circular citation is the defect.
#:
#: So the cited report covers only the mechanisms the RERUN nodes actually
#: re-executed, whose results do not depend on the chain at all, and the chain's
#: own suites are reported separately where nothing cites them.
SELF_SUITES: tuple[dict[str, str], ...] = (
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


def run_suite(suite: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (deterministic verdict, volatile run log) for one suite.

    They are separated because the verdict is cited by links in an append-only
    event log. A cited artifact has to be content-addressable: if its bytes move
    every time it is produced, every citation to it goes stale on the next run,
    and the only way to keep the citations valid is to never re-run the suites —
    which is a worse rule than splitting the file. So elapsed time, wall-clock
    instants and raw output tails live in the run log, and the verdict holds only
    what is reproducible: which suite, at which digest, how many tests, and
    whether it passed.
    """
    target = REPO_ROOT / suite["path"]
    done = subprocess.run(
        [sys.executable, "-I", str(target)],
        cwd=str(target.parent), capture_output=True, text=True, check=False,
    )
    combined = done.stdout + done.stderr
    match = COUNT_RE.search(combined)
    verdict = {
        **suite,
        "suite_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "argv": ["python3", "-I", suite["path"]],
        "cwd": str(target.parent.relative_to(REPO_ROOT)),
        "exit_code": done.returncode,
        "tests_run": int(match.group(1)) if match else None,
        "result": "OK" if done.returncode == 0 and "\nOK" in combined else "FAILED",
        "evidence_label": "DIRECTLY_REPRODUCED",
    }
    tail = combined.strip().splitlines()
    log = {
        "suite_id": suite["suite_id"],
        "summary_tail": tail[-1] if tail else "",
        "failure_tail": [line for line in tail if line.startswith(("FAIL:", "ERROR:"))][:20],
    }
    return verdict, log


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out = argv[0] if argv else None
    pairs = [run_suite(suite) for suite in SUITES]
    results = [verdict for verdict, _ in pairs]
    logs = [log for _, log in pairs]
    self_pairs = [run_suite(suite) for suite in SELF_SUITES]
    self_results = [verdict for verdict, _ in self_pairs]
    self_logs = [log for _, log in self_pairs]
    report = {
        "report_id": "SCP-B-REGRESSION-RERUN",
        "decision_changed": [],
        "deterministic": True,
        "deterministic_note": (
            "This file carries no wall-clock instant and no elapsed time, so re-running "
            "the suites with the same code and the same results produces the same bytes. "
            "It is cited by RERUN links in an append-only event log, and a citation can "
            "only stay valid if the artifact it addresses is content-addressable. The "
            "instants and output tails for a particular run are in the sibling run log, "
            "which nothing cites."
        ),
        "run_log": "receipts/so02/2026-08-27/scp-b/reproductions/REGRESSION-RERUN-RUNLOG.json",
        "invocation_note": (
            "python3 -I implies -P, so `python3 -I -m unittest <module>` cannot import a suite "
            "from the current directory and reports a load error. Each suite is run as a script."
        ),
        "cited_by": "the RERUN links of ICH-01 through ICH-04",
        "excluded_suites": [suite["suite_id"] for suite in SELF_SUITES],
        "why_those_are_excluded": (
            "They test the chain mechanism itself. A RERUN link citing the verdict of the "
            "suite that tests that link is circular: the artifact's contents depend on the "
            "link being valid, and the link's validity depends on the artifact's digest. "
            "Re-anchoring under that arrangement oscillates between a passing and a "
            "failing digest and never settles. Their results are in the sibling "
            "self-test report, which nothing cites."
        ),
        "self_test_report": "receipts/so02/2026-08-27/scp-b/reproductions/"
                            "REGRESSION-RERUN-SELF-TEST.json",
        "suites": results,
        "total_tests_run": sum(item["tests_run"] or 0 for item in results),
        "all_passed": all(item["exit_code"] == 0 and item["result"] == "OK" for item in results),
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    self_report = {
        "report_id": "SCP-B-REGRESSION-RERUN-SELF-TEST",
        "decision_changed": [],
        "deterministic": True,
        "not_cited_because": (
            "these suites test the chain, so a chain link citing them would be citing its "
            "own verdict"
        ),
        "suites": self_results,
        "total_tests_run": sum(item["tests_run"] or 0 for item in self_results),
        "all_passed": all(item["exit_code"] == 0 and item["result"] == "OK"
                          for item in self_results),
    }
    everything_passed = report["all_passed"] and self_report["all_passed"]
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        (Path(out).parent / "REGRESSION-RERUN-SELF-TEST.json").write_text(
            json.dumps(self_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        runlog = {
            "report_id": "SCP-B-REGRESSION-RERUN-RUNLOG",
            "produced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "decision_changed": [],
            "verdict_file": out,
            "not_cited_because": "carries wall-clock instants and elapsed times, so its "
                                 "bytes move on every run",
            "interpreter": f"python3 -I {sys.version.split()[0]}",
            "suites": logs + self_logs,
        }
        (Path(out).parent / "REGRESSION-RERUN-RUNLOG.json").write_text(
            json.dumps(runlog, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")
        print(f"cited suites      : tests={report['total_tests_run']} "
              f"passed={report['all_passed']}")
        print(f"self-test suites  : tests={self_report['total_tests_run']} "
              f"passed={self_report['all_passed']}")
        for item in results + self_results:
            if item["result"] != "OK":
                print(f"  FAILED {item['suite_id']} exit={item['exit_code']}")
    else:
        print(text, end="")
    return 0 if everything_passed else 1


if __name__ == "__main__":
    sys.exit(main())
