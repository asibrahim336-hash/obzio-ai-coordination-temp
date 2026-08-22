#!/usr/bin/env python3
"""Prove the live PO-03 path-scope guard actually rejects, not merely exists.

Every scenario runs `workstreams/po03/tools/check_path_scope.py` as a separate
process and compares its real exit status and output against a stated
expectation.  A guard that passed everything, or that crashed into a pass, would
fail this fixture.

Out-of-allowlist mutations are never committed to the branch under test.  They
exist only as synthetic `--path` arguments or as commits inside a throwaway git
repository created for the run and deleted afterwards, so exercising the guard
cannot itself violate the boundary the guard defends.

Exit codes: 0 every scenario behaved as expected, 1 at least one deviation,
2 harness error.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_GUARD = REPO_ROOT / "workstreams/po03/tools/check_path_scope.py"

IN_ALLOWLIST = (
    "workstreams/po03/attempts/po03-wa-b2e7-027-changed-path-rejection-fixture/rejection_fixture.py",
    "workstreams/po03/tools/check_path_scope.py",
    "receipts/po03/2026-08-22/amendment-activation.json",
    ".github/workflows/po03-contracts.yml",
)

OUT_OF_ALLOWLIST = (
    "state/PO03-SHOULD-NOT-WRITE.json",
    "workstreams/po01/producer-result.json",
    ".cursor/environment.json",
    "packs/pack-a/manifest.json",
    "modules/module-a/index.js",
    "_transport/spool/message.json",
    "dispatch/queue.json",
    "COMMISSION.md",
    ".github/workflows/not-po03.yml",
    "README.md",
)


class HarnessError(Exception):
    """Raised when the fixture cannot run the guard at all."""


class Scenario:
    def __init__(self, name: str, expectation: str, expected_exit: int, expected_marker: str) -> None:
        self.name = name
        self.expectation = expectation
        self.expected_exit = expected_exit
        self.expected_marker = expected_marker
        self.actual_exit: int | None = None
        self.output = ""

    @property
    def passed(self) -> bool:
        return self.actual_exit == self.expected_exit and self.expected_marker in self.output

    def record(self, completed: subprocess.CompletedProcess) -> "Scenario":
        self.actual_exit = completed.returncode
        self.output = (completed.stdout or "") + (completed.stderr or "")
        return self

    def as_dict(self) -> dict:
        return {
            "scenario": self.name,
            "expectation": self.expectation,
            "expected_exit": self.expected_exit,
            "actual_exit": self.actual_exit,
            "expected_marker": self.expected_marker,
            "marker_present": self.expected_marker in self.output,
            "passed": self.passed,
            "output": self.output.strip(),
        }


def run_guard(guard: Path, arguments: tuple[str, ...], cwd: Path) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            (sys.executable, "-I", str(guard), *arguments),
            cwd=cwd, capture_output=True, text=True,
        )
    except OSError as exc:
        raise HarnessError(f"cannot execute guard {guard}: {exc}") from exc


def synthetic_scenarios(guard: Path) -> list[Scenario]:
    """Drive the guard with explicit --path arguments and no repository at all."""
    scenarios: list[Scenario] = []
    control = Scenario(
        "synthetic-in-allowlist-control",
        "all four commissioned prefixes pass together",
        0,
        "PO03_PATH_SCOPE_PASS",
    )
    arguments = tuple(argument for path in IN_ALLOWLIST for argument in ("--path", path))
    scenarios.append(control.record(run_guard(guard, arguments, REPO_ROOT)))

    for path in OUT_OF_ALLOWLIST:
        scenario = Scenario(
            f"synthetic-rejected:{path}",
            "an out-of-allowlist mutation is refused with a non-zero exit",
            1,
            f"PO03_PATH_SCOPE_VIOLATION: {path}",
        )
        scenarios.append(scenario.record(run_guard(guard, ("--path", path), REPO_ROOT)))

    mixed = Scenario(
        "synthetic-one-bad-path-among-many-good",
        "a single out-of-allowlist path taints an otherwise clean change set",
        1,
        "PO03_PATH_SCOPE_VIOLATION: state/PO03-SHOULD-NOT-WRITE.json",
    )
    mixed_arguments = tuple(argument for path in IN_ALLOWLIST for argument in ("--path", path))
    mixed_arguments += ("--path", "state/PO03-SHOULD-NOT-WRITE.json")
    scenarios.append(mixed.record(run_guard(guard, mixed_arguments, REPO_ROOT)))
    return scenarios


def git(repo: Path, *arguments: str) -> str:
    try:
        return subprocess.run(
            ("git", *arguments), cwd=repo, check=True, capture_output=True, text=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HarnessError(f"git {' '.join(arguments)} failed in scratch repository: {exc}") from exc


def build_scratch_repository(root: Path) -> tuple[Path, str]:
    """Create a throwaway repository whose history the guard can be pointed at."""
    repo = root / "scratch-repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "scratch", ".")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "po03-rejection-fixture")
    base_file = repo / "workstreams/po03/attempts/scratch/base.txt"
    base_file.parent.mkdir(parents=True)
    base_file.write_text("base\n", encoding="utf-8")
    git(repo, "add", "workstreams")
    git(repo, "commit", "-qm", "scratch base inside the allowlist")
    return repo, git(repo, "rev-parse", "HEAD").strip()


def scratch_scenarios(guard: Path, scratch_root: Path) -> list[Scenario]:
    """Drive the guard from a real `git diff` over commits it has never seen."""
    repo, base = build_scratch_repository(scratch_root)
    scenarios: list[Scenario] = []

    allowed = repo / "workstreams/po03/attempts/scratch/added.txt"
    allowed.write_text("added inside the allowlist\n", encoding="utf-8")
    git(repo, "add", "workstreams")
    git(repo, "commit", "-qm", "in-allowlist change")
    in_allowlist_head = git(repo, "rev-parse", "HEAD").strip()
    control = Scenario(
        "scratch-repo-in-allowlist-control",
        "a real commit touching only allowlisted paths passes",
        0,
        "PO03_PATH_SCOPE_PASS",
    )
    scenarios.append(
        control.record(run_guard(guard, ("--base", base, "--head", in_allowlist_head), repo))
    )

    violation = repo / "state/PO03-SHOULD-NOT-WRITE.json"
    violation.parent.mkdir(parents=True, exist_ok=True)
    violation.write_text('{"deliberate": "out of allowlist"}\n', encoding="utf-8")
    git(repo, "add", "state")
    git(repo, "commit", "-qm", "deliberate out-of-allowlist mutation")
    violation_head = git(repo, "rev-parse", "HEAD").strip()
    rejected = Scenario(
        "scratch-repo-out-of-allowlist-mutation",
        "a real staged and committed out-of-allowlist mutation is refused",
        1,
        "PO03_PATH_SCOPE_VIOLATION: state/PO03-SHOULD-NOT-WRITE.json",
    )
    scenarios.append(
        rejected.record(run_guard(guard, ("--base", base, "--head", violation_head), repo))
    )

    deletion_target = repo / "state/PO03-SHOULD-NOT-WRITE.json"
    deletion_target.unlink()
    git(repo, "add", "-A", "state")
    git(repo, "commit", "-qm", "delete the out-of-allowlist file again")
    deletion_head = git(repo, "rev-parse", "HEAD").strip()
    deletion = Scenario(
        "scratch-repo-out-of-allowlist-deletion",
        "deleting an out-of-allowlist path is a change of scope and is refused",
        1,
        "PO03_PATH_SCOPE_VIOLATION: state/PO03-SHOULD-NOT-WRITE.json",
    )
    scenarios.append(
        deletion.record(run_guard(guard, ("--base", violation_head, "--head", deletion_head), repo))
    )

    unknown_base = Scenario(
        "unresolvable-base-fails-closed",
        "a base the repository does not contain is an error, never a pass",
        2,
        "PO03_PATH_SCOPE_ERROR",
    )
    scenarios.append(
        unknown_base.record(run_guard(guard, ("--base", "f" * 40, "--head", "HEAD"), repo))
    )
    return scenarios


def repo_scope_scenario(guard: Path, base: str) -> Scenario:
    """Assert the branch under test has itself stayed inside the allowlist."""
    scenario = Scenario(
        f"real-repository-scope:{base}..HEAD",
        "the branch under test changed only allowlisted paths",
        0,
        "PO03_PATH_SCOPE_PASS",
    )
    return scenario.record(run_guard(guard, ("--base", base, "--head", "HEAD"), REPO_ROOT))


def run_all(guard: Path, scratch_root: Path, repo_scope_base: str | None = None) -> list[Scenario]:
    scenarios = synthetic_scenarios(guard)
    scenarios.extend(scratch_scenarios(guard, scratch_root))
    if repo_scope_base:
        scenarios.append(repo_scope_scenario(guard, repo_scope_base))
    return scenarios


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guard", default=str(DEFAULT_GUARD), help="path-scope guard under test")
    parser.add_argument(
        "--scratch-root",
        help="where to build the throwaway repository; defaults to a system temporary directory",
    )
    parser.add_argument(
        "--include-repo-scope",
        metavar="BASE",
        help="also assert this branch changed only allowlisted paths since BASE",
    )
    parser.add_argument("--json", action="store_true", help="emit the scenario table as JSON")
    args = parser.parse_args(argv)

    guard = Path(args.guard)
    if not guard.is_file():
        print(f"PO03_FIXTURE_ERROR: no guard at {guard}", file=sys.stderr)
        return 2
    holder = Path(tempfile.mkdtemp(prefix="po03-scratch-", dir=args.scratch_root or None))
    try:
        scenarios = run_all(guard, holder, args.include_repo_scope)
    except HarnessError as exc:
        print(f"PO03_FIXTURE_ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        shutil.rmtree(holder, ignore_errors=True)

    table = [scenario.as_dict() for scenario in scenarios]
    failed = [entry for entry in table if not entry["passed"]]
    if args.json:
        print(json.dumps({"guard": str(guard), "scenarios": table}, indent=2, sort_keys=True))
    else:
        for entry in table:
            print(
                f"{'OK      ' if entry['passed'] else 'DEVIATED'} {entry['scenario']} "
                f"expected_exit={entry['expected_exit']} actual_exit={entry['actual_exit']} "
                f"marker={'present' if entry['marker_present'] else 'ABSENT'}"
            )
    if failed:
        for entry in failed:
            print(
                f"PO03_FIXTURE_DEVIATION: {entry['scenario']} expected exit "
                f"{entry['expected_exit']} with {entry['expected_marker']!r}, got exit "
                f"{entry['actual_exit']} and output {entry['output']!r}",
                file=sys.stderr,
            )
        return 1
    rejecting = sum(1 for entry in table if entry["expected_exit"] != 0)
    summary = (
        f"PO03_FIXTURE_PASS scenarios={len(table)} rejecting={rejecting} "
        f"passing={len(table) - rejecting} guard={guard.name}"
    )
    # In JSON mode stdout must stay a single parseable document.
    print(summary, file=sys.stderr if args.json else sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
