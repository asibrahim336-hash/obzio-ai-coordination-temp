#!/usr/bin/env python3
"""Scan an immutable pack tree for machine, transport and reference coupling."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import PurePosixPath
from typing import Any


ABSOLUTE = re.compile(r"(?<![A-Za-z0-9_.-])/(?:tmp|home|workspace|Users)/[^\s`'\"<>]+")
TRANSPORT = re.compile(r"(?:_transport/|packs2/|\.\./)")


def git(repo: str, *args: str, check: bool = True) -> bytes:
    return subprocess.run(
        ("git", *args), cwd=repo, check=check, capture_output=True
    ).stdout


def read_blob(repo: str, commit: str, path: str) -> bytes | None:
    proc = subprocess.run(
        ("git", "cat-file", "blob", f"{commit}:{path}"),
        cwd=repo,
        check=False,
        capture_output=True,
    )
    return proc.stdout if proc.returncode == 0 else None


def manifest_references(path: str, value: dict[str, Any]) -> list[str]:
    parent = PurePosixPath(path).parent
    files = value.get("files", {})
    if isinstance(files, dict):
        return [str(parent / name) for name in files]
    if isinstance(files, list):
        refs = []
        for row in files:
            target = row.get("path")
            if isinstance(target, str):
                refs.append(target if "/" in target else str(parent / target))
        return refs
    return []


def scan(repo: str, commit: str, prefix: str) -> dict[str, Any]:
    listing = git(repo, "ls-tree", "-r", "--name-only", "-z", commit, "--", prefix)
    paths = sorted(item.decode() for item in listing.split(b"\0") if item)
    absolute_paths = []
    transport_assumptions = []
    unresolved_references = []

    for path in paths:
        body = read_blob(repo, commit, path)
        if body is None or b"\0" in body:
            continue
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in ABSOLUTE.finditer(line):
                absolute_paths.append(
                    {"path": path, "line": line_number, "reference": match.group(0)}
                )
            for match in TRANSPORT.finditer(line):
                transport_assumptions.append(
                    {"path": path, "line": line_number, "reference": match.group(0)}
                )
        if path.endswith("MANIFEST.json"):
            try:
                manifest = json.loads(text)
            except json.JSONDecodeError:
                continue
            for target in manifest_references(path, manifest):
                if read_blob(repo, commit, target) is None:
                    unresolved_references.append(
                        {"manifest": path, "target": target}
                    )

    findings = len(absolute_paths) + len(transport_assumptions) + len(unresolved_references)
    return {
        "commit": commit,
        "prefix": prefix,
        "files_scanned": len(paths),
        "absolute_paths": absolute_paths,
        "transport_assumptions": transport_assumptions,
        "unresolved_internal_references": unresolved_references,
        "finding_count": findings,
        "qualification": "FAIL_NONPORTABLE" if findings else "PASS_PORTABLE",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--prefix", required=True)
    args = parser.parse_args()
    print(json.dumps(scan(args.repo, args.commit, args.prefix), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
