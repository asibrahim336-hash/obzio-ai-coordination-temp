#!/usr/bin/env python3
"""Static control for hidden local-state assumptions, for PO03-WA-024.

The differential harness in ``clean_runner_probe.py`` finds hidden local-state
dependence by execution.  This module finds the same classes by inspection, so
the defects can be blocked before a clean runner ever executes them.

Rules
-----
``R1_UNRESOLVABLE_OBJECT_ID``
    A forty-character hex identifier recorded in a scanned file does not name an
    object in this repository.  Three subclasses are distinguished, because they
    carry different weight.  ``PREFIX_ONLY_CORRECT`` is an error: a warm object
    store resolves the abbreviation, so the identifier looks verifiable while the
    recorded forty-character value is wrong and no clean runner can check it.
    ``UNKNOWN_OBJECT`` is a warning, because an identifier that resolves nowhere
    locally may legitimately name an object in another repository.
    ``EXTERNAL_DECLARED`` is informational and covers identifiers the caller has
    declared, with a reason, in an external-identifier allowlist.

``R2_HISTORY_DEPENDENT_WITHOUT_FULL_FETCH``
    A workflow job runs a git command that needs history while its
    ``actions/checkout`` step leaves ``fetch-depth`` at the default of 1.

``R3_BARE_INTERPRETER_WITHOUT_SETUP``
    A workflow job runs a bare interpreter name that only a setup action puts on
    ``PATH``, without that setup action in the same job.

``R4_HOST_ABSOLUTE_PATH``
    A scanned executable file hard-codes a host-absolute path that does not exist
    on a runner.  A line carrying the marker ``local-state-lint: allow`` followed
    by the rule name is exempt, so a file whose purpose is to *name* these
    patterns can declare that intent instead of being reported.

``R5_UNTRACKED_REFERENCED_PATH``
    A workflow step or declared probe names a repository-relative file that is
    not tracked at the scanned commit, so it exists only in a warm checkout.

Only the standard library is used.  Workflow YAML is read with a deliberately
small subset parser (see ``parse_yaml_subset``) rather than a third-party
dependency, because the control must run on a bare runner.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HEX40 = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{40}(?![0-9a-fA-F])")

HISTORY_DEPENDENT_GIT = (
    "merge-base",
    "rev-list",
    "git log",
    "describe",
    "for-each-ref",
    "cat-file",
    "shortlog",
    "cherry",
    "bisect",
)

SETUP_ACTION_INTERPRETERS = {
    "python": "actions/setup-python",
    "node": "actions/setup-node",
    "go": "actions/setup-go",
}

HOST_ABSOLUTE_PATHS = (
    "/workspace/",  # local-state-lint: allow R4_HOST_ABSOLUTE_PATH
    "/home/ubuntu/",  # local-state-lint: allow R4_HOST_ABSOLUTE_PATH
    "/Users/",  # local-state-lint: allow R4_HOST_ABSOLUTE_PATH
)

SUPPRESSION = re.compile(r"local-state-lint:\s*allow\s+([A-Z0-9_]+)")

SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


# ---------------------------------------------------------------------------
# Minimal YAML subset parser
# ---------------------------------------------------------------------------


def _scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        return ""
    if text[0] in "\"'" and text[-1] == text[0] and len(text) >= 2:
        return text[1:-1]
    if text in {"true", "True"}:
        return True
    if text in {"false", "False"}:
        return False
    if text in {"null", "~"}:
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [_scalar(part) for part in inner.split(",")] if inner else []
    return text


def _strip_comment(line: str) -> str:
    out: list[str] = []
    quote: str | None = None
    for index, char in enumerate(line):
        if quote:
            out.append(char)
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            out.append(char)
            continue
        if char == "#" and (index == 0 or line[index - 1] in " \t"):
            break
        out.append(char)
    return "".join(out).rstrip()


def parse_yaml_subset(text: str) -> Any:
    """Parse the GitHub-workflow subset of YAML: nested maps, sequences of maps,
    plain scalars, quoted scalars and ``|``/``>`` block scalars.

    Anchors, aliases, flow mappings, multi-document streams and tags are not
    supported; :func:`parse_yaml_subset` raises ``ValueError`` for anchors and
    aliases rather than silently mis-parsing them.
    """
    raw = text.expandtabs(2).splitlines()
    lines: list[tuple[int, str]] = []
    index = 0
    while index < len(raw):
        line = raw[index]
        stripped = _strip_comment(line)
        if not stripped.strip():
            index += 1
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        body = stripped.strip()
        if body.startswith("---") or body.startswith("..."):
            index += 1
            continue
        if re.search(r"(^|\s)[&*][A-Za-z0-9_-]+", body):
            raise ValueError(f"unsupported YAML anchor or alias: {body!r}")
        match = re.match(r"^(-\s+)?([^:]+):\s*([|>][-+]?)\s*$", body)
        if match:
            block_indent = None
            collected: list[str] = []
            probe = index + 1
            while probe < len(raw):
                candidate = raw[probe]
                if not candidate.strip():
                    collected.append("")
                    probe += 1
                    continue
                candidate_indent = len(candidate) - len(candidate.lstrip(" "))
                if candidate_indent <= indent:
                    break
                if block_indent is None:
                    block_indent = candidate_indent
                collected.append(candidate[block_indent:])
                probe += 1
            joiner = "\n" if match.group(3).startswith("|") else " "
            value = joiner.join(collected).strip("\n")
            prefix = match.group(1) or ""
            lines.append((indent, f"{prefix}{match.group(2)}: \x00{value}"))
            index = probe
            continue
        lines.append((indent, body))
        index += 1

    def build(pos: int, indent: int) -> tuple[Any, int]:
        if pos >= len(lines):
            return None, pos
        if lines[pos][1].startswith("- "):
            items: list[Any] = []
            while pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
                head_indent, body = lines[pos]
                remainder = body[2:]
                if ":" in remainder and not remainder.startswith("\x00"):
                    item_indent = head_indent + 2
                    lines[pos] = (item_indent, remainder)
                    value, pos = build(pos, item_indent)
                    items.append(value)
                else:
                    items.append(_scalar(remainder))
                    pos += 1
            return items, pos
        mapping: dict[str, Any] = {}
        while pos < len(lines) and lines[pos][0] == indent:
            body = lines[pos][1]
            if body.startswith("- "):
                break
            if ":" not in body:
                pos += 1
                continue
            key, _, rest = body.partition(":")
            key = _scalar(key)
            rest = rest.strip()
            if rest.startswith("\x00"):
                mapping[str(key)] = rest[1:]
                pos += 1
            elif rest:
                mapping[str(key)] = _scalar(rest)
                pos += 1
            else:
                pos += 1
                if pos < len(lines) and lines[pos][0] > indent:
                    value, pos = build(pos, lines[pos][0])
                    mapping[str(key)] = value
                else:
                    mapping[str(key)] = None
        return mapping, pos

    value, _ = build(0, lines[0][0] if lines else 0)
    return value


# ---------------------------------------------------------------------------
# Repository access
# ---------------------------------------------------------------------------


class Repo:
    def __init__(self, root: Path, commit: str = "HEAD") -> None:
        self.root = root.resolve()
        self.commit = self._run(["rev-parse", commit]).strip()
        self._tracked: set[str] | None = None
        self._object_cache: dict[str, bool] = {}
        self._prefix_cache: dict[str, str | None] = {}

    def _run(self, args: list[str], check: bool = True) -> str:
        proc = subprocess.run(["git", *args], cwd=str(self.root), capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
        return proc.stdout

    @property
    def shallow(self) -> bool:
        return (self.root / ".git" / "shallow").exists()

    @property
    def tracked(self) -> set[str]:
        if self._tracked is None:
            listing = self._run(["ls-tree", "-r", "--name-only", self.commit])
            self._tracked = {line for line in listing.splitlines() if line}
        return self._tracked

    def object_exists(self, oid: str) -> bool:
        if oid not in self._object_cache:
            proc = subprocess.run(
                ["git", "cat-file", "-e", f"{oid}^{{object}}"],
                cwd=str(self.root),
                capture_output=True,
                text=True,
            )
            self._object_cache[oid] = proc.returncode == 0
        return self._object_cache[oid]

    def resolve_prefix(self, prefix: str) -> str | None:
        if prefix not in self._prefix_cache:
            proc = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", prefix],
                cwd=str(self.root),
                capture_output=True,
                text=True,
            )
            self._prefix_cache[prefix] = proc.stdout.strip() or None
        return self._prefix_cache[prefix]

    def read(self, path: str) -> str:
        return self._run(["show", f"{self.commit}:{path}"])


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _finding(
    rule: str, path: str, detail: str, severity: str = "error", **extra: Any
) -> dict[str, Any]:
    row = {"rule": rule, "path": path, "detail": detail, "severity": severity}
    row.update(extra)
    return row


def rule_object_ids(
    repo: Repo, paths: list[str], external: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    external = external or {}
    if repo.shallow:
        return [
            _finding(
                "R1_UNRESOLVABLE_OBJECT_ID",
                "<repository>",
                "NOT_SUPPORTED: the scanned repository is shallow, so object identifiers cannot be "
                "verified. Re-run against a full-history clone.",
                severity="info",
                subclass="NOT_SUPPORTED_SHALLOW_REPOSITORY",
            )
        ]
    findings: list[dict[str, Any]] = []
    for path in paths:
        try:
            text = repo.read(path)
        except RuntimeError:
            continue
        for oid in sorted(set(HEX40.findall(text))):
            if repo.object_exists(oid):
                continue
            resolved = repo.resolve_prefix(oid[:7])
            if resolved and resolved != oid:
                subclass, severity = "PREFIX_ONLY_CORRECT", "error"
                detail = (
                    f"recorded identifier {oid} names no object, but its prefix {oid[:7]} resolves to "
                    f"{resolved}; a warm full-history checkout makes the abbreviation appear valid"
                )
            elif oid in external:
                subclass, severity = "EXTERNAL_DECLARED", "info"
                detail = (
                    f"identifier {oid} is declared as belonging to another repository: {external[oid]}"
                )
            else:
                subclass, severity = "UNKNOWN_OBJECT", "warning"
                detail = (
                    f"recorded identifier {oid} names no object in this repository; it is either wrong "
                    "or belongs to another repository and has not been declared as external"
                )
            findings.append(
                _finding(
                    "R1_UNRESOLVABLE_OBJECT_ID",
                    path,
                    detail,
                    severity=severity,
                    subclass=subclass,
                    recorded_object_id=oid,
                    prefix_resolves_to=resolved,
                )
            )
    return findings


def _workflow_jobs(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict):
        return {}
    jobs = doc.get("jobs")
    return jobs if isinstance(jobs, dict) else {}


def _steps(job: Any) -> list[dict[str, Any]]:
    if not isinstance(job, dict):
        return []
    steps = job.get("steps")
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, dict)]


def rule_history_depth(path: str, doc: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for job_id, job in sorted(_workflow_jobs(doc).items()):
        steps = _steps(job)
        checkouts = [step for step in steps if str(step.get("uses", "")).startswith("actions/checkout")]
        if not checkouts:
            continue
        full_history = any(
            str((step.get("with") or {}).get("fetch-depth", "")) == "0" for step in checkouts
        )
        if full_history:
            continue
        for step in steps:
            run = step.get("run")
            if not isinstance(run, str):
                continue
            hits = sorted({token for token in HISTORY_DEPENDENT_GIT if token in run})
            if hits:
                findings.append(
                    _finding(
                        "R2_HISTORY_DEPENDENT_WITHOUT_FULL_FETCH",
                        path,
                        f"job '{job_id}' runs history-dependent git commands {hits} while "
                        "actions/checkout leaves fetch-depth at its default of 1",
                        job=job_id,
                        commands=hits,
                    )
                )
    return findings


def rule_bare_interpreter(path: str, doc: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for job_id, job in sorted(_workflow_jobs(doc).items()):
        steps = _steps(job)
        uses = {str(step.get("uses", "")).split("@")[0] for step in steps}
        for interpreter, setup in sorted(SETUP_ACTION_INTERPRETERS.items()):
            pattern = re.compile(rf"(?<![\w./-]){re.escape(interpreter)}(?![\w.-])")
            for step in steps:
                run = step.get("run")
                if not isinstance(run, str) or not pattern.search(run):
                    continue
                severity = "info" if setup in uses else "warning"
                detail = (
                    f"job '{job_id}' runs bare '{interpreter}'; this resolves only because {setup} "
                    "is present in the same job, so the command is not portable outside Actions"
                    if setup in uses
                    else f"job '{job_id}' runs bare '{interpreter}' without {setup} in the same job"
                )
                findings.append(
                    _finding(
                        "R3_BARE_INTERPRETER_WITHOUT_SETUP",
                        path,
                        detail,
                        severity=severity,
                        job=job_id,
                        interpreter=interpreter,
                        setup_action=setup,
                        setup_present=setup in uses,
                    )
                )
                break
    return findings


def rule_host_paths(repo: Repo, paths: list[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in paths:
        if not path.endswith((".py", ".sh", ".yml", ".yaml")):
            continue
        try:
            text = repo.read(path)
        except RuntimeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            allowed = {match for match in SUPPRESSION.findall(line)}
            if "R4_HOST_ABSOLUTE_PATH" in allowed:
                continue
            for needle in HOST_ABSOLUTE_PATHS:
                if needle in line:
                    findings.append(
                        _finding(
                            "R4_HOST_ABSOLUTE_PATH",
                            path,
                            f"line {number} hard-codes host-absolute path prefix '{needle}'",
                            severity="warning",
                            line=number,
                            prefix=needle,
                        )
                    )
    return findings


def rule_untracked_references(repo: Repo, path: str, doc: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    candidate = re.compile(r"(?<![\w./-])((?:[\w.-]+/)+[\w.-]+\.(?:py|sh|json|yml|yaml))")
    for job_id, job in sorted(_workflow_jobs(doc).items()):
        for step in _steps(job):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            for reference in sorted(set(candidate.findall(run))):
                if reference.startswith((".", "/")) or reference in repo.tracked:
                    continue
                if any(tracked.startswith(reference.rstrip("/") + "/") for tracked in repo.tracked):
                    continue
                findings.append(
                    _finding(
                        "R5_UNTRACKED_REFERENCED_PATH",
                        path,
                        f"job '{job_id}' references '{reference}', which is not tracked at "
                        f"{repo.commit[:12]}",
                        job=job_id,
                        reference=reference,
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def load_external_object_ids(path: Path) -> dict[str, str]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc["external_object_ids"] if isinstance(doc, dict) else doc
    declared: dict[str, str] = {}
    for row in rows:
        if not HEX40.fullmatch(row["object_id"]):
            raise RuntimeError(f"{path}: not a lowercase forty-character object id: {row['object_id']}")
        if not str(row.get("why", "")).strip():
            raise RuntimeError(f"{path}: declaration for {row['object_id']} needs a 'why'")
        declared[row["object_id"]] = f"{row.get('repository', 'unspecified')} ({row['why']})"
    return declared


def lint(
    repo_root: Path,
    commit: str = "HEAD",
    scan_globs: tuple[str, ...] = ("workstreams/po03/", "receipts/po03/", ".github/workflows/"),
    workflow_prefix: str = ".github/workflows/",
    external_object_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    repo = Repo(repo_root, commit)
    scanned = sorted(
        path for path in repo.tracked if any(path.startswith(prefix) for prefix in scan_globs)
    )
    workflows = sorted(
        path for path in repo.tracked if path.startswith(workflow_prefix) and path.endswith((".yml", ".yaml"))
    )

    findings: list[dict[str, Any]] = []
    findings.extend(rule_object_ids(repo, scanned, external_object_ids))
    parse_errors: list[dict[str, str]] = []
    for path in workflows:
        try:
            doc = parse_yaml_subset(repo.read(path))
        except (ValueError, RuntimeError) as exc:
            parse_errors.append({"path": path, "error": str(exc)})
            continue
        findings.extend(rule_history_depth(path, doc))
        findings.extend(rule_bare_interpreter(path, doc))
        findings.extend(rule_untracked_references(repo, path, doc))
    findings.extend(rule_host_paths(repo, scanned))

    findings.sort(key=lambda row: (row["rule"], row["path"], row.get("detail", "")))
    counts: dict[str, int] = {}
    for row in findings:
        counts[row["rule"]] = counts.get(row["rule"], 0) + 1
    return {
        "protocol_version": "PO03-WA-024-LOCAL-STATE-LINT-v1",
        "repository_commit": repo.commit,
        "repository_shallow": repo.shallow,
        "declared_external_object_ids": sorted(external_object_ids or {}),
        "scanned_file_count": len(scanned),
        "workflow_count": len(workflows),
        "workflow_parse_errors": parse_errors,
        "findings": findings,
        "counts_by_rule": dict(sorted(counts.items())),
        "counts_by_severity": {
            severity: sum(1 for row in findings if row["severity"] == severity)
            for severity in ("error", "warning", "info")
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--json", dest="json_out", type=Path, default=None)
    parser.add_argument("--fail-on", choices=("error", "warning", "info", "never"), default="error")
    parser.add_argument(
        "--allow-external-object-ids",
        type=Path,
        default=None,
        help="JSON file declaring object ids that belong to another repository, each with a reason",
    )
    args = parser.parse_args(argv)

    try:
        external = (
            load_external_object_ids(args.allow_external_object_ids)
            if args.allow_external_object_ids
            else {}
        )
        report = lint(args.repo, args.commit, external_object_ids=external)
    except (RuntimeError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"LINT ERROR: {exc}", file=sys.stderr)
        return 2

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)

    for row in report["findings"]:
        print(f"{row['severity'].upper()} {row['rule']} {row['path']}: {row['detail']}", file=sys.stderr)
    print(
        "LOCAL STATE LINT: {n} findings across {f} files ({c})".format(
            n=len(report["findings"]),
            f=report["scanned_file_count"],
            c=report["counts_by_severity"],
        ),
        file=sys.stderr,
    )
    if args.fail_on == "never":
        return 0
    threshold = SEVERITY_ORDER[args.fail_on]
    if any(SEVERITY_ORDER[row["severity"]] >= threshold for row in report["findings"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
