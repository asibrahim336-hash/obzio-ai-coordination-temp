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

Precision comes from syntactic role, not from a forgiven-value list.  A string
literal is a portability defect only when the program uses it as a path; a
literal that is compared against, asserted on, matched as a pattern or carried
as data is a string under test.  Each exempted literal is retained in the report
with the role that exempted it, so a suppression is always visible and can be
argued with.  A value allowlist was rejected: it grows without bound and it
forgives a real defect that happens to share a spelling with a fixture.

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
    __slots__ = ("rule", "path", "line", "detail", "exempt_role", "severity")

    def __init__(
        self,
        rule: str,
        path: str,
        line: int,
        detail: str,
        exempt_role: str | None = None,
        severity: str = "high",
    ) -> None:
        self.rule = rule
        self.path = path
        self.line = line
        self.detail = detail
        self.exempt_role = exempt_role
        self.severity = severity

    @property
    def reportable(self) -> bool:
        """A finding fails the gate only when nothing exempts it and it is not advisory."""
        return self.exempt_role is None and self.severity != "advisory"

    def as_dict(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "rule": self.rule,
            "path": self.path,
            "line": self.line,
            "detail": self.detail,
            "severity": self.severity,
        }
        if self.exempt_role is not None:
            record["exempt_role"] = self.exempt_role
        return record

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
    roles = rules.setdefault("literal_roles", {})
    roles["_string_methods"] = set(roles.get("string_operation_methods", []))
    roles["_regex"] = set(roles.get("regex_functions", []))
    roles["_sinks"] = set(roles.get("filesystem_sinks", []))
    roles["_io_methods"] = set(roles.get("path_io_methods", []))
    roles["_assert_prefixes"] = tuple(roles.get("assertion_prefixes", []))
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


DIFF_MARKERS = ("--- ", "+++ ", "@@")


def parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def ancestors(node: ast.AST, parents: dict[int, ast.AST]) -> list[ast.AST]:
    chain: list[ast.AST] = []
    current = parents.get(id(node))
    while current is not None:
        chain.append(current)
        current = parents.get(id(current))
    return chain


def is_diff_payload(text: str) -> bool:
    """A literal that is itself a unified diff carries a change, not a path."""
    lines = text.splitlines()
    if len(lines) < 2:
        return False
    return sum(1 for line in lines if line.startswith(DIFF_MARKERS)) >= 2


def anchored_names(tree: ast.AST) -> set[str]:
    """Module-level names whose value derives, transitively, from ``__file__``.

    A directory computed from ``__file__`` is inside the clone by construction,
    so a clean clone always has it.  Resolution iterates to a fixed point
    because these roots are usually defined in a chain: ``PO03 = HERE.parents[1]``.
    """
    assignments: dict[str, ast.AST] = {}
    for statement in getattr(tree, "body", []):
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            targets = [statement.target]
            value = statement.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                assignments[target.id] = value

    anchored: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, value in assignments.items():
            if name in anchored:
                continue
            if expression_is_anchored(value, anchored):
                anchored.add(name)
                changed = True
    return anchored


def expression_is_anchored(node: ast.AST, anchored: set[str]) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name):
            if inner.id == "__file__" or inner.id in anchored:
                return True
    return False


def pattern_table_literals(tree: ast.AST, roles: dict[str, Any]) -> set[int]:
    """Literals in a module-level collection used only for comparison.

    A detector that keeps its table of forbidden prefixes in Python rather than
    in data is holding patterns, not paths.  The table is exempt only when every
    load of its name in the module sits in comparison position, so a table that
    is also opened still fires.
    """
    tables: dict[str, list[ast.Constant]] = {}
    for statement in getattr(tree, "body", []):
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        value = statement.value
        if not isinstance(target, ast.Name):
            continue
        if not isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            continue
        elements = [
            element
            for element in value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
        if elements and len(elements) == len(value.elts):
            tables[target.id] = elements

    if not tables:
        return set()

    parents = parent_map(tree)
    used_elsewhere: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or node.id not in tables:
            continue
        if isinstance(node.ctx, ast.Store):
            continue
        if comparison_role(node, parents, roles) is None:
            used_elsewhere.add(node.id)

    exempt: set[int] = set()
    for name, elements in tables.items():
        if name in used_elsewhere:
            continue
        exempt.update(id(element) for element in elements)
    return exempt


def sink_reaching_literals(tree: ast.AST, roles: dict[str, Any]) -> set[int]:
    """String literals that reach a filesystem sink, directly or by one binding.

    Taint starts at the arguments of a sink call and spreads backwards to a
    fixed point through module-level bindings and through the return values of
    functions whose result is itself passed to a sink.  That is deliberately
    shallow: it closes the case that matters -- a named scratch directory that
    a test later opens -- without pretending to be a full dataflow analysis.
    A literal laundered through a container and a helper is a stated limit of
    the role classifier, not a claim it makes.
    """
    sinks = roles["_sinks"]
    tainted_names: set[str] = set()
    literals: set[int] = set()

    def absorb(expression: ast.AST) -> None:
        for inner in ast.walk(expression):
            if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                literals.add(id(inner))
            elif isinstance(inner, ast.Name):
                tainted_names.add(inner.id)
            elif isinstance(inner, ast.Call):
                called = dotted_name(inner.func)
                if called is not None:
                    tainted_names.add(called.split(".")[-1])

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = dotted_name(node.func)
        argument_sink = dotted is not None and bool(call_aliases(dotted) & sinks)
        receiver_sink = (
            isinstance(node.func, ast.Attribute) and node.func.attr in roles["_io_methods"]
        )
        if not argument_sink and not receiver_sink:
            continue
        if receiver_sink:
            # Path(SCRATCH).mkdir(): the path acted on is the receiver, and
            # constructing it was pure until this call.
            absorb(node.func.value)
        if argument_sink:
            for argument in node.args:
                absorb(argument)
            for keyword in node.keywords:
                absorb(keyword.value)

    module_bindings: list[tuple[str, ast.AST]] = []
    functions: list[ast.AST] = []
    for statement in ast.walk(tree):
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    module_bindings.append((target.id, statement.value))
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(statement)

    changed = True
    while changed:
        changed = False
        before = (len(tainted_names), len(literals))
        for name, value in module_bindings:
            if name in tainted_names:
                absorb(value)
        for function in functions:
            if getattr(function, "name", None) not in tainted_names:
                continue
            for inner in ast.walk(function):
                if isinstance(inner, ast.Return) and inner.value is not None:
                    absorb(inner.value)
        if (len(tainted_names), len(literals)) != before:
            changed = True

    return literals


def comparison_role(node: ast.AST, parents: dict[int, ast.AST], roles: dict[str, Any]) -> str | None:
    """Return ``COMPARISON_OPERAND`` when the node sits in string-comparison position."""
    parent = parents.get(id(node))
    # A tuple of alternatives, as in startswith(("a", "b")), is transparent.
    if isinstance(parent, ast.Tuple):
        parent = parents.get(id(parent))
    if isinstance(parent, ast.Compare):
        if all(isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)) for op in parent.ops):
            return "COMPARISON_OPERAND"
        return None
    if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute):
        if parent.func.attr in roles["_string_methods"]:
            return "COMPARISON_OPERAND"
    return None


def literal_role(
    node: ast.Constant,
    parents: dict[int, ast.AST],
    roles: dict[str, Any],
    is_test_module: bool,
    table_literals: set[int],
    sink_literals: set[int],
) -> str | None:
    """Name the syntactic role that exempts this literal, or ``None`` to report it."""
    # The roles divide in two.  First, judgements about what the string *is*:
    # a detector's table, a diff, a JSON Pointer, a fragment that cannot be
    # absolute.  Those hold however the string is used.
    if id(node) in table_literals:
        return "PATTERN_TABLE"

    if is_diff_payload(node.value):
        return "DIFF_PAYLOAD"

    chain = ancestors(node, parents)

    # An f-string piece that follows an interpolation cannot be absolute.
    for index, ancestor in enumerate(chain):
        if isinstance(ancestor, ast.JoinedStr):
            child = node if index == 0 else chain[index - 1]
            position = ancestor.values.index(child) if child in ancestor.values else -1
            if position > 0:
                return "FSTRING_FRAGMENT"
            break

    # An RFC 6902 operation addresses a document, not a filesystem.
    parent = parents.get(id(node))
    if isinstance(parent, ast.Dict) and node in parent.values:
        keys = {
            key.value
            for key in parent.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        index = parent.values.index(node)
        key_node = parent.keys[index]
        named = isinstance(key_node, ast.Constant) and key_node.value == "path"
        if named and "op" in keys:
            return "JSON_POINTER"

    # Second, judgements about how the string is *used* -- and a literal that
    # reaches a filesystem call is a path in use whatever surrounds it.  The
    # sink check therefore outranks every positional role: wrapping
    # os.path.exists("/srv/x") in an assertion does not make /srv/x data.
    if id(node) in sink_literals:
        return None

    direct = comparison_role(node, parents, roles)
    if direct is not None:
        return direct

    for ancestor in chain:
        if not isinstance(ancestor, ast.Call):
            continue
        dotted = dotted_name(ancestor.func)
        if dotted is None:
            continue
        if call_aliases(dotted) & roles["_regex"]:
            return "REGEX_PATTERN"
        if isinstance(ancestor.func, ast.Attribute) and ancestor.func.attr.startswith(
            roles["_assert_prefixes"]
        ):
            return "ASSERTION_OPERAND"

    if any(isinstance(ancestor, ast.Assert) for ancestor in chain):
        return "ASSERTION_OPERAND"

    # In a test module the literals are the material of the test.  What makes
    # one a defect is not where it sits but whether the code acts on it, so the
    # exemption is withdrawn exactly when the literal reaches a sink.
    if is_test_module and id(node) not in sink_literals:
        return "TEST_FIXTURE"
    return None


def sys_path_argument_is_anchored(node: ast.Call, anchored: set[str]) -> bool:
    return any(expression_is_anchored(argument, anchored) for argument in node.args)


def scan_source(relative_path: str, source: str, rules: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    try:
        tree = ast.parse(source, filename=relative_path)
    except SyntaxError as exc:
        return [Finding("PARSE_ERROR", relative_path, exc.lineno or 0, str(exc.msg))]

    docstrings = collect_docstring_nodes(tree)
    table = rules["rules"]
    roles = rules["literal_roles"]
    parents = parent_map(tree)
    anchored = anchored_names(tree)
    table_literals = pattern_table_literals(tree, roles)
    sink_literals = sink_reaching_literals(tree, roles)
    is_test_module = Path(relative_path).match(roles.get("test_module_glob", "test_*.py"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            role: str | None | bool = False
            for name, rule in table.items():
                compiled = rule.get("_compiled")
                if compiled is None or not compiled.search(node.value):
                    continue
                if role is False:
                    role = literal_role(
                        node, parents, roles, is_test_module, table_literals, sink_literals
                    )
                findings.append(
                    Finding(
                        name,
                        relative_path,
                        node.lineno,
                        node.value[:120],
                        exempt_role=role or None,
                        severity=rule.get("severity", "high"),
                    )
                )
            continue

        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
            for name, rule in table.items():
                if alias.name in rule["_modules"] or root in rule["_modules"]:
                    findings.append(
                        Finding(
                            name,
                            relative_path,
                            node.lineno,
                            f"import {alias.name}",
                            severity=rule.get("severity", "high"),
                        )
                    )
            continue

        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            for name, rule in table.items():
                if module in rule["_modules"] or (root and root in rule["_modules"]):
                    findings.append(
                        Finding(
                            name,
                            relative_path,
                            node.lineno,
                            f"from {module} import ...",
                            severity=rule.get("severity", "high"),
                        )
                    )
            continue

        if isinstance(node, ast.Call):
            dotted = dotted_name(node.func)
            if dotted is None:
                continue
            aliases = call_aliases(dotted)
            for name, rule in table.items():
                if not aliases & rule["_calls"]:
                    continue
                downgrade = rule.get("anchored_argument_downgrades_to")
                if downgrade and sys_path_argument_is_anchored(node, anchored):
                    downgraded = table.get(downgrade, {})
                    findings.append(
                        Finding(
                            downgrade,
                            relative_path,
                            node.lineno,
                            f"{dotted}(...) anchored to __file__",
                            severity=downgraded.get("severity", "advisory"),
                        )
                    )
                    continue
                findings.append(
                    Finding(
                        name,
                        relative_path,
                        node.lineno,
                        f"{dotted}(...)",
                        severity=rule.get("severity", "high"),
                    )
                )
            continue

        if isinstance(node, ast.Subscript):
            dotted = dotted_name(node.value)
            if dotted is None:
                continue
            aliases = call_aliases(dotted)
            for name, rule in table.items():
                if aliases & rule["_subscripts"]:
                    findings.append(
                        Finding(
                            name,
                            relative_path,
                            node.lineno,
                            f"{dotted}[...]",
                            severity=rule.get("severity", "high"),
                        )
                    )

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
    reportable = [finding for finding in findings if finding.reportable]
    exempt = [finding for finding in findings if finding.exempt_role is not None]
    advisory = [
        finding
        for finding in findings
        if finding.exempt_role is None and finding.severity == "advisory"
    ]
    by_rule: dict[str, int] = {}
    for finding in reportable:
        by_rule[finding.rule] = by_rule.get(finding.rule, 0) + 1
    by_role: dict[str, int] = {}
    for finding in exempt:
        assert finding.exempt_role is not None
        by_role[finding.exempt_role] = by_role.get(finding.exempt_role, 0) + 1
    return {
        "schema": REPORT_SCHEMA,
        "rules_available": sorted(rules["rules"]),
        "scanned_file_count": len(paths),
        "finding_count": len(reportable),
        "findings_by_rule": by_rule,
        "findings": [finding.as_dict() for finding in reportable],
        # Every suppression is retained so that a reviewer can dispute it.  A
        # gate whose exemptions are invisible cannot be audited.
        "exempt_count": len(exempt),
        "exempt_by_role": by_role,
        "exempt": [finding.as_dict() for finding in exempt],
        "advisory_count": len(advisory),
        "advisory": [finding.as_dict() for finding in advisory],
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
    parser.add_argument(
        "--show-exempt",
        action="store_true",
        help="also print literals a syntactic role exempted, and advisory findings",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    rules = load_rules(Path(args.rules))

    targets: list[Path] = []
    if args.paths:
        for raw in args.paths:
            candidate = Path(raw)
            if candidate.is_dir():
                # Resolved first: discover() compares against absolute excluded
                # directories, so a relative argument silently matched nothing
                # and pulled the planted fixtures into an ordinary scan.
                targets.extend(discover(candidate.resolve(), rules, repo_root))
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
        for record in report["findings"]:
            print(f"{record['rule']}: {record['path']}:{record['line']}: {record['detail']}")
        if args.show_exempt:
            for record in report["exempt"]:
                print(
                    f"exempt[{record['exempt_role']}]: {record['rule']}: "
                    f"{record['path']}:{record['line']}: {record['detail']}"
                )
            for record in report["advisory"]:
                print(
                    f"advisory: {record['rule']}: {record['path']}:{record['line']}: "
                    f"{record['detail']}"
                )
        summary = (
            f"{len(targets)} file(s), {report['exempt_count']} exempt by role, "
            f"{report['advisory_count']} advisory"
        )
        if report["findings"]:
            print(f"FAIL {report['finding_count']} hermeticity finding(s) across {summary}")
        else:
            print(f"PASS 0 hermeticity findings across {summary}")
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
