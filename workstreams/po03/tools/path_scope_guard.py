#!/usr/bin/env python3
"""Changed-path guard for the PO-03 wave-one write allowlist.

Reads changed repository paths from argv or stdin, one per line (or NUL
separated with --null), and rejects any path outside the allowlist.  Ambiguous
input is rejected rather than interpreted, so an evasion attempt fails the
build instead of passing unnoticed.

Exit codes: 0 all paths in scope, 1 at least one path out of scope or
unusable, 2 invalid usage.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
from typing import NamedTuple


DIRECTORY_ALLOWLIST: tuple[str, ...] = (
    "workstreams/po03/",
    "receipts/po03/",
)

WORKFLOW_DIRECTORY = ".github/workflows/"
WORKFLOW_PREFIX = "po03-"
WORKFLOW_SUFFIX = ".yml"

ALLOWLIST_DESCRIPTION = (
    "workstreams/po03/**, receipts/po03/**, .github/workflows/po03-*.yml"
)

DRIVE_RE = re.compile(r"^[A-Za-z]:")

EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_USAGE = 2


class Rejection(NamedTuple):
    raw: str
    reason: str


def normalize(raw: str) -> tuple[str | None, str]:
    candidate = raw.rstrip("\r\n")
    if not candidate.strip():
        return None, "blank"
    if "\x00" in candidate:
        return None, "contains NUL byte"
    if candidate.startswith('"'):
        return None, "git-quoted path is ambiguous; re-run the diff with -z and pass --null"
    if "\\" in candidate:
        return None, "backslash is not a supported path separator"
    if candidate.startswith("/") or DRIVE_RE.match(candidate):
        return None, "absolute paths are not repository-relative"
    normalized = posixpath.normpath(candidate)
    if normalized == "." or normalized == ".." or normalized.startswith("../"):
        return None, "resolves outside the repository root"
    return normalized, ""


def is_allowed(normalized: str) -> bool:
    for prefix in DIRECTORY_ALLOWLIST:
        if normalized.startswith(prefix) and len(normalized) > len(prefix):
            return True
    if normalized.startswith(WORKFLOW_DIRECTORY):
        filename = normalized[len(WORKFLOW_DIRECTORY) :]
        if "/" in filename:
            return False
        return (
            filename.startswith(WORKFLOW_PREFIX)
            and filename.endswith(WORKFLOW_SUFFIX)
            and len(filename) > len(WORKFLOW_PREFIX) + len(WORKFLOW_SUFFIX)
        )
    return False


def check(paths: list[str]) -> tuple[list[str], list[Rejection]]:
    accepted: list[str] = []
    rejected: list[Rejection] = []
    for raw in paths:
        normalized, reason = normalize(raw)
        if normalized is None:
            if reason == "blank":
                continue
            rejected.append(Rejection(raw, reason))
            continue
        if is_allowed(normalized):
            accepted.append(normalized)
        else:
            rejected.append(Rejection(raw, "outside the PO-03 write allowlist"))
    return accepted, rejected


def split_input(text: str, null_separated: bool) -> list[str]:
    separator = "\x00" if null_separated else "\n"
    return [part for part in text.split(separator)]


def main(argv: list[str] | None = None, stdin: object | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when a changed path falls outside the PO-03 allowlist."
    )
    parser.add_argument("paths", nargs="*", help="changed repository paths")
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="read paths from standard input even when positional paths are given",
    )
    parser.add_argument(
        "--null",
        action="store_true",
        help="treat standard input as NUL separated (pair with git diff --name-only -z)",
    )
    args = parser.parse_args(argv)

    paths = list(args.paths)
    if args.stdin or not paths:
        stream = sys.stdin if stdin is None else stdin
        try:
            text = stream.read()
        except OSError as exc:
            print(f"PATH-SCOPE GUARD: ERROR reading stdin: {exc}")
            return EXIT_USAGE
        paths.extend(split_input(text, args.null))

    accepted, rejected = check(paths)

    if rejected:
        for item in rejected:
            print(f"OUT-OF-ALLOWLIST: {item.raw} :: {item.reason}")
        print(
            f"PATH-SCOPE GUARD: FAIL {len(rejected)} rejected, "
            f"{len(accepted)} in scope"
        )
        print(f"PATH-SCOPE GUARD: allowlist is {ALLOWLIST_DESCRIPTION}")
        return EXIT_REJECTED

    print(f"PATH-SCOPE GUARD: PASS {len(accepted)} paths in scope")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
