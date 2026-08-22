#!/usr/bin/env python3
"""Execute one portable Python route without invoking a shell."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping


class UnsupportedCommand(ValueError):
    pass


SHELL_TOKENS = {"|", "||", "&&", ";", ">", ">>", "<", "<<", "&"}
ALLOWED_FLAGS = {"--repo", "--manifest"}


def prepare_argv(command: str, repo: Path) -> list[str]:
    try:
        raw = shlex.split(command, posix=True)
    except ValueError as error:
        raise UnsupportedCommand(f"UNPARSEABLE_COMMAND:{error}") from error
    if not raw or raw[0] not in {"python3", "python"}:
        raise UnsupportedCommand("UNSUPPORTED_EXECUTABLE")
    if len(raw) < 2 or raw[1].startswith("-"):
        raise UnsupportedCommand("PYTHON_SCRIPT_REQUIRED")
    if any(
        token in SHELL_TOKENS or "`" in token or "$(" in token or "\n" in token
        for token in raw
    ):
        raise UnsupportedCommand("SHELL_SYNTAX_FORBIDDEN")
    script = (repo / raw[1]).resolve()
    try:
        script.relative_to(repo.resolve())
    except ValueError as error:
        raise UnsupportedCommand("SCRIPT_ESCAPES_REPOSITORY") from error
    if script.name != "successor_reproducer.py" or not script.is_file():
        raise UnsupportedCommand("UNSUPPORTED_PYTHON_SCRIPT")
    trailing = raw[2:]
    if len(trailing) % 2:
        raise UnsupportedCommand("FLAG_VALUE_PAIRS_REQUIRED")
    for index in range(0, len(trailing), 2):
        if trailing[index] not in ALLOWED_FLAGS:
            raise UnsupportedCommand(f"UNSUPPORTED_FLAG:{trailing[index]}")
    return [sys.executable, str(script), *trailing]


def execute(
    command: str,
    repo: Path,
    *,
    environment: Mapping[str, str] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    try:
        argv = prepare_argv(command, repo)
    except UnsupportedCommand as error:
        return {
            "disposition": "NOT_SUPPORTED",
            "executed": False,
            "shell": False,
            "defects": [str(error)],
        }
    completed = subprocess.run(
        argv,
        cwd=repo,
        env=dict(environment) if environment is not None else dict(os.environ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )
    return {
        "argv": argv,
        "shell": False,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "executed": True,
        "defects": [] if completed.returncode == 0 else ["PORTABLE_COMMAND_FAILED"],
        "disposition": "PASS" if completed.returncode == 0 else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = execute(manifest.get("reproduction_command", ""), args.repo)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["disposition"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
