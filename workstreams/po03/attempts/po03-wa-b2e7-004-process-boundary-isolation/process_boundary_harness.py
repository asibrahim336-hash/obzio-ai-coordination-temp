#!/usr/bin/env python3
"""Run declared mechanisms twice in distinct isolated Python interpreters."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def canonical_observation(result: subprocess.CompletedProcess[str]) -> bytes:
    value = {
        "returncode": result.returncode,
        "stderr": result.stderr,
        "stdout": result.stdout,
    }
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def load_cases(spec_path: Path) -> list[dict[str, Any]]:
    value = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not value:
        raise ValueError("spec must be a non-empty array")
    for case in value:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("name"), str)
            or not isinstance(case.get("script"), str)
            or not isinstance(case.get("args", []), list)
            or not all(isinstance(arg, str) for arg in case.get("args", []))
        ):
            raise ValueError("each case requires name, script, and a string args array")
    return value


def run_harness(repo_root: Path, cases: list[dict[str, Any]]) -> tuple[int, dict[str, object]]:
    reports: list[dict[str, object]] = []
    for case in cases:
        script = (repo_root / case["script"]).resolve()
        if not script.is_relative_to(repo_root) or not script.is_file():
            return 2, {"error": f"mechanism script is absent or outside repository: {case['script']}"}
        argv = [sys.executable, "-I", "-B", str(script), *case.get("args", [])]
        first = subprocess.run(argv, cwd=repo_root, capture_output=True, text=True)
        second = subprocess.run(argv, cwd=repo_root, capture_output=True, text=True)
        first_bytes = canonical_observation(first)
        second_bytes = canonical_observation(second)
        reports.append(
            {
                "name": case["name"],
                "argv": ["python", "-I", "-B", case["script"], *case.get("args", [])],
                "equivalent": first_bytes == second_bytes,
                "first": json.loads(first_bytes),
                "second": json.loads(second_bytes),
            }
        )
    mismatches = [case["name"] for case in reports if not case["equivalent"]]
    report: dict[str, object] = {
        "mechanism_count": len(reports),
        "mismatches": mismatches,
        "all_process_boundaries_equivalent": not mismatches,
        "mechanisms": reports,
    }
    return (1 if mismatches else 0), report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".", type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.spec)
        code, report = run_harness(args.repo_root.resolve(), cases)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        code, report = 2, {"error": str(exc)}
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
