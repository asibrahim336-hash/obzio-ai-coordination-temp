#!/usr/bin/env python3
"""Wave-one path-scope guard for CI (unit a3-u03).

Fails the build when a change writes outside the commission's wave-one
allowlist, and optionally when a writer touches paths outside its own owned
subtree.

The allowlist decision is not reimplemented here.  ``control_plane.py`` is the
coordinator-owned authority for that logic and this module binds directly to its
``path_in_allowlist``, ``check_allowlist`` and ``check_ownership`` functions.  A
second copy of an allowlist is a second thing to drift, and a guard that drifts
from the rule it enforces is worse than no guard: it reports PASS with
authority it no longer has.

Three input sources are supported so the same decision code runs everywhere:

* ``git``      -- changed paths computed from a merge base, which is what CI uses;
* ``paths``    -- a newline-delimited changed-path list;
* ``diff``     -- a unified diff.

``selftest`` runs the committed fixtures, including a deliberate
out-of-allowlist mutation, and fails unless each one produces its recorded
verdict.  The fixtures are data, never commits: proving the guard by actually
writing outside the allowlist would be the very act it exists to prevent.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

RUNTIME_DIR = Path(__file__).resolve().parent
PO03_ROOT = RUNTIME_DIR.parent
REPO_ROOT = PO03_ROOT.parents[1]
CONTROL_PLANE_PATH = PO03_ROOT / "tools" / "control_plane.py"
FIXTURE_DIR = RUNTIME_DIR / "fixtures" / "path_scope"
FIXTURE_EXPECTATIONS = FIXTURE_DIR / "expected-verdicts.json"

REPORT_SCHEMA = "po03-path-scope-report-v1"


def load_control_plane():
    """Bind to the coordinator-owned allowlist authority by file path.

    ``workstreams/po03`` is not an importable package, and a clean clone has
    nothing on sys.path that would make it one, so the module is loaded from its
    committed location instead of imported.
    """
    spec = importlib.util.spec_from_file_location("po03_control_plane", CONTROL_PLANE_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable in a valid tree
        raise RuntimeError(f"cannot load the control plane from {CONTROL_PLANE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


control_plane = load_control_plane()

# Exported so tests can assert identity rather than equivalence: the guard must
# be the same callable the control plane uses, not a lookalike.
path_in_allowlist = control_plane.path_in_allowlist
check_allowlist = control_plane.check_allowlist
check_ownership = control_plane.check_ownership

# The workflow pattern is read from the control plane too, so the probes below
# hold no independent copy of the allowlist shape.
WORKFLOW_DIR = control_plane.ALLOWLIST_WORKFLOW_DIR
WORKFLOW_PREFIX = control_plane.ALLOWLIST_WORKFLOW_PREFIX
WORKFLOW_SUFFIX = control_plane.ALLOWLIST_WORKFLOW_SUFFIX

# Retired at 6f5e386, where the coordinator fixed the lstrip("./") normaliser.
# This module used to carry a narrow compensation that admitted dot-directory
# workflow paths the upstream helper wrongly rejected. With the defect gone the
# compensation was unreachable code, and unreachable code that would have
# admitted a path is worse than no code at all: a future regression would have
# been silently absorbed instead of reported. What replaces it is a guard that
# asserts the fixed behaviour, so a regression fails the build.
RETIRED_COMPENSATION = {
    "defect_id": "PO03-CP-001-lstrip-dot-directory",
    "fixed_upstream_at": "6f5e386",
    "independently_rediscovered_by": ["coordinator test suite", "po03-worker-a10", "po03-worker-a3"],
    "disposition": "converted to the normalisation guard below rather than deleted, so the "
    "behaviour the compensation depended on is now asserted instead of assumed",
}

# Probe values are composed from the control plane's own allowlist constants
# rather than written out, so this module holds no absolute path of its own and
# stays clean under the a3-u02 hermeticity gate.
WORKFLOW_PROBE = f"{control_plane.ALLOWLIST_WORKFLOW_DIR}{control_plane.ALLOWLIST_WORKFLOW_PREFIX}probe{control_plane.ALLOWLIST_WORKFLOW_SUFFIX}"
ABSOLUTE_PROBE = "/" + control_plane.ALLOWLIST_PREFIXES[0] + "probe"
TRAVERSAL_PROBE = control_plane.ALLOWLIST_PREFIXES[0] + "../../etc/passwd"
RELATIVE_PROBE = control_plane.ALLOWLIST_PREFIXES[0] + "probe"
DOT_SEGMENT_PROBE = "./" + RELATIVE_PROBE

# Each probe pairs a path with the verdict a correct normaliser must reach.
# Every expectation is drawn from the commission's written allowlist, so the
# guard states an invariant rather than describing what the code does today.
NORMALISATION_PROBES = (
    ("dot_directory_workflow_is_admitted", WORKFLOW_PROBE, True),
    ("absolute_path_is_refused", ABSOLUTE_PROBE, False),
    ("traversal_is_refused", TRAVERSAL_PROBE, False),
)

# Spellings that denote the same path and must therefore be judged the same
# way.  Whether "./x" is in the allowlist is the authority's policy and not
# mine; that it agrees with "x" is a property of normalisation itself, and it
# is the exact property lstrip("./") broke.
EQUIVALENT_SPELLINGS = (
    ("leading_dot_segment_is_equivalent", DOT_SEGMENT_PROBE, RELATIVE_PROBE),
)


def normalisation_guard() -> list[dict[str, Any]]:
    """Report every probe on which the upstream normaliser breaks its contract.

    A guard, not a compensation.  While the allowlist behaves this returns
    nothing; when it stops behaving, the caller fails rather than routing around
    the disagreement.  The distinction matters because a compensation keeps the
    build green while the authority is wrong, which is how a normalisation
    defect survives long enough to be discovered three times independently.
    """
    failures: list[dict[str, Any]] = []
    for name, candidate, expected in NORMALISATION_PROBES:
        actual = bool(path_in_allowlist(candidate))
        if actual is not expected:
            failures.append(
                {
                    "probe": name,
                    "path": candidate,
                    "expected_in_allowlist": expected,
                    "actual_in_allowlist": actual,
                }
            )
    for name, spelling, equivalent in EQUIVALENT_SPELLINGS:
        decided = bool(path_in_allowlist(spelling))
        reference = bool(path_in_allowlist(equivalent))
        if decided is not reference:
            failures.append(
                {
                    "probe": name,
                    "path": spelling,
                    "expected_in_allowlist": reference,
                    "actual_in_allowlist": decided,
                    "equivalent_to": equivalent,
                }
            )
    return failures


def is_absolute_path(path: str) -> bool:
    return path.strip().startswith("/")


def owned_prefixes(owner: str) -> tuple[str, ...]:
    ownership = control_plane.load_path_ownership()
    entry = ownership.get("owners", {}).get(owner)
    if entry is None:
        return ()
    return tuple(entry.get("owned_prefixes", []))


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def empty_tree_id() -> str:
    result = subprocess.run(
        ["git", "mktree"],
        cwd=REPO_ROOT,
        input="",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git mktree failed: {result.stderr.strip()}")
    return result.stdout.strip()


def parse_path_list(text: str) -> list[str]:
    paths: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        paths.append(stripped)
    return paths


def parse_unified_diff(text: str) -> list[str]:
    """Collect every path a unified diff touches, including both rename sides."""
    paths: list[str] = []

    def add(candidate: str) -> None:
        candidate = candidate.strip()
        # Diff paths are always repository-relative. The only absolute value git
        # emits is the added/deleted sentinel, so rejecting absolute candidates
        # discards it structurally rather than by matching one magic name.
        if not candidate or candidate.startswith("/"):
            return
        for prefix in ("a/", "b/"):
            if candidate.startswith(prefix):
                candidate = candidate[len(prefix) :]
                break
        if candidate not in paths:
            paths.append(candidate)

    for line in text.splitlines():
        if line.startswith("diff --git "):
            remainder = line[len("diff --git ") :].split()
            for token in remainder:
                add(token)
        elif line.startswith("--- ") or line.startswith("+++ "):
            add(line[4:].split("\t")[0])
        elif line.startswith("rename from ") or line.startswith("rename to "):
            add(line.split(" ", 2)[2])
    return paths


def changed_paths_from_git(base: str, head: str) -> tuple[list[str], str]:
    """Resolve changed paths against the merge base of ``base`` and ``head``.

    Diffing against the raw base tip would attribute every unrelated commit on
    the base branch to this change, which produces both false violations and, on
    a rebased branch, false silence.
    """
    try:
        merge_base = git("merge-base", base, head).strip()
        strategy = f"merge-base({base}, {head})"
    except RuntimeError:
        # No shared history: treat every path in HEAD's diff against the empty
        # tree as changed.  Failing closed is the only safe direction here.
        # git mktree with no input yields the empty tree id for whichever hash
        # algorithm the repository uses, so no hash constant is baked in.
        merge_base = empty_tree_id()
        strategy = "empty-tree (no merge base found)"
    output = git("diff", "--name-only", "--no-renames", f"{merge_base}..{head}")
    return parse_path_list(output), strategy


def attribute(path: str, base: str, head: str, limit: int = 5) -> list[dict[str, str]]:
    """Name the commits in base..head that touched a path.

    A guard that reports only "something is outside the allowlist" is hard to
    act on, and it is indistinguishable from a guard misfiring.  Naming the
    commit turns the failure into a fact: either one of the commits under review
    wrote outside the allowlist, or the write was inherited from the lineage the
    branch was created on and the base is the thing that is wrong.
    """
    try:
        output = git("log", "--no-merges", f"--max-count={limit}", "--format=%H%x1f%s", f"{base}..{head}", "--", path)
    except RuntimeError:
        return []
    commits: list[dict[str, str]] = []
    for line in output.splitlines():
        if "\x1f" not in line:
            continue
        sha, subject = line.split("\x1f", 1)
        commits.append({"commit": sha, "subject": subject})
    return commits


def evaluate(paths: Iterable[str], *, source: str, owner: str | None = None) -> dict[str, Any]:
    """Decide each path individually against the upstream authority.

    The upstream helpers report violations in their own normalised form, so
    deciding one path at a time keeps the original string in hand and the report
    names the path the author actually wrote.
    """
    ordered = list(paths)
    violations: list[str] = []
    ownership_violations: list[str] = []

    for path in ordered:
        if is_absolute_path(path):
            # Belt and braces, kept deliberately independent of upstream. A
            # guard must fail closed on an absolute path whatever the authority
            # returns, because that is the direction in which a normalisation
            # defect grants access rather than denying it.
            violations.append(path)
            continue
        if check_allowlist([path]):
            violations.append(path)
        if owner and check_ownership(owner, [path]):
            ownership_violations.append(path)

    violations = sorted(set(violations))
    ownership_violations = sorted(set(ownership_violations))
    guard_failures = normalisation_guard()

    return {
        "schema": REPORT_SCHEMA,
        "source": source,
        "owner": owner,
        "changed_path_count": len(ordered),
        "changed_paths": ordered,
        "allowlist_violations": violations,
        "ownership_violations": ownership_violations,
        "normalisation_guard_failures": guard_failures,
        "retired_compensation": RETIRED_COMPENSATION,
        "verdict": "FAIL" if violations or ownership_violations or guard_failures else "PASS",
    }


def emit(report: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for path in report["allowlist_violations"]:
            print(f"OUT_OF_ALLOWLIST: {path}")
        for path in report["ownership_violations"]:
            print(f"NOT_OWNED_BY_{report['owner']}: {path}")
        for failure in report["normalisation_guard_failures"]:
            print(
                f"UPSTREAM_NORMALISATION_REGRESSED: {failure['probe']}: {failure['path']} "
                f"expected in_allowlist={failure['expected_in_allowlist']}, "
                f"got {failure['actual_in_allowlist']}"
            )
        if report["verdict"] == "FAIL":
            print(
                f"FAIL {len(report['allowlist_violations'])} out-of-allowlist and "
                f"{len(report['ownership_violations'])} ownership violation(s) "
                f"across {report['changed_path_count']} changed path(s) [{report['source']}]"
            )
        else:
            print(
                f"PASS {report['changed_path_count']} changed path(s) inside the "
                f"wave-one allowlist [{report['source']}]"
            )
    return 1 if report["verdict"] == "FAIL" else 0


def cmd_git(args: argparse.Namespace) -> int:
    paths, strategy = changed_paths_from_git(args.base, args.head)
    report = evaluate(paths, source=f"git {strategy}", owner=args.owner)
    report["base"] = args.base
    report["head"] = args.head
    report["attribution"] = {
        path: attribute(path, args.base, args.head)
        for path in report["allowlist_violations"] + report["ownership_violations"]
    }
    code = emit(report, args.json)
    if not args.json:
        for path, commits in report["attribution"].items():
            for commit in commits:
                print(f"  introduced by {commit['commit'][:12]} {commit['subject']}")
    return code


def cmd_paths(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8")
    report = evaluate(parse_path_list(text), source=f"path-list {args.file}", owner=args.owner)
    return emit(report, args.json)


def cmd_diff(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8")
    report = evaluate(parse_unified_diff(text), source=f"diff {args.file}", owner=args.owner)
    return emit(report, args.json)


def run_selftest(as_json: bool = False) -> tuple[int, list[dict[str, Any]]]:
    """Replay the committed fixtures and require their recorded verdicts.

    This is the proof that the guard rejects an out-of-allowlist mutation, and
    it runs the same ``evaluate`` path CI runs on real changed paths.
    """
    expectations = json.loads(FIXTURE_EXPECTATIONS.read_text(encoding="utf-8"))
    outcomes: list[dict[str, Any]] = []
    failures = 0
    for case in expectations["cases"]:
        fixture = REPO_ROOT / case["fixture"]
        text = fixture.read_text(encoding="utf-8")
        if case["kind"] == "path-list":
            paths = parse_path_list(text)
        elif case["kind"] == "diff":
            paths = parse_unified_diff(text)
        else:
            raise ValueError(f"unknown fixture kind: {case['kind']}")
        report = evaluate(paths, source=case["fixture"], owner=case.get("owner"))
        verdict_ok = report["verdict"] == case["expected_verdict"]
        rejected_ok = sorted(report["allowlist_violations"]) == sorted(
            case.get("expected_allowlist_violations", [])
        )
        ownership_ok = sorted(report["ownership_violations"]) == sorted(
            case.get("expected_ownership_violations", [])
        )
        passed = verdict_ok and rejected_ok and ownership_ok
        failures += 0 if passed else 1
        outcomes.append(
            {
                "fixture": case["fixture"],
                "expected_verdict": case["expected_verdict"],
                "actual_verdict": report["verdict"],
                "expected_allowlist_violations": sorted(case.get("expected_allowlist_violations", [])),
                "actual_allowlist_violations": sorted(report["allowlist_violations"]),
                "expected_ownership_violations": sorted(case.get("expected_ownership_violations", [])),
                "actual_ownership_violations": sorted(report["ownership_violations"]),
                "outcome": "PASS" if passed else "FAIL",
            }
        )
    if as_json:
        print(json.dumps({"schema": "po03-path-scope-selftest-v1", "cases": outcomes}, indent=2, sort_keys=True))
    else:
        for outcome in outcomes:
            print(
                f"{outcome['outcome']} {outcome['fixture']}: "
                f"expected {outcome['expected_verdict']}, got {outcome['actual_verdict']}"
            )
        if failures:
            print(f"FAIL {failures} of {len(outcomes)} path-scope fixture(s) did not match")
        else:
            print(f"PASS {len(outcomes)} path-scope fixture(s) produced their recorded verdicts")
    return (1 if failures else 0), outcomes


def cmd_selftest(args: argparse.Namespace) -> int:
    code, _ = run_selftest(args.json)
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PO-03 wave-one path-scope guard")
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    sub = parser.add_subparsers(dest="command", required=True)

    from_git = sub.add_parser("git", help="check paths changed between a merge base and a head")
    from_git.add_argument("--base", default="origin/main")
    from_git.add_argument("--head", default="HEAD")
    from_git.add_argument("--owner", help="also enforce this owner's subtree from path-ownership.json")
    from_git.set_defaults(func=cmd_git)

    from_paths = sub.add_parser("paths", help="check a newline-delimited changed-path list")
    from_paths.add_argument("file")
    from_paths.add_argument("--owner")
    from_paths.set_defaults(func=cmd_paths)

    from_diff = sub.add_parser("diff", help="check every path touched by a unified diff")
    from_diff.add_argument("file")
    from_diff.add_argument("--owner")
    from_diff.set_defaults(func=cmd_diff)

    selftest = sub.add_parser("selftest", help="prove the guard rejects the committed mutation fixtures")
    selftest.set_defaults(func=cmd_selftest)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError, OSError) as exc:
        # Failing closed: an unresolvable base or unreadable fixture must never
        # be reported as a clean scope.
        print(f"PATH_SCOPE_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
