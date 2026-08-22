"""Sandbox kit for the partial-write and commit-boundary injections.

The live custody mechanism is imported and never modified.  Every injection
targets a throwaway repository; the durable evidence for this unit is the
committed bytes in this subtree, not anything under a temporary directory.
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


def init_repository(sandbox: Path) -> str:
    """Initialise the throwaway repository with a baseline commit so HEAD exists."""
    git(sandbox, "init", "--quiet")
    git(sandbox, "config", "user.email", "po03-c6@obzio.invalid")
    git(sandbox, "config", "user.name", "PO-03 C6 Fault Injection")
    git(sandbox, "add", "-A")
    git(sandbox, "commit", "--quiet", "-m", "po03: sandbox baseline")
    return git(sandbox, "rev-parse", "HEAD")


def commit_all(sandbox: Path, message: str) -> str:
    git(sandbox, "add", "-A")
    git(sandbox, "commit", "--quiet", "-m", message)
    return git(sandbox, "rev-parse", "HEAD")


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


def build_result_document(
    module,
    *,
    task_id: str,
    commit: str,
    paths: list[str],
    fence_token: int,
    worker_id: str,
    provider_state: str = "RUNNING",
    obzio_state: str = "RESULT_COMMITTED",
    timestamp: str = "2026-08-22T07:00:00Z",
    locator_commit: str | None = None,
) -> dict[str, Any]:
    """Build a contract-shaped result; hashes are measured from committed bytes."""
    locator = commit if locator_commit is None else locator_commit
    artifacts: list[dict[str, Any]] = []
    total_bytes = 0
    for index, path in enumerate(paths, start=1):
        body = module.read_object_bytes(f"git:{commit}:{path}")
        artifacts.append(
            {
                "artifact_id": f"{task_id}-artifact-{index:03d}",
                "logical_name": Path(path).name,
                "content_uri": f"git:{locator}:{path}",
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
            "manifest_uri": f"git:{locator}:{paths[0]}" if paths else None,
            "manifest_sha256": artifacts[0]["sha256"] if artifacts else None,
            "artifact_count": len(artifacts),
            "total_bytes": total_bytes,
            "committed_at": timestamp,
            "verified_at": timestamp,
            "parent_ingested_at": None,
            "result_commit_id": locator,
        },
        "artifacts": artifacts,
        "completion_actor": None,
        "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
    }
