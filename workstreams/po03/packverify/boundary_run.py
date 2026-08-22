#!/usr/bin/env python3
"""Execute committed pack entry points across a real process boundary."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Mapping, Sequence

if not __package__:  # Support ``python3 -I path/to/boundary_run.py``.
    sys.path.insert(0, str(Path(__file__).resolve().parent))

if __package__:
    from .git_tree import GitTree
else:  # pragma: no cover - direct command entry point
    from git_tree import GitTree


def sanitized_environment(workspace: Path) -> dict[str, str]:
    home = workspace / "home"
    temp = workspace / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)
    return {
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(temp),
    }


def run_process(
    command: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: int = 120,
) -> dict[str, object]:
    try:
        process = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(environment),
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
        )
        return {
            "command": list(command),
            "exit_code": process.returncode,
            "stdout": process.stdout.decode("utf-8", "replace"),
            "stderr": process.stderr.decode("utf-8", "replace"),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": list(command),
            "exit_code": None,
            "stdout": (exc.stdout or b"").decode("utf-8", "replace"),
            "stderr": (exc.stderr or b"").decode("utf-8", "replace"),
            "timed_out": True,
        }


def execute(
    tree: GitTree,
    root: str,
    scratch_base: Path,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Export committed bytes and run the aggregate entry point once."""
    scratch_base.mkdir(parents=True, exist_ok=True)
    workspace = scratch_base / f"boundary-{uuid.uuid4().hex}"
    checkout = workspace / "checkout"
    workspace.mkdir(parents=False, exist_ok=False)
    try:
        pack_root = tree.export(root, checkout)
        entrypoint = pack_root / "run_all_tests.sh"
        if not entrypoint.is_file():
            return {
                "commit_sha": tree.commit_sha,
                "root": root,
                "outcome": "NOT_YET",
                "reason": "claimed aggregate entry point run_all_tests.sh is absent",
                "clean_export": True,
                "process": None,
            }
        environment = sanitized_environment(workspace)
        result = run_process(
            ["bash", "run_all_tests.sh"],
            cwd=pack_root,
            environment=environment,
            timeout_seconds=timeout_seconds,
        )
        return {
            "commit_sha": tree.commit_sha,
            "root": root,
            "entrypoint": f"{root}/run_all_tests.sh",
            "clean_export": True,
            "environment_policy": {
                "inherited": ["PATH"],
                "sanitized": sorted(key for key in environment if key != "PATH"),
                "python_isolated_from_user_site": True,
                "temporary_directory_inside_owned_scratch": True,
            },
            "process": result,
            "outcome": (
                "PASS"
                if result["exit_code"] == 0 and not result["timed_out"]
                else "FAIL"
            ),
        }
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=".")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = execute(
        GitTree(Path(args.repository), args.commit),
        args.root,
        Path(args.scratch),
        timeout_seconds=args.timeout,
    )
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if result["outcome"] in {"PASS", "NOT_YET"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
