#!/usr/bin/env python3
"""Compare canonical PO-03 test output from two independent clean clones."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


FULL_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
ISO_TIMESTAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\b")
UNITTEST_ELAPSED = re.compile(r"(Ran \d+ tests? in )\d+\.\d+(s)")


def execute(argv: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)


def discover(clone: Path, commit: str) -> list[str]:
    result = execute(
        [
            "git",
            "ls-tree",
            "-r",
            "--name-only",
            "-z",
            commit,
            "--",
            "workstreams/po03",
        ],
        clone,
    )
    if result.returncode:
        raise RuntimeError("cannot discover committed tests")
    return sorted(
        path
        for path in result.stdout.split("\0")
        if path and Path(path).name.startswith("test_") and path.endswith(".py")
    )


def normalize(text: str, clone: Path) -> tuple[str, dict[str, int]]:
    fields: dict[str, int] = {}
    text, count = ISO_TIMESTAMP.subn("<TIMESTAMP>", text)
    if count:
        fields["iso8601_timestamp"] = count
    text, count = UNITTEST_ELAPSED.subn(r"\1<ELAPSED>\2", text)
    if count:
        fields["unittest_elapsed_seconds"] = count
    text, count = re.subn(re.escape(str(clone)), "<CLONE_ROOT>", text)
    if count:
        fields["clone_root"] = count
    return text, fields


def run_suite(clone: Path, commit: str, runtime: Path) -> tuple[list[dict[str, object]], dict[str, int]]:
    tests = discover(clone, commit)
    if not tests:
        raise RuntimeError("no committed PO-03 tests discovered")
    runtime.mkdir()
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", ""),
        "TMPDIR": str(runtime),
    }
    records: list[dict[str, object]] = []
    normalized_fields: dict[str, int] = {}
    try:
        for path in tests:
            result = execute([sys.executable, "-I", "-B", path], clone, environment)
            stdout, stdout_fields = normalize(result.stdout, clone)
            stderr, stderr_fields = normalize(result.stderr, clone)
            for collection in (stdout_fields, stderr_fields):
                for field, count in collection.items():
                    normalized_fields[field] = normalized_fields.get(field, 0) + count
            records.append(
                {
                    "path": path,
                    "returncode": result.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                }
            )
    finally:
        shutil.rmtree(runtime)
    return records, normalized_fields


def run_double_clone(source: Path, commit: str, workspace: Path) -> tuple[int, dict[str, object]]:
    if not source.exists() or not FULL_OBJECT_ID.fullmatch(commit):
        return 2, {"error": "source must exist and commit must be a full object ID"}
    if workspace.exists() or not workspace.parent.is_dir():
        return 2, {"error": "workspace must be absent and its parent must exist"}
    workspace.mkdir()
    clones = [workspace / "clone-a", workspace / "clone-b"]
    try:
        for clone in clones:
            result = execute(
                ["git", "clone", "--quiet", "--no-checkout", str(source), str(clone)],
                source,
            )
            if result.returncode:
                return 2, {"error": "clone failed", "stderr": result.stderr}
            checkout = execute(["git", "checkout", "--quiet", "--detach", commit], clone)
            if checkout.returncode:
                return 2, {"error": "commit checkout failed", "stderr": checkout.stderr}
        first, first_fields = run_suite(clones[0], commit, workspace / "runtime-a")
        second, second_fields = run_suite(clones[1], commit, workspace / "runtime-b")
        clean = []
        for clone in clones:
            status = execute(["git", "status", "--porcelain=v1", "--untracked-files=all"], clone)
            clean.append(status.returncode == 0 and not status.stdout)
        equal = first == second
        failed = sorted(
            {
                str(item["path"])
                for suite in (first, second)
                for item in suite
                if item["returncode"] != 0
            }
        )
        report: dict[str, object] = {
            "commit": commit,
            "test_file_count": len(first),
            "byte_equivalent": equal,
            "failed_tests": failed,
            "clean_after_run": clean,
            "normalized_fields": {
                "clone_a": first_fields,
                "clone_b": second_fields,
            },
            "canonical_results": {"clone_a": first, "clone_b": second},
        }
        return (0 if equal and not failed and all(clean) else 1), report
    except RuntimeError as exc:
        return 2, {"error": str(exc)}
    finally:
        shutil.rmtree(workspace)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args(argv)
    code, report = run_double_clone(
        args.source.resolve(), args.commit, args.workspace.resolve()
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
