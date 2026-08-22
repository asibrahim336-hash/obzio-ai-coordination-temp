#!/usr/bin/env python3
"""beforeShellExecution guard for the Obzio control plane.

Refuses, before execution, the four shell actions that have repeatedly damaged
this estate: committing or pushing onto a protected branch, opening or moving a
pull request from inside a lane, rewriting history that immutable-SHA custody
depends on, and committing while the repository's own currentness check fails.

Contract (https://cursor.com/docs/hooks.md):
  stdin   JSON with at least {"command": str, "cwd": str}
  stdout  JSON {"continue": bool, "permission": "allow"|"deny"|"ask",
                "user_message": str, "agent_message": str}
  exit 0  use the JSON output
  exit 2  block, equivalent to permission "deny"
  other   the hook failed and the action proceeds (fail-open)

Fail-open is the platform default for an unexpected exit code, so every
unexpected condition here is caught and turned into an explicit allow. A guard
that crashes must not silently become a guard that blocks everything.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CONFIG_PATH = Path(".cursor/write-scope.json")


def emit(permission: str, user_message: str = "", agent_message: str = "") -> None:
    out = {"continue": True, "permission": permission}
    if user_message:
        out["user_message"] = user_message
    if agent_message:
        out["agent_message"] = agent_message
    print(json.dumps(out))
    sys.exit(0)


def allow() -> None:
    emit("allow")


def audit(config: dict, record: dict) -> None:
    path = config.get("audit_log")
    if not path:
        return
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        record["at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass


def current_branch(cwd: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def is_protected(branch: str, globs: list) -> bool:
    return any(fnmatch.fnmatch(branch, g) for g in globs)


def push_targets(command: str, cwd: Path) -> list:
    """Branch names a `git push` would update, best effort.

    Handles `git push origin BRANCH`, `git push origin SRC:DST`, `git push -u
    origin BRANCH` and the bare `git push`, which targets the current branch.
    An unparseable push is treated as targeting the current branch, which is
    the conservative reading.
    """
    try:
        args = shlex.split(command)
    except ValueError:
        return [current_branch(cwd)]

    if "push" not in args:
        return []
    tail = args[args.index("push") + 1:]
    positionals = [a for a in tail if not a.startswith("-")]
    # First positional after `push` is the remote; the rest are refspecs.
    refspecs = positionals[1:] if len(positionals) > 1 else []
    if not refspecs:
        return [current_branch(cwd)]

    out = []
    for spec in refspecs:
        dst = spec.split(":", 1)[1] if ":" in spec else spec
        out.append(dst.replace("refs/heads/", "").lstrip("+"))
    return out


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        allow()

    command = (payload.get("command") or "").strip()
    if not command:
        allow()

    cwd = Path(payload.get("cwd") or os.getcwd())

    try:
        config = json.loads((cwd / CONFIG_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # No configuration means no declared boundary. Do not invent one.
        allow()

    branch_globs = config.get("protected_branch_globs", [])

    # 1. Named command refusals.
    for rule in config.get("refused_commands", []):
        try:
            if re.search(rule["pattern"], command):
                audit(config, {"decision": "deny", "rule": rule["id"], "command": command})
                emit(
                    "deny",
                    user_message=f"Refused by write-scope guard ({rule['id']}).",
                    agent_message=(
                        f"The command was refused before execution by rule {rule['id']} in "
                        f".cursor/write-scope.json.\n\nCommand: {command}\n\nReason: {rule['reason']}\n\n"
                        "This is a declared boundary, not a transient failure. Do not retry it or "
                        "work around it. If the boundary is genuinely wrong for this task, say so "
                        "and stop; changing .cursor/write-scope.json is an explicit decision, not a "
                        "step inside a task."
                    ),
                )
        except re.error:
            continue

    # 2. Pushes onto a protected branch.
    if re.search(r"\bgit\s+push\b", command):
        for target in push_targets(command, cwd):
            if target and is_protected(target, branch_globs):
                audit(config, {"decision": "deny", "rule": "PROTECTED-BRANCH-PUSH",
                               "branch": target, "command": command})
                emit(
                    "deny",
                    user_message=f"Refused: push to protected branch {target}.",
                    agent_message=(
                        f"Refused before execution: this command would push to '{target}', which "
                        f"matches a protected branch pattern in .cursor/write-scope.json.\n\n"
                        f"Command: {command}\n\n"
                        "Protected branches are shared projection surfaces with a single declared "
                        "writer. Push to your own isolated lane branch instead and let the "
                        "reconciling writer integrate it. Do not retry against the protected branch."
                    ),
                )

    # 3. Commits made while HEAD is a protected branch.
    if re.search(r"\bgit\s+commit\b", command):
        branch = current_branch(cwd)
        if branch and is_protected(branch, branch_globs):
            audit(config, {"decision": "deny", "rule": "PROTECTED-BRANCH-COMMIT",
                           "branch": branch, "command": command})
            emit(
                "deny",
                user_message=f"Refused: commit on protected branch {branch}.",
                agent_message=(
                    f"Refused before execution: HEAD is '{branch}', which matches a protected "
                    "branch pattern in .cursor/write-scope.json.\n\n"
                    "Create an isolated branch for this work first, then commit there. Committing "
                    "on a protected branch is how two writers silently produce competing claims "
                    "about what is current."
                ),
            )

        # 4. Currentness must hold before a commit is allowed to exist.
        if config.get("require_currentness_check_before_commit"):
            cmd = config.get("currentness_command") or []
            if cmd:
                try:
                    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
                except (OSError, subprocess.SubprocessError):
                    allow()  # cannot check, so do not block
                if r.returncode != 0:
                    detail = (r.stdout + r.stderr).strip()[-1200:]
                    audit(config, {"decision": "deny", "rule": "CURRENTNESS-FAILED",
                                   "command": command, "check_exit": r.returncode})
                    emit(
                        "deny",
                        user_message="Refused: the operator currentness check is failing.",
                        agent_message=(
                            "Refused before execution: "
                            f"`{' '.join(cmd)}` exited {r.returncode}, so the repository's own "
                            "currentness contract does not hold at this working tree.\n\n"
                            f"Check output:\n{detail}\n\n"
                            "AGENTS.md instruction 10 requires this check to pass before commit. "
                            "Repair the currentness break first. Committing over a failing "
                            "currentness check is what produces two files that each claim to be "
                            "current."
                        ),
                    )

    audit(config, {"decision": "allow", "command": command})
    allow()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - a guard that crashes must never block everything
        print(json.dumps({"continue": True, "permission": "allow"}))
        sys.exit(0)
