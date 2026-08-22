#!/usr/bin/env python3
"""Emit a contract-valid transactional result for one PO-03 work unit.

A subordinate producer runs this after committing its component so the result
document it hands back is generated from committed bytes rather than asserted
from memory.  Artifact locators point at an immutable commit, every hash and
byte count is measured, and the document is validated against the seeded
contract before it is written.

The producer may only reach RESULT_COMMITTED.  Only the coordinator can ingest
and complete, so this tool refuses to emit COMPLETED or a self-acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import mimetypes
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COMMISSION_ID = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
PROTOCOL_VERSION = "OBZIO-TRANSACTIONAL-RESULT-v1"
GENERATED = ("manifest.json", "result.json")
VERDICTS = ("PASS", "FAIL", "NOT_YET", "NOT_SUPPORTED", "OWNER_BLOCKED")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments), cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def list_committed(repo: Path, commit: str, slot: str) -> list[str]:
    listing = git(repo, "ls-tree", "-r", "--name-only", "-z", commit, "--", slot)
    return sorted(item for item in listing.split("\0") if item)


def read_committed(repo: Path, commit: str, path: str) -> bytes:
    return subprocess.run(
        ("git", "cat-file", "blob", f"{commit}:{path}"),
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout


def load_validator(repo: Path):
    module_path = repo / "workstreams/po03/tools/validate_contracts.py"
    spec = importlib.util.spec_from_file_location("po03_validate_contracts", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load contract validator at {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--artifact-commit", required=True, help="commit holding the component artifacts")
    parser.add_argument("--result-branch", required=True, help="branch the manifest and result are committed to")
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--provider-run-id", required=True)
    parser.add_argument("--exact-model", required=True)
    parser.add_argument("--verdict", required=True, choices=VERDICTS)
    parser.add_argument("--evidence", required=True, help="what was executed and what it showed")
    parser.add_argument("--limitation", action="append", default=[], help="an observed limitation; repeatable")
    parser.add_argument("--checkpoint-seq", type=int, default=1)
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    capsule_path = repo / "workstreams/po03/control/tasks" / args.task_id / "input.json"
    if not capsule_path.is_file():
        raise SystemExit(f"no immutable capsule for {args.task_id}")
    capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    slot = capsule["ownership"]["result_slot"]
    transaction = capsule["transaction"]

    committed = [path for path in list_committed(repo, args.artifact_commit, slot)
                 if Path(path).name not in GENERATED]
    if not committed:
        raise SystemExit(
            f"{args.task_id}: commit {args.artifact_commit} contains no artifacts under {slot}; "
            "a counted unit must leave durable bytes"
        )

    artifacts = []
    total_bytes = 0
    for index, path in enumerate(committed, start=1):
        body = read_committed(repo, args.artifact_commit, path)
        if not body:
            raise SystemExit(f"{args.task_id}: refusing to count empty artifact {path}")
        media_type = mimetypes.guess_type(path)[0] or "text/plain"
        artifacts.append(
            {
                "artifact_id": f"{args.task_id}-artifact-{index:03d}",
                "logical_name": Path(path).relative_to(slot).as_posix(),
                "content_uri": f"git:{args.artifact_commit}:{path}",
                "sha256": sha256_bytes(body),
                "bytes": len(body),
                "media_type": media_type,
                "readback_verified_at": utc_now(),
            }
        )
        total_bytes += len(body)

    manifest = {
        "manifest_version": "PO03-ARTIFACT-MANIFEST-v1",
        "task_id": args.task_id,
        "result_slot": slot,
        "artifact_commit": args.artifact_commit,
        "artifact_count": len(artifacts),
        "total_bytes": total_bytes,
        "artifacts": artifacts,
        "falsifiable_hypothesis": capsule["falsifiable_hypothesis"],
        "verdict": args.verdict,
        "evidence": args.evidence,
        "limitations": args.limitation,
        "producer": {
            "obzio_state_claim": "READY_TO_COMMIT",
            "worker_id": args.worker_id,
            "exact_model": args.exact_model,
            "provider_run_id": args.provider_run_id,
        },
        "generated_at": utc_now(),
        "decision_changed": [],
    }
    manifest_bytes = canonical(manifest)
    manifest_path = repo / slot / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(manifest_bytes)

    result = {
        "protocol_version": PROTOCOL_VERSION,
        "task_id": args.task_id,
        "commission_id": COMMISSION_ID,
        "immutable_input_manifest_sha256": sha256_bytes(capsule_path.read_bytes()),
        "acceptance_contract_sha256": capsule["source_hashes"]["acceptance_contract_sha256"],
        "provider_state": "RUNNING",
        "obzio_state": "RESULT_COMMITTED",
        "attempt": {
            "attempt_id": f"{args.task_id}-attempt-{transaction['attempt_number']}",
            "idempotency_key": transaction["idempotency_key"],
            "lease_id": transaction["lease_id"],
            "fence_token": transaction["fence_token"],
            "provider_run_id": args.provider_run_id,
            "worker_id": args.worker_id,
            "heartbeat_at": utc_now(),
            "checkpoint_seq": args.checkpoint_seq,
        },
        "result_transaction": {
            "result_txn_id": f"result-{args.task_id}-{transaction['attempt_number']}",
            "state": "COMMITTED",
            # The manifest is committed after the artifacts it describes, so it is
            # located by branch ref rather than by the artifact commit.
            "manifest_uri": f"git:refs/heads/{args.result_branch}:{slot}/manifest.json",
            "manifest_sha256": sha256_bytes(manifest_bytes),
            "artifact_count": len(artifacts),
            "total_bytes": total_bytes,
            "committed_at": utc_now(),
            "verified_at": utc_now(),
            "parent_ingested_at": None,
            "result_commit_id": args.artifact_commit,
        },
        "artifacts": artifacts,
        "completion_actor": None,
        "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
    }

    validator = load_validator(repo)
    errors = validator.validate_result(result)
    if errors:
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1

    result_path = repo / slot / "result.json"
    result_path.write_bytes(canonical(result))
    print(
        json.dumps(
            {
                "task_id": args.task_id,
                "obzio_state": "RESULT_COMMITTED",
                "artifact_count": len(artifacts),
                "total_bytes": total_bytes,
                "manifest_sha256": result["result_transaction"]["manifest_sha256"],
                "verdict": args.verdict,
                "next": "commit manifest.json and result.json, push, then report READY_TO_COMMIT",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
