#!/usr/bin/env python3
"""Report manifest claims whose corresponding immutable blob is absent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

if not __package__:  # Support ``python3 -I path/to/qualify.py``.
    sys.path.insert(0, str(Path(__file__).resolve().parent))

if __package__:
    from .git_tree import GitTree
    from .manifest_model import ManifestEntry, all_entries, load_documents
else:  # pragma: no cover - direct command entry point
    from git_tree import GitTree
    from manifest_model import ManifestEntry, all_entries, load_documents


def find_missing(
    entries: Iterable[ManifestEntry], available_paths: Iterable[str]
) -> list[dict[str, object]]:
    available = frozenset(available_paths)
    findings = [
        {
            "class": "manifest_entry_missing_blob",
            "manifest_path": entry.manifest_path,
            "logical_path": entry.logical_path,
            "tree_path": entry.tree_path,
            "expected_sha256": entry.expected_sha256,
        }
        for entry in entries
        if entry.tree_path not in available
    ]
    return sorted(
        findings,
        key=lambda item: (
            str(item["tree_path"]),
            str(item["manifest_path"]),
        ),
    )


def qualify(tree: GitTree, root: str) -> dict[str, object]:
    documents = load_documents(tree, root)
    entries = all_entries(documents, root)
    findings = find_missing(entries, tree.paths())
    return {
        "commit_sha": tree.commit_sha,
        "root": root,
        "manifest_count": len(documents),
        "claimed_entry_count": len(entries),
        "missing_blob_count": len(findings),
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
    result = qualify(GitTree(Path(args.repository), args.commit), args.root)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 1 if result["outcome"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
