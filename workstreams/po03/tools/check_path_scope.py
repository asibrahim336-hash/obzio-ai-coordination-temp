#!/usr/bin/env python3
"""Fail closed when a PO-03 change escapes its commissioned path allowlist."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import PurePosixPath


PINNED_BASE_SHA = "5db7affeb7f00763e148e6d98a33ee6b751f2def"
ALLOWED_PREFIXES = ("workstreams/po03/", "receipts/po03/")
WORKFLOW_PREFIX = ".github/workflows/po03-"
WORKFLOW_SUFFIX = ".yml"


def normalize(path: str) -> str:
    if "\\" in path or "\x00" in path:
        raise ValueError(f"non-canonical changed path: {path!r}")
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts or str(value) != path:
        raise ValueError(f"non-canonical changed path: {path!r}")
    return path


def is_allowed(path: str) -> bool:
    path = normalize(path)
    if any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        return True
    return path.startswith(WORKFLOW_PREFIX) and path.endswith(WORKFLOW_SUFFIX)


def violations(paths: list[str]) -> list[str]:
    invalid: list[str] = []
    for path in paths:
        try:
            allowed = is_allowed(path)
        except ValueError:
            allowed = False
        if not allowed:
            invalid.append(path)
    return sorted(set(invalid))


def changed_paths(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ("git", "diff", "--name-only", "--diff-filter=ACMRDTUXB", "-z", f"{base}...{head}"),
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=PINNED_BASE_SHA)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--path", action="append", dest="paths")
    args = parser.parse_args(argv)
    try:
        paths = args.paths if args.paths is not None else changed_paths(args.base, args.head)
        invalid = violations(paths)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"PO03_PATH_SCOPE_ERROR: {exc}", file=sys.stderr)
        return 2
    if invalid:
        for path in invalid:
            print(f"PO03_PATH_SCOPE_VIOLATION: {path}", file=sys.stderr)
        return 1
    print(f"PO03_PATH_SCOPE_PASS changed_paths={len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
