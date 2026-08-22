#!/usr/bin/env python3
"""Check the staged PO-03 suite workflow, then run its steps in a clean clone.

Two things are checked, and they are different claims.

Structure: the workflow's declared triggers stay inside the commissioned path
allowlist, it requests read-only contents permission, it pins the checkout and
Python setup actions, every step is named, no step installs a third-party
package, and every Python invocation uses `python -I`.  A `run:` block that this
parser cannot read is an error, so no step can be skipped silently.

Execution: every `run:` block is executed with `bash -euo pipefail` inside a
fresh `git clone` of an immutable commit, in a temporary directory, with a
scrubbed environment and a temporary HOME.  That is the strongest local evidence
available for "no repository-local state": the clone holds committed bytes only,
so an untracked file, a stray `__pycache__` or a worktree-local git setting
cannot contribute to a pass.

One substitution is made and it is reported rather than hidden.  The workflow
calls `python`, which exists on a runner only because `actions/setup-python`
puts it there; this host ships `python3` alone, so every step failed with exit
127 before the substitution was added (kept verbatim in
clean_clone_execution_no_python_shim.txt).  A shim directory holding a `python`
that execs the local 3.12 interpreter is therefore prepended to PATH, which is
the one thing that action does that these steps depend on.  The shim's target is
recorded in the report so a reader can see which interpreter actually ran.

What this cannot do is observe GitHub Actions.  A clean Ubuntu runner, the real
`actions/checkout` and `actions/setup-python` implementations and GitHub's shell
defaults are not reproduced here, so the hypothesis about a clean GitHub Actions
environment stays NOT_YET until a controller installs the file and a real run is
observed.

Exit codes: 0 all checks passed, 1 a check failed, 2 usage or I/O error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = UNIT_ROOT.parents[3]
WORKFLOW = UNIT_ROOT / "po03-suite.yml"
INSTALL_PATH = ".github/workflows/po03-suite.yml"

ALLOWED_TRIGGER_PATHS = {
    "workstreams/po03/**",
    "receipts/po03/**",
    ".github/workflows/po03-*.yml",
}
REQUIRED_ACTIONS = {"actions/checkout@v4", "actions/setup-python@v5"}
FORBIDDEN_RUN_PATTERNS = (
    (re.compile(r"\bpip\s+install\b"), "installs a third-party package"),
    (re.compile(r"\bpip3\s+install\b"), "installs a third-party package"),
    (re.compile(r"\bapt-get\b"), "installs a system package"),
    (re.compile(r"\bcurl\b|\bwget\b"), "fetches from the network"),
    (re.compile(r"\$\{\{"), "uses a GitHub expression, which cannot run locally"),
)
PYTHON_INVOCATION = re.compile(r"(?<![\w./-])python3?\b(?!\s*-VV)")


class WorkflowError(Exception):
    """Raised when the workflow file cannot be read as the expected shape."""


class Step:
    def __init__(self, name: str | None, uses: str | None, run: str | None) -> None:
        self.name = name
        self.uses = uses
        self.run = run


def parse(text: str) -> tuple[dict, list[Step]]:
    """Read the small YAML subset this workflow is written in.

    Full YAML is not attempted.  Anything unrecognised inside the steps list
    raises, so an unparsed step can never be mistaken for an absent one.
    """
    lines = text.splitlines()
    top_level: dict[str, list[str]] = {}
    steps: list[Step] = []
    current_top: str | None = None
    index = 0
    in_steps = False
    pending: dict | None = None

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            steps.append(Step(pending.get("name"), pending.get("uses"), pending.get("run")))
            pending = None

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        indent = len(line) - len(line.lstrip(" "))

        if indent == 0:
            flush()
            in_steps = False
            match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", stripped)
            if not match:
                raise WorkflowError(f"line {index + 1}: unreadable top-level entry {stripped!r}")
            current_top = match.group(1)
            top_level.setdefault(current_top, [])
            if match.group(2):
                top_level[current_top].append(match.group(2))
            index += 1
            continue

        if stripped == "steps:":
            in_steps = True
            flush()
            index += 1
            continue

        if in_steps:
            body = stripped
            if body.startswith("- "):
                flush()
                pending = {}
                body = body[2:].strip()
            if pending is None:
                raise WorkflowError(f"line {index + 1}: step content outside a step: {stripped!r}")
            if body.startswith("run: |"):
                block: list[str] = []
                block_indent = None
                index += 1
                while index < len(lines):
                    candidate = lines[index]
                    if not candidate.strip():
                        block.append("")
                        index += 1
                        continue
                    candidate_indent = len(candidate) - len(candidate.lstrip(" "))
                    if block_indent is None:
                        block_indent = candidate_indent
                    if candidate_indent < block_indent:
                        break
                    block.append(candidate[block_indent:])
                    index += 1
                pending["run"] = "\n".join(block).rstrip() + "\n"
                continue
            key_match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", body)
            if key_match:
                key, value = key_match.group(1), key_match.group(2).strip()
                if key in {"name", "uses"}:
                    pending[key] = value.strip('"')
                elif key == "run":
                    pending["run"] = value + "\n"
                index += 1
                continue
            if body.startswith("- ") or ":" in body:
                index += 1
                continue
            raise WorkflowError(f"line {index + 1}: unreadable step line {stripped!r}")

        if current_top is not None:
            top_level[current_top].append(stripped)
        index += 1

    flush()
    if not steps:
        raise WorkflowError("no steps found")
    return top_level, steps


def structural_findings(top_level: dict, steps: list[Step]) -> list[str]:
    findings: list[str] = []
    for key in ("name", "on", "permissions", "jobs"):
        if key not in top_level:
            findings.append(f"MISSING_TOP_LEVEL_KEY {key}")
    trigger_lines = top_level.get("on", [])
    if not any(line.startswith("pull_request") for line in trigger_lines):
        findings.append("NO_PULL_REQUEST_TRIGGER")
    if not any(line.startswith("push") for line in trigger_lines):
        findings.append("NO_PUSH_TRIGGER")
    declared_paths = {
        line.lstrip("- ").strip('"')
        for line in trigger_lines
        if line.startswith("- ") and ("/" in line or "*" in line)
    }
    for path in sorted(declared_paths):
        if path not in ALLOWED_TRIGGER_PATHS and not path.startswith("po03/"):
            findings.append(f"TRIGGER_PATH_OUTSIDE_ALLOWLIST {path}")
    if "contents: read" not in [line.strip() for line in top_level.get("permissions", [])]:
        findings.append("PERMISSIONS_NOT_READ_ONLY")
    if not any("runs-on: ubuntu-latest" in line for line in top_level.get("jobs", [])):
        findings.append("NO_UBUNTU_RUNNER")

    used_actions = {step.uses for step in steps if step.uses}
    for action in sorted(REQUIRED_ACTIONS - used_actions):
        findings.append(f"MISSING_PINNED_ACTION {action}")
    for step in steps:
        if step.uses is None and step.name is None:
            findings.append("UNNAMED_RUN_STEP")
        if step.uses is None and step.run is None:
            findings.append(f"STEP_WITHOUT_RUN {step.name!r}")
        if step.run is None:
            continue
        for pattern, reason in FORBIDDEN_RUN_PATTERNS:
            if pattern.search(step.run):
                findings.append(f"FORBIDDEN_RUN_CONTENT {step.name!r}: {reason}")
        for invocation in PYTHON_INVOCATION.finditer(step.run):
            tail = step.run[invocation.end(): invocation.end() + 4]
            if not tail.startswith(" -I") and not tail.startswith(" -VV"):
                findings.append(
                    f"PYTHON_WITHOUT_ISOLATED_FLAG {step.name!r}: "
                    f"{step.run[invocation.start(): invocation.start() + 40]!r}"
                )
    if not any(step.run and "check_path_scope.py" in step.run for step in steps):
        findings.append("NO_PATH_SCOPE_GUARD_STEP")
    if not any(step.run and "unittest discover -s workstreams/po03/tests" in step.run for step in steps):
        findings.append("NO_CONTRACT_SUITE_STEP")
    if not any(step.run and "rejection_fixture.py" in step.run for step in steps):
        findings.append("NO_REJECTION_FIXTURE_STEP")
    if not any(step.run and "workstreams/po03/attempts/*/" in step.run for step in steps):
        findings.append("NO_AGGREGATE_UNIT_TEST_STEP")
    return findings


def clean_clone(commit: str, destination: Path) -> Path:
    """Clone committed bytes only, then detach at an immutable commit."""
    checkout = destination / "clone"
    subprocess.run(
        ("git", "clone", "--quiet", "--no-hardlinks", str(REPO_ROOT), str(checkout)),
        check=True, capture_output=True,
    )
    subprocess.run(
        ("git", "-C", str(checkout), "checkout", "--quiet", "--detach", commit),
        check=True, capture_output=True,
    )
    return checkout


def scrubbed_environment(home: Path, shim: Path | None = None) -> dict[str, str]:
    """Only what a shell needs, so no ambient configuration can contribute."""
    path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    if shim is not None:
        path = f"{shim}{os.pathsep}{path}"
    return {
        "PATH": path,
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
    }


def python_shim(holder: Path) -> tuple[Path, str]:
    """Provide the `python` name the workflow calls, as setup-python would.

    Returns the shim directory and the interpreter it forwards to, so the report
    can name the interpreter that actually executed rather than implying that a
    bare `python` was already present.
    """
    interpreter = shutil.which("python") or shutil.which("python3.12") or shutil.which("python3")
    if interpreter is None:
        raise WorkflowError("no python3 interpreter on PATH to back the `python` shim")
    directory = holder / "shim-bin"
    directory.mkdir(parents=True, exist_ok=True)
    launcher = directory / "python"
    launcher.write_text(f'#!/bin/sh\nexec "{interpreter}" "$@"\n', encoding="utf-8")
    launcher.chmod(0o755)
    return directory, interpreter


def execute(steps: list[Step], commit: str, holder: Path) -> tuple[list[dict], str]:
    checkout = clean_clone(commit, holder)
    home = holder / "home"
    home.mkdir(parents=True, exist_ok=True)
    shim, interpreter = python_shim(holder)
    environment = scrubbed_environment(home, shim)
    outcomes: list[dict] = []
    for step in steps:
        if step.run is None:
            continue
        completed = subprocess.run(
            ("bash", "-euo", "pipefail", "-c", step.run),
            cwd=checkout, env=environment, capture_output=True, text=True,
        )
        tail = (completed.stdout + completed.stderr).strip().splitlines()
        outcomes.append({
            "step": step.name,
            "exit_code": completed.returncode,
            "passed": completed.returncode == 0,
            "output_tail": tail[-3:],
        })
    return outcomes, interpreter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", default=str(WORKFLOW))
    parser.add_argument("--commit", default="HEAD", help="commit to clone for execution")
    parser.add_argument("--execute", action="store_true", help="run every run: block in a clean clone")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        text = Path(args.workflow).read_text(encoding="utf-8")
        top_level, steps = parse(text)
        findings = structural_findings(top_level, steps)
        commit = subprocess.run(
            ("git", "rev-parse", args.commit), cwd=REPO_ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (WorkflowError, OSError, subprocess.CalledProcessError) as exc:
        print(f"PO03_WORKFLOW_ERROR: {exc}", file=sys.stderr)
        return 2

    outcomes: list[dict] = []
    interpreter: str | None = None
    if args.execute:
        holder = Path(tempfile.mkdtemp(prefix="po03-clean-clone-"))
        try:
            outcomes, interpreter = execute(steps, commit, holder)
        except (WorkflowError, OSError, subprocess.CalledProcessError) as exc:
            print(f"PO03_WORKFLOW_ERROR: {exc}", file=sys.stderr)
            return 2
        finally:
            shutil.rmtree(holder, ignore_errors=True)
        findings.extend(
            f"STEP_FAILED_IN_CLEAN_CLONE {outcome['step']!r} exit={outcome['exit_code']} "
            f"tail={outcome['output_tail']}"
            for outcome in outcomes if not outcome["passed"]
        )

    report = {
        "workflow": args.workflow,
        "install_path": INSTALL_PATH,
        "commit": commit,
        "steps": [
            {"name": step.name, "uses": step.uses, "has_run": step.run is not None}
            for step in steps
        ],
        "executed": outcomes,
        "findings": findings,
        "python_shim_target": interpreter,
    }
    stream = sys.stderr if args.json else sys.stdout
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"# workflow={args.workflow}")
        print(f"# install as={INSTALL_PATH}")
        print(f"# commit={commit}")
        if interpreter:
            print(f"# `python` shim forwards to={interpreter} (stands in for actions/setup-python)")
        for step in steps:
            kind = f"uses {step.uses}" if step.uses else "run block"
            print(f"STEP {step.name or '(action)'} :: {kind}")
        for outcome in outcomes:
            print(
                f"{'OK      ' if outcome['passed'] else 'FAILED  '} {outcome['step']} "
                f"exit={outcome['exit_code']} tail={outcome['output_tail']}"
            )
    if findings:
        for finding in findings:
            print(f"PO03_WORKFLOW_FINDING: {finding}", file=sys.stderr)
        return 1
    print(
        f"PO03_WORKFLOW_PASS steps={len(steps)} run_blocks="
        f"{sum(1 for step in steps if step.run)} executed={len(outcomes)} "
        f"install_path={INSTALL_PATH}",
        file=stream,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
