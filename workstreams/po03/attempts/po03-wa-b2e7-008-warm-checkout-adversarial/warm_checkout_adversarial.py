#!/usr/bin/env python3
"""Prove the clean-clone runner rejects a deliberately warm-only gate."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def execute(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


def exercise(
    fixture: Path,
    clean_runner: Path,
    workspace: Path,
) -> tuple[int, dict[str, object]]:
    if not fixture.is_file() or not clean_runner.is_file():
        return 2, {"error": "fixture and clean-clone runner must exist"}
    if workspace.exists() or not workspace.parent.is_dir():
        return 2, {"error": "workspace must be absent and its parent must exist"}
    workspace.mkdir()
    repository = workspace / "warm-repository"
    clean_clone = workspace / "clean-clone"
    try:
        execute(["git", "init", "-q", str(repository)], workspace)
        execute(
            ["git", "config", "user.email", "fixture@example.invalid"],
            repository,
        )
        execute(["git", "config", "user.name", "Fixture"], repository)
        committed_test = (
            repository / "workstreams" / "po03" / "tests" / "test_warm_only.py"
        )
        committed_test.parent.mkdir(parents=True)
        committed_test.write_bytes(fixture.read_bytes())
        execute(["git", "add", "."], repository)
        committed = execute(["git", "commit", "-qm", "warm-only fixture"], repository)
        if committed.returncode:
            return 2, {"error": "cannot commit adversarial fixture", "stderr": committed.stderr}
        commit = execute(["git", "rev-parse", "HEAD"], repository).stdout.strip()

        marker = repository / ".warm-state"
        marker.write_text("uncommitted warm state\n", encoding="utf-8")
        tracked = execute(["git", "ls-files", "--error-unmatch", ".warm-state"], repository)
        warm = execute(
            [sys.executable, "-I", "-B", "workstreams/po03/tests/test_warm_only.py"],
            repository,
        )
        clean = execute(
            [
                sys.executable,
                "-I",
                "-B",
                str(clean_runner),
                "--source",
                str(repository),
                "--commit",
                commit,
                "--destination",
                str(clean_clone),
            ],
            workspace,
        )
        try:
            clean_report = json.loads(clean.stdout)
        except json.JSONDecodeError:
            clean_report = {"unparseable_stdout": clean.stdout}
        expected_path = "workstreams/po03/tests/test_warm_only.py"
        caught = (
            warm.returncode == 0
            and tracked.returncode != 0
            and clean.returncode != 0
            and expected_path in clean_report.get("failed_tests", [])
        )
        report: dict[str, object] = {
            "fixture_commit": commit,
            "warm_marker_tracked": tracked.returncode == 0,
            "warm_returncode": warm.returncode,
            "warm_stdout": warm.stdout,
            "warm_stderr": warm.stderr,
            "clean_runner_returncode": clean.returncode,
            "clean_runner_report": clean_report,
            "warm_checkout_dependence_caught": caught,
        }
        return (0 if caught else 1), report
    finally:
        shutil.rmtree(workspace)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--clean-runner", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args(argv)
    code, report = exercise(
        args.fixture.resolve(),
        args.clean_runner.resolve(),
        args.workspace.resolve(),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
