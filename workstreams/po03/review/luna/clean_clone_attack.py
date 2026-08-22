#!/usr/bin/env python3
"""Probe a fetched producer commit without checking it out or changing it."""

from __future__ import annotations

import argparse
import json
import subprocess


REQUIRED = {
    "runner": "workstreams/po03/runtime/clean_clone.sh",
    "tests": "workstreams/po03/tests/test_a3_clean_clone.py",
    "transcript": "workstreams/po03/runtime/transcripts/clean-clone.json",
}


def git(*args: str) -> tuple[int, bytes, bytes]:
    process = subprocess.run(["git", *args], capture_output=True, check=False)
    return process.returncode, process.stdout, process.stderr


def probe(ref: str) -> dict:
    objects = {}
    for label, path in REQUIRED.items():
        code, _, _ = git("cat-file", "-e", f"{ref}:{path}")
        objects[label] = {"path": path, "present": code == 0}

    code, runner, stderr = git("show", f"{ref}:{REQUIRED['runner']}")
    syntax = subprocess.run(
        ["sh", "-n"],
        input=runner,
        capture_output=True,
        check=False,
    )
    text = runner.decode("utf-8", errors="replace") if code == 0 else ""
    checks = {
        "runner_object_read": code == 0,
        "runner_shell_syntax": syntax.returncode == 0,
        "runner_clones_remote": "git clone" in text,
        "runner_strips_environment": "env -i" in text,
        "runner_rejects_inside_repo_scratch": "refusing scratch directory inside the repository" in text,
        "runner_uses_external_default_scratch": 'SCRATCH=$(mktemp -d)' in text,
    }
    missing = [label for label, item in objects.items() if not item["present"]]
    tree_code, tree_output, _ = git("ls-tree", "-r", "--name-only", ref)
    tracked_generated = [
        path
        for path in tree_output.decode("utf-8", errors="replace").splitlines()
        if "__pycache__/" in path or path.endswith(".pyc")
    ]
    return {
        "ref": ref,
        "objects": objects,
        "runner_checks": checks,
        "tracked_generated_files": tracked_generated,
        "missing_required_objects": missing,
        "status": "ESCAPE_FOUND" if missing or tracked_generated else "NO_ESCAPE_IN_PROBES",
        "stderr": stderr.decode("utf-8", errors="replace") if code else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True)
    args = parser.parse_args()
    print(json.dumps(probe(args.ref), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
