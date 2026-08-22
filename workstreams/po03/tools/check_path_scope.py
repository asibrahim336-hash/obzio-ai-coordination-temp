#!/usr/bin/env python3
"""Fail closed when a PO-03 change escapes its commissioned path allowlist."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import PurePosixPath


PINNED_BASE_SHA = "5db7affeb7f00763e148e6d98a33ee6b751f2def"
ALLOWED_PREFIXES = ("workstreams/po03/", "receipts/po03/")

# The commissioned allowlist is the glob .github/workflows/po03-*.yml, which
# admits a single file directly in that directory. A prefix-and-suffix test also
# admitted nested paths such as .github/workflows/po03-a/b.yml, so the name
# segment must be matched explicitly and must not contain a separator.
WORKFLOW_RE = re.compile(r"^\.github/workflows/po03-[^/]*\.yml$")

# git mode bits for a symbolic link and a gitlink. Neither is a plain file, so a
# changed-path check that only reads names cannot see where they point.
SYMLINK_MODE = "120000"
GITLINK_MODE = "160000"


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
    return WORKFLOW_RE.fullmatch(path) is not None


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
    """Enumerate every changed path, including both images of a rename.

    `git diff --name-only` reports only a rename's destination, so a file moved
    *out* of the allowlist would show only its new name. Reading the raw format
    exposes both images and the file mode, which is also the only way to see that
    an entry is a symlink or a gitlink rather than a plain file.
    """
    result = subprocess.run(
        ("git", "diff", "--raw", "-M", "-C", "-z", f"{base}...{head}"),
        check=True,
        capture_output=True,
    )
    fields = [item.decode("utf-8") for item in result.stdout.split("\0".encode()) if item]
    paths: list[str] = []
    index = 0
    while index < len(fields):
        record = fields[index]
        if not record.startswith(":"):
            index += 1
            continue
        # ":<old-mode> <new-mode> <old-sha> <new-sha> <status>"
        parts = record[1:].split()
        status = parts[4] if len(parts) > 4 else ""
        followers = 2 if status[:1] in {"R", "C"} else 1
        for offset in range(1, followers + 1):
            if index + offset < len(fields):
                paths.append(fields[index + offset])
        index += followers + 1
    return paths


def non_plain_entries(base: str, head: str) -> list[str]:
    """Report changed entries that are symlinks or gitlinks.

    A name-only check cannot see a symlink's target, so an in-allowlist name can
    point anywhere. Such entries are reported so they are never silently trusted.
    """
    result = subprocess.run(
        ("git", "diff", "--raw", "-M", "-C", "-z", f"{base}...{head}"),
        check=True,
        capture_output=True,
    )
    fields = [item.decode("utf-8") for item in result.stdout.split("\0".encode()) if item]
    flagged: list[str] = []
    index = 0
    while index < len(fields):
        record = fields[index]
        if not record.startswith(":"):
            index += 1
            continue
        parts = record[1:].split()
        old_mode, new_mode = (parts[0], parts[1]) if len(parts) > 1 else ("", "")
        status = parts[4] if len(parts) > 4 else ""
        followers = 2 if status[:1] in {"R", "C"} else 1
        if {old_mode, new_mode} & {SYMLINK_MODE, GITLINK_MODE}:
            for offset in range(1, followers + 1):
                if index + offset < len(fields):
                    kind = "symlink" if SYMLINK_MODE in {old_mode, new_mode} else "gitlink"
                    flagged.append(f"{fields[index + offset]} ({kind})")
        index += followers + 1
    return sorted(set(flagged))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=PINNED_BASE_SHA)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--path", action="append", dest="paths")
    args = parser.parse_args(argv)
    try:
        from_git = args.paths is None
        paths = changed_paths(args.base, args.head) if from_git else args.paths
        invalid = violations(paths)
        flagged = non_plain_entries(args.base, args.head) if from_git else []
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"PO03_PATH_SCOPE_ERROR: {exc}", file=sys.stderr)
        return 2
    if invalid:
        for path in invalid:
            print(f"PO03_PATH_SCOPE_VIOLATION: {path}", file=sys.stderr)
        return 1
    if flagged:
        for entry in flagged:
            print(f"PO03_PATH_SCOPE_NON_PLAIN_ENTRY: {entry}", file=sys.stderr)
        return 1
    print(f"PO03_PATH_SCOPE_PASS changed_paths={len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
