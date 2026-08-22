#!/usr/bin/env python3
"""Detect path dependencies that cannot travel with a clean checkout."""

from __future__ import annotations

import argparse
import json
import posixpath
import re
from pathlib import Path
from typing import Iterable, Mapping

if __package__:
    from .git_tree import GitTree
else:  # pragma: no cover - direct command entry point
    from git_tree import GitTree


_POSIX_ABSOLUTE = re.compile(
    r"(?<![A-Za-z0-9:])"
    r"(/(?:tmp|home|Users|workspace|root|var|etc|usr|opt|mnt)"
    r"(?:/[A-Za-z0-9._{}$-]+)+)"
)
_WINDOWS_DRIVE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]:\\[^\s\"'`]+)")
_WINDOWS_UNC = re.compile(r"(\\\\[A-Za-z0-9._-]+\\[^\s\"'`]+)")
_RELATIVE_REFERENCE = re.compile(r"[\"']((?:\.\.?/)[^\"'\s]+)[\"']")
_MACHINE_ROOTS = ("/tmp/", "/home/", "/Users/", "/workspace/", "/root/")


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def scan_text(
    source_path: str, data: bytes, available_paths: Iterable[str]
) -> list[dict[str, object]]:
    if b"\0" in data:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []

    findings: list[dict[str, object]] = []
    for pattern, classification in (
        (_POSIX_ABSOLUTE, "absolute_posix_path"),
        (_WINDOWS_DRIVE, "windows_drive_path"),
        (_WINDOWS_UNC, "windows_unc_path"),
    ):
        for match in pattern.finditer(text):
            value = match.group(1)
            specific = (
                "machine_specific_root"
                if classification == "absolute_posix_path"
                and value.startswith(_MACHINE_ROOTS)
                else classification
            )
            findings.append(
                {
                    "class": specific,
                    "source_path": source_path,
                    "line": _line_number(text, match.start(1)),
                    "value": value,
                }
            )

    available = frozenset(available_paths)
    source_parent = posixpath.dirname(source_path)
    for match in _RELATIVE_REFERENCE.finditer(text):
        value = match.group(1)
        value_without_fragment = value.split("#", 1)[0].split("?", 1)[0]
        resolved = posixpath.normpath(
            posixpath.join(source_parent, value_without_fragment)
        )
        if resolved not in available:
            findings.append(
                {
                    "class": "unresolvable_relative_reference",
                    "source_path": source_path,
                    "line": _line_number(text, match.start(1)),
                    "value": value,
                    "resolved_path": resolved,
                }
            )
    return sorted(
        findings,
        key=lambda item: (
            str(item["source_path"]),
            int(item["line"]),
            str(item["class"]),
            str(item["value"]),
        ),
    )


def scan_mapping(blobs: Mapping[str, bytes]) -> list[dict[str, object]]:
    paths = frozenset(blobs)
    findings = [
        finding
        for path in sorted(blobs)
        for finding in scan_text(path, blobs[path], paths)
    ]
    return sorted(
        findings,
        key=lambda item: (
            str(item["source_path"]),
            int(item["line"]),
            str(item["class"]),
            str(item["value"]),
        ),
    )


def inspect(tree: GitTree, root: str) -> dict[str, object]:
    prefix = root.rstrip("/") + "/"
    blobs = {
        path: tree.blob(path)
        for path in sorted(tree.paths())
        if path.startswith(prefix)
    }
    findings = scan_mapping(blobs)
    counts: dict[str, int] = {}
    for finding in findings:
        classification = str(finding["class"])
        counts[classification] = counts.get(classification, 0) + 1
    return {
        "commit_sha": tree.commit_sha,
        "root": root,
        "files_scanned": len(blobs),
        "finding_count": len(findings),
        "counts_by_class": dict(sorted(counts.items())),
        "findings": findings,
        "outcome": "FAIL" if findings else "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=".")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = inspect(GitTree(Path(args.repository), args.commit), args.root)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 1 if result["outcome"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
