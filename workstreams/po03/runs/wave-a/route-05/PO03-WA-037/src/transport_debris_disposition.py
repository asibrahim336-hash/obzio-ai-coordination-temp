#!/usr/bin/env python3
"""Detect transport debris in a tree and record a disposition without deleting.

"Transport debris" is what arrives in a repository as a side effect of moving
work between machines, editors and runtimes rather than as authored content:
bytecode caches, editor swap files, merge leftovers, platform metadata,
archive extraction residue.  The operating rule for PO-03 is that debris is
*classified and dispositioned*, never silently removed, because a file that
looks like debris can also be the only surviving evidence of how a run
behaved.

This component therefore has no delete path at all.  It emits, for every
detected item, one of:

    IGNORE_RULE        regenerable, propose an ignore rule; leave the bytes
    QUARANTINE_RECORD  suspicious, record location and digest for review
    RETAIN_AS_EVIDENCE debris that carries irreproducible run information
    REVIEW_REQUIRED    matched a rule whose disposition depends on context

Non-destructiveness is enforced three ways, not merely asserted:

1. ``--policy delete`` is accepted by the parser and then refused with exit
   code 3, so an operator who asks for deletion gets an explicit refusal
   rather than a silent no-op.
2. ``census`` records a SHA-256 of every file before and after a run, and
   ``verify_census_unchanged`` proves nothing moved.
3. ``self_audit`` parses this module's own source with ``ast`` and fails if
   any deletion call (``os.remove``, ``os.unlink``, ``shutil.rmtree``,
   ``Path.unlink``, ``os.rmdir``, ``Path.rmdir``) is present.  The guarantee
   is checked against the code, not against the docstring.

Exit codes: 0 clean, 1 debris detected, 2 usage error, 3 deletion refused.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


IGNORE_RULE = "IGNORE_RULE"
QUARANTINE_RECORD = "QUARANTINE_RECORD"
RETAIN_AS_EVIDENCE = "RETAIN_AS_EVIDENCE"
REVIEW_REQUIRED = "REVIEW_REQUIRED"

PROHIBITED_DELETION_CALLS = frozenset(
    {"remove", "unlink", "rmtree", "rmdir", "removedirs", "rename", "replace", "truncate"}
)


@dataclass(frozen=True)
class DebrisRule:
    rule_id: str
    pattern: str
    kind: str  # "name", "path", or "dir"
    disposition: str
    rationale: str


DEFAULT_RULES: tuple[DebrisRule, ...] = (
    DebrisRule("pycache-dir", "__pycache__", "dir", IGNORE_RULE, "regenerable CPython bytecode cache"),
    DebrisRule("pyc", "*.pyc", "name", IGNORE_RULE, "compiled bytecode, regenerable from source"),
    DebrisRule("pyo", "*.pyo", "name", IGNORE_RULE, "optimised bytecode, regenerable from source"),
    DebrisRule("pytest-cache", ".pytest_cache", "dir", IGNORE_RULE, "test runner cache"),
    DebrisRule("mypy-cache", ".mypy_cache", "dir", IGNORE_RULE, "type checker cache"),
    DebrisRule("ipynb-checkpoints", ".ipynb_checkpoints", "dir", IGNORE_RULE, "notebook autosave directory"),
    DebrisRule("node-modules", "node_modules", "dir", IGNORE_RULE, "installed dependency tree"),
    DebrisRule("ds-store", ".DS_Store", "name", IGNORE_RULE, "macOS directory metadata"),
    DebrisRule("thumbs-db", "Thumbs.db", "name", IGNORE_RULE, "Windows thumbnail cache"),
    DebrisRule("apple-double", "._*", "name", QUARANTINE_RECORD, "AppleDouble resource fork from archive transport"),
    DebrisRule("merge-orig", "*.orig", "name", RETAIN_AS_EVIDENCE, "pre-merge original; records a real conflict"),
    DebrisRule("merge-rej", "*.rej", "name", RETAIN_AS_EVIDENCE, "rejected hunk; records a failed patch application"),
    DebrisRule("patch-backup", "*.bak", "name", QUARANTINE_RECORD, "editor or script backup of unknown provenance"),
    DebrisRule("vim-swap", "*.swp", "name", QUARANTINE_RECORD, "editor swap file; may hold unsaved content"),
    DebrisRule("emacs-autosave", "#*#", "name", QUARANTINE_RECORD, "editor autosave; may hold unsaved content"),
    DebrisRule("tilde-backup", "*~", "name", QUARANTINE_RECORD, "editor backup copy"),
    DebrisRule("conflict-markers", "*", "content", RETAIN_AS_EVIDENCE, "file contains unresolved merge conflict markers"),
    DebrisRule("zero-byte", "*", "empty", REVIEW_REQUIRED, "zero-byte file; may be a truncated transfer"),
)

CONFLICT_MARKERS = (b"<<<<<<< ", b"=======\n", b">>>>>>> ")


@dataclass(frozen=True)
class DebrisFinding:
    path: str
    rule_id: str
    disposition: str
    rationale: str
    sha256: str
    bytes: int


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def census(root: Path) -> dict[str, str]:
    """Digest every regular file under ``root``, keyed by relative path."""
    result: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(dirnames)
        for name in sorted(filenames):
            absolute = Path(dirpath) / name
            relative = os.path.relpath(absolute, root)
            if absolute.is_symlink():
                result[relative] = "symlink:" + os.readlink(absolute)
                continue
            digest, size = sha256_file(absolute)
            result[relative] = f"{digest}:{size}"
    return result


def verify_census_unchanged(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Return a list of violations; empty means nothing was created, changed or removed."""
    violations: list[str] = []
    for path, digest in before.items():
        if path not in after:
            violations.append(f"DELETED: {path}")
        elif after[path] != digest:
            violations.append(f"MODIFIED: {path}")
    for path in after:
        if path not in before:
            violations.append(f"CREATED: {path}")
    return sorted(violations)


def _has_conflict_markers(path: Path) -> bool:
    try:
        head = path.read_bytes()
    except OSError:
        return False
    if b"\x00" in head[:8192]:
        return False
    return all(marker in head for marker in CONFLICT_MARKERS)


def scan(root: Path, rules: Iterable[DebrisRule] = DEFAULT_RULES) -> list[DebrisFinding]:
    rule_list = list(rules)
    dir_rules = [r for r in rule_list if r.kind == "dir"]
    name_rules = [r for r in rule_list if r.kind == "name"]
    content_rules = [r for r in rule_list if r.kind == "content"]
    empty_rules = [r for r in rule_list if r.kind == "empty"]

    findings: list[DebrisFinding] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        current = Path(dirpath)
        relative_dir = os.path.relpath(dirpath, root)
        dir_components = [] if relative_dir == "." else relative_dir.split(os.sep)
        matched_dir_rule = next(
            (r for r in dir_rules if any(fnmatch.fnmatch(part, r.pattern) for part in dir_components)),
            None,
        )
        for name in sorted(filenames):
            absolute = current / name
            if absolute.is_symlink() or not absolute.is_file():
                continue
            relative = os.path.relpath(absolute, root)
            digest, size = sha256_file(absolute)

            rule = matched_dir_rule
            if rule is None:
                rule = next((r for r in name_rules if fnmatch.fnmatch(name, r.pattern)), None)
            if rule is None and size == 0 and empty_rules:
                rule = empty_rules[0]
            if rule is None and content_rules and _has_conflict_markers(absolute):
                rule = content_rules[0]
            if rule is None:
                continue
            findings.append(
                DebrisFinding(relative, rule.rule_id, rule.disposition, rule.rationale, digest, size)
            )
    return findings


def self_audit(module_path: Path | None = None) -> list[str]:
    """Parse this module and report any deletion or in-place mutation call."""
    source_path = module_path or Path(__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    offences: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in PROHIBITED_DELETION_CALLS:
            offences.append(f"line {node.lineno}: prohibited call {name!r}")
        if name == "open":
            for arg in list(node.args[1:]) + [kw.value for kw in node.keywords if kw.arg == "mode"]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and (
                    "w" in arg.value or "a" in arg.value or "+" in arg.value
                ):
                    offences.append(f"line {node.lineno}: writable open mode {arg.value!r}")
    return offences


def build_report(root: Path, findings: list[DebrisFinding], census_violations: list[str]) -> dict:
    by_disposition: dict[str, int] = {}
    for finding in findings:
        by_disposition[finding.disposition] = by_disposition.get(finding.disposition, 0) + 1
    return {
        "component": "transport_debris_disposition",
        "root": str(root),
        "debris_found": len(findings),
        "by_disposition": dict(sorted(by_disposition.items())),
        "deleted": 0,
        "non_destructive": not census_violations,
        "census_violations": census_violations,
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify transport debris without deleting evidence.")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument(
        "--policy",
        choices=("record", "delete"),
        default="record",
        help="'delete' is accepted only so it can be explicitly refused",
    )
    parser.add_argument("--self-audit", action="store_true", help="also assert this module has no deletion path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.policy == "delete":
        print(
            "DELETION_PROHIBITED: PO-03 disposition never deletes evidence; "
            "re-run with --policy record",
            file=sys.stderr,
        )
        return 3
    if not args.root.is_dir():
        print(f"USAGE_ERROR: root is not a directory: {args.root}", file=sys.stderr)
        return 2

    before = census(args.root)
    findings = scan(args.root)
    after = census(args.root)
    violations = verify_census_unchanged(before, after)

    report = build_report(args.root, findings, violations)
    if args.self_audit:
        report["self_audit_offences"] = self_audit()
        report["non_destructive"] = report["non_destructive"] and not report["self_audit_offences"]

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for finding in report["findings"]:
            print(
                f"{finding['disposition']:<18} {finding['rule_id']:<20} {finding['path']}  "
                f"({finding['bytes']} bytes, sha256={finding['sha256'][:16]}...)"
            )
        print(
            f"summary: debris={report['debris_found']} deleted={report['deleted']} "
            f"non_destructive={report['non_destructive']}"
        )
    if not report["non_destructive"]:
        return 1
    return 1 if report["debris_found"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
