#!/usr/bin/env python3
"""Emit a transactional result document for one PO-03 work unit.

A subordinate never hand-writes custody metadata.  It names the artifacts it
actually produced and this tool derives the hashes, byte counts and locators
from the committed tree, so a result can only describe bytes that exist.  The
strongest state a subordinate may emit is RESULT_COMMITTED; COMPLETED belongs
to the coordinator and ACCEPTED belongs to an independent reviewer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("unit_id")
    parser.add_argument("--root", default=".", help="worktree root")
    parser.add_argument("--artifact", action="append", default=[], help="repo-relative artifact path")
    parser.add_argument("--fence-token", type=int, default=1)
    parser.add_argument("--provider-run-id", required=True)
    parser.add_argument(
        "--state",
        default="RESULT_COMMITTED",
        choices=["RESULT_COMMITTED", "PROVIDER_COMPLETED_UNCOMMITTED", "FAILED_TERMINAL"],
    )
    parser.add_argument("--out", help="output path (defaults to the unit record slot)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    dispatch = json.loads(
        (root / "workstreams/po03/control/dispatch" / f"{args.unit_id}.json").read_text(encoding="utf-8")
    )
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    commit = git(root, "rev-parse", "HEAD")
    worker_id = dispatch["owner"]

    committed = args.state == "RESULT_COMMITTED"
    artifacts = []
    for index, relative in enumerate(sorted(set(args.artifact)), start=1):
        target = root / relative
        if not target.is_file():
            raise SystemExit(f"artifact does not exist in the worktree: {relative}")
        tracked = git(root, "ls-files", "--error-unmatch", relative)
        if not tracked:
            raise SystemExit(f"artifact is not committed: {relative}")
        media, _ = mimetypes.guess_type(relative)
        artifacts.append(
            {
                "artifact_id": f"{args.unit_id}-art-{index:02d}",
                "logical_name": relative.rsplit("/", 1)[-1],
                "content_uri": f"git:{branch}@{commit}:{relative}",
                "sha256": sha256_file(target),
                "bytes": target.stat().st_size,
                "media_type": media or "application/octet-stream",
                "readback_verified_at": utc_now() if committed else None,
            }
        )

    if committed and not artifacts:
        raise SystemExit("RESULT_COMMITTED requires at least one committed artifact")

    manifest = {
        "unit_id": args.unit_id,
        "branch": branch,
        "commit": commit,
        "artifacts": [{"logical_name": a["logical_name"], "sha256": a["sha256"], "bytes": a["bytes"]} for a in artifacts],
    }
    manifest_sha = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    now = utc_now()
    document = {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": args.unit_id,
        "commission_id": dispatch["commission_id"],
        "immutable_input_manifest_sha256": dispatch["immutable_input_manifest_sha256"],
        "acceptance_contract_sha256": dispatch["acceptance_contract_sha256"],
        "provider_state": "COMPLETED" if committed else "UNKNOWN",
        "obzio_state": args.state,
        "attempt": {
            "attempt_id": f"{args.unit_id}-attempt-{args.fence_token}",
            "idempotency_key": dispatch["idempotency_key"],
            "lease_id": f"lease-{args.unit_id}-{args.fence_token}",
            "fence_token": args.fence_token,
            "provider_run_id": args.provider_run_id,
            "worker_id": worker_id,
            "heartbeat_at": now,
            "checkpoint_seq": len(artifacts),
        },
        "result_transaction": {
            "result_txn_id": f"{args.unit_id}-txn-{args.fence_token}",
            "state": "COMMITTED" if committed else "RESERVED",
            "manifest_uri": f"git:{branch}@{commit}:{args.unit_id}" if committed else None,
            "manifest_sha256": manifest_sha if committed else None,
            "artifact_count": len(artifacts),
            "total_bytes": sum(a["bytes"] for a in artifacts),
            "committed_at": now if committed else None,
            "verified_at": now if committed else None,
            "parent_ingested_at": None,
            "result_commit_id": commit if committed else None,
        },
        "artifacts": artifacts,
        "completion_actor": None,
        "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
    }

    out = Path(args.out) if args.out else root / dispatch["result_slot"]["unit_record"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(artifacts)} artifacts, {document['result_transaction']['total_bytes']} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
