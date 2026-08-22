#!/usr/bin/env python3
"""Static hermeticity prober for PO-03 Python sources (unit a3-u02).

Flags the five dependency classes that make a suite pass on a warm developer
checkout and fail in a clean runner: absolute filesystem paths, system
temporary directories, home-directory dependence, ambient environment reads and
outbound network use.

Design notes
------------
The prober reads its detection patterns from ``hermeticity-rules.json`` rather
than embedding them.  A prober whose own source contained the literals it hunts
for would flag itself, and the only escape would be a self-exemption -- exactly
the hole that makes such gates worthless.

Docstrings are not scanned.  Prose that mentions a temporary directory cannot
make a program non-portable, and treating documentation as evidence of
non-portability produces noise that trains reviewers to ignore the gate.
Comments are invisible to the AST and are likewise out of scope.

Directory exclusions apply only to discovery.  A file named explicitly on the
command line is always scanned, which is how the planted non-portable fixtures
are proved to be detected rather than silently skipped.

Dependency-free: standard library only, no network, no environment reads.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

RUNTIME_DIR = Path(__file__).resolve().parent
REPO_ROOT = RUNTIME_DIR.parents[2]
DEFAULT_RULES = RUNTIME_DIR / "hermeticity-rules.json"

REPORT_SCHEMA = "po03-hermeticity-report-v1"


class Finding:
    __slots__ = ("rule", "path", "line", "detail")

    def __init__(self, rule: str, path: str, line: int, detail: str) -> None:
        self.rule = rule
        self.path = path
        self.line = line
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "path": self.path, "line": self.line, "detail": self.detail}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Finding({self.rule}, {self.path}:{self.line})"


def load_rules(rules_path: Path) -> dict[str, Any]:
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    if rules.get("schema") != "po03-hermeticity-rules-v1":
        raise ValueError(f"unexpected rules schema: {rules.get('schema')!r}")
    for name, rule in rules["rules"].items():
        if "string_regex" in rule:
            rule["_compiled"] = re.compile(rule["string_regex"])
        rule["_calls"] = set(rule.get("calls", []))
        rule["_modules"] = set(rule.get("modules", []))
        rule["_subscripts"] = set(rule.get("subscript_targets", []))
        rule["_name"] = name
    return rules


def dotted_name(node: ast.AST) -> str | None:
    """Render ``a.b.c`` attribute chains and bare names as dotted strings."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def call_aliases(dotted: str) -> set[str]:
    """A call written ``Path.home`` and ``pathlib.Path.home`` is one thing.

    Matching on every dotted suffix makes the rule table independent of how the
    caller happened to import the symbol.
    """
    parts = dotted.split(".")
    return {".".join(parts[index:]) for index in range(len(parts))}


def collect_docstring_nodes(tree: ast.AST) -> set[int]:
    """Identify docstring Constant nodes so prose is never treated as code."""
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.add(id(first.value))
    return docstrings


def scan_source(relative_path: str, source: str, rules: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    try:
        tree = ast.parse(source, filename=relative_path)
    except SyntaxError as exc:
        return [Finding("PARSE_ERROR", relative_path, exc.lineno or 0, str(exc.msg))]

    docstrings = collect_docstring_nodes(tree)
    table = rules["rules"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            for name, rule in table.items():
                compiled = rule.get("_compiled")
                if compiled is not None and compiled.search(node.value):
                    findings.append(Finding(name, relative_path, node.lineno, node.value[:120]))
            continue

        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                for name, rule in table.items():
                    if alias.name in rule["_modules"] or root in rule["_modules"]:
                        findings.append(Finding(name, relative_path, node.lineno, f"import {alias.name}"))
            continue

        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            for name, rule in table.items():
                if module in rule["_modules"] or (root and root in rule["_modules"]):
                    findings.append(Finding(name, relative_path, node.lineno, f"from {module} import ..."))
            continue

        if isinstance(node, ast.Call):
            dotted = dotted_name(node.func)
            if dotted is None:
                continue
            aliases = call_aliases(dotted)
            for name, rule in table.items():
                if aliases & rule["_calls"]:
                    findings.append(Finding(name, relative_path, node.lineno, f"{dotted}(...)"))
            continue

        if isinstance(node, ast.Subscript):
            dotted = dotted_name(node.value)
            if dotted is None:
                continue
            aliases = call_aliases(dotted)
            for name, rule in table.items():
                if aliases & rule["_subscripts"]:
                    findings.append(Finding(name, relative_path, node.lineno, f"{dotted}[...]"))

    findings.sort(key=lambda finding: (finding.path, finding.line, finding.rule))
    return findings


def discover(root: Path, rules: dict[str, Any], repo_root: Path) -> list[Path]:
    excluded_names = set(rules.get("excluded_dir_names", []))
    excluded_dirs = {
        (repo_root / relative).resolve() for relative in rules.get("excluded_relative_dirs", [])
    }
    found: list[Path] = []
    for candidate in sorted(root.rglob("*.py")):
        parts = set(candidate.parts)
        if parts & excluded_names:
            continue
        if any(excluded == candidate.parent or excluded in candidate.parents for excluded in excluded_dirs):
            continue
        found.append(candidate)
    return found


def scan_paths(paths: Iterable[Path], rules: dict[str, Any], repo_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        try:
            relative = str(path.resolve().relative_to(repo_root))
        except ValueError:
            relative = str(path)
        findings.extend(scan_source(relative, path.read_text(encoding="utf-8"), rules))
    return findings


def build_report(paths: list[Path], findings: list[Finding], rules: dict[str, Any]) -> dict[str, Any]:
    by_rule: dict[str, int] = {}
    for finding in findings:
        by_rule[finding.rule] = by_rule.get(finding.rule, 0) + 1
    return {
        "schema": REPORT_SCHEMA,
        "rules_available": sorted(rules["rules"]),
        "scanned_file_count": len(paths),
        "finding_count": len(findings),
        "findings_by_rule": by_rule,
        "findings": [finding.as_dict() for finding in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PO-03 static hermeticity prober")
    parser.add_argument(
        "paths",
        nargs="*",
        help="explicit files or directories to scan (default: the scan root from the rules file)",
    )
    parser.add_argument("--rules", default=str(DEFAULT_RULES))
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    rules = load_rules(Path(args.rules))

    targets: list[Path] = []
    if args.paths:
        for raw in args.paths:
            candidate = Path(raw)
            if candidate.is_dir():
                targets.extend(discover(candidate, rules, repo_root))
            else:
                # Explicit files bypass directory exclusions on purpose.
                targets.append(candidate)
    else:
        targets = discover(repo_root / rules["scan_root"], rules, repo_root)

    findings = scan_paths(targets, rules, repo_root)
    report = build_report(targets, findings, rules)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for finding in findings:
            print(f"{finding.rule}: {finding.path}:{finding.line}: {finding.detail}")
        if findings:
            print(f"FAIL {len(findings)} hermeticity finding(s) across {len(targets)} file(s)")
        else:
            print(f"PASS 0 hermeticity findings across {len(targets)} file(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
