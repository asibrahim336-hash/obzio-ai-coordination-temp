#!/usr/bin/env python3
"""Run committed PO-03 tests in a Linux user and network namespace."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
NETWORK_FAILURE = re.compile(
    r"(Network is unreachable|Name or service not known|Temporary failure in name resolution|"
    r"socket\.(?:gaierror|herror)|ConnectionError|ConnectionRefusedError|"
    r"\[Errno (?:99|101|111)\])",
    re.IGNORECASE,
)


def execute(argv: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)


def discover(clone: Path, commit: str) -> list[str]:
    listing = execute(
        ["git", "ls-tree", "-r", "--name-only", "-z", commit, "--", "workstreams/po03"],
        clone,
    )
    if listing.returncode:
        raise RuntimeError("cannot enumerate committed tests")
    return sorted(
        path
        for path in listing.stdout.split("\0")
        if path and Path(path).name.startswith("test_") and path.endswith(".py")
    )


def run_denied(source: Path, commit: str, workspace: Path) -> tuple[int, dict[str, object]]:
    if not source.exists() or not OBJECT_ID.fullmatch(commit):
        return 2, {"error": "source must exist and commit must be a full object ID"}
    if workspace.exists() or not workspace.parent.is_dir():
        return 2, {"error": "workspace must be absent and its parent must exist"}
    preflight = execute(["unshare", "-Urn", "--", "true"], source)
    if preflight.returncode:
        return 2, {
            "error": "network namespace denial is not supported",
            "stderr": preflight.stderr,
        }

    workspace.mkdir()
    clone = workspace / "clone"
    runtime = workspace / "runtime"
    try:
        cloned = execute(
            ["git", "clone", "--quiet", "--no-checkout", str(source), str(clone)],
            source,
        )
        if cloned.returncode:
            return 2, {"error": "clone failed", "stderr": cloned.stderr}
        checkout = execute(["git", "checkout", "--quiet", "--detach", commit], clone)
        if checkout.returncode:
            return 2, {"error": "checkout failed", "stderr": checkout.stderr}
        tests = discover(clone, commit)
        if not tests:
            return 2, {"error": "no committed PO-03 tests found"}
        runtime.mkdir()
        environment = {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": os.environ.get("PATH", ""),
            "TMPDIR": str(runtime),
        }
        cases: list[dict[str, object]] = []
        for path in tests:
            result = execute(
                [
                    "unshare",
                    "-Urn",
                    "--",
                    sys.executable,
                    "-I",
                    "-B",
                    path,
                ],
                clone,
                environment,
            )
            combined = result.stdout + result.stderr
            classification = (
                "PASS"
                if result.returncode == 0
                else ("NETWORK_DEPENDENCE" if NETWORK_FAILURE.search(combined) else "UNRELATED_FAILURE")
            )
            cases.append(
                {
                    "path": path,
                    "returncode": result.returncode,
                    "classification": classification,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
        network_failures = [
            str(case["path"])
            for case in cases
            if case["classification"] == "NETWORK_DEPENDENCE"
        ]
        unrelated_failures = [
            str(case["path"])
            for case in cases
            if case["classification"] == "UNRELATED_FAILURE"
        ]
        status = execute(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            clone,
        )
        clean = status.returncode == 0 and not status.stdout
        report: dict[str, object] = {
            "commit": commit,
            "sandbox": "linux-user-and-network-namespace",
            "network_namespace_preflight": "SUPPORTED",
            "test_file_count": len(tests),
            "network_dependency_failures": network_failures,
            "unrelated_failures": unrelated_failures,
            "clean_after_run": clean,
            "cases": cases,
        }
        return (0 if not network_failures and not unrelated_failures and clean else 1), report
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
    code, report = run_denied(
        args.source.resolve(), args.commit, args.workspace.resolve()
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
