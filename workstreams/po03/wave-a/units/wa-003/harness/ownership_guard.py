#!/usr/bin/env python3
"""Changed-path ownership guard for PO-03 subordinate work units.

Reads the allowlist and denylist straight out of an immutable task input, then
refuses any commit range that touches a path the unit does not own.  The guard is
standard-library only so it runs in the same pristine clones the clean-clone
harness certifies.

Exit codes: 0 allowed, 1 violation, 2 guard error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clean_clone_harness import glob_match, local_git_env  # noqa: E402  (sibling module)

SCHEMA_VERSION = "OBZIO-PO03-OWNERSHIP-GUARD-v1"


class GuardError(RuntimeError):
    """Raised when the guard cannot evaluate, as distinct from a violation."""


def changed_paths(repo: Path, base: str, head: str) -> list[dict[str, str]]:
    result = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-status", "-M", "--find-renames", f"{base}..{head}"],
        capture_output=True,
        text=True,
        env=local_git_env(),
    )
    if result.returncode != 0:
        raise GuardError(f"git diff {base}..{head} failed: {result.stderr.strip()}")
    changes: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        status = fields[0]
        if status.startswith("R") and len(fields) >= 3:
            changes.append({"status": status, "path": fields[2], "previous_path": fields[1]})
            changes.append({"status": "D", "path": fields[1], "previous_path": ""})
        else:
            changes.append({"status": status, "path": fields[-1], "previous_path": ""})
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for change in changes:
        unique[(change["status"], change["path"])] = change
    return sorted(unique.values(), key=lambda item: (item["path"], item["status"]))


def load_ownership(input_path: Path) -> dict[str, list[str]]:
    document = json.loads(input_path.read_text(encoding="utf-8"))
    ownership = document.get("ownership")
    if not isinstance(ownership, dict):
        raise GuardError(f"{input_path}: missing ownership object")
    allowed = ownership.get("allowed_write_globs")
    prohibited = ownership.get("prohibited_globs", [])
    if not isinstance(allowed, list) or not allowed:
        raise GuardError(f"{input_path}: ownership.allowed_write_globs must be a non-empty array")
    if not isinstance(prohibited, list):
        raise GuardError(f"{input_path}: ownership.prohibited_globs must be an array")
    return {"allowed": [str(item) for item in allowed], "prohibited": [str(item) for item in prohibited]}


def evaluate(
    changes: Sequence[dict[str, str]],
    allowed: Sequence[str],
    prohibited: Sequence[str],
) -> dict[str, Any]:
    outside: list[dict[str, Any]] = []
    denied: list[dict[str, Any]] = []
    inside: list[str] = []
    for change in changes:
        path = change["path"]
        matched_allow = [pattern for pattern in allowed if glob_match(path, pattern)]
        matched_deny = [pattern for pattern in prohibited if glob_match(path, pattern)]
        if matched_deny:
            denied.append({"path": path, "status": change["status"], "patterns": matched_deny})
        if not matched_allow:
            outside.append({"path": path, "status": change["status"]})
        else:
            inside.append(path)
    disposition = "PASS" if not outside and not denied else "FAIL"
    return {
        "schema_version": SCHEMA_VERSION,
        "disposition": disposition,
        "changed_count": len(changes),
        "inside_allowlist": sorted(set(inside)),
        "outside_allowlist": outside,
        "prohibited_hits": denied,
        "allowed_globs": list(allowed),
        "prohibited_globs": list(prohibited),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ownership_guard",
        description="Fail when a commit range writes outside the unit's declared ownership.",
    )
    parser.add_argument("--repo", default=".", help="repository containing the commit range")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--input", default=None, help="immutable task input carrying the ownership block")
    parser.add_argument("--allow", action="append", default=[], dest="allow")
    parser.add_argument("--deny", action="append", default=[], dest="deny")
    parser.add_argument("--receipt", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).resolve()
    allowed = list(args.allow)
    prohibited = list(args.deny)
    try:
        if args.input:
            ownership = load_ownership(repo / args.input if not Path(args.input).is_absolute() else Path(args.input))
            allowed.extend(ownership["allowed"])
            prohibited.extend(ownership["prohibited"])
        if not allowed:
            raise GuardError("no allowlist supplied; pass --input or --allow")
        report = evaluate(changed_paths(repo, args.base, args.head), allowed, prohibited)
    except (GuardError, OSError, json.JSONDecodeError) as error:
        print(f"GUARD-ERROR: {error}", file=sys.stderr)
        return 2
    report["repo"] = str(repo)
    report["base"] = args.base
    report["head"] = args.head
    if args.receipt:
        receipt = Path(args.receipt)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for violation in report["outside_allowlist"]:
        print(f"OUT-OF-ALLOWLIST {violation['status']} {violation['path']}")
    for violation in report["prohibited_hits"]:
        print(f"PROHIBITED {violation['status']} {violation['path']} matches {violation['patterns']}")
    print(
        f"OWNERSHIP {report['disposition']} changed={report['changed_count']} "
        f"inside={len(report['inside_allowlist'])} outside={len(report['outside_allowlist'])} "
        f"prohibited={len(report['prohibited_hits'])}"
    )
    return 0 if report["disposition"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
