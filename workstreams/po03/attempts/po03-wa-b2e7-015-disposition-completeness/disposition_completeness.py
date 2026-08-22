#!/usr/bin/env python3
"""Check that every superseded file carries an explicit disposition, or is
reported as an open defect.

FALSIFIABLE HYPOTHESIS (task po03-wa-b2e7-015-disposition-completeness):
    Every superseded file either carries an explicit disposition or is
    reported as an open defect.

This module is a self-contained (does not import from any other unit's
subtree) disposition-completeness checker. It:

  1. Discovers "superseded" files the same way as the sibling
     supersession-graph mechanism: by scanning committed JSON/JSONL files
     for any key whose name contains "supersed" and normalising the value
     shapes actually observed in this repository into (older_file,
     inline_standing) pairs. `superseded_by` is treated as a backward key
     (the record carrying it is itself the older/superseded file); every
     other "supersed*" key is forward (its value names older files/
     evidence it supersedes).

  2. For each discovered superseded file, looks for an explicit
     disposition from exactly three structured, committed sources:
       a. INLINE_STANDING — a `"standing"` field co-located in the same
          JSON object as the path/objects list that named the file.
       b. DISPOSITION_TABLE — a row of
          operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md whose
          first cell is a backtick-quoted path equal to the file.
       c. VERIFIED_HIGH_RISK_MARKER — the file is a key of the
          `high_risk_markers` dict literal in
          scripts/check_operator_taxonomy.py *and* the file's own
          committed text actually contains that exact marker string (a
          verified, not merely claimed, disposition).

  3. Reports, for every superseded file, whether it has an explicit
     disposition and from which source(s); every file with none of the
     three is reported as an OPEN_DEFECT — a precise, named list, never a
     silent drop.

This module only reads repository files. It never deletes, rewrites, or
mutates any scanned file, and it writes nothing outside its own directory.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

DISPOSITION_TABLE_PATH = "operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md"
TAXONOMY_SCRIPT_PATH = "scripts/check_operator_taxonomy.py"

# Field names on the *older* side of the relation: the record carrying this
# key is itself the file being superseded, and its value names the *newer*
# file. Everything else containing "supersed" is forward: the record
# carrying the key is the newer file, naming older file(s)/evidence it
# supersedes. (Same convention as the sibling supersession-graph unit,
# reimplemented here independently so this unit has no cross-subtree
# import dependency.)
BACKWARD_KEYS = {"superseded_by"}

_PATH_LIKE_RE = re.compile(r"^([\w\-./]+\.(?:json|jsonl|md))\b")
_TABLE_ROW_RE = re.compile(
    r"^\|\s*`([\w\-./]+\.(?:json|jsonl|md))`\s*\|\s*([^|]+?)\s*\|"
)
_HIGH_RISK_MARKERS_RE = re.compile(r"high_risk_markers\s*=\s*\{(.*?)\n\}", re.DOTALL)
_MARKER_ENTRY_RE = re.compile(r'"([^"]+)"\s*:\s*"([^"]+)"')


class DispositionCheckError(Exception):
    """Raised when a required structured source cannot be read (fail-closed)."""


def _path_like(text: str) -> str | None:
    match = _PATH_LIKE_RE.match(text.strip())
    return match.group(1) if match else None


def _extract_targets_with_standing(value: Any) -> list[tuple[str, str | None]]:
    """Return (path, inline_standing) pairs found inside one supersession
    field's value, for every shape actually observed in this repository:
    dict-with-path(+standing), dict-with-objects-list(+standing shared by
    all listed objects), list of the above, or a plain path-like string
    (no standing available at this level)."""
    results: list[tuple[str, str | None]] = []

    def handle(item: Any) -> None:
        if isinstance(item, dict):
            standing = item.get("standing") if isinstance(item.get("standing"), str) else None
            if isinstance(item.get("path"), str):
                results.append((item["path"], standing))
            elif isinstance(item.get("objects"), list):
                for obj in item["objects"]:
                    if isinstance(obj, str):
                        head = obj.split("@", 1)[0]
                        resolved = _path_like(head)
                        if resolved:
                            results.append((resolved, standing))
            # A dict with neither 'path' nor 'objects' names no file target
            # at this level; it contributes nothing rather than guessing.
        elif isinstance(item, list):
            for sub in item:
                handle(sub)
        elif isinstance(item, str):
            resolved = _path_like(item)
            if resolved:
                results.append((resolved, None))

    handle(value)
    return results


def discover_superseded_files(repo_root: Path, scan_glob: str = "**/*.json*") -> dict[str, Any]:
    """Scan committed JSON/JSONL files for supersession keys and return,
    per discovered older/superseded file, every inline standing value seen
    naming it (possibly none)."""
    repo_root = Path(repo_root)
    superseded: dict[str, list[str | None]] = {}
    scanned = 0
    unparsable: list[str] = []

    for file_path in sorted(repo_root.glob(scan_glob)):
        if not file_path.is_file() or ".git" in file_path.parts:
            continue
        rel = file_path.relative_to(repo_root).as_posix()
        scanned += 1
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError:
            unparsable.append(rel)
            continue

        records: list[Any] = []
        if file_path.suffix == ".jsonl":
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    unparsable.append(rel)
        else:
            try:
                records = [json.loads(text)]
            except json.JSONDecodeError:
                unparsable.append(rel)

        for record in records:
            if not isinstance(record, dict):
                continue
            for key, value in record.items():
                if "supersed" not in key.lower():
                    continue
                backward = key.lower() in BACKWARD_KEYS
                for target, standing in _extract_targets_with_standing(value):
                    older = rel if backward else target
                    superseded.setdefault(older, []).append(standing)

    return {
        "superseded": superseded,
        "files_scanned": scanned,
        "unparsable_files": sorted(set(unparsable)),
    }


def load_disposition_table(repo_root: Path, table_path: str = DISPOSITION_TABLE_PATH) -> dict[str, str]:
    table_file = Path(repo_root) / table_path
    if not table_file.is_file():
        raise DispositionCheckError(f"disposition table missing: {table_path}")
    text = table_file.read_text(encoding="utf-8")
    result: dict[str, str] = {}
    for line in text.splitlines():
        match = _TABLE_ROW_RE.match(line.strip())
        if match:
            result[match.group(1)] = match.group(2).strip()
    return result


def load_verified_high_risk_markers(repo_root: Path, script_path: str = TAXONOMY_SCRIPT_PATH) -> dict[str, str]:
    """Extract the `high_risk_markers` dict literal straight from the
    committed source text of scripts/check_operator_taxonomy.py (never
    imported or executed), then verify each named file's own committed
    text actually contains its claimed marker string. Only verified
    entries are returned; a claimed-but-absent marker is not a
    disposition."""
    script_file = Path(repo_root) / script_path
    if not script_file.is_file():
        raise DispositionCheckError(f"taxonomy script missing: {script_path}")
    script_text = script_file.read_text(encoding="utf-8")
    match = _HIGH_RISK_MARKERS_RE.search(script_text)
    if not match:
        raise DispositionCheckError(f"could not locate high_risk_markers literal in {script_path}")
    claimed = dict(_MARKER_ENTRY_RE.findall(match.group(1)))

    verified: dict[str, str] = {}
    for path, marker in claimed.items():
        target = Path(repo_root) / path
        if target.is_file() and marker in target.read_text(encoding="utf-8", errors="replace"):
            verified[path] = marker
    return verified


def compute_completeness(repo_root: Path) -> dict[str, Any]:
    repo_root = Path(repo_root)
    discovery = discover_superseded_files(repo_root)
    superseded = discovery["superseded"]
    disposition_table = load_disposition_table(repo_root)
    verified_markers = load_verified_high_risk_markers(repo_root)

    dispositioned: list[dict[str, Any]] = []
    open_defects: list[str] = []

    for path in sorted(superseded):
        sources: list[dict[str, str]] = []
        standings = [s for s in superseded[path] if s]
        for standing in sorted(set(standings)):
            sources.append({"kind": "INLINE_STANDING", "value": standing})
        if path in disposition_table:
            sources.append({"kind": "DISPOSITION_TABLE", "value": disposition_table[path]})
        if path in verified_markers:
            sources.append({"kind": "VERIFIED_HIGH_RISK_MARKER", "value": verified_markers[path]})

        if sources:
            dispositioned.append({"path": path, "sources": sources})
        else:
            open_defects.append(path)

    all_dispositioned = not open_defects
    return {
        "files_scanned": discovery["files_scanned"],
        "unparsable_files": discovery["unparsable_files"],
        "superseded_file_count": len(superseded),
        "dispositioned_count": len(dispositioned),
        "open_defect_count": len(open_defects),
        "dispositioned": dispositioned,
        "open_defects": sorted(open_defects),
        "disposition_table_entries": len(disposition_table),
        "verified_high_risk_marker_entries": len(verified_markers),
        "all_dispositioned": all_dispositioned,
        "status": "ALL_DISPOSITIONED" if all_dispositioned else "OPEN_DEFECTS_PRESENT",
    }


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(default_root))
    args = parser.parse_args(argv)

    try:
        report = compute_completeness(Path(args.repo_root))
    except DispositionCheckError as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "reason": str(exc)}, indent=2, sort_keys=True))
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["all_dispositioned"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
