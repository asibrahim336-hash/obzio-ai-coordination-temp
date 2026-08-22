#!/usr/bin/env python3
"""Classify transport/staging residue without mutating repository paths."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath

if not __package__:  # Support ``python3 -I path/to/debris.py``.
    sys.path.insert(0, str(Path(__file__).resolve().parent))

if __package__:
    from .git_tree import GitTree
else:  # pragma: no cover - direct command entry point
    from git_tree import GitTree


EXACT_SEGMENTS = frozenset(
    {"_transport", "transport", "staging", "stage", "tmp", "temp"}
)
TEMP_PREFIXES = (".tmp-", ".upload-", ".stage-")
TEMP_SUFFIXES = (".part", ".upload", ".tmp")


def classify_path(path: str) -> dict[str, object] | None:
    parts = PurePosixPath(path).parts
    for part in parts:
        lowered = part.lower()
        if lowered in EXACT_SEGMENTS:
            return {
                "class": "transport_debris_candidate",
                "path": path,
                "reason": f"path segment {part!r} is a staging/transport marker",
                "proposed_disposition": (
                    "QUARANTINE_REVIEW_THEN_RETAIN_OR_ARCHIVE; DO_NOT_DELETE"
                ),
            }
        if lowered.startswith(TEMP_PREFIXES) or lowered.endswith(TEMP_SUFFIXES):
            return {
                "class": "transport_debris_candidate",
                "path": path,
                "reason": f"path segment {part!r} has a temporary-transfer marker",
                "proposed_disposition": (
                    "QUARANTINE_REVIEW_THEN_RETAIN_OR_ARCHIVE; DO_NOT_DELETE"
                ),
            }
    return None


def inspect(tree: GitTree) -> dict[str, object]:
    findings = [
        finding
        for path in sorted(tree.paths())
        if (finding := classify_path(path)) is not None
    ]
    return {
        "commit_sha": tree.commit_sha,
        "classification_rule": {
            "exact_segments": sorted(EXACT_SEGMENTS),
            "temporary_prefixes": list(TEMP_PREFIXES),
            "temporary_suffixes": list(TEMP_SUFFIXES),
            "scope": "tracked regular-file paths only",
            "mutation": "NONE",
        },
        "finding_count": len(findings),
        "findings": findings,
        "outcome": "FAIL" if findings else "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=".")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = inspect(GitTree(Path(args.repository), args.commit))
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 1 if result["outcome"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
