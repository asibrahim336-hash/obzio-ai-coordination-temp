#!/usr/bin/env python3
"""Run every committed PO-03 test from a clean clone of an immutable commit."""

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


def command(*argv: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)


def clean_environment(runtime_directory: Path) -> dict[str, str]:
    return {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "TMPDIR": str(runtime_directory),
    }


def committed_tests(clone: Path, commit: str, test_root: str) -> list[str]:
    listing = command(
        "git", "ls-tree", "-r", "--name-only", "-z", commit, "--", test_root, cwd=clone
    )
    if listing.returncode:
        raise RuntimeError(listing.stderr.strip() or "cannot enumerate committed tests")
    return sorted(
        path
        for path in listing.stdout.split("\0")
        if path and Path(path).name.startswith("test_") and Path(path).suffix == ".py"
    )


def run_clean_clone(
    source: Path,
    commit: str,
    destination: Path,
    test_root: str = "workstreams/po03",
) -> tuple[int, dict[str, object]]:
    if not source.exists():
        return 2, {"error": "source repository is absent"}
    if not OBJECT_ID.fullmatch(commit):
        return 2, {"error": "commit must be a full lowercase Git object ID"}
    if destination.exists():
        return 2, {"error": "destination must not already exist"}
    if not destination.parent.is_dir():
        return 2, {"error": "destination parent is absent"}

    clone = command("git", "clone", "--no-checkout", "--quiet", str(source), str(destination), cwd=source)
    if clone.returncode:
        return 2, {"error": "clone failed", "stderr": clone.stderr}
    checkout = command("git", "checkout", "--detach", "--quiet", commit, cwd=destination)
    if checkout.returncode:
        return 2, {"error": "immutable commit checkout failed", "stderr": checkout.stderr}
    observed = command("git", "rev-parse", "HEAD", cwd=destination)
    if observed.returncode or observed.stdout.strip() != commit:
        return 2, {"error": "checked-out object does not equal requested commit"}
    initial_status = command("git", "status", "--porcelain=v1", "--untracked-files=all", cwd=destination)
    if initial_status.returncode or initial_status.stdout:
        return 3, {"error": "clone is dirty before test execution", "status": initial_status.stdout}
    if not (destination / test_root).is_dir():
        return 2, {"error": f"required test root is absent: {test_root}"}

    try:
        tests = committed_tests(destination, commit, test_root)
    except RuntimeError as exc:
        return 2, {"error": str(exc)}
    if not tests:
        return 2, {"error": f"no committed test_*.py files under {test_root}"}

    runtime_directory = destination.parent / f".{destination.name}-runtime"
    if runtime_directory.exists():
        return 2, {"error": "runtime directory already exists"}
    runtime_directory.mkdir()
    results: list[dict[str, object]] = []
    try:
        environment = clean_environment(runtime_directory)
        for relative in tests:
            outcome = command(
                sys.executable,
                "-I",
                "-B",
                relative,
                cwd=destination,
                env=environment,
            )
            results.append(
                {
                    "path": relative,
                    "returncode": outcome.returncode,
                    "stdout": outcome.stdout,
                    "stderr": outcome.stderr,
                }
            )
    finally:
        shutil.rmtree(runtime_directory)

    final_status = command("git", "status", "--porcelain=v1", "--untracked-files=all", cwd=destination)
    dirty = final_status.returncode != 0 or bool(final_status.stdout)
    failed = [item["path"] for item in results if item["returncode"] != 0]
    summary: dict[str, object] = {
        "commit": commit,
        "test_count": len(results),
        "failed_tests": failed,
        "dirty_after_run": dirty,
        "results": results,
    }
    if dirty:
        summary["working_tree_status"] = final_status.stdout
    return (0 if not failed and not dirty else 3), summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--test-root", default="workstreams/po03")
    args = parser.parse_args(argv)
    code, summary = run_clean_clone(
        args.source.resolve(), args.commit, args.destination.resolve(), args.test_root
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
