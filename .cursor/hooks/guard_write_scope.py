#!/usr/bin/env python3
"""beforeShellExecution guard for the Obzio control plane.

## Re-founded 2026-08-23 on founder authority

Ahmed Sadek, standing amendment:

    "the write-scope guard now checks that a write was **declared and reasoned**,
    not that its target avoided a forbidden list."

    "Every surface in the Ahmed/Obzio-controlled estate is writable under my
    authority [...] No surface is off-limits because of a name on a list."

The `protected_branch_globs` refusals are therefore gone: this hook no longer
refuses a push or a commit because of the branch it names. What replaces them is
a declaration requirement — a write to a ref must be covered by a write
declaration that `write_admission.py` admits. `PROTECTED-BRANCH-PUSH` and
`PROTECTED-BRANCH-COMMIT` are retired; `UNDECLARED-WRITE` and
`WRITE-DECLARATION-REFUSED` take their place.

The declaration requirement is off by default (`require_write_declaration`).
A hook that starts refusing every push the moment it is installed is an
over-broad guard blocking legitimate work, which is the first risk the estate's
own apply notes name. Turning it on is an explicit operator act.

## What is kept, and why each is kept

Every remaining refusal is EARNED — it caught a real defect — and cites it:

- `DETACHED-HEAD` and `PUSH-REF-BEHIND-HEAD`: lanes sharing one checkout
  committed onto a detached HEAD, so `git push` published a stale ref, printed
  "Everything up-to-date" and exited 0. A lane trusting that exit code reports
  work it never published.
- `FORCE-PUSH` and `HISTORY-REWRITE`: both destroy the immutable-SHA custody the
  evidence ladder depends on. Note these are the mechanism half of the founder's
  own distinction — he removed an authority restriction, not the requirement
  that writes be recoverable.
- `CURRENTNESS-FAILED`: committing over a failing currentness check is how two
  files each come to claim they are current.
- `PR-WRITE` / `ISSUE-WRITE`: this route's credential is read-only for these,
  so the refusal makes an existing boundary explicit rather than inventing one.

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

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
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


def find_declaration(cwd: Path, config: dict, ref: str, operation: str) -> tuple[dict | None, str | None]:
    """Locate an active write declaration covering this ref and operation.

    Declarations are files, not memory, so the same artifact the guard consults
    is the one a reviewer reads afterwards. Absence of a declaration is the
    refusal; it is never treated as permission.
    """
    directory = config.get("write_declarations_dir")
    if not directory:
        return None, "no write_declarations_dir is configured"
    root = (cwd / directory) if not os.path.isabs(directory) else Path(directory)
    if not root.is_dir():
        return None, f"no declaration directory at {root}"

    candidates = []
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        target = payload.get("target") or {}
        if target.get("ref") != ref:
            continue
        if operation and target.get("operation") not in (operation, None):
            continue
        candidates.append((path, payload))
    if not candidates:
        return None, f"no declaration in {root} names ref {ref!r} for operation {operation!r}"
    return candidates[-1][1], None


def admit_declaration(cwd: Path, config: dict, declaration: dict) -> tuple[bool, str]:
    """Run the admission guard. A guard that cannot check must not pretend it did."""
    tool = config.get("write_admission_tool")
    if not tool:
        return False, "no write_admission_tool is configured, so the declaration cannot be admitted"
    tool_path = (cwd / tool) if not os.path.isabs(tool) else Path(tool)
    if not tool_path.exists():
        return False, f"write_admission_tool not found at {tool_path}"
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(declaration, handle)
            temp = handle.name
        result = subprocess.run(
            [sys.executable, str(tool_path), temp, "--repo", str(cwd)]
            + (["--no-rehearsal"] if not config.get("rehearse_reversal_in_hook", True) else []),
            cwd=cwd, capture_output=True, text=True, timeout=config.get("admission_timeout", 120),
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()[-1500:]
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"the admission guard could not be run: {exc}"
    finally:
        try:
            os.unlink(temp)
        except (OSError, NameError):
            pass


def _rev_parse(cwd: Path, rev: str) -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", rev],
                           cwd=cwd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _contains(cwd: Path, ref: str, sha: str) -> bool:
    """True when `ref` already contains `sha`, or when the answer is unknowable."""
    try:
        r = subprocess.run(["git", "merge-base", "--is-ancestor", sha, ref],
                           cwd=cwd, capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return True  # cannot tell, so do not block


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

    # 2. Detached HEAD, and pushes of a branch ref that is strictly behind HEAD.
    #
    # Added after reproducing the failure it prevents: sibling lanes sharing one
    # /workspace checkout committed onto a detached HEAD, so their branch refs
    # stayed at the base commit. `git push -u origin <lane-branch>` then pushed
    # the stale ref, printed "Everything up-to-date" and exited 0. A lane that
    # trusted that exit code would report work it had not published.
    #
    # The two halves are deliberately narrow. Commit is refused on a detached
    # HEAD because that is the root cause. Push is refused only when the target
    # ref sits on HEAD's own lineage and behind it, which is the exact signature
    # of the silent no-op; a divergent or unrelated branch is somebody pushing a
    # different branch on purpose and is allowed.
    if re.search(r"\bgit\s+commit\b", command) and config.get("refuse_detached_head", True):
        branch = current_branch(cwd)
        if branch == "HEAD":
            audit(config, {"decision": "deny", "rule": "DETACHED-HEAD", "command": command})
            emit(
                "deny",
                user_message="Refused: HEAD is detached.",
                agent_message=(
                    "Refused before execution: HEAD is detached, so this commit would advance no "
                    "branch and a later `git push <branch>` would silently push the branch's old "
                    "position and report 'Everything up-to-date' with exit 0.\n\n"
                    "If several agents share this checkout, take your own worktree first:\n"
                    "  git worktree add /tmp/<lane> -b <lane-branch> <base-sha>\n"
                    "and work there. Otherwise check out your branch before committing."
                ),
            )

    if re.search(r"\bgit\s+push\b", command) and config.get("refuse_stale_ref_push", True):
        head_sha = _rev_parse(cwd, "HEAD")
        for target in push_targets(command, cwd):
            ref_sha = _rev_parse(cwd, target)
            if not head_sha or not ref_sha or head_sha == ref_sha:
                continue
            strictly_behind = (
                _contains(cwd, "HEAD", ref_sha) and not _contains(cwd, target, head_sha)
            )
            if strictly_behind:
                audit(config, {"decision": "deny", "rule": "PUSH-REF-BEHIND-HEAD",
                               "branch": target, "command": command})
                emit(
                    "deny",
                    user_message=f"Refused: '{target}' is behind your current HEAD.",
                    agent_message=(
                        f"Refused before execution: branch '{target}' is at {ref_sha[:12]}, HEAD is "
                        f"at {head_sha[:12]}, and '{target}' sits on HEAD's own lineage behind it.\n\n"
                        "Pushing now would publish that older position, print 'Everything "
                        "up-to-date' and exit 0, so the exit code would not mean your work was "
                        "published. Move the ref onto the work you mean to publish first.\n\n"
                        "If your commits are on a detached HEAD, take your own worktree:\n"
                        "  git worktree add /tmp/<lane> <lane-branch>\n"
                        "then cherry-pick your commits onto the branch there and push from it."
                    ),
                )

    # 3. A push must be declared and reasoned. Its target is not consulted.
    #
    # This replaces the retired PROTECTED-BRANCH-PUSH refusal. The founder voided
    # the protected-surface category on 2026-08-23: "you need a reason and a
    # rollback", not permission. So the question asked here is whether a write
    # declaration covers this ref and survives admission, and the answer is the
    # same for `main` as for a scratch branch.
    if re.search(r"\bgit\s+push\b", command) and config.get("require_write_declaration"):
        for target in push_targets(command, cwd):
            if not target:
                continue
            declaration, why = find_declaration(cwd, config, target, "COMMIT_AND_PUSH")
            if declaration is None:
                audit(config, {"decision": "deny", "rule": "UNDECLARED-WRITE",
                               "branch": target, "command": command})
                emit(
                    "deny",
                    user_message=f"Refused: the push to {target} is undeclared.",
                    agent_message=(
                        f"Refused before execution: this command would push to '{target}' and no "
                        f"write declaration covers it ({why}).\n\n"
                        f"Command: {command}\n\n"
                        "This is not a protected branch — there is no such category. Every surface "
                        "in this estate is writable, and a write needs a reason and a rollback "
                        "rather than permission. Write a declaration carrying:\n"
                        "  target      — the ref and the paths this write may touch\n"
                        "  reason      — a code from the closed vocabulary, with its required "
                        "fields, whose statement names this target\n"
                        "  reversal    — the exact argv that undoes it, plus its custody artifact\n"
                        "  evidence    — for a write asserting a result, what supports it\n"
                        "  concurrency — the observed agent list showing the target is not in flight\n\n"
                        f"Put it in {config.get('write_declarations_dir')} and validate it with "
                        "write_admission.py before retrying."
                    ),
                )
            admitted, detail = admit_declaration(cwd, config, declaration)
            if not admitted:
                audit(config, {"decision": "deny", "rule": "WRITE-DECLARATION-REFUSED",
                               "branch": target, "command": command})
                emit(
                    "deny",
                    user_message=f"Refused: the declaration for {target} did not pass admission.",
                    agent_message=(
                        f"Refused before execution: a write declaration for '{target}' exists but "
                        f"did not pass admission.\n\n{detail}\n\n"
                        "Repair the failing gate rather than the declaration's wording. A refused "
                        "concurrency gate expires on its own when the run holding the target "
                        "finishes; a refused reversibility or evidence gate does not."
                    ),
                )

    # 4. Currentness must hold before a commit is allowed to exist.
    #
    # The PROTECTED-BRANCH-COMMIT refusal that stood here is retired with the
    # category. Committing on any branch is now ordinary; what is still checked
    # is that the repository's own contract holds when the commit is made.
    if re.search(r"\bgit\s+commit\b", command) and config.get("require_currentness_check_before_commit"):
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
