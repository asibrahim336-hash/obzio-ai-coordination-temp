#!/usr/bin/env python3
"""Run a repository component with empty HOME and a fixed minimal environment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping


def sanitized_environment(declared: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = {
        "HOME": "",
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if declared:
        for key, value in declared.items():
            if key.startswith("PO03_DECLARED_"):
                environment[key] = value
    return environment


def run_isolated(
    repo: Path,
    script_relative: str,
    arguments: Iterable[str],
    *,
    ambient: Mapping[str, str] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    root = repo.resolve()
    script = (root / script_relative).resolve()
    try:
        script.relative_to(root)
    except ValueError:
        return {"disposition": "FAIL", "defects": ["SCRIPT_ESCAPES_REPOSITORY"]}
    if not script.is_file():
        return {"disposition": "FAIL", "defects": ["SCRIPT_UNAVAILABLE"]}
    environment = sanitized_environment(ambient)
    completed = subprocess.run(
        [sys.executable, "-I", str(script), *list(arguments)],
        cwd=root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )
    return {
        "argv_prefix": [sys.executable, "-I", script_relative],
        "environment_keys": sorted(environment),
        "home": environment["HOME"],
        "ambient_keys_inherited": [],
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "defects": [] if completed.returncode == 0 else ["ISOLATED_EXECUTION_FAILED"],
        "disposition": "PASS" if completed.returncode == 0 else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--script", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    report = run_isolated(
        args.repo,
        args.script,
        ["--repo", ".", "--manifest", args.manifest],
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["disposition"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
