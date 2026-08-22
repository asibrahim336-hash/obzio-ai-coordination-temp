#!/usr/bin/env python3
"""Compare warm-working-tree behavior with a pristine export of the same commit."""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path


def execute(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


def observation(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def compare(repo: Path, commit: str, scratch: Path, argv: list[str]) -> tuple[int, dict[str, object]]:
    if not (repo / ".git").exists():
        return 2, {"error": "repository is absent or is not a standalone Git checkout"}
    if scratch.exists() or not scratch.parent.is_dir():
        return 2, {"error": "scratch path must be absent and its parent must exist"}
    if not argv:
        return 2, {"error": "a command is required"}
    head = execute(["git", "rev-parse", "HEAD"], repo)
    if head.returncode or head.stdout.strip() != commit:
        return 2, {"error": "working tree HEAD does not equal requested commit"}
    exists = execute(["git", "cat-file", "-e", f"{commit}^{{commit}}"], repo)
    if exists.returncode:
        return 2, {"error": "requested commit is absent"}

    warm = execute(argv, repo)
    archive = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=repo,
        capture_output=True,
    )
    if archive.returncode:
        return 2, {"error": "cannot export requested commit", "stderr": archive.stderr.decode()}
    scratch.mkdir()
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as bundle:
            bundle.extractall(scratch, filter="data")
        pristine = execute(argv, scratch)
        warm_observation = observation(warm)
        pristine_observation = observation(pristine)
        divergence = warm_observation != pristine_observation
        report: dict[str, object] = {
            "commit": commit,
            "command": argv,
            "hidden_state_dependence": divergence,
            "warm": warm_observation,
            "pristine": pristine_observation,
        }
        return (1 if divergence else 0), report
    finally:
        shutil.rmtree(scratch)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    code, report = compare(
        args.repo.resolve(), args.commit, args.scratch.resolve(), command
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
