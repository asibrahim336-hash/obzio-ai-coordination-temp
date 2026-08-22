#!/usr/bin/env python3
"""Build each synthetic estate, compile it, and check the frozen expectations.

The runner is the reproducible half of the unit: it materialises every case as
a real Git repository, pins a commit, compiles it with the same code the tests
import, and emits one deterministic evidence document.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

RUNNER_VERSION = "PO03-CURRENTNESS-CASE-RUNNER-v1"
UNIT_ROOT = Path(__file__).resolve().parents[1]
COMPILER_PATH = UNIT_ROOT / "tools" / "currentness_compiler.py"
CASES_PATH = UNIT_ROOT / "fixtures" / "synthetic" / "cases.json"
SYNTHETIC_SPEC_PATH = "spec/currentness.spec.json"


def load_compiler() -> Any:
    specification = importlib.util.spec_from_file_location("currentness_compiler", COMPILER_PATH)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"unable to load compiler at {COMPILER_PATH}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(("git", "-C", str(repository), *arguments), check=True, capture_output=True)


def materialize_case(root: Path, case: dict[str, Any], base_spec: dict[str, Any]) -> str:
    """Write one synthetic estate into a fresh repository and pin a commit."""
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "po03-wave-a-003@obzio.invalid")
    _git(root, "config", "user.name", "PO-03 wave-a-003 case runner")
    _git(root, "config", "commit.gpgsign", "false")
    for relative, content in case["files"].items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if "json" in content:
            payload = (json.dumps(content["json"], indent=2, sort_keys=True) + "\n").encode("utf-8")
        else:
            payload = content["text"].encode("utf-8")
        target.write_bytes(payload)
    spec = dict(base_spec)
    spec.update(case.get("spec_overrides", {}))
    spec_target = root / SYNTHETIC_SPEC_PATH
    spec_target.parent.mkdir(parents=True, exist_ok=True)
    spec_target.write_bytes((json.dumps(spec, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", f"synthetic case {case['case_id']}")
    return subprocess.run(
        ("git", "-C", str(root), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def check_case(report: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    """Compare one compilation against its frozen expectation."""
    failures: list[str] = []
    if report["gate"] != expect["gate"]:
        failures.append(f"gate {report['gate']} != expected {expect['gate']}")
    observed_violations = sorted({item["violation"] for item in report["violations"]})
    expected_violations = sorted(expect.get("violations", []))
    if observed_violations != expected_violations:
        failures.append(f"violations {observed_violations} != expected {expected_violations}")
    for path in expect.get("current_includes", []):
        if path not in report["current_source_set"]:
            failures.append(f"missing from current source set: {path}")
    for path in expect.get("current_excludes", []):
        if path in report["current_source_set"]:
            failures.append(f"unexpectedly current: {path}")
    for path in expect.get("superseded_includes", []):
        if path not in report["retained_superseded_set"]:
            failures.append(f"missing from retained superseded set: {path}")
    for path in expect.get("superseded_excludes", []):
        if path in report["retained_superseded_set"]:
            failures.append(f"unexpectedly superseded: {path}")
    for name, value in expect.get("counts", {}).items():
        if report["counts"].get(name) != value:
            failures.append(f"count {name}={report['counts'].get(name)} != expected {value}")
    return failures


def run_cases(*, cases_path: Path = CASES_PATH) -> dict[str, Any]:
    compiler = load_compiler()
    document = json.loads(cases_path.read_text(encoding="utf-8"))
    results = []
    for case in document["cases"]:
        with tempfile.TemporaryDirectory(prefix="po03-wa003-case-") as directory:
            root = Path(directory)
            commit = materialize_case(root, case, document["base_spec"])
            report = compiler.compile_currentness(
                repository=str(root),
                revision=commit,
                spec_path=SYNTHETIC_SPEC_PATH,
            )
            failures = check_case(report, case["expect"])
            results.append(
                {
                    "case_id": case["case_id"],
                    "purpose": case["purpose"],
                    "outcome": "PASS" if not failures else "FAIL",
                    "failures": failures,
                    "observed": {
                        "gate": report["gate"],
                        "counts": report["counts"],
                        "violations": sorted({item["violation"] for item in report["violations"]}),
                        "current_source_set": report["current_source_set"],
                        "retained_superseded_set": report["retained_superseded_set"],
                        "determinism_digest": report["determinism_digest"],
                    },
                }
            )
    return {
        "runner_version": RUNNER_VERSION,
        "cases_version": document["cases_version"],
        "cases_sha256": compiler.sha256_bytes(cases_path.read_bytes()),
        "compiler_sha256": compiler.sha256_bytes(COMPILER_PATH.read_bytes()),
        "case_count": len(results),
        "passed": sum(result["outcome"] == "PASS" for result in results),
        "failed": sum(result["outcome"] == "FAIL" for result in results),
        "results": results,
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the synthetic currentness case matrix.")
    parser.add_argument("--out", default=None)
    arguments = parser.parse_args(argv)
    summary = run_cases()
    payload = (json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    if arguments.out:
        Path(arguments.out).write_bytes(payload)
    print(f"CURRENTNESS_CASES passed={summary['passed']} failed={summary['failed']} of {summary['case_count']}")
    for result in summary["results"]:
        if result["outcome"] == "FAIL":
            print(f"  FAIL {result['case_id']}: {result['failures']}", file=sys.stderr)
    return 0 if summary["failed"] == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
