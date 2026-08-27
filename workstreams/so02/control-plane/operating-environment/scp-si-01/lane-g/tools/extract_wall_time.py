#!/usr/bin/env python3
"""Recompute per-branch wall-time facts from git history instead of transcribing them.

Nothing here trusts a receipt's own timestamp claim: for each branch this walks
the actual commits between the declared base and the branch tip and reports the
first and last commit timestamps it finds THERE, plus the commit count. This is
the same discipline `evidence_integrity.verify_readback_truth` uses for custody:
recompute from the object store, don't read a summary of it.

Usage: python3 extract_wall_time.py --repo <path> --base <sha> branch1 branch2 ...
Emits one JSON object per branch to stdout (JSON Lines).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(args: list[str], cwd: Path) -> str:
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def branch_commits(repo: Path, base: str, branch: str) -> list[dict]:
    fmt = "%H\x1f%aI\x1f%s"
    out = run(["git", "log", f"{base}..{branch}", f"--format={fmt}"], repo)
    commits = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, iso, subject = line.split("\x1f", 2)
        commits.append({"sha": sha, "authored_at": iso, "subject": subject})
    return commits


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo", default=".")
    p.add_argument("--base", required=True)
    p.add_argument("--spec", action="append", default=[],
                    help="branch:subject_prefix1|subject_prefix2 — restricts commits counted to "
                         "this lane's own subject prefixes, since a later lane's branch base "
                         "carries every earlier wave's commits too and an unfiltered range "
                         "over-counts wall time and commit count for everything after wave 1")
    p.add_argument("branches", nargs="*")
    args = p.parse_args(argv)
    repo = Path(args.repo)

    specs: list[tuple[str, list[str] | None]] = []
    for branch in args.branches:
        specs.append((branch, None))
    for raw in args.spec:
        branch, _, prefixes = raw.partition(":")
        specs.append((branch, prefixes.split("|") if prefixes else None))

    for branch, prefixes in specs:
        try:
            commits = branch_commits(repo, args.base, f"origin/{branch}")
            resolved_ref = f"origin/{branch}"
        except RuntimeError:
            try:
                commits = branch_commits(repo, args.base, branch)
                resolved_ref = branch
            except RuntimeError as exc:
                print(json.dumps({
                    "branch": branch, "resolvable": False, "error": str(exc),
                }))
                continue

        all_count = len(commits)
        if prefixes:
            commits = [c for c in commits if any(c["subject"].startswith(p) for p in prefixes)]

        commits_sorted = sorted(commits, key=lambda c: c["authored_at"])
        record = {
            "branch": branch,
            "resolvable": True,
            "resolved_ref": resolved_ref,
            "subject_prefix_filter": prefixes,
            "commit_count_in_full_base_range": all_count,
            "commit_count_matching_this_lane": len(commits_sorted),
            "first_commit_at": commits_sorted[0]["authored_at"] if commits_sorted else None,
            "last_commit_at": commits_sorted[-1]["authored_at"] if commits_sorted else None,
            "first_commit_sha": commits_sorted[0]["sha"] if commits_sorted else None,
            "last_commit_sha": commits_sorted[-1]["sha"] if commits_sorted else None,
            "subjects": [c["subject"] for c in commits_sorted],
        }
        print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
