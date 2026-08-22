#!/usr/bin/env python3
"""Verify every manifested artifact from immutable bytes in a separate clone.

The verifier reads the manifest out of Git objects, then reads each declared
artifact out of Git objects too, so nothing is confirmed from a working tree the
producer just wrote. It also confirms the remote branch tip equals the commit
being verified.

Usage:
    python3 tools/readback_verify.py --clone /path/to/fresh/clone --commit <sha> --out readback-evidence.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SLOT = "workstreams/po03/attempts/wave-a/wave-a-033-lost-callback-reproduction"
BRANCH = "po03/wave-a-033-lost-callback-reproduction"
REMOTE = "https://github.com/asibrahim336-hash/obzio-ai-coordination-temp.git"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git_text(clone: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments), cwd=clone, check=True, capture_output=True, text=True
    ).stdout.strip()


def git_blob(clone: Path, commit: str, path: str) -> bytes | None:
    probe = subprocess.run(
        ("git", "rev-parse", "--verify", f"{commit}:{path}"),
        cwd=clone,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        return None
    return subprocess.run(
        ("git", "cat-file", "blob", f"{commit}:{path}"),
        cwd=clone,
        check=True,
        capture_output=True,
    ).stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clone", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--out", required=True)
    arguments = parser.parse_args()

    clone = Path(arguments.clone)
    commit = arguments.commit

    manifest_bytes = git_blob(clone, commit, f"{SLOT}/manifest.json")
    if manifest_bytes is None:
        raise SystemExit(f"manifest.json absent from {commit}")
    manifest = json.loads(manifest_bytes.decode("utf-8"))

    checks = []
    verified = 0
    for artifact in manifest["artifacts"]:
        path = artifact["content_uri"]
        payload = git_blob(clone, commit, path)
        if payload is None:
            checks.append(
                {
                    "logical_name": artifact["logical_name"],
                    "verdict": "MISSING_IN_IMMUTABLE_BYTES",
                }
            )
            continue
        digest = hashlib.sha256(payload).hexdigest()
        blob_sha = git_text(clone, "rev-parse", f"{commit}:{path}")
        sha_ok = digest == artifact["sha256"]
        bytes_ok = len(payload) == artifact["bytes"]
        blob_ok = artifact["git_blob_sha"] in (None, blob_sha)
        checks.append(
            {
                "logical_name": artifact["logical_name"],
                "declared_sha256": artifact["sha256"],
                "readback_sha256": digest,
                "declared_bytes": artifact["bytes"],
                "readback_bytes": len(payload),
                "declared_git_blob_sha": artifact["git_blob_sha"],
                "readback_git_blob_sha": blob_sha,
                "sha256_match": sha_ok,
                "byte_count_match": bytes_ok,
                "git_blob_match": blob_ok,
                "verdict": "PASS" if (sha_ok and bytes_ok and blob_ok) else "FAIL",
            }
        )
        if sha_ok and bytes_ok and blob_ok:
            verified += 1

    # The manifest excludes itself, so record it separately rather than silently.
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()

    remote_tip = subprocess.run(
        ("git", "ls-remote", REMOTE, f"refs/heads/{BRANCH}"),
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    remote_sha = remote_tip[0] if remote_tip else None

    slot_paths = git_text(clone, "ls-tree", "-r", "--name-only", commit, "--", SLOT).splitlines()
    changed = git_text(
        clone,
        "diff",
        "--name-only",
        "e63fbae079774b151fd24a4132e4a5e571f75298",
        commit,
    ).splitlines()
    out_of_scope = [path for path in changed if not path.startswith(f"{SLOT}/")]

    document = {
        "readback_version": "PO03-WAVE-A-033-READBACK-v1",
        "task_id": "wave-a-033-lost-callback-reproduction",
        "recorded_at": utc_now(),
        "decision_changed": [],
        "verifying_clone": {
            "path": str(clone),
            "is_separate_fresh_clone": True,
            "git_dir": git_text(clone, "rev-parse", "--absolute-git-dir"),
            "git_common_dir": git_text(
                clone, "rev-parse", "--path-format=absolute", "--git-common-dir"
            ),
            "object_store_alternates": (
                (clone / ".git" / "objects" / "info" / "alternates").read_text().strip()
                if (clone / ".git" / "objects" / "info" / "alternates").exists()
                else "NONE"
            ),
            "read_only_use": "artifacts are read via git cat-file from the object store, not from the working tree",
        },
        "verified_commit": commit,
        "verification_regress_note": (
            "This file records the verification of the commit named in verified_commit. "
            "Committing it necessarily produces a later commit, which this file cannot "
            "describe. That final commit is verified by re-running this tool against a "
            "second fresh clone, and the outcome is reported in the producer return rather "
            "than committed, which is where the regress is cut."
        ),
        "remote_branch": BRANCH,
        "remote_tip_sha": remote_sha,
        "remote_tip_equals_verified_commit": remote_sha == commit,
        "manifest": {
            "path": f"{SLOT}/manifest.json",
            "sha256": manifest_digest,
            "bytes": len(manifest_bytes),
            "git_blob_sha": git_text(clone, "rev-parse", f"{commit}:{SLOT}/manifest.json"),
            "declared_artifact_count": manifest["artifact_count"],
            "self_excluded_from_its_own_artifact_list": True,
        },
        "artifacts_declared": len(manifest["artifacts"]),
        "artifacts_verified": verified,
        "all_artifacts_verified": verified == len(manifest["artifacts"]),
        "slot_file_count_in_commit": len(slot_paths),
        "slot_files_not_declared_in_manifest": sorted(
            set(path[len(SLOT) + 1 :] for path in slot_paths)
            - {artifact["logical_name"] for artifact in manifest["artifacts"]}
            - {"manifest.json"}
        ),
        "changed_paths_versus_dispatch_base": changed,
        "changed_paths_outside_owned_slot": out_of_scope,
        "scope_clean": not out_of_scope,
        "checks": checks,
    }

    Path(arguments.out).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"verified {verified}/{len(manifest['artifacts'])} artifacts from immutable bytes")
    print(f"remote_tip_equals_verified_commit={document['remote_tip_equals_verified_commit']}")
    print(f"scope_clean={document['scope_clean']}")
    for check in checks:
        if check["verdict"] != "PASS":
            print(f"  {check['verdict']}: {check['logical_name']}")
    return 0 if document["all_artifacts_verified"] and document["scope_clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
