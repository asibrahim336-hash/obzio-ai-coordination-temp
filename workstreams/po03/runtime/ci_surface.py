"""Unit a3-u04: check the properties that make the clean-runner claim testable.

The claim is that the PO-03 suite reproduces on a runner with nothing of ours on
it. Two things falsify it -- a preinstalled dependency and a warm cache -- so
both are checked rather than asserted.

The checks live here rather than inside the workflow because a grep written into
a workflow scans the file that contains it: the pattern matches its own line and
the check fails unconditionally. That is not a hypothetical, it is why this
module exists. The patterns are data in ``ci-surface-rules.json`` for the same
reason the hermeticity rules are.

Run without arguments to check every workflow and the checkout's bytecode:

    python3 -I workstreams/po03/runtime/ci_surface.py
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parent
REPO_ROOT = RUNTIME_DIR.parents[2]
RULES_PATH = RUNTIME_DIR / "ci-surface-rules.json"

ACTION_PATTERN = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.MULTILINE)
RUNNER_PATTERN = re.compile(r"^\s*runs-on:\s*(\S+)", re.MULTILINE)


class Finding:
    __slots__ = ("rule", "path", "detail")

    def __init__(self, rule: str, path: str, detail: str) -> None:
        self.rule = rule
        self.path = path
        self.detail = detail

    def as_dict(self) -> dict:
        return {"rule": self.rule, "path": self.path, "detail": self.detail}

    def __str__(self) -> str:
        return f"{self.rule}: {self.path}: {self.detail}"


def load_rules(path: Path = RULES_PATH) -> dict:
    rules = json.loads(path.read_text(encoding="utf-8"))
    if rules.get("schema") != "po03-ci-surface-rules-v1":
        raise ValueError(f"unexpected rules schema: {rules.get('schema')!r}")
    return rules


def check_workflow(rules: dict, root: Path, relative: str) -> list[Finding]:
    path = root / relative
    if not path.is_file():
        return [Finding("MISSING_WORKFLOW", relative, "declared but not committed")]

    text = path.read_text(encoding="utf-8")
    findings: list[Finding] = []

    for required in rules["required_substrings"]:
        if required not in text:
            findings.append(Finding("MISSING_REQUIRED", relative, repr(required)))

    for name, rule in rules["forbidden_patterns"].items():
        pattern = re.compile(rule["regex"], re.MULTILINE)
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            findings.append(Finding(name, relative, f"line {line}: {match.group(0).strip()!r}"))

    allowed_actions = set(rules["allowed_actions"])
    for match in ACTION_PATTERN.finditer(text):
        if match.group(1) not in allowed_actions:
            findings.append(Finding("UNAPPROVED_ACTION", relative, match.group(1)))

    allowed_runners = set(rules["allowed_runners"])
    for match in RUNNER_PATTERN.finditer(text):
        if match.group(1) not in allowed_runners:
            findings.append(Finding("UNAPPROVED_RUNNER", relative, match.group(1)))

    if not Path(relative).name.startswith("po03-"):
        findings.append(Finding("OUT_OF_SCOPE_FILENAME", relative, "must start with po03-"))

    return findings


def check_seeded_control(rules: dict, root: Path) -> list[Finding]:
    """The pre-existing gate is an active control; this unit may not weaken it."""
    spec = rules["seeded_control"]
    relative = spec["path"]
    path = root / relative
    if not path.is_file():
        return [Finding("SEEDED_CONTROL_REMOVED", relative, "the seeded gate is gone")]
    text = path.read_text(encoding="utf-8")
    return [
        Finding("SEEDED_CONTROL_WEAKENED", relative, repr(required))
        for required in spec["required_substrings"]
        if required not in text
    ]


def present_bytecode(root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*.pyc")
        if ".git" not in path.relative_to(root).parts
    )


def tracked_bytecode(root: Path) -> list[str]:
    listing = subprocess.run(
        ["git", "ls-files", "*.pyc"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(listing.stdout.split())


def check_bytecode(rules: dict, root: Path) -> list[Finding]:
    """Bytecode beyond the committed exceptions is a warm cache."""
    exceptions = set(rules["bytecode_policy"]["tracked_exceptions"])
    tracked = set(tracked_bytecode(root))
    findings: list[Finding] = []

    for unexpected in sorted(tracked - exceptions):
        findings.append(Finding("UNDECLARED_TRACKED_BYTECODE", unexpected, "committed but not registered"))
    for missing in sorted(exceptions - tracked):
        findings.append(Finding("STALE_BYTECODE_EXCEPTION", missing, "registered but no longer committed"))
    for warm in sorted(set(present_bytecode(root)) - tracked):
        findings.append(Finding("WARM_BYTECODE_CACHE", warm, "present in the checkout but not committed"))
    return findings


def run(rules: dict, root: Path, skip_bytecode: bool = False) -> dict:
    findings: list[Finding] = []
    for relative in rules["owned_workflows"]:
        findings.extend(check_workflow(rules, root, relative))
    findings.extend(check_seeded_control(rules, root))
    if not skip_bytecode:
        findings.extend(check_bytecode(rules, root))

    return {
        "schema": "po03-ci-surface-report-v1",
        "unit_id": "a3-u04",
        "workflows_checked": list(rules["owned_workflows"]),
        "seeded_control": rules["seeded_control"]["path"],
        "bytecode_checked": not skip_bytecode,
        "findings": [finding.as_dict() for finding in findings],
        "verdict": "PASS" if not findings else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PO-03 clean-runner CI surface check")
    parser.add_argument("--root", default=str(REPO_ROOT), help="repository root")
    parser.add_argument("--rules", default=str(RULES_PATH), help="rules document")
    parser.add_argument("--skip-bytecode", action="store_true", help="check workflows only")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    try:
        rules = load_rules(Path(args.rules))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"CI_SURFACE_ERROR: {error}", file=sys.stderr)
        return 2

    report = run(rules, Path(args.root).resolve(), skip_bytecode=args.skip_bytecode)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for finding in report["findings"]:
            print(f"{finding['rule']}: {finding['path']}: {finding['detail']}")
        checked = len(report["workflows_checked"]) + 1
        if report["verdict"] == "PASS":
            print(f"PASS {checked} workflow(s) carry no cache, no install and no secret")
        else:
            print(f"FAIL {len(report['findings'])} CI surface finding(s) across {checked} workflow(s)")

    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
