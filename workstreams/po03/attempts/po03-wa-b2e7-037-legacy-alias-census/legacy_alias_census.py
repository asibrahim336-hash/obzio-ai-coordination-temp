#!/usr/bin/env python3
"""Census historical routing aliases as evidence; never rewrite input."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable

ALIAS_PATTERNS = (
    ("Operator D", re.compile(r"\bOperator\s+D\b", re.IGNORECASE)),
    ("Claude extension", re.compile(r"\bClaude(?:\s+Chrome)?\s+extension\b", re.IGNORECASE)),
    ("Claude browser operator", re.compile(r"\bClaude\s+browser\s+operator\b", re.IGNORECASE)),
    (
        "principal AI operator",
        re.compile(r"\bprincipal(?:\s+strategic)?\s+AI[- ]operator\b", re.IGNORECASE),
    ),
)
FIELD = re.compile(r"""["']?([A-Za-z][\w .-]*)["']?\s*:""")
HEADING = re.compile(r"^\s*#+\s+(.+?)\s*$")


def _files(paths: Iterable[str | Path]) -> list[Path]:
    files: set[Path] = set()
    for value in paths:
        path = Path(value)
        if path.is_file():
            files.add(path)
        elif path.is_dir():
            files.update(item for item in path.rglob("*") if item.is_file())
    return sorted(files, key=lambda item: item.as_posix())


def _enclosing_field(lines: list[str], index: int, match_start: int) -> str:
    same_line = list(FIELD.finditer(lines[index][:match_start]))
    if same_line:
        return same_line[-1].group(1).strip()
    for prior in range(index, -1, -1):
        heading = HEADING.match(lines[prior])
        if heading:
            return heading.group(1)
    return "unstructured-line"


def census(paths: Iterable[str | Path]) -> dict[str, object]:
    """Read files and return one evidence record per alias occurrence."""

    occurrences: list[dict[str, object]] = []
    for path in _files(paths):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        lines = text.splitlines()
        for index, line in enumerate(lines):
            for alias, pattern in ALIAS_PATTERNS:
                for match in pattern.finditer(line):
                    occurrences.append(
                        {
                            "alias": alias,
                            "file": path.as_posix(),
                            "line": index + 1,
                            "enclosing_field": _enclosing_field(lines, index, match.start()),
                            "text": line,
                        }
                    )
    occurrences.sort(key=lambda item: (item["file"], item["line"], item["alias"]))
    return {
        "occurrences": occurrences,
        "occurrence_count": len(occurrences),
        "replacement_performed": False,
        "replacement_assertion": "No alias replacement was performed; inputs were read-only.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="+", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(census(args.path), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    else:
        print(result, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
