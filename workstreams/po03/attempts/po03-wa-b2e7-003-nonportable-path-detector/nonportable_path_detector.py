#!/usr/bin/env python3
"""Scan committed PO-03 text blobs for machine-bound filesystem paths."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
from pathlib import Path
from typing import Any


PATTERNS = {
    "temporary-root": re.compile(r"(?<![A-Za-z0-9_])/(?:private/)?tmp(?:/|(?=[\s\"'`,.;:)]|$))"),
    "home-relative": re.compile(r"(?<![A-Za-z0-9_])~/[^\s\"'`]*"),
    "user-home-root": re.compile(r"(?<![A-Za-z0-9_])/(?:home|Users)/[^\s\"'`]+"),
    "worktree-root": re.compile(r"(?<![A-Za-z0-9_])/[^\s\"'`]*worktrees?/[^\s\"'`]*"),
    "machine-root": re.compile(r"(?<![A-Za-z0-9_])/(?:workspace|root|opt|var|etc|usr|mnt|srv)/[^\s\"'`]+"),
    "windows-user-root": re.compile(r"(?i)(?<![A-Za-z0-9_])[a-z]:\\Users\\[^\s\"'`]+"),
}


def git(repo: Path, *argv: str, text: bool = True) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ("git", *argv),
        cwd=repo,
        capture_output=True,
        text=text,
    )


def allowed(entries: list[dict[str, object]], path: str, pattern: str, line: int) -> bool:
    for entry in entries:
        if not fnmatch.fnmatchcase(path, str(entry.get("path", ""))):
            continue
        if entry.get("pattern") not in (None, "*", pattern):
            continue
        if entry.get("line") not in (None, line):
            continue
        return True
    return False


def scan(repo: Path, commit: str, allowlist: list[dict[str, object]]) -> tuple[int, dict[str, object]]:
    exists = git(repo, "cat-file", "-e", f"{commit}^{{commit}}")
    if exists.returncode:
        return 2, {"error": "commit is absent"}
    listing = git(
        repo,
        "ls-tree",
        "-r",
        "--name-only",
        "-z",
        commit,
        "--",
        "workstreams/po03",
    )
    if listing.returncode:
        return 2, {"error": "cannot enumerate committed PO-03 artifacts"}

    findings: list[dict[str, object]] = []
    scanned = 0
    skipped_binary = 0
    for path in sorted(item for item in listing.stdout.split("\0") if item):
        blob = git(repo, "cat-file", "blob", f"{commit}:{path}", text=False)
        if blob.returncode:
            return 2, {"error": f"cannot read committed blob: {path}"}
        body = blob.stdout
        if b"\0" in body:
            skipped_binary += 1
            continue
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            skipped_binary += 1
            continue
        scanned += 1
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern_id, expression in PATTERNS.items():
                for match in expression.finditer(line):
                    if allowed(allowlist, path, pattern_id, line_number):
                        continue
                    findings.append(
                        {
                            "path": path,
                            "line": line_number,
                            "column": match.start() + 1,
                            "pattern": pattern_id,
                            "match": match.group(0),
                        }
                    )
    report: dict[str, object] = {
        "commit": commit,
        "scanned_text_artifacts": scanned,
        "skipped_binary_artifacts": skipped_binary,
        "finding_count": len(findings),
        "findings": findings,
    }
    return (1 if findings else 0), report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--allowlist", type=Path)
    args = parser.parse_args(argv)
    allowlist: list[dict[str, object]] = []
    if args.allowlist:
        try:
            loaded = json.loads(args.allowlist.read_text(encoding="utf-8"))
            if not isinstance(loaded, list) or not all(isinstance(item, dict) for item in loaded):
                raise ValueError("allowlist must be an array of objects")
            allowlist = loaded
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({"error": f"invalid allowlist: {exc}"}, sort_keys=True))
            return 2
    code, report = scan(args.repo.resolve(), args.commit, allowlist)
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
