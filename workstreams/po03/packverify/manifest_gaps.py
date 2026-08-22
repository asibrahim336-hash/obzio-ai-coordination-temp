#!/usr/bin/env python3
"""Enforce the manifest/provenance closed set for an immutable pack root."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

if not __package__:  # Support ``python3 -I path/to/manifest_gaps.py``.
    sys.path.insert(0, str(Path(__file__).resolve().parent))

if __package__:
    from .git_tree import GitTree
    from .manifest_model import (
        ManifestDocument,
        ManifestEntry,
        all_entries,
        load_documents,
    )
else:  # pragma: no cover - direct command entry point
    from git_tree import GitTree
    from manifest_model import (
        ManifestDocument,
        ManifestEntry,
        all_entries,
        load_documents,
    )


GAP_CLASSES = ("unlisted_files", "unhashed_entries", "hash_mismatches")


def _explicit_exclusions(
    documents: Iterable[ManifestDocument], root: str
) -> frozenset[str]:
    excluded: set[str] = set()
    root_path = PurePosixPath(root)
    for document in documents:
        parent = PurePosixPath(document.path).parent
        value = document.value.get("excluded")
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    candidate = PurePosixPath(item)
                    excluded.add(
                        str(
                            candidate
                            if candidate.parts[: len(root_path.parts)]
                            == root_path.parts
                            else parent / candidate
                        )
                    )
        elif isinstance(value, Mapping):
            for details in value.values():
                if not isinstance(details, Mapping):
                    continue
                paths = details.get("paths")
                if isinstance(paths, list):
                    excluded.update(
                        path for path in paths if isinstance(path, str)
                    )
    return frozenset(excluded)


def audit_entries(
    entries: Iterable[ManifestEntry],
    actual_blobs: Mapping[str, bytes],
    manifest_paths: Iterable[str] = (),
    excluded_paths: Iterable[str] = (),
) -> dict[str, list[dict[str, object]]]:
    entries = tuple(entries)
    listed = {entry.tree_path for entry in entries}
    exempt = set(manifest_paths) | set(excluded_paths)

    unlisted = [
        {"class": "unlisted_file", "tree_path": path}
        for path in sorted(set(actual_blobs) - listed - exempt)
    ]
    unhashed = [
        {
            "class": "unhashed_entry",
            "manifest_path": entry.manifest_path,
            "logical_path": entry.logical_path,
            "tree_path": entry.tree_path,
            "observed_value": entry.expected_sha256,
        }
        for entry in entries
        if not entry.has_valid_hash
    ]
    mismatches: list[dict[str, object]] = []
    for entry in entries:
        if not entry.has_valid_hash or entry.tree_path not in actual_blobs:
            continue
        observed = hashlib.sha256(actual_blobs[entry.tree_path]).hexdigest()
        if observed != entry.expected_sha256:
            mismatches.append(
                {
                    "class": "hash_mismatch",
                    "manifest_path": entry.manifest_path,
                    "logical_path": entry.logical_path,
                    "tree_path": entry.tree_path,
                    "expected_sha256": entry.expected_sha256,
                    "observed_sha256": observed,
                }
            )
    return {
        "unlisted_files": unlisted,
        "unhashed_entries": sorted(
            unhashed,
            key=lambda item: (
                str(item["tree_path"]),
                str(item["manifest_path"]),
            ),
        ),
        "hash_mismatches": sorted(
            mismatches,
            key=lambda item: (
                str(item["tree_path"]),
                str(item["manifest_path"]),
            ),
        ),
    }


def audit(tree: GitTree, root: str) -> dict[str, object]:
    prefix = root.rstrip("/") + "/"
    documents = load_documents(tree, root)
    entries = all_entries(documents, root)
    blobs = {
        path: tree.blob(path)
        for path in sorted(tree.paths())
        if path.startswith(prefix)
    }
    gaps = audit_entries(
        entries,
        blobs,
        manifest_paths=(document.path for document in documents),
        excluded_paths=_explicit_exclusions(documents, root),
    )
    counts = {name: len(gaps[name]) for name in GAP_CLASSES}
    return {
        "commit_sha": tree.commit_sha,
        "root": root,
        "closed_set_rule": (
            "Every regular file below the aggregate root must be hash-listed "
            "by a manifest or explicitly excluded; every listed entry must "
            "carry a valid SHA-256 matching immutable blob bytes."
        ),
        "manifest_count": len(documents),
        "actual_file_count": len(blobs),
        "claimed_entry_count": len(entries),
        "counts": counts,
        "gaps": gaps,
        "outcome": "FAIL" if any(counts.values()) else "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=".")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = audit(GitTree(Path(args.repository), args.commit), args.root)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 1 if result["outcome"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
