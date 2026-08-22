#!/usr/bin/env python3
"""Independently read every manifested artifact back from git, not the working tree.

Two independent reads are performed for each artifact:
  local commit  -- `git cat-file blob <commit>:<path>`
  remote ref    -- the same read against the commit that `git ls-remote` reports
                   for the result branch, so the evidence is proven durable at the
                   remote and not merely committed locally.

Digests are recomputed from the returned bytes and compared with manifest.json.
A working-tree read would prove nothing about durability, so none is used here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ATTEMPT_ROOT = HERE.parent
MANIFEST = ATTEMPT_ROOT / "manifest.json"
BRANCH = "po03/wave-a-041-schema-adversarial-review"


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ATTEMPT_ROOT, check=True, capture_output=True, text=False
    )
    return result.stdout.decode("utf-8", errors="strict")


def git_blob(commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "cat-file", "blob", f"{commit}:{path}"],
        cwd=ATTEMPT_ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout


def remote_commit() -> str:
    output = git("ls-remote", "origin", f"refs/heads/{BRANCH}").strip()
    if not output:
        raise SystemExit(f"remote branch {BRANCH} not found")
    return output.split()[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", default="HEAD", help="local commit to read artifacts from")
    parser.add_argument("--skip-remote", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    local = git("rev-parse", args.commit).strip()
    remote = None if args.skip_remote else remote_commit()

    report = {
        "readback_version": "PO03-WAVE-A-041-READBACK-v1",
        "branch": BRANCH,
        "local_commit": local,
        "remote_commit": remote,
        "remote_matches_local": remote == local if remote else None,
        "artifact_count": manifest["artifact_count"],
        "sources_read": ["git object at local commit"] + ([] if args.skip_remote else ["git object at remote commit"]),
        "artifacts": [],
    }

    failures = 0
    for artifact in manifest["artifacts"]:
        entry = {"logical_name": artifact["logical_name"], "expected_sha256": artifact["sha256"], "expected_bytes": artifact["bytes"]}
        for label, commit in (("local", local), ("remote", remote)):
            if commit is None:
                continue
            data = git_blob(commit, artifact["repository_path"])
            digest = hashlib.sha256(data).hexdigest()
            ok = digest == artifact["sha256"] and len(data) == artifact["bytes"]
            entry[f"{label}_sha256"] = digest
            entry[f"{label}_bytes"] = len(data)
            entry[f"{label}_verified"] = ok
            if not ok:
                failures += 1
        report["artifacts"].append(entry)

    # The manifest cannot cover itself, so verify it separately.
    manifest_entry = {"logical_name": "manifest.json"}
    for label, commit in (("local", local), ("remote", remote)):
        if commit is None:
            continue
        data = git_blob(commit, f"{manifest['result_slot']}/manifest.json")
        manifest_entry[f"{label}_sha256"] = hashlib.sha256(data).hexdigest()
        manifest_entry[f"{label}_bytes"] = len(data)
    digests = {value for key, value in manifest_entry.items() if key.endswith("_sha256")}
    manifest_entry["local_and_remote_agree"] = len(digests) == 1
    if not manifest_entry["local_and_remote_agree"]:
        failures += 1
    report["manifest_self"] = manifest_entry

    report["outcome"] = "PASS" if failures == 0 else "FAIL"
    report["failed_reads"] = failures
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
