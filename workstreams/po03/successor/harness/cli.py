#!/usr/bin/env python3
"""Shared body for each generation's own entry point.

Every generation ships a ``run.py`` so it can be executed standalone, which is
what "runs from its own entry point" has to mean if it is to be checkable.  The
reporting logic is shared so three transcripts stay comparable line for line;
what differs between the entry points is only which generation they load.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .controller_api import OPERATIONS
from .runner import load_cases, run_suite
from .score import summarise


def run_generation(*, po03: Path, controller_cls, build, provenance: str, argv: list[str] | None = None) -> int:
    suites = {
        "public": po03 / "successor" / "suite" / "public" / "cases.json",
        "holdout": po03 / "successor" / "suite" / "holdout" / "cases.json",
    }
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=sorted(suites) + ["all"], default="all")
    parser.add_argument("--verbose", action="store_true", help="print the full step trace of each failure")
    args = parser.parse_args(argv)

    print(f"generation {controller_cls.generation_id}: {controller_cls.generation_label}")
    print(f"provenance: {provenance}")
    present = controller_cls.capabilities()
    print(f"capabilities: {', '.join(present)}")
    print(f"absent capabilities: {', '.join(sorted(set(OPERATIONS) - set(present))) or 'none'}")

    keys = sorted(suites) if args.suite == "all" else [args.suite]
    for key in keys:
        # A suite that has not landed is reported as an observed boundary rather
        # than substituted for.  The holdout in particular is authored by another
        # cohort, so its absence is a fact about the programme's state and must
        # not be papered over with a locally authored stand-in.
        if not suites[key].is_file():
            print(f"[{key}] NOT_YET: no case file at {suites[key].name}; suite not scored")
            continue
        _, cases = load_cases(suites[key])
        records = run_suite(build, cases)
        summary = summarise(records)
        print(
            f"[{key}] {summary['cases_passed']}/{summary['cases_total']} passed "
            f"rate={summary['pass_rate']} critical={summary['critical_pass_rate']} "
            f"false_completions={summary['false_completion_count']} "
            f"unsupported_cases={summary['unsupported_case_count']}"
        )
        for record in records:
            if not record["passed"]:
                print(f"  FAIL {record['case_id']}: {'; '.join(record['failures']) or record['crash']}")
                if args.verbose:
                    print(json.dumps(record["trace"], indent=2, sort_keys=True))
    # A measured shortfall is the finding, not a command failure.  Only a harness
    # defect raises, and that surfaces as a traceback and a non-zero exit.
    return 0
