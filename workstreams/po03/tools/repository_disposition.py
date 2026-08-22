#!/usr/bin/env python3
"""Read-only disposition analyser for the Obzio governance estate.

Resolves the pointer-reachable (CURRENT) path set from `operations/README.md`
and `state/operator-system/ACTIVE_INSTRUCTION_STACK.json`, scans the governance
directories, and classifies every scanned file as CURRENT, SUPERSEDED or
UNCLASSIFIED.  The scanned directories are opened for reading only; the single
write is the evidence document inside the PO-03 allowlist.

Exit codes: 0 success, 2 environment or input error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]

POINTER_README = "operations/README.md"
INSTRUCTION_STACK = "state/operator-system/ACTIVE_INSTRUCTION_STACK.json"
OPERATOR_SYSTEM_POINTER = "state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json"
TAXONOMY_CHECK = "scripts/check_operator_taxonomy.py"
ALIAS_REGISTER = "state/operator-system/OPERATOR_ALIAS_REGISTER.jsonl"

SCAN_DIRECTORIES: tuple[str, ...] = (
    "state",
    "dispatch",
    "commissions",
    "handover",
    "handoff",
    "templates",
)

WRITE_ALLOWED_PREFIX = "workstreams/po03/"
DEFAULT_OUTPUT = "workstreams/po03/evidence/repository-disposition.json"

MARKER_HEAD_BYTES = 2048

QUALIFIED_MARKERS: tuple[str, ...] = (
    "SUPERSEDED FOR ACTIVE ROUTING",
    "QUARANTINED OPERATOR REPORT",
)

BARE_MARKERS: tuple[str, ...] = (
    "SUPERSEDED",
    "QUARANTINED",
    "HALTED",
)

READ_IN_ORDER_RE = re.compile(r"^\s*\d+\.\s*`([^`]+)`")
REQUIRED_ALIASES_RE = re.compile(r"^required_aliases\s*=\s*\{(.*?)\}", re.MULTILINE | re.DOTALL)
QUOTED_RE = re.compile(r'"([^"]*)"')
EXCLUDED_DIRECTORY_NAMES = frozenset({".git", "__pycache__"})

EXIT_OK = 0
EXIT_ERROR = 2


class DispositionError(Exception):
    pass


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_readme_order(root: Path) -> list[str]:
    target = root / POINTER_README
    if not target.exists():
        raise DispositionError(f"missing pointer source: {POINTER_README}")
    paths: list[str] = []
    in_section = False
    for line in _read_text(target).splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            in_section = stripped.lower().lstrip("# ").startswith("read in this order")
            continue
        if not in_section:
            continue
        match = READ_IN_ORDER_RE.match(line)
        if match:
            candidate = match.group(1).strip()
            if candidate and not candidate.endswith("/"):
                paths.append(candidate)
    return paths


def parse_instruction_stack(root: Path) -> tuple[list[str], list[str]]:
    target = root / INSTRUCTION_STACK
    if not target.exists():
        raise DispositionError(f"missing pointer source: {INSTRUCTION_STACK}")
    try:
        stack = json.loads(_read_text(target))
    except json.JSONDecodeError as exc:
        raise DispositionError(f"invalid json {INSTRUCTION_STACK}: {exc}") from exc
    resolve = [str(item) for item in stack.get("resolve_in_order", [])]
    evidence = [str(item) for item in stack.get("immutable_execution_evidence", [])]
    return resolve, evidence


def reachable_paths(root: Path) -> dict[str, list[str]]:
    readme = parse_readme_order(root)
    resolve, evidence = parse_instruction_stack(root)
    return {
        "operations_readme_read_in_this_order": readme,
        "instruction_stack_resolve_in_order": resolve,
        "instruction_stack_immutable_execution_evidence": evidence,
    }


def scan_files(root: Path) -> list[str]:
    found: list[str] = []
    for directory in SCAN_DIRECTORIES:
        base = root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.split("/")):
                continue
            found.append(relative)
    return sorted(found)


def find_marker(root: Path, relative_path: str) -> str | None:
    try:
        with (root / relative_path).open("rb") as handle:
            head = handle.read(MARKER_HEAD_BYTES)
    except OSError:
        return None
    text = head.decode("utf-8", errors="replace")
    upper = text.upper()
    for marker in QUALIFIED_MARKERS:
        if marker in upper:
            return marker
    for marker in BARE_MARKERS:
        if marker in upper:
            return marker
    return None


def sha256_file(root: Path, relative_path: str) -> str:
    return hashlib.sha256((root / relative_path).read_bytes()).hexdigest()


def alias_cross_check(root: Path) -> dict[str, Any]:
    check_source = root / TAXONOMY_CHECK
    register = root / ALIAS_REGISTER
    if not check_source.is_file() or not register.is_file():
        return {
            "state": "NOT_APPLICABLE",
            "reason": f"{TAXONOMY_CHECK} or {ALIAS_REGISTER} is absent at this head",
        }
    match = REQUIRED_ALIASES_RE.search(_read_text(check_source))
    if match is None:
        return {
            "state": "NOT_SUPPORTED",
            "reason": f"required_aliases literal was not found in {TAXONOMY_CHECK}",
        }
    required = sorted(set(QUOTED_RE.findall(match.group(1))))
    classified: list[str] = []
    for line in _read_text(register).splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        alias = row.get("alias")
        if isinstance(alias, str):
            classified.append(alias)
    missing = sorted(set(required) - set(classified))
    return {
        "state": "CONSISTENT" if not missing else "INCONSISTENT",
        "required_alias_source": TAXONOMY_CHECK,
        "classified_alias_source": ALIAS_REGISTER,
        "required_alias_count": len(required),
        "classified_alias_count": len(classified),
        "required_aliases": required,
        "required_aliases_missing_from_register": missing,
        "classified_aliases_beyond_required": sorted(set(classified) - set(required)),
    }


def analyse(root: Path) -> dict[str, Any]:
    sources = reachable_paths(root)
    reachable: list[str] = []
    for values in sources.values():
        for value in values:
            if value not in reachable:
                reachable.append(value)
    reachable_set = set(reachable)

    scanned = scan_files(root)
    current: list[str] = []
    superseded: list[dict[str, str]] = []
    unclassified: list[str] = []
    current_but_marked: list[dict[str, str]] = []

    for relative_path in scanned:
        marker = find_marker(root, relative_path)
        if relative_path in reachable_set:
            current.append(relative_path)
            if marker is not None:
                current_but_marked.append({"path": relative_path, "marker": marker})
        elif marker is not None:
            superseded.append({"path": relative_path, "marker": marker})
        else:
            unclassified.append(relative_path)

    missing = sorted(path for path in reachable if not (root / path).exists())
    reachable_outside_scan = sorted(
        path
        for path in reachable
        if path.split("/")[0] not in SCAN_DIRECTORIES
    )

    pointer_source_hashes = []
    for relative_path in (POINTER_README, INSTRUCTION_STACK, OPERATOR_SYSTEM_POINTER):
        target = root / relative_path
        if target.is_file():
            pointer_source_hashes.append(
                {
                    "path": relative_path,
                    "sha256": sha256_file(root, relative_path),
                    "bytes": target.stat().st_size,
                }
            )
        else:
            pointer_source_hashes.append({"path": relative_path, "sha256": "NOT_APPLICABLE", "bytes": 0})

    return {
        "evidence_id": "EV-PO03-REPOSITORY-DISPOSITION-WAVE-A-20260822-v001",
        "generator": "workstreams/po03/tools/repository_disposition.py",
        "access_mode": "READ_ONLY_OUTSIDE_PO03_ALLOWLIST",
        "scanned_directories": list(SCAN_DIRECTORIES),
        "pointer_sources": pointer_source_hashes,
        "reachable_path_sources": sources,
        "reachable_paths": reachable,
        "reachable_paths_missing_from_disk": missing,
        "reachable_paths_outside_scanned_directories": reachable_outside_scan,
        "alias_cross_check": alias_cross_check(root),
        "marker_definitions": {
            "head_bytes_inspected": MARKER_HEAD_BYTES,
            "case_insensitive": True,
            "qualified_markers": list(QUALIFIED_MARKERS),
            "bare_markers": list(BARE_MARKERS),
            "qualified_marker_origin": "scripts/check_operator_taxonomy.py high_risk_markers",
        },
        "classification_precedence": "A pointer-reachable path is CURRENT even when it also carries a supersession marker; such files are listed under current_but_marked_superseded.",
        "totals": {
            "scanned_files": len(scanned),
            "current": len(current),
            "superseded": len(superseded),
            "unclassified": len(unclassified),
            "reachable_declared": len(reachable),
            "reachable_missing_from_disk": len(missing),
            "current_but_marked_superseded": len(current_but_marked),
        },
        "current_files": current,
        "superseded_files": superseded,
        "unclassified_files": unclassified,
        "current_but_marked_superseded": current_but_marked,
        "limitations": [
            "Classification is textual. A file without a recognised marker is UNCLASSIFIED, not proven current.",
            "Only the first 2048 bytes of each file are inspected for markers.",
            "Reachability is one hop from the two pointer sources; transitive references inside reachable documents are not followed.",
            "Transport-debris detection over packs/**, modules/** and _transport/** is NOT_APPLICABLE: those trees do not exist at this head.",
        ],
    }


def _validate_output_path(root: Path, output: Path) -> str:
    try:
        relative = output.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise DispositionError(f"output path escapes the repository root: {output}") from exc
    if not relative.startswith(WRITE_ALLOWED_PREFIX):
        raise DispositionError(
            f"refusing to write outside {WRITE_ALLOWED_PREFIX}: {relative}"
        )
    return relative


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--stdout", action="store_true", help="print the report instead of writing it")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    try:
        report = analyse(root)
        payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.stdout:
            print(payload, end="")
            return EXIT_OK
        output = args.output if args.output is not None else root / DEFAULT_OUTPUT
        relative = _validate_output_path(root, output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
        totals = report["totals"]
        print(
            "REPOSITORY DISPOSITION: "
            f"scanned={totals['scanned_files']} current={totals['current']} "
            f"superseded={totals['superseded']} unclassified={totals['unclassified']}"
        )
        print(f"REPOSITORY DISPOSITION: wrote {relative}")
        return EXIT_OK
    except DispositionError as exc:
        print(f"REPOSITORY DISPOSITION ERROR: {exc}")
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
