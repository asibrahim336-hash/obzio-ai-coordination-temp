#!/usr/bin/env python3
"""Read every manifest artifact back from an immutable commit and verify it.

Clones the repository with ``--no-hardlinks`` so the verifying copy shares no
object storage with the producing worktree, then reads each artifact with
``git show --no-textconv <commit>:<path>`` and compares SHA-256 and byte count
against the manifest.  A read-back that succeeds only because it shared inodes
with the producer would prove nothing.

Usage:

    PYTHONDONTWRITEBYTECODE=1 python3 verify_readback.py \\
        --remote <url-or-path> --commit <sha> --out readback-verification.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MANIFEST_PATH = "workstreams/po03/wave-a/units/wa-013/result/artifact-manifest.json"
OWNED_PREFIX = "workstreams/po03/wave-a/units/wa-013/"


def redact_remote(remote: str) -> str:
    """Strip any userinfo from a remote URL so tokens never reach durable evidence."""
    scheme, separator, rest = remote.partition("://")
    if not separator:
        return remote
    userinfo, at, hostpath = rest.rpartition("@")
    if not at:
        return remote
    return f"{scheme}://<redacted-credential>@{hostpath}"


def git(args: list[str], cwd: Path, *, binary: bool = False) -> Any:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(
            f"git {' '.join(args)} failed in {cwd}: {result.stderr.decode(errors='replace')}"
        )
    return result.stdout if binary else result.stdout.decode()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", required=True, help="remote URL or path to clone from")
    parser.add_argument("--commit", required=True, help="immutable result commit to read back")
    parser.add_argument("--branch", default="cursor/po03-wa-013-b195-a02-1a9f")
    parser.add_argument("--out", type=Path, default=HERE / "readback-verification.json")
    parser.add_argument("--keep-clone", type=Path, default=None)
    args = parser.parse_args(argv)

    workdir = Path(tempfile.mkdtemp(prefix="po03-wa-013-readback-"))
    clone = workdir / "clone"
    try:
        git(
            [
                "clone",
                "--no-hardlinks",
                "--no-local",
                "--branch",
                args.branch,
                "--single-branch",
                args.remote,
                str(clone),
            ],
            workdir,
        )
        git(["fetch", "--force", "origin", args.commit], clone)
        head = git(["rev-parse", "FETCH_HEAD"], clone).strip()
        commit_present = git(["cat-file", "-t", args.commit], clone).strip()

        alternates = clone / ".git" / "objects" / "info" / "alternates"
        shares_object_store = alternates.is_file()

        raw_manifest = git(["show", "--no-textconv", f"{args.commit}:{MANIFEST_PATH}"], clone, binary=True)
        manifest = json.loads(raw_manifest)

        checks: list[dict[str, Any]] = []
        total = 0
        for artifact in manifest["artifacts"]:
            path = artifact["content_uri"]
            blob = git(["show", "--no-textconv", f"{args.commit}:{path}"], clone, binary=True)
            digest = hashlib.sha256(blob).hexdigest()
            matches = digest == artifact["sha256"] and len(blob) == artifact["bytes"]
            total += len(blob)
            checks.append(
                {
                    "path": path,
                    "expected_sha256": artifact["sha256"],
                    "observed_sha256": digest,
                    "expected_bytes": artifact["bytes"],
                    "observed_bytes": len(blob),
                    "matches": matches,
                }
            )

        manifest_digest = hashlib.sha256(raw_manifest).hexdigest()
        changed = git(
            ["diff", "--name-only", "6559606ac8db12e3f484e9bb74c2b4a05cc3a998", args.commit], clone
        ).split()
        outside = sorted(path for path in changed if not path.startswith(OWNED_PREFIX))

        report = {
            "protocol_version": "OBZIO-IMMUTABLE-READBACK-v1",
            "task_id": "PO03-WA-013",
            "attempt_id": "PO03-WA-013-A02",
            "method": "git clone --no-hardlinks --no-local --single-branch, then git show --no-textconv <commit>:<path> for every manifest artifact",
            "clone_shares_object_store_with_producer": shares_object_store,
            "clone_is_independent_copy": not shares_object_store,
            "remote": redact_remote(args.remote),
            "branch": args.branch,
            "result_commit": args.commit,
            "result_commit_object_type": commit_present,
            "remote_branch_tip_at_readback": head,
            "immutable_controller_base": "6559606ac8db12e3f484e9bb74c2b4a05cc3a998",
            "manifest_path": MANIFEST_PATH,
            "manifest_sha256": manifest_digest,
            "manifest_bytes": len(raw_manifest),
            "declared_artifact_count": manifest["artifact_count"],
            "declared_total_bytes": manifest["total_bytes"],
            "verified_artifact_count": len(checks),
            "verified_total_bytes": total,
            "artifact_count_matches": len(checks) == manifest["artifact_count"],
            "total_bytes_matches": total == manifest["total_bytes"],
            "all_artifacts_match": all(check["matches"] for check in checks),
            "changed_paths_from_immutable_base": sorted(changed),
            "changed_path_count": len(changed),
            "changed_paths_outside_owned_prefix": outside,
            "out_of_scope_changed_path_count": len(outside),
            "checks": checks,
            "decision_changed": [],
        }
        payload = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode("utf-8")
        args.out.write_bytes(payload)

        ok = (
            report["all_artifacts_match"]
            and report["artifact_count_matches"]
            and report["total_bytes_matches"]
            and report["clone_is_independent_copy"]
            and not outside
        )
        print(f"readback artifacts={len(checks)} bytes={total} all_match={report['all_artifacts_match']}")
        print(f"independent_clone={report['clone_is_independent_copy']} out_of_scope_paths={len(outside)}")
        print(f"manifest_sha256={manifest_digest} bytes={len(raw_manifest)}")
        if args.keep_clone is not None:
            shutil.move(str(clone), str(args.keep_clone))
            print(f"clone retained at {args.keep_clone}")
        return 0 if ok else 1
    finally:
        if clone.exists():
            shutil.rmtree(clone, ignore_errors=True)
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
