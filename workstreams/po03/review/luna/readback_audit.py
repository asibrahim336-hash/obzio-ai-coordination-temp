#!/usr/bin/env python3
"""Audit result artifacts directly from immutable git objects."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess


URI = re.compile(r"^git:.+@([0-9a-f]{40}):(.+)$")


def git(*args: str) -> tuple[int, bytes, bytes]:
    process = subprocess.run(["git", *args], capture_output=True, check=False)
    return process.returncode, process.stdout, process.stderr


def audit_target(target: str) -> dict:
    ref, record_path = target.split(":", 1)
    code, raw, stderr = git("show", f"{ref}:{record_path}")
    if code != 0:
        return {
            "target": target,
            "status": "UNAVAILABLE",
            "reason": stderr.decode("utf-8", errors="replace").strip(),
            "artifacts_checked": 0,
        }
    document = json.loads(raw)
    artifacts = document.get("artifacts", [])
    checks = []
    for artifact in artifacts:
        uri = artifact.get("content_uri", "")
        match = URI.match(uri)
        if not match:
            checks.append(
                {
                    "logical_name": artifact.get("logical_name"),
                    "status": "INVALID_URI",
                }
            )
            continue
        commit, path = match.groups()
        object_code, content, object_stderr = git("cat-file", "blob", f"{commit}:{path}")
        observed_hash = hashlib.sha256(content).hexdigest() if object_code == 0 else None
        checks.append(
            {
                "logical_name": artifact.get("logical_name"),
                "declared_sha256": artifact.get("sha256"),
                "observed_sha256": observed_hash,
                "declared_bytes": artifact.get("bytes"),
                "observed_bytes": len(content) if object_code == 0 else None,
                "immutable_commit": commit,
                "path": path,
                "hash_match": observed_hash == artifact.get("sha256"),
                "bytes_match": len(content) == artifact.get("bytes") if object_code == 0 else False,
                "object_present": object_code == 0,
                "object_error": object_stderr.decode("utf-8", errors="replace").strip(),
            }
        )
    result_commit = document.get("result_transaction", {}).get("result_commit_id")
    record_present_at_result_commit = False
    if isinstance(result_commit, str) and result_commit:
        record_present_at_result_commit = (
            git("cat-file", "-e", f"{result_commit}:{record_path}")[0] == 0
        )
    mismatches = [
        check
        for check in checks
        if not check.get("object_present")
        or not check.get("hash_match")
        or not check.get("bytes_match")
    ]
    if not record_present_at_result_commit:
        mismatches.append(
            {
                "kind": "result_record_not_at_declared_commit",
                "declared_result_commit": result_commit,
                "record_path": record_path,
            }
        )
    return {
        "target": target,
        "status": "AUDITED",
        "task_id": document.get("task_id"),
        "result_record_sha256": hashlib.sha256(raw).hexdigest(),
        "artifacts_checked": len(checks),
        "checks": checks,
        "declared_result_commit": result_commit,
        "record_present_at_declared_result_commit": record_present_at_result_commit,
        "discrepancy_count": len(mismatches),
        "discrepancies": mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", action="append", required=True, help="REF:result record path")
    args = parser.parse_args()
    report = {"targets": [audit_target(target) for target in args.target]}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
