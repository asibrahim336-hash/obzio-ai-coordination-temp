"""Sandbox kit for the push-boundary injections.

This unit needs three real repositories: a bare remote, a producer clone that
commits and pushes a result, and a separate controller clone that ingests.  The
live custody mechanism is imported and never modified; the durable evidence for
this unit is the committed bytes in this subtree.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import Any


REAL_REPO_ROOT = Path(__file__).resolve().parents[4]
FACTORY_SOURCE = REAL_REPO_ROOT / "workstreams" / "po03" / "tools" / "transactional_factory.py"
VALIDATOR_SOURCE = REAL_REPO_ROOT / "workstreams" / "po03" / "tools" / "validate_contracts.py"


def load_factory(instance: str):
    spec = importlib.util.spec_from_file_location(f"po03_factory_{instance}", FACTORY_SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {FACTORY_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bind_sandbox(module, sandbox: Path):
    po03 = sandbox / "workstreams" / "po03"
    (po03 / "contracts").mkdir(parents=True, exist_ok=True)
    (po03 / "tools").mkdir(parents=True, exist_ok=True)
    (po03 / "COMMISSION.md").write_bytes(b"sandbox commission\n")
    (po03 / "contracts" / "transactional-result.schema.json").write_bytes(b"{}\n")
    (po03 / "tools" / "validate_contracts.py").write_bytes(VALIDATOR_SOURCE.read_bytes())
    module.REPO_ROOT = sandbox
    module.PO03_ROOT = po03
    module.CONTROL_ROOT = po03 / "control"
    module.RECEIPT_ROOT = sandbox / "receipts" / "po03" / "2026-08-22"
    module.CONTROL_ROOT.mkdir(parents=True, exist_ok=True)
    return module


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments), cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def git_bytes(repo: Path, *arguments: str) -> bytes:
    """Read exact bytes from git without any text decoding or stripping."""
    return subprocess.run(("git", *arguments), cwd=repo, check=True, capture_output=True).stdout


def git_attempt(repo: Path, *arguments: str) -> dict[str, Any]:
    """Run git without raising so a rejected push can be observed."""
    completed = subprocess.run(
        ("git", *arguments), cwd=repo, capture_output=True, text=True
    )
    return {
        "argv": ["git", *arguments],
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def identify(repo: Path) -> None:
    git(repo, "config", "user.email", "po03-c6@obzio.invalid")
    git(repo, "config", "user.name", "PO-03 C6 Fault Injection")


def build_remote(root: Path) -> Path:
    remote = root / "remote.git"
    remote.mkdir(parents=True, exist_ok=True)
    git(remote, "init", "--bare", "--quiet")
    return remote


def build_producer(root: Path, remote: Path, branch: str) -> Path:
    producer = root / "producer"
    producer.mkdir(parents=True, exist_ok=True)
    git(producer, "init", "--quiet")
    identify(producer)
    git(producer, "remote", "add", "origin", str(remote))
    (producer / "README.sandbox").write_bytes(b"po03 c6 push-boundary sandbox\n")
    git(producer, "add", "-A")
    git(producer, "commit", "--quiet", "-m", "po03: sandbox baseline")
    git(producer, "branch", "-M", branch)
    git(producer, "push", "--quiet", "-u", "origin", branch)
    return producer


def clone_controller(root: Path, remote: Path, branch: str) -> Path:
    controller = root / "controller"
    subprocess.run(
        ("git", "clone", "--quiet", "--branch", branch, str(remote), str(controller)),
        check=True,
        capture_output=True,
        text=True,
    )
    identify(controller)
    return controller


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def seed_capsule(module, task_id: str, *, hypothesis: str, fence_token: int = 1) -> dict[str, str]:
    slot = f"workstreams/po03/attempts/{task_id}"
    return module.task_capsule(
        task_id=task_id,
        head_sha="0" * 40,
        run_id="c6-sandbox",
        model="claude-opus-5-thinking-high",
        reasoning="high",
        hypothesis=hypothesis,
        prompt="execute the sandbox unit",
        owned_paths=[f"{slot}/**"],
        result_slot=slot,
        acceptance={"criteria": ["sandbox"], "decision_changed": []},
        lease_seconds=60,
        fence_token=fence_token,
        function="transactional-recovery-and-fault-injection",
    )


def build_result_document_from_bytes(
    module,
    *,
    task_id: str,
    commit: str,
    bodies: dict[str, bytes],
    fence_token: int,
    worker_id: str,
    provider_state: str = "RUNNING",
    obzio_state: str = "RESULT_COMMITTED",
    timestamp: str = "2026-08-22T07:00:00Z",
) -> dict[str, Any]:
    """Build a contract-shaped result from bytes the producer actually committed.

    Hashes come from the producer's bytes; the capsule hashes come from the
    controller's immutable capsule, which is where ingestion will check them.
    """
    artifacts: list[dict[str, Any]] = []
    total_bytes = 0
    for index, (path, body) in enumerate(sorted(bodies.items()), start=1):
        artifacts.append(
            {
                "artifact_id": f"{task_id}-artifact-{index:03d}",
                "logical_name": Path(path).name,
                "content_uri": f"git:{commit}:{path}",
                "sha256": module.sha256_bytes(body),
                "bytes": len(body),
                "media_type": "application/json",
                "readback_verified_at": timestamp,
            }
        )
        total_bytes += len(body)
    task_directory = module.CONTROL_ROOT / "tasks" / task_id
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": task_id,
        "commission_id": module.COMMISSION_ID,
        "immutable_input_manifest_sha256": module.sha256_file(task_directory / "input.json"),
        "acceptance_contract_sha256": module.sha256_file(task_directory / "acceptance.json"),
        "provider_state": provider_state,
        "obzio_state": obzio_state,
        "attempt": {
            "attempt_id": f"{task_id}-attempt-1",
            "idempotency_key": f"{module.COMMISSION_ID}:{task_id}:attempt-1",
            "lease_id": f"lease-{task_id}-1",
            "fence_token": fence_token,
            "provider_run_id": "sandbox-provider-run-1",
            "worker_id": worker_id,
            "heartbeat_at": timestamp,
            "checkpoint_seq": 1,
        },
        "result_transaction": {
            "result_txn_id": f"result-{task_id}-1",
            "state": "COMMITTED",
            "manifest_uri": artifacts[0]["content_uri"] if artifacts else None,
            "manifest_sha256": artifacts[0]["sha256"] if artifacts else None,
            "artifact_count": len(artifacts),
            "total_bytes": total_bytes,
            "committed_at": timestamp,
            "verified_at": timestamp,
            "parent_ingested_at": None,
            "result_commit_id": commit,
        },
        "artifacts": artifacts,
        "completion_actor": None,
        "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
    }
