#!/usr/bin/env python3
"""Emit the PO-03 child-canary artifacts for task po03-bc94cf-opus-canary-001.

The deterministic payload is derived from the immutable input capsule rather
than transcribed, and the capsule is hash-verified against the transaction
record first, so a transcription slip cannot silently change the nonce, the
controller commit or the lease identity.

Modes:
  payload  write the canonical deterministic payload file
  result   write canary.json from the payload, the independent read-back
           receipt for that payload and the observed runtime evidence
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

PAYLOAD_VERSION = "PO03-CHILD-CANARY-PAYLOAD-v1"
RESULT_VERSION = "PO03-CHILD-CANARY-RESULT-v1"
CANONICALIZATION = (
    'json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\\n", encoded utf-8'
)


def repo_root(script: Path) -> Path:
    root = script.resolve().parents[7]
    if not (root / "AGENTS.md").is_file():
        raise ValueError(f"repository root not resolved from {script}")
    return root


def canonical(obj: object) -> bytes:
    rendered = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return rendered.encode("utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_capsule(contract_dir: Path) -> tuple[dict, dict]:
    """Return (capsule, transaction) only when the frozen hash chain holds."""
    input_path = contract_dir / "canary-input.json"
    acceptance_path = contract_dir / "canary-acceptance.json"
    transaction_path = contract_dir / "transaction-created.json"

    capsule = load_json(input_path)
    transaction = load_json(transaction_path)

    expected = (
        (input_path, digest(input_path), transaction["immutable_input_manifest_sha256"]),
        (acceptance_path, digest(acceptance_path), transaction["acceptance_contract_sha256"]),
        (acceptance_path, digest(acceptance_path), capsule["canary"]["acceptance_sha256"]),
    )
    for path, observed, declared in expected:
        if observed != declared:
            raise ValueError(
                f"frozen input hash mismatch for {path.name}: "
                f"observed={observed} declared={declared}"
            )
    return capsule, transaction


def build_payload(capsule: dict, transaction: dict, branch: str, base_commit: str) -> dict:
    txn = capsule["transaction"]
    return {
        "acceptance_contract_sha256": capsule["canary"]["acceptance_sha256"],
        "attempt_id": txn["attempt_id"],
        "child_base_commit_sha": base_commit,
        "child_branch": branch,
        "commission_id": capsule["commission_id"],
        "controller_branch": capsule["controller_branch"],
        "controller_commit_sha": capsule["controller_commit_sha"],
        "decision_changed": [],
        "fence_token": txn["fence_token"],
        "idempotency_key": txn["idempotency_key"],
        "immutable_input_manifest_sha256": transaction["immutable_input_manifest_sha256"],
        "lease_id": txn["lease_id"],
        "material_work_authorized": capsule["runtime"]["material_work_authorized"],
        "nonce": capsule["canary"]["nonce"],
        "owned_paths": txn["owned_paths"],
        "parent_run_id": capsule["parent_run_id"],
        "payload_version": PAYLOAD_VERSION,
        "requested_runtime": capsule["runtime"],
        "reserved_material_tasks_not_started": [
            task["task_id"] for task in capsule["reserved_material_tasks_after_canary"]
        ],
        "result_slot": txn["result_slot"],
        "task_id": txn["task_id"],
    }


def build_result(payload: dict, readback: dict, runtime: dict, runtime_sha256: str,
                 runtime_path: str, payload_path: str) -> dict:
    observed = runtime["interpretation"]
    result = dict(payload)
    result.update(
        {
            "canary_version": RESULT_VERSION,
            "child_report": "READY_TO_COMMIT",
            "completion_actor": None,
            "obzio_completion_claim": "NONE",
            "obzio_state_claimed_by_child": "RESULT_STAGED",
            "obzio_state_note": (
                "RESULT_VERIFIED, RESULT_COMMITTED, PARENT_INGESTED, COMPLETED and "
                "ACCEPTED are the controller's and the independent reviewer's to set. "
                "This child claims none of them."
            ),
            "deterministic_payload_fields": sorted(payload),
            "deterministic_payload_file": payload_path,
            "deterministic_payload_canonicalization": CANONICALIZATION,
            "determinism_rule": (
                "Every field listed in deterministic_payload_fields is reproducible from "
                "the frozen input capsule. Only observed_runtime, writer, "
                "local_independent_process_readback and observed_runtime_evidence carry "
                "runtime identity or timestamps."
            ),
            "local_independent_process_readback": readback,
            "observed_runtime": observed,
            "observed_runtime_evidence": {
                "path": runtime_path,
                "sha256": runtime_sha256,
            },
            "provider_run_id": observed["provider_run_id"],
            "provider_run_id_scope": observed["provider_run_id_scope"],
            "child_provider_run_id": observed["child_provider_run_id"],
            "independent_remote_readback": {
                "state": "PENDING_PARENT_VERIFICATION",
                "commit_sha": None,
                "observed_sha256": None,
                "observed_bytes": None,
                "observed_at": None,
            },
            "scope_attestation": {
                "writes_confined_to": payload["owned_paths"],
                "shared_po03_paths_modified": [],
                "po01_contact_or_mutation": "NONE",
                "pr_8_modified": False,
                "workflows_modified": [],
                "pointer_or_state_files_modified": [],
                "reserved_material_tasks_started": [],
                "merge_or_promotion": "NONE",
            },
            "writer": {
                "process": "python3 canary_writer.py --mode result",
                "pid": os.getpid(),
                "platform": platform.platform(),
                "python": platform.python_version(),
                "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        }
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("payload", "result"), required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--base-commit", required=True)
    args = parser.parse_args(argv)

    script = Path(__file__).resolve()
    owned_dir = script.parent
    contract_dir = owned_dir.parent / "opus-001-contract"

    try:
        root = repo_root(script)
        capsule, transaction = verified_capsule(contract_dir)
        payload = build_payload(capsule, transaction, args.branch, args.base_commit)

        payload_file = owned_dir / "canary-payload.json"
        if args.mode == "payload":
            payload_file.write_bytes(canonical(payload))
            out = payload_file
        else:
            staged = json.loads(payload_file.read_text(encoding="utf-8"))
            if staged != payload:
                raise ValueError("staged canary-payload.json does not match the derived payload")
            runtime_file = owned_dir / "observed-runtime.json"
            readback = load_json(owned_dir / "readback-payload.json")
            result = build_result(
                payload,
                readback,
                load_json(runtime_file),
                digest(runtime_file),
                runtime_file.relative_to(root).as_posix(),
                payload_file.relative_to(root).as_posix(),
            )
            out = owned_dir / "canary.json"
            if out.relative_to(root).as_posix() != payload["result_slot"]:
                raise ValueError("result slot does not match the commissioned path")
            out.write_bytes(canonical(result))
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"PO03_CANARY_WRITER_ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"PO03_CANARY_WRITER_OK mode={args.mode} path={out.relative_to(root).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
