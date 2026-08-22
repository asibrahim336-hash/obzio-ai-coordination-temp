#!/usr/bin/env python3
"""Check G2 for quality regression against a test suite this cohort did not write.

The frozen custody suite can only find regressions in the behaviour it happens to
probe, and it was written by the same producer who wrote G2.  The repository's own
58 baseline tests were not: they load the factory by relative path, which means a
sandbox with G2 in the tools directory runs them against the successor unchanged.

Both generations are run through that suite and the results are compared test by
test.  A test that passes under G1 and fails under G2 is a quality regression, and
it is reported as one no matter how the frozen suite scored.  This is the guard
that catches a repair which fixes the hazard and breaks the legitimate path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CHECK_VERSION = "PO03-G2-REGRESSION-CHECK-v1"
SANDBOX_SOURCES = (
    "workstreams/po03/COMMISSION.md",
    "workstreams/po03/contracts",
    "workstreams/po03/tests",
    "workstreams/po03/tools/validate_contracts.py",
    "workstreams/po03/tools/check_path_scope.py",
)
FACTORY_RELATIVE = "workstreams/po03/tools/transactional_factory.py"
OUTCOME_RE = re.compile(r"^(?P<name>[\w.]+) \((?P<case>[\w.]+)\)(?: \.\.\.)? (?P<outcome>ok|FAIL|ERROR|skipped.*)$")
RAN_RE = re.compile(r"^Ran (?P<count>\d+) tests? in ")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def parse_outcomes(output: str) -> dict[str, str]:
    """Map every reported test to ok, FAIL, ERROR or skipped from verbose output.

    The parenthesised dotted path is unittest's own test id, so it is used as the
    identifier directly rather than being recombined with the method name.
    """
    outcomes: dict[str, str] = {}
    for line in output.splitlines():
        match = OUTCOME_RE.match(line.strip())
        if match is None:
            continue
        outcome = match.group("outcome")
        outcomes[match.group("case")] = "skipped" if outcome.startswith("skipped") else outcome
    return outcomes


def reported_total(output: str) -> int | None:
    """The count unittest itself printed, used to prove the parse missed nothing."""
    for line in output.splitlines():
        match = RAN_RE.match(line.strip())
        if match is not None:
            return int(match.group("count"))
    return None


def run_suite(repo: Path, factory: Path, label: str) -> dict[str, Any]:
    sandbox = Path(tempfile.mkdtemp(prefix=f"po03-regression-{label.lower()}-"))
    try:
        for relative in SANDBOX_SOURCES:
            source = repo / relative
            destination = sandbox / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
        shutil.copy2(factory, sandbox / FACTORY_RELATIVE)

        completed = subprocess.run(
            ("python3", "-I", "-m", "unittest", "discover", "-s",
             (sandbox / "workstreams/po03/tests").as_posix(), "-p", "test_*.py", "-v"),
            cwd=sandbox,
            capture_output=True,
            text=True,
        )
        combined = completed.stdout + completed.stderr
        outcomes = parse_outcomes(combined)
        announced = reported_total(combined)
        totals = {
            "ran": len(outcomes),
            "ok": sum(1 for value in outcomes.values() if value == "ok"),
            "failed": sum(1 for value in outcomes.values() if value in {"FAIL", "ERROR"}),
            "skipped": sum(1 for value in outcomes.values() if value == "skipped"),
            "announced_by_unittest": announced,
            # A silently incomplete parse would look like a clean comparison, so
            # the parsed count is checked against the count unittest printed.
            "parse_is_complete": announced is not None and announced == len(outcomes),
        }
        return {
            "label": label,
            "factory": factory.as_posix(),
            "factory_sha256": sha256_bytes(factory.read_bytes()),
            "exit_code": completed.returncode,
            "totals": totals,
            "outcomes": outcomes,
            "tail": combined.strip().splitlines()[-6:],
        }
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    regressions = sorted(
        identifier
        for identifier, outcome in before["outcomes"].items()
        if outcome == "ok" and after["outcomes"].get(identifier) != "ok"
    )
    repairs = sorted(
        identifier
        for identifier, outcome in before["outcomes"].items()
        if outcome != "ok" and after["outcomes"].get(identifier) == "ok"
    )
    return {
        "regressed_tests": regressions,
        "regression_count": len(regressions),
        "repaired_tests": repairs,
        "disappeared_tests": sorted(set(before["outcomes"]) - set(after["outcomes"])),
        "appeared_tests": sorted(set(after["outcomes"]) - set(before["outcomes"])),
        "no_quality_regression": not regressions
        and not (set(before["outcomes"]) - set(after["outcomes"]))
        and bool(before.get("totals", {}).get("parse_is_complete", True))
        and bool(after.get("totals", {}).get("parse_is_complete", True)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--g1-source", required=True)
    parser.add_argument("--g2-source", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    before = run_suite(repo, Path(args.g1_source).resolve(), "G1")
    after = run_suite(repo, Path(args.g2_source).resolve(), "G2")
    comparison = compare(before, after)

    record = {
        "check_version": CHECK_VERSION,
        "ran_at": utc_now(),
        "suite": {
            "origin": "workstreams/po03/tests",
            "authored_by": "not this cohort; the repository's own baseline suite",
            "note": "the suite loads the factory from workstreams/po03/tools/, so a sandbox copy runs it "
                    "against either generation with no edit to the tests",
        },
        "g1": before,
        "g2": after,
        "comparison": comparison,
        "decision_changed": [],
    }
    Path(args.out).write_bytes(canonical(record))
    print(json.dumps({key: value for key, value in record.items() if key not in {"g1", "g2"}}, indent=2, sort_keys=True))
    for arm in (before, after):
        print(f"{arm['label']}: ran {arm['totals']['ran']} ok {arm['totals']['ok']} "
              f"failed {arm['totals']['failed']} exit {arm['exit_code']}")
    if comparison["regressed_tests"]:
        print("QUALITY REGRESSION in the independent suite:", file=sys.stderr)
        for identifier in comparison["regressed_tests"]:
            print(f"  {identifier}: G1 ok -> G2 {after['outcomes'].get(identifier)}", file=sys.stderr)
        return 1
    print(f"NO REGRESSION: {before['totals']['ok']} tests pass under G1 and still pass under G2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
