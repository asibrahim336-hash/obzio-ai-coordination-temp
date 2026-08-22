#!/usr/bin/env python3
"""Resolve prohibited colloquial routing aliases to durable function/appointment IDs.

FALSIFIABLE HYPOTHESIS (task po03-wa-b2e7-011-alias-resolution):
    Colloquial actor aliases can be resolved to a durable function and
    appointment, or explicitly refused, without global text replacement.

AGENTS.md rule 4 names `Operator D`, `Claude extension`,
`Claude browser operator`, `principal AI operator` "and similar" as
historical/colloquial aliases prohibited for *active routing*, permitted
only "inside explicit alias, runtime or provenance fields".

This module:
  1. Loads the committed alias register
     (state/operator-system/OPERATOR_ALIAS_REGISTER.jsonl) as the sole
     source of truth mapping an alias string to a target_type/target_id.
     It never invents a mapping that is not in the register.
  2. Scans committed JSON/JSONL documents for literal occurrences of a
     given set of alias strings and classifies each occurrence's
     containing field as ALLOWED (name matches alias/runtime/provenance)
     or FLAGGED (routing-shaped field name; occurrence is not a rewrite,
     just a report).
  3. Reports every alias occurrence that has no register entry as
     "unresolved" rather than guessing a target -- this is the "explicitly
     refused" branch of the hypothesis.

It never mutates the scanned files: no global text replacement is ever
performed by this module.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ALIAS_REGISTER_PATH = "state/operator-system/OPERATOR_ALIAS_REGISTER.jsonl"

# Field-name patterns permitted to carry a prohibited alias verbatim under
# AGENTS.md rule 4 ("alias, runtime or provenance fields").
_ALLOWED_FIELD_RE = re.compile(
    r"alias|runtime|provenance|recorded_by|identity_note|identity_verification|execution_record",
    re.IGNORECASE,
)


class AliasRegisterError(Exception):
    """Raised when the alias register itself cannot be loaded (fail-closed)."""


def load_alias_register(repo_root: Path, register_path: str = ALIAS_REGISTER_PATH) -> list[dict[str, Any]]:
    path = Path(repo_root) / register_path
    if not path.is_file():
        raise AliasRegisterError(f"alias register missing: {register_path}")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AliasRegisterError(f"invalid jsonl at {register_path}:{number}: {exc}") from exc
    return rows


def resolve_alias(register: list[dict[str, Any]], alias_text: str) -> dict[str, Any] | None:
    """Look up `alias_text` (case-insensitive, exact string match) in the
    register. Returns the register row (carrying target_type/target_id/
    status/replacement) or None if unresolved. Never fabricates a target."""
    needle = alias_text.strip().lower()
    for row in register:
        if str(row.get("alias", "")).strip().lower() == needle:
            return row
    return None


def is_allowed_field(field_path: str) -> bool:
    return bool(_ALLOWED_FIELD_RE.search(field_path))


def _walk(node: Any, path: list[str], filepath: str, aliases: list[str], out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            _walk(value, path + [key], filepath, aliases, out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk(value, path + [f"[{index}]"], filepath, aliases, out)
    elif isinstance(node, str):
        field_path = ".".join(path)
        for alias in aliases:
            if alias.lower() in node.lower():
                out.append(
                    {
                        "file": filepath,
                        "field_path": field_path,
                        "alias": alias,
                        "snippet": node[:160],
                        "field_allowed": is_allowed_field(field_path),
                    }
                )


def scan_repository(
    repo_root: Path,
    aliases: list[str],
    scan_glob: str = "**/*.json*",
) -> list[dict[str, Any]]:
    """Find every literal occurrence of any alias in `aliases` inside
    committed JSON/JSONL files under repo_root, returning one entry per
    occurrence with its field-context classification. Read-only: never
    writes to any scanned file."""
    repo_root = Path(repo_root)
    occurrences: list[dict[str, Any]] = []
    for file_path in sorted(repo_root.glob(scan_glob)):
        if not file_path.is_file() or ".git" in file_path.parts:
            continue
        rel = file_path.relative_to(repo_root).as_posix()
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if file_path.suffix == ".jsonl":
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                _walk(record, [], rel, aliases, occurrences)
        else:
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                continue
            _walk(record, [], rel, aliases, occurrences)
    return occurrences


def build_report(repo_root: Path, aliases: list[str]) -> dict[str, Any]:
    register = load_alias_register(repo_root)
    occurrences = scan_repository(repo_root, aliases)

    resolved: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []
    for alias in aliases:
        row = resolve_alias(register, alias)
        if row is None:
            unresolved.append(alias)
        else:
            resolved[alias] = {
                "target_type": row.get("target_type"),
                "target_id": row.get("target_id"),
                "status": row.get("status"),
                "replacement": row.get("replacement"),
            }

    flagged = [occ for occ in occurrences if not occ["field_allowed"]]
    allowed = [occ for occ in occurrences if occ["field_allowed"]]

    return {
        "aliases_checked": aliases,
        "register_entries": len(register),
        "resolved": resolved,
        "unresolved": unresolved,
        "occurrence_count": len(occurrences),
        "allowed_field_occurrences": allowed,
        "flagged_field_occurrences": flagged,
        "mutated_files": [],
    }


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[4]
    default_aliases = [
        "Operator D",
        "Claude extension",
        "Claude browser operator",
        "principal AI operator",
    ]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(default_root))
    parser.add_argument("--alias", action="append", dest="aliases", default=None)
    args = parser.parse_args(argv)
    aliases = args.aliases or default_aliases

    try:
        report = build_report(Path(args.repo_root), aliases)
    except AliasRegisterError as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "reason": str(exc)}, indent=2, sort_keys=True))
        return 1

    print(json.dumps({"status": "RESOLVED", **report}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
