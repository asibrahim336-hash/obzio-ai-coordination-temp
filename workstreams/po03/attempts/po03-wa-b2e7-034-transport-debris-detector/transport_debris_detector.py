#!/usr/bin/env python3
"""Classify transport/package files using explicit, read-only evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Iterable

DEBRIS_SUFFIXES = (
    ".bak",
    ".orig",
    ".partial",
    ".rej",
    ".stage",
    ".staging",
    ".swp",
    ".tmp",
)
DEBRIS_NAMES = frozenset({".ds_store", "thumbs.db"})
LIVE_MARKER = b"OBZIO-LIVE-SURFACE"
DEBRIS_MARKER = b"OBZIO-TRANSPORT-DEBRIS"


def _files(roots: Iterable[Path]) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    unavailable: list[str] = []
    for root in roots:
        if not root.exists():
            unavailable.append(root.as_posix())
        elif root.is_file():
            files.append(root)
        else:
            files.extend(path for path in root.rglob("*") if path.is_file())
    return sorted(set(files)), unavailable


def classify_bytes(
    display_path: str, body: bytes, live_paths: set[str] | None = None
) -> dict[str, object]:
    """Classify one file; ambiguous files remain unresolved."""

    normalized = display_path
    name = Path(display_path).name.lower()
    if DEBRIS_MARKER in body or name in DEBRIS_NAMES or name.endswith(DEBRIS_SUFFIXES):
        classification, reason = "debris", "explicit debris marker or transient suffix"
    elif LIVE_MARKER in body or (live_paths and normalized in live_paths):
        classification, reason = "live", "explicit live marker or current-path evidence"
    else:
        classification, reason = "unresolved", "no live or debris evidence"
    return {
        "path": normalized,
        "classification": classification,
        "reason": reason,
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
    }


def classify(path: Path, live_paths: set[str] | None = None) -> dict[str, object]:
    return classify_bytes(path.as_posix(), path.read_bytes(), live_paths)


def scan(roots: Iterable[str | Path], live_paths: Iterable[str] = ()) -> dict[str, object]:
    paths, unavailable = _files([Path(root) for root in roots])
    live = {Path(path).as_posix() for path in live_paths}
    artifacts = [classify(path, live) for path in paths]
    return {
        "artifacts": artifacts,
        "unavailable_roots": unavailable,
        "counts": {
            kind: sum(item["classification"] == kind for item in artifacts)
            for kind in ("live", "debris", "unresolved")
        },
    }


def scan_git_tree(repo: str | Path, commit: str, prefix: str = "packs") -> dict[str, object]:
    """Read a committed tree through git plumbing without checking it out."""

    repo_path = Path(repo).resolve()
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", commit, "--", prefix],
        cwd=repo_path,
        check=True,
        capture_output=True,
    ).stdout
    paths = sorted(item for item in listing.decode("utf-8").split("\0") if item)
    artifacts = []
    for path in paths:
        body = subprocess.run(
            ["git", "cat-file", "blob", f"{commit}:{path}"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        ).stdout
        artifacts.append(classify_bytes(path, body))
    return {
        "source_commit": commit,
        "source_prefix": prefix,
        "artifacts": artifacts,
        "counts": {
            kind: sum(item["classification"] == kind for item in artifacts)
            for kind in ("live", "debris", "unresolved")
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="*", type=Path)
    parser.add_argument("--live-path", action="append", default=[])
    parser.add_argument("--git-commit")
    parser.add_argument("--git-prefix", default="packs")
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args()
    if args.git_commit:
        report = scan_git_tree(args.repo, args.git_commit, args.git_prefix)
    elif args.root:
        report = scan(args.root, args.live_path)
    else:
        parser.error("provide roots or --git-commit")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
