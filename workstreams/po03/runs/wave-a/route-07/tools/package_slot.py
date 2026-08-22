"""Package one route-07 result slot: rerun tests, hash artifacts, emit receipts.

Writes only inside the slot it is given. Produces:

  evidence/observed-output.txt  the exact command and its observed output
  FINDING.md                    hypothesis, method, result, limitations, disposition
  manifest.json                 every artifact with sha256 and byte count
  result.json                   the transactional result contract for the slot

`result.json` binds the manifest by hash and therefore cannot appear inside it;
that self-reference is the circular-hash impossibility recorded in the route-07
review erratum, so the manifest covers every artifact except itself and the
receipt that hashes it.

Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PROTOCOL = "OBZIO-TRANSACTIONAL-RESULT-v1"
COMMISSION = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
WAVE = "PO03-WAVE-A-20260822"
ROUTE = "route-07"
WORKER = "route-07-material-worker"
MODEL = "claude-opus-5-thinking-high"
FENCE_TOKEN = 1
TEST_COMMAND = "python3 -m unittest discover -s . -p 'test_*.py' -v"

MEDIA_TYPES = {
    ".py": "text/x-python",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_tests(slot: Path) -> tuple:
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py", "-v"],
        capture_output=True,
        text=True,
        cwd=str(slot),
        timeout=600,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    ran = 0
    for line in output.splitlines():
        if line.startswith("Ran ") and " test" in line:
            ran = int(line.split()[1])
    return proc.returncode, ran, output


def slot_artifacts(slot: Path) -> list:
    out = []
    for path in sorted(slot.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.name in ("manifest.json", "result.json"):
            continue
        out.append(path)
    return out


def write_manifest(slot: Path, task_id: str, acceptance_sha: str, source_lock_sha: str) -> dict:
    artifacts = []
    for path in slot_artifacts(slot):
        rel = path.relative_to(slot).as_posix()
        artifacts.append(
            {
                "artifact_id": f"{task_id}:{rel}",
                "bytes": path.stat().st_size,
                "content_uri": path.relative_to(slot.parents[4]).as_posix()
                if len(slot.parents) > 4
                else rel,
                "logical_name": rel,
                "media_type": MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
                "path": rel,
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "acceptance_contract_sha256": acceptance_sha,
        "acceptance_contract_uri": f"workstreams/po03/control/tasks/{task_id}/acceptance.json",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "decision_changed": [],
        "immutable_input_manifest_sha256": source_lock_sha,
        "manifest_version": "PO03-ROUTE07-SLOT-MANIFEST-v1",
        "route_id": ROUTE,
        "scope_note": (
            "Covers every artifact in the slot except manifest.json itself and result.json, "
            "which binds this manifest by sha256 and therefore cannot be listed inside it."
        ),
        "state": "RESULT_STAGED",
        "task_id": task_id,
        "total_bytes": sum(a["bytes"] for a in artifacts),
    }
    (slot / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def write_result(
    slot: Path, task_id: str, acceptance_sha: str, source_lock_sha: str, manifest: dict, stamped: str
) -> dict:
    manifest_path = slot / "manifest.json"
    slot_rel = slot.relative_to(slot.parents[4]).as_posix() if len(slot.parents) > 4 else slot.name
    artifacts = [
        {
            "artifact_id": a["artifact_id"],
            "bytes": a["bytes"],
            "content_uri": f"{slot_rel}/{a['path']}",
            "logical_name": a["logical_name"],
            "media_type": a["media_type"],
            "readback_verified_at": stamped,
            "sha256": a["sha256"],
        }
        for a in manifest["artifacts"]
    ]
    result = {
        "acceptance_contract_sha256": acceptance_sha,
        "artifacts": artifacts,
        "attempt": {
            "attempt_id": f"{task_id}-attempt-1",
            "checkpoint_seq": 3,
            "fence_token": FENCE_TOKEN,
            "heartbeat_at": stamped,
            "idempotency_key": f"{WAVE}:{task_id}:attempt-1",
            "lease_id": f"lease-{task_id}-1",
            "provider_run_id": "bc-aa38db59-c61c-4e29-9c26-4424b20f6e19",
            "worker_id": WORKER,
        },
        "commission_id": COMMISSION,
        "completion_actor": None,
        "immutable_input_manifest_sha256": source_lock_sha,
        "independent_acceptance": {"receipt_uri": None, "reviewer_id": None, "state": "NOT_TESTED"},
        "obzio_state": "RESULT_STAGED",
        "protocol_version": PROTOCOL,
        "provider_state": "RUNNING",
        "result_transaction": {
            "artifact_count": len(artifacts),
            "committed_at": None,
            "manifest_sha256": sha256_file(manifest_path),
            "manifest_uri": f"{slot_rel}/manifest.json",
            "parent_ingested_at": None,
            "result_commit_id": None,
            "result_txn_id": f"{task_id}-txn-1",
            "state": "STAGED",
            "total_bytes": sum(a["bytes"] for a in artifacts),
            "verified_at": stamped,
        },
        "task_id": task_id,
    }
    (slot / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--task-id", required=True)
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    task_id = args.task_id
    slot = repo_root / f"workstreams/po03/runs/wave-a/{ROUTE}/{task_id}"
    task_dir = repo_root / f"workstreams/po03/control/tasks/{task_id}"
    acceptance_sha = sha256_file(task_dir / "acceptance.json")
    source_lock_sha = sha256_file(repo_root / "workstreams/po03/evidence/source-lock.json")

    returncode, ran, output = run_tests(slot)
    if returncode != 0:
        sys.stderr.write(output)
        raise SystemExit(f"{task_id}: tests failed with exit {returncode}")

    stamped = now()
    evidence = slot / "evidence"
    evidence.mkdir(exist_ok=True)
    (evidence / "observed-output.txt").write_text(
        f"# {task_id} — observed test execution\n"
        f"# recorded_at: {stamped}\n"
        f"# cwd: workstreams/po03/runs/wave-a/{ROUTE}/{task_id}\n"
        f"# exact_model_configuration: {MODEL}\n"
        f"$ {TEST_COMMAND}\n"
        f"{output}"
        f"# exit_code: {returncode}\n"
        f"# tests_run: {ran}\n",
        encoding="utf-8",
    )

    manifest = write_manifest(slot, task_id, acceptance_sha, source_lock_sha)
    result = write_result(slot, task_id, acceptance_sha, source_lock_sha, manifest, stamped)

    print(
        json.dumps(
            {
                "task_id": task_id,
                "tests_run": ran,
                "artifact_count": manifest["artifact_count"],
                "total_bytes": manifest["total_bytes"],
                "manifest_sha256": result["result_transaction"]["manifest_sha256"],
                "obzio_state": result["obzio_state"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
