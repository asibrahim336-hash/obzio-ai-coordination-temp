#!/usr/bin/env python3
"""Partition instruction-bearing files into launch surface, evidence, or ambiguous.

FALSIFIABLE HYPOTHESIS (task po03-wa-b2e7-013-launch-surface-classifier):
    Launch surfaces and evidence-only files are mechanically separable, so
    a superseded file cannot be mistaken for a launch file.

This classifier never guesses from a filename (e.g. a "_CURRENT" or
version-number suffix). A file lands in LAUNCH_SURFACE or EVIDENCE only
because a *structured, committed source* explicitly names it that way:

  - LAUNCH_SURFACE: named by `resolve_in_order` in the active instruction
    stack (state/operator-system/ACTIVE_INSTRUCTION_STACK.json), or is
    AGENTS.md, or is the repository-root README.md, or is a path that the
    repository-root README.md names via an actual markdown link (parsed
    from its `[text](path)` syntax, not guessed from a filename).
  - EVIDENCE: named by `immutable_execution_evidence` in the same stack
    document, OR is a key of `high_risk_markers` in
    scripts/check_operator_taxonomy.py *and its own committed text
    contains that exact marker string* (a verified, not merely claimed,
    disposition), OR is named by an explicit backtick path inside
    operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md's
    disposition table.
  - AMBIGUOUS: every other candidate instruction-bearing file. The
    classifier fails closed for these: it never assigns them to either
    bucket by inference, and the overall run reports NOT_ALL_CLASSIFIED
    when the ambiguous set is non-empty.

Candidate instruction-bearing files are `.md` files under a fixed list of
directories that carry operator instructions in this repository
(dispatch/, commissions/, handoff/, handover/, state/, templates/,
operations/, instructions/) plus the two repository-root governing files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

STACK_PATH = "state/operator-system/ACTIVE_INSTRUCTION_STACK.json"
DISPOSITION_TABLE_PATH = "operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md"
TAXONOMY_SCRIPT_PATH = "scripts/check_operator_taxonomy.py"

CANDIDATE_DIRS = (
    "dispatch",
    "commissions",
    "handoff",
    "handover",
    "state",
    "templates",
    "operations",
    "instructions",
)
CANDIDATE_ROOT_FILES = ("AGENTS.md", "README.md")

_BACKTICK_PATH_RE = re.compile(r"`([\w\-./]+\.(?:md|json|jsonl))`")
_MARKDOWN_LINK_RE = re.compile(r"\]\(([\w\-./]+\.md)\)")
_HIGH_RISK_MARKERS_RE = re.compile(
    r'high_risk_markers\s*=\s*\{(.*?)\n\}', re.DOTALL
)
_MARKER_ENTRY_RE = re.compile(r'"([^"]+)"\s*:\s*"([^"]+)"')


class ClassificationError(Exception):
    """Raised when a required structured source cannot be read (fail-closed)."""


def discover_candidates(repo_root: Path) -> list[str]:
    repo_root = Path(repo_root)
    candidates: list[str] = []
    for dirname in CANDIDATE_DIRS:
        base = repo_root / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            candidates.append(path.relative_to(repo_root).as_posix())
    for name in CANDIDATE_ROOT_FILES:
        if (repo_root / name).is_file():
            candidates.append(name)
    return sorted(set(candidates))


def load_stack_sets(repo_root: Path) -> tuple[set[str], set[str]]:
    stack_file = Path(repo_root) / STACK_PATH
    if not stack_file.is_file():
        raise ClassificationError(f"instruction stack missing: {STACK_PATH}")
    try:
        stack = json.loads(stack_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ClassificationError(f"instruction stack invalid: {STACK_PATH}: {exc}") from exc
    return (
        set(stack.get("resolve_in_order", [])),
        set(stack.get("immutable_execution_evidence", [])),
    )


def load_high_risk_markers(repo_root: Path) -> dict[str, str]:
    """Extract the `high_risk_markers` dict literal straight out of
    scripts/check_operator_taxonomy.py's source text. This module never
    imports or executes that script; it only parses its committed source
    text for this one dict literal, so it stays entirely inside its own
    owned subtree while still grounding EVIDENCE classification in the
    repository's own existing currentness gate."""
    script_path = Path(repo_root) / TAXONOMY_SCRIPT_PATH
    if not script_path.is_file():
        raise ClassificationError(f"taxonomy script missing: {TAXONOMY_SCRIPT_PATH}")
    text = script_path.read_text(encoding="utf-8")
    match = _HIGH_RISK_MARKERS_RE.search(text)
    if not match:
        raise ClassificationError(f"could not locate high_risk_markers literal in {TAXONOMY_SCRIPT_PATH}")
    return dict(_MARKER_ENTRY_RE.findall(match.group(1)))


def load_root_readme_linked_paths(repo_root: Path) -> set[str]:
    """Parse the repository-root README.md for markdown links
    (`[text](path)`) pointing at committed `.md` files. This is how
    operations/README.md itself is mechanically established as launch
    surface: the root README.md's own link syntax names it, so no
    filename heuristic ("contains README" or "contains CURRENT") is
    involved."""
    readme_path = Path(repo_root) / "README.md"
    if not readme_path.is_file():
        return set()
    text = readme_path.read_text(encoding="utf-8")
    linked = set()
    for candidate in _MARKDOWN_LINK_RE.findall(text):
        if (Path(repo_root) / candidate).is_file():
            linked.add(candidate)
    return linked


def load_disposition_table_paths(repo_root: Path) -> set[str]:
    table_file = Path(repo_root) / DISPOSITION_TABLE_PATH
    if not table_file.is_file():
        raise ClassificationError(f"disposition table missing: {DISPOSITION_TABLE_PATH}")
    text = table_file.read_text(encoding="utf-8")
    return set(_BACKTICK_PATH_RE.findall(text))


def classify(repo_root: Path) -> dict[str, Any]:
    repo_root = Path(repo_root)
    candidates = discover_candidates(repo_root)
    launch_from_stack, evidence_from_stack = load_stack_sets(repo_root)
    markers = load_high_risk_markers(repo_root)
    disposition_paths = load_disposition_table_paths(repo_root)
    root_readme_links = load_root_readme_linked_paths(repo_root)

    launch_surface: list[str] = []
    evidence: list[dict[str, str]] = []
    ambiguous: list[str] = []

    for path in candidates:
        if path in launch_from_stack or path == "AGENTS.md" or path == "README.md" or path in root_readme_links:
            launch_surface.append(path)
            continue

        if path in evidence_from_stack:
            evidence.append({"path": path, "reason": "immutable_execution_evidence"})
            continue

        if path in markers:
            marker_text = markers[path]
            target = repo_root / path
            body = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
            if marker_text in body:
                evidence.append({"path": path, "reason": f"verified_marker:{marker_text}"})
                continue
            # Marker claimed by the taxonomy script but not actually present
            # in the file's own text: this is NOT a verified disposition.
            ambiguous.append(path)
            continue

        if path in disposition_paths:
            evidence.append({"path": path, "reason": "instruction_estate_disposition_table"})
            continue

        ambiguous.append(path)

    all_classified = not ambiguous
    return {
        "candidate_count": len(candidates),
        "launch_surface": sorted(launch_surface),
        "evidence": sorted(evidence, key=lambda e: e["path"]),
        "ambiguous": sorted(ambiguous),
        "all_classified": all_classified,
        "status": "ALL_CLASSIFIED" if all_classified else "FAILED_CLOSED_AMBIGUOUS_FILES_PRESENT",
    }


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(default_root))
    args = parser.parse_args(argv)

    try:
        report = classify(Path(args.repo_root))
    except ClassificationError as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "reason": str(exc)}, indent=2, sort_keys=True))
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["all_classified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
