#!/usr/bin/env python3
"""Settle, safely and repeatably, whether Cursor actually fires this
repository's project hooks in the runtime you are standing in.

Never registered in hooks.json, so it never runs on a turn. Run it by hand.

Why this exists
---------------
Script correctness and hook firing are different claims. `verify_hooks.py`
proves the first across 69 cases by feeding the scripts synthetic payloads. It
cannot prove the second, because nothing in it asks Cursor to do anything.

APPLY.md proposed proving the second with:

    git checkout -b throwaway/hook-firing-probe
    git push origin main

That test is unsafe by construction. It uses a destructive command to check
whether the thing that would stop it exists, so the branch where the answer is
"no, hooks are not firing" is exactly the branch where the push lands on main.
A probe for a safety net must not be the thing the net was installed to catch.

This probe inverts that. Every command it asks you to run is inert whether or
not a hook intercepts it, and the guard's own audit log is used as the witness.

Design
------
The guard writes an append-only audit line for every decision it reaches,
including `allow`. So a benign `git status` is a sufficient witness: if the
hook fires, a line appears; if it does not, nothing does. No refusal has to be
provoked to get a positive signal.

Two probe commands are offered for the deny path, one per alternation in the
hooks.json matcher (`git|gh `), and both are chosen to be no-ops:

  git rebase --abort   HISTORY-REWRITE; errors harmlessly with no rebase running
  gh workflow list     ISSUE-WRITE; a read-only listing on this route

Before drawing any conclusion the probe establishes a control by running the
guard by hand against those same commands. Without the control, "the command
was not refused" is ambiguous between "the hook did not fire" and "the command
never matched a rule". With it, non-refusal means non-firing.

Usage
-----
    python3 .cursor/hooks/probe_hook_firing.py --arm     # control + snapshot
    ... run the printed commands through the agent's shell tool ...
    python3 .cursor/hooks/probe_hook_firing.py --check   # verdict

Exit codes: 0 armed, or checked and hooks are firing. 1 checked and hooks are
not firing. 2 the probe could not establish its control and reached no verdict.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

GUARD = Path(".cursor/hooks/guard_write_scope.py")
CONFIG = Path(".cursor/write-scope.json")
STATE = Path(".cursor/.run/hook-firing-probe.json")

BENIGN_PROBE = "git status --porcelain"
DENY_PROBES = [
    ("git rebase --abort", "HISTORY-REWRITE"),
    ("gh workflow list", "ISSUE-WRITE"),
]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def audit_path() -> Path:
    try:
        return Path(json.loads(CONFIG.read_text(encoding="utf-8"))["audit_log"])
    except (OSError, json.JSONDecodeError, KeyError):
        return Path(".cursor/.run/write-scope-audit.jsonl")


def audit_state(path: Path) -> dict:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"exists": False, "lines": 0}
    return {"exists": True, "lines": len(lines)}


def ask_guard(command: str) -> str:
    """Run the guard by hand exactly as the platform would, return its verdict."""
    payload = json.dumps({"command": command, "cwd": str(Path.cwd())})
    try:
        r = subprocess.run([sys.executable, str(GUARD)], input=payload,
                           capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout).get("permission", "?")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return "?"


def project_root_note() -> list:
    """Where Cursor looks for project hooks, and whether you are standing there.

    Project hooks load from <project-root>/.cursor/hooks.json. In a cloud agent
    the project root is the checkout the run booted with, not whatever worktree
    a lane later created. A lane working in a `git worktree` under /tmp has its
    hooks in a directory Cursor never reads.
    """
    notes = []
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=10)
        top = r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        top = ""
    if top:
        notes.append(f"working tree root : {top}")
        notes.append(f"hooks.json present: {Path(top, '.cursor/hooks.json').exists()}")
        if not top.startswith("/workspace"):
            notes.append(
                "NOTE: this working tree is not /workspace. If the agent run booted "
                "with /workspace as its project root, Cursor reads project hooks from "
                "there and the hooks in this tree cannot fire, however correct they are."
            )
    return notes


def arm() -> int:
    if not GUARD.exists():
        print(f"cannot arm: {GUARD} is missing", file=sys.stderr)
        return 2

    print("Control — running the guard by hand against each probe command.")
    print("A probe is only meaningful if the guard refuses these when asked directly.\n")

    control = {}
    for command, rule in DENY_PROBES:
        verdict = ask_guard(command)
        control[command] = verdict
        print(f"  {verdict:5}  {command}   (expects deny, rule {rule})")

    benign = ask_guard(BENIGN_PROBE)
    control[BENIGN_PROBE] = benign
    print(f"  {benign:5}  {BENIGN_PROBE}   (expects allow, and an audited line)\n")

    usable = [c for c, (v) in control.items() if c != BENIGN_PROBE and v == "deny"]
    if not usable or benign != "allow":
        print("Control failed: the guard did not behave as expected when run by hand.")
        print("Fix that first — until it holds, a non-refusal proves nothing.", file=sys.stderr)
        return 2

    for line in project_root_note():
        print(f"  {line}")

    apath = audit_path()
    state = {"armed_at": now(), "audit_log": str(apath),
             "before": audit_state(apath), "control": control}
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"cannot write probe state: {exc}", file=sys.stderr)
        return 2

    print(f"\nArmed at {state['armed_at']}. Audit log {apath} currently has "
          f"{state['before']['lines']} line(s).\n")
    print("Now run these through the agent's own shell tool, one call each.")
    print("Do NOT run them from inside this script — the point is to make Cursor")
    print("execute a tool call, which is the only thing that can trigger a hook.\n")
    for index, command in enumerate([BENIGN_PROBE] + [c for c, _ in DENY_PROBES], start=1):
        print(f"  {index}.  {command}")
    print("\nEvery one of these is inert. None writes a ref, opens a pull request,")
    print("or contacts anything that changes state. If a hook is firing, command 1")
    print("adds an audited line and the others are refused before they execute.\n")
    print("Then: python3 .cursor/hooks/probe_hook_firing.py --check")
    return 0


def check() -> int:
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("not armed: run --arm first", file=sys.stderr)
        return 2

    apath = Path(state.get("audit_log", ""))
    before = state.get("before", {})
    after = audit_state(apath)
    added = after.get("lines", 0) - before.get("lines", 0)

    print(f"armed at   : {state.get('armed_at')}")
    print(f"checked at : {now()}")
    print(f"audit log  : {apath}")
    print(f"lines      : {before.get('lines', 0)} -> {after.get('lines', 0)}  (added {added})\n")

    if added > 0:
        print("VERDICT: project hooks ARE firing in this runtime.")
        print("The guard recorded a decision for a command it did not run by hand,")
        print("so Cursor invoked it. The refusals it declares are real refusals.")
        return 0

    print("VERDICT: project hooks are NOT firing in this runtime.")
    print("The guard refuses these commands when run by hand — that control passed")
    print("at arm time — and recorded nothing when the same commands went through")
    print("the agent's shell tool. So the scripts are correct and unreached.\n")
    for line in project_root_note():
        print(f"  {line}")
    print("\nDo not treat any boundary in write-scope.json as enforced here.")
    print("Until this probe returns the other verdict, the guard is documentation.")
    return 1


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--arm"
    if mode == "--arm":
        return arm()
    if mode == "--check":
        return check()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
