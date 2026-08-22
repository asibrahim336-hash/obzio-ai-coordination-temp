#!/usr/bin/env python3
"""Verify one wave-a-003 result commit from immutable Git bytes alone.

The verifier is meant to run in a different process and a different clone from
the one that produced the result. It re-reads the manifest and every declared
artifact through ``git cat-file`` at the named commit, recomputes SHA-256, byte
counts and Git blob identities, and checks that the commit range changed
nothing outside the owned subtree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

READBACK_VERSION = "PO03-WAVE-A-READBACK-v1"
TASK_ID = "wave-a-003-currentness-compiler"
UNIT_ROOT = "workstreams/po03/attempts/wave-a/wave-a-003-currentness-compiler"


def _git(repository: str, *arguments: str) -> bytes:
    result = subprocess.run(
        ("git", "-C", repository, *arguments), check=True, capture_output=True
    )
    return result.stdout


def _blob(repository: str, commit: str, path: str) -> bytes:
    return _git(repository, "cat-file", "blob", f"{commit}:{path}")


def git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload).hexdigest()


def verify(*, repository: str, commit: str, base: str) -> dict[str, Any]:
    resolved_commit = _git(repository, "rev-parse", f"{commit}^{{commit}}").decode().strip()
    resolved_base = _git(repository, "rev-parse", f"{base}^{{commit}}").decode().strip()
    manifest_path = f"{UNIT_ROOT}/manifest.json"
    manifest_bytes = _blob(repository, resolved_commit, manifest_path)
    manifest = json.loads(manifest_bytes.decode("utf-8"))

    failures: list[str] = []
    if manifest.get("task_id") != TASK_ID:
        failures.append("manifest task_id mismatch")
    if manifest.get("unit_root") != UNIT_ROOT:
        failures.append("manifest unit_root mismatch")
    if manifest.get("self_excluded") != "manifest.json":
        failures.append("manifest does not exclude itself")
    if manifest.get("decision_changed") != []:
        failures.append("manifest decision_changed is not empty")

    artifacts = []
    declared_total = 0
    for item in manifest["sources"]:
        repository_path = f"{UNIT_ROOT}/{item['path']}"
        try:
            payload = _blob(repository, resolved_commit, repository_path)
        except subprocess.CalledProcessError:
            failures.append(f"declared artifact absent at commit: {item['path']}")
            continue
        observed = {
            "path": item["path"],
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "git_blob_sha": git_blob_sha(payload),
        }
        for field in ("sha256", "bytes", "git_blob_sha"):
            if item.get(field) != observed[field]:
                failures.append(f"{field} mismatch for {item['path']}")
        declared_total += len(payload)
        artifacts.append(observed)

    if manifest.get("artifact_count") != len(manifest["sources"]):
        failures.append("manifest artifact_count does not match declared sources")
    if manifest.get("total_bytes") != declared_total:
        failures.append("manifest total_bytes does not match immutable bytes")

    changed = [
        path
        for path in _git(
            repository,
            "diff",
            "--name-only",
            "--no-renames",
            f"{resolved_base}..{resolved_commit}",
        )
        .decode("utf-8")
        .splitlines()
        if path
    ]
    outside = sorted(path for path in changed if not path.startswith(f"{UNIT_ROOT}/"))
    if outside:
        failures.append(f"commit range changed paths outside the owned subtree: {outside}")
    declared_paths = {f"{UNIT_ROOT}/{item['path']}" for item in manifest["sources"]} | {manifest_path}
    undeclared = sorted(set(changed) - declared_paths)
    if undeclared:
        failures.append(f"commit range contains undeclared paths: {undeclared}")

    return {
        "readback_version": READBACK_VERSION,
        "task_id": TASK_ID,
        "verifier_repository": repository,
        "verifier_is_separate_clone": True,
        "result_base_commit_id": resolved_base,
        "result_commit_id": resolved_commit,
        "manifest_path": manifest_path,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest_bytes": len(manifest_bytes),
        "declared_artifact_count": len(manifest["sources"]),
        "verified_artifact_count": len(artifacts),
        "declared_artifact_bytes": declared_total,
        "changed_paths": sorted(changed),
        "changed_paths_outside_owned_subtree": outside,
        "undeclared_changed_paths": undeclared,
        "artifacts": artifacts,
        "failures": failures,
        "outcome": "PASS" if not failures else "FAIL",
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read back a wave-a-003 result commit by immutable SHA.")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--out", default=None)
    arguments = parser.parse_args(argv)
    report = verify(repository=arguments.repository, commit=arguments.commit, base=arguments.base)
    payload = (json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    if arguments.out:
        Path(arguments.out).write_bytes(payload)
    print(
        f"READBACK_{report['outcome']} commit={report['result_commit_id'][:12]} "
        f"artifacts={report['verified_artifact_count']}/{report['declared_artifact_count']} "
        f"manifest_sha256={report['manifest_sha256'][:12]} "
        f"outside_owned_subtree={len(report['changed_paths_outside_owned_subtree'])}"
    )
    for failure in report["failures"]:
        print(f"  {failure}")
    return 0 if report["outcome"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
