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

# The workflow pattern is read from the control plane too, so even the
# compensation below holds no independent copy of the allowlist shape.
WORKFLOW_DIR = control_plane.ALLOWLIST_WORKFLOW_DIR
WORKFLOW_PREFIX = control_plane.ALLOWLIST_WORKFLOW_PREFIX
WORKFLOW_SUFFIX = control_plane.ALLOWLIST_WORKFLOW_SUFFIX

DEFECT_ID = "PO03-CP-001-lstrip-dot-directory"

# Probe values are composed from the control plane's own allowlist constants
# rather than written out, so this module holds no absolute path of its own and
# stays clean under the a3-u02 hermeticity gate.
WORKFLOW_PROBE = f"{control_plane.ALLOWLIST_WORKFLOW_DIR}{control_plane.ALLOWLIST_WORKFLOW_PREFIX}probe{control_plane.ALLOWLIST_WORKFLOW_SUFFIX}"
ABSOLUTE_PROBE = "/" + control_plane.ALLOWLIST_PREFIXES[0] + "probe"


def compensates_dot_directory_defect(path: str) -> bool:
    """Admit workflow paths the upstream normaliser wrongly rejects.

    ``control_plane.path_in_allowlist`` normalises with ``lstrip("./")``, which
    strips characters rather than a leading ``./`` segment.  Every path under a
    dot directory therefore loses its leading dot, so ``.github/workflows/
    po03-*.yml`` becomes ``github/workflows/po03-*.yml`` and is judged outside
    an allowlist that explicitly contains it.  ``check_ownership`` normalises
    the same way and rejects the identical paths.

    This compensation is deliberately narrow: it admits only the workflow class
    the commission's written allowlist already contains, applies no other
    widening, and every path it admits is enumerated in the report as a
    compensation rather than as a clean pass.  The repair itself belongs to the
    coordinator, so it ships as a patch under ``runtime/repair-candidates/``
    instead of being applied to a file this writer does not own.
    """
    candidate = path.strip()
    if not candidate.startswith(WORKFLOW_DIR):
        return False
    if ".." in candidate.split("/"):
        return False
    leaf = candidate[len(WORKFLOW_DIR) :]
    return (
        "/" not in leaf
        and leaf.startswith(WORKFLOW_PREFIX)
        and leaf.endswith(WORKFLOW_SUFFIX)
    )


def is_absolute_path(path: str) -> bool:
    return path.strip().startswith("/")


def upstream_admits_absolute_paths() -> bool:
    """True while an absolute in-allowlist-looking path is wrongly admitted."""
    return path_in_allowlist(ABSOLUTE_PROBE)


def upstream_defect_present() -> bool:
    """True while the coordinator's normaliser still rejects a valid workflow path."""
    return not path_in_allowlist(WORKFLOW_PROBE)


def owned_prefixes(owner: str) -> tuple[str, ...]:
    ownership = control_plane.load_path_ownership()
    entry = ownership.get("owners", {}).get(owner)
    if entry is None:
        return ()
    return tuple(entry.get("owned_prefixes", []))


def compensates_ownership_defect(owner: str, path: str) -> bool:
    """The same normaliser defect makes owned workflow paths look unowned."""
    candidate = path.strip()
    if not candidate.startswith(WORKFLOW_DIR):
        return False
    return candidate.startswith(owned_prefixes(owner))


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


def evaluate(paths: Iterable[str], *, source: str, owner: str | None = None) -> dict[str, Any]:
    """Decide each path individually against the upstream authority.

    The upstream helpers report violations in their own normalised form, which
    for a dot directory is the damaged spelling.  Deciding one path at a time
    keeps the original string in hand, so the report names the path the author
    actually wrote and the compensation can be applied to it.
    """
    ordered = list(paths)
    violations: list[str] = []
    compensated: list[str] = []
    ownership_violations: list[str] = []
    ownership_compensated: list[str] = []

    for path in ordered:
        if is_absolute_path(path):
            # The same lstrip defect runs the other way too: "/workstreams/po03/x"
            # loses its leading slash and is *admitted*. A guard must fail closed,
            # so an absolute path is a violation whatever upstream returns.
            violations.append(path)
            continue
        if check_allowlist([path]):
            if compensates_dot_directory_defect(path):
                compensated.append(path)
            else:
                violations.append(path)
        if owner and check_ownership(owner, [path]):
            if compensates_ownership_defect(owner, path):
                ownership_compensated.append(path)
            else:
                ownership_violations.append(path)

    violations = sorted(set(violations))
    ownership_violations = sorted(set(ownership_violations))

    return {
        "schema": REPORT_SCHEMA,
        "source": source,
        "owner": owner,
        "changed_path_count": len(ordered),
        "changed_paths": ordered,
        "allowlist_violations": violations,
        "ownership_violations": ownership_violations,
        "upstream_defect_id": DEFECT_ID,
        "upstream_defect_present": upstream_defect_present(),
        "upstream_admits_absolute_paths": upstream_admits_absolute_paths(),
        "compensated_allowlist_paths": sorted(set(compensated)),
        "compensated_ownership_paths": sorted(set(ownership_compensated)),
        "verdict": "FAIL" if violations or ownership_violations else "PASS",
    }


def emit(report: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for path in report["allowlist_violations"]:
            print(f"OUT_OF_ALLOWLIST: {path}")
        for path in report["ownership_violations"]:
            print(f"NOT_OWNED_BY_{report['owner']}: {path}")
        for path in report["compensated_allowlist_paths"]:
            print(f"COMPENSATED_{report['upstream_defect_id']}: {path}")
        for path in report["compensated_ownership_paths"]:
            print(f"COMPENSATED_OWNERSHIP_{report['upstream_defect_id']}: {path}")
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
    return emit(report, args.json)


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
