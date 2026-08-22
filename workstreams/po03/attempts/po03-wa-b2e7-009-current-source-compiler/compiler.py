#!/usr/bin/env python3
"""Compile the current operator route into an explicit ordered current-source set.

FALSIFIABLE HYPOTHESIS (task po03-wa-b2e7-009-current-source-compiler):
    The current operator route can be compiled mechanically from repository
    pointers rather than inferred from filenames.

This module never guesses a "current" file from its filename (e.g. by
preferring the highest version suffix or a literal "CURRENT" token). It only
follows two named, structured sources:

    1. `operations/README.md`      -- the "Read in this order" list, parsed
                                       from its numbered/backtick markup.
    2. `<stack_path>`               -- `resolve_in_order` inside the active
                                       instruction stack JSON document.

It fails closed (raises CurrentSourceCompilationError) when either source is
missing, unreadable, unparsable, or when a path either source names does not
exist on disk. It does NOT fail closed merely because the two sources
disagree with each other; that disagreement is real, structured evidence and
is reported explicitly instead of being silently reconciled or hidden.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


class CurrentSourceCompilationError(Exception):
    """Raised when the pointer chain cannot be resolved: a fail-closed signal."""


README_PATH = "operations/README.md"
STACK_PATH = "state/operator-system/ACTIVE_INSTRUCTION_STACK.json"

# Matches lines like: "1. `state/ACTIVE_CONTROL_POINTER_CURRENT.json` — ..."
_ORDER_LINE_RE = re.compile(r"^\d+\.\s+`([^`]+)`")
_SECTION_HEADER_RE = re.compile(r"^#{1,6}\s+")


def extract_readme_order(readme_text: str, section_title: str = "Read in this order") -> list[str]:
    """Pull the ordered backtick-quoted paths out of a named section.

    Parses markup structure (numbered list + backticks), never filenames'
    lexical content, so a file named e.g. "..._CURRENT.md" is not treated as
    current unless this section actually names it.
    """
    paths: list[str] = []
    in_section = False
    for raw_line in readme_text.splitlines():
        line = raw_line.strip()
        if _SECTION_HEADER_RE.match(line):
            in_section = section_title.lower() in line.lower()
            continue
        if in_section:
            match = _ORDER_LINE_RE.match(line)
            if match:
                paths.append(match.group(1))
    return paths


def _dedupe(items: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return list(seen.keys())


def compile_current_source(
    repo_root: Path,
    readme_path: str = README_PATH,
    stack_path: str = STACK_PATH,
) -> dict[str, Any]:
    """Resolve the entrypoint README plus the active instruction stack into one
    explicit, ordered current-source report.

    Returns a dict describing both orderings, their agreement/disagreement,
    and a deterministic current_source_set (the union, in first-seen order:
    README order first, then any stack-only entries appended). Raises
    CurrentSourceCompilationError (fail-closed) if a named path is missing,
    unreadable or unparsable.
    """
    repo_root = Path(repo_root)

    readme_file = repo_root / readme_path
    if not readme_file.is_file():
        raise CurrentSourceCompilationError(f"entrypoint missing: {readme_path}")
    try:
        readme_text = readme_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise CurrentSourceCompilationError(f"entrypoint unreadable: {readme_path}: {exc}") from exc

    readme_order = _dedupe(extract_readme_order(readme_text))
    if not readme_order:
        raise CurrentSourceCompilationError(
            f"fail-closed: no ordered pointer list found under 'Read in this order' in {readme_path}"
        )

    stack_file = repo_root / stack_path
    if not stack_file.is_file():
        raise CurrentSourceCompilationError(f"instruction stack missing: {stack_path}")
    try:
        stack_doc = json.loads(stack_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CurrentSourceCompilationError(f"instruction stack unreadable/invalid: {stack_path}: {exc}") from exc

    if not isinstance(stack_doc, dict) or "resolve_in_order" not in stack_doc:
        raise CurrentSourceCompilationError(f"fail-closed: {stack_path} carries no resolve_in_order field")
    stack_order = _dedupe([str(item) for item in stack_doc["resolve_in_order"]])
    if not stack_order:
        raise CurrentSourceCompilationError(f"fail-closed: {stack_path} resolve_in_order is empty")

    missing: list[str] = []
    for path, named_by in [(p, readme_path) for p in readme_order] + [(p, stack_path) for p in stack_order]:
        if not (repo_root / path).is_file():
            missing.append(f"{path} (named by {named_by})")
    if missing:
        raise CurrentSourceCompilationError(
            "fail-closed: pointer path(s) missing or unreadable: " + "; ".join(sorted(set(missing)))
        )

    only_in_readme = [p for p in readme_order if p not in stack_order]
    only_in_stack = [p for p in stack_order if p not in readme_order]
    order_agrees = readme_order == stack_order
    membership_agrees = set(readme_order) == set(stack_order)

    current_source_set = _dedupe(readme_order + stack_order)

    return {
        "entrypoint": readme_path,
        "instruction_stack": stack_path,
        "readme_order": readme_order,
        "stack_order": stack_order,
        "order_agrees": order_agrees,
        "membership_agrees": membership_agrees,
        "only_in_readme": only_in_readme,
        "only_in_stack": only_in_stack,
        "current_source_set": current_source_set,
        "all_named_paths_resolved": True,
    }


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(default_root))
    parser.add_argument("--readme-path", default=README_PATH)
    parser.add_argument("--stack-path", default=STACK_PATH)
    args = parser.parse_args(argv)

    try:
        report = compile_current_source(Path(args.repo_root), args.readme_path, args.stack_path)
    except CurrentSourceCompilationError as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "reason": str(exc)}, indent=2, sort_keys=True))
        return 1

    print(json.dumps({"status": "RESOLVED", **report}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
