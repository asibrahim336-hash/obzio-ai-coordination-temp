#!/usr/bin/env python3
"""Disposable sandbox repositories that host the live PO-03 factory unmodified.

Every scenario needs its own control tree, because the factory binds its
repository roots at import time. The mechanism itself is never edited: it is
extracted byte-for-byte from immutable Git object bytes at a pinned commit and
imported from that copy, so a reproduction cannot silently test a patched
controller.
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

PINNED_COMMIT = "e63fbae079774b151fd24a4132e4a5e571f75298"

# Paths the factory resolves relative to its own location once imported.
MECHANISM_PATHS = (
    "workstreams/po03/tools/transactional_factory.py",
    "workstreams/po03/tools/validate_contracts.py",
    "workstreams/po03/COMMISSION.md",
    "workstreams/po03/contracts/transactional-result.schema.json",
    "workstreams/po03/contracts/wave-compounding.schema.json",
)

_MODULE_COUNTER = itertools.count(1)


def source_repository() -> Path:
    """Return the isolated clone that owns this attempt."""
    return Path(__file__).resolve().parents[5]


def read_immutable_blob(repository: Path, path: str, commit: str = PINNED_COMMIT) -> bytes:
    """Read one path's exact committed bytes without touching the worktree."""
    completed = subprocess.run(
        ("git", "cat-file", "blob", f"{commit}:{path}"),
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def immutable_blob_sha(repository: Path, path: str, commit: str = PINNED_COMMIT) -> str:
    completed = subprocess.run(
        ("git", "rev-parse", f"{commit}:{path}"),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


@dataclass(frozen=True)
class Sandbox:
    """One throwaway repository plus the live factory module bound to it."""

    root: Path
    factory: ModuleType
    mechanism_sha256: str
    mechanism_blob_sha: str

    def control_root(self) -> Path:
        return self.root / "workstreams" / "po03" / "control"

    def events(self, task_id: str) -> list[Path]:
        directory = self.control_root() / "events" / task_id
        return sorted(directory.glob("*.json")) if directory.exists() else []

    def event_count(self, task_id: str) -> int:
        return len(self.events(task_id))

    def head_sha(self) -> str:
        completed = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()


def build_sandbox(label: str) -> Sandbox:
    """Materialise a Git repository containing only the pinned mechanism."""
    repository = source_repository()
    root = Path(tempfile.mkdtemp(prefix=f"po03-033-{label}-"))
    payloads: dict[str, bytes] = {}
    for relative in MECHANISM_PATHS:
        payload = read_immutable_blob(repository, relative)
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        payloads[relative] = payload

    # The factory shells out to Git for result-commit validation, so the
    # sandbox must be a real repository with at least one commit.
    subprocess.run(("git", "init", "--quiet"), cwd=root, check=True, capture_output=True)
    for key, value in (
        ("user.name", "po03-wave-a-033-sandbox"),
        ("user.email", "po03-wave-a-033-sandbox@invalid.local"),
        ("commit.gpgsign", "false"),
    ):
        subprocess.run(("git", "config", key, value), cwd=root, check=True, capture_output=True)
    subprocess.run(("git", "add", "-A"), cwd=root, check=True, capture_output=True)
    subprocess.run(
        ("git", "commit", "--quiet", "-m", "sandbox: pinned PO-03 mechanism"),
        cwd=root,
        check=True,
        capture_output=True,
    )

    mechanism = root / "workstreams" / "po03" / "tools" / "transactional_factory.py"
    module_name = f"po03_sandbox_factory_{next(_MODULE_COUNTER)}"
    specification = importlib.util.spec_from_file_location(module_name, mechanism)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load pinned mechanism from {mechanism}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)

    factory_bytes = payloads["workstreams/po03/tools/transactional_factory.py"]
    return Sandbox(
        root=root,
        factory=module,
        mechanism_sha256=hashlib.sha256(factory_bytes).hexdigest(),
        mechanism_blob_sha=immutable_blob_sha(
            repository, "workstreams/po03/tools/transactional_factory.py"
        ),
    )


def seed_task(
    sandbox: Sandbox,
    task_id: str,
    *,
    lease_seconds: int,
    fence_token: int = 1,
) -> dict[str, str]:
    """Create one immutable capsule through the factory's own public API."""
    return sandbox.factory.task_capsule(
        task_id=task_id,
        head_sha=sandbox.head_sha(),
        run_id="po03-wave-a-033-reproduction",
        model="claude-opus-5-thinking-high",
        reasoning="high",
        hypothesis="A lost provider callback leaves the task recoverable from immutable input and ledger state.",
        prompt="Lost-callback fault injection fixture.",
        owned_paths=[f"workstreams/po03/attempts/wave-a/{task_id}/**"],
        result_slot=f"workstreams/po03/attempts/wave-a/{task_id}",
        acceptance={
            "acceptance_version": "PO03-WAVE-A-ACCEPTANCE-v1",
            "task_id": task_id,
            "criteria": ["recovery classification is rebuilt from immutable state"],
            "forbidden": ["false completion"],
            "decision_changed": [],
        },
        lease_seconds=lease_seconds,
        fence_token=fence_token,
    )


def lease_reservation(
    sandbox: Sandbox,
    task_id: str,
    *,
    worker_id: str,
    fence_token: int = 1,
) -> Path:
    """Lease a pre-provider reservation, exactly as the controller does."""
    return sandbox.factory.advance_task(
        task_id,
        state="LEASED",
        actor="integration-controller",
        fence_token=fence_token,
        details={
            "worker_id": worker_id,
            "provider_run_id": f"reservation:{task_id}:attempt-{fence_token}",
            "clone_path": f"/home/ubuntu/po03-{task_id}-isolated",
            "requested_model": "claude-opus-5-thinking-high",
            "route_policy": "FRESH_CLONE_ONLY_MAX_2",
        },
    )


def provider_starts_running(
    sandbox: Sandbox,
    task_id: str,
    *,
    worker_id: str,
    provider_task_id: str,
    worker_agent_id: str,
    fence_token: int = 1,
) -> Path:
    """Record genuine provider execution evidence, mirroring a real worker."""
    return sandbox.factory.advance_task(
        task_id,
        state="RUNNING",
        actor=worker_id,
        fence_token=fence_token,
        details={
            "provider": "Cursor",
            "provider_task_id": provider_task_id,
            "worker_agent_id": worker_agent_id,
            "clone_path": f"/home/ubuntu/po03-{task_id}-isolated",
            "requested_model": "claude-opus-5-thinking-high",
        },
    )


def wait_for_lease_expiry(sandbox: Sandbox, task_id: str, *, timeout: float = 30.0) -> float:
    """Block until the frozen reservation lease has provably expired.

    The factory truncates event timestamps to whole seconds, so the deadline is
    derived from the recorded event rather than from a blind sleep. That keeps
    the expiry fault deterministic instead of racing the clock.
    """
    import time
    from datetime import datetime, timezone

    factory = sandbox.factory
    events = factory.task_events(task_id)
    lease = next(event for event in reversed(events) if event["state"] == "LEASED")
    input_document = factory.read_json(
        sandbox.control_root() / "tasks" / task_id / "input.json"
    )
    lease_seconds = int(input_document["transaction"]["lease_seconds"])
    leased_at = datetime.fromisoformat(lease["observed_at"].replace("Z", "+00:00"))
    deadline = leased_at.astimezone(timezone.utc).timestamp() + lease_seconds
    started = time.time()
    while time.time() < deadline:
        if time.time() - started > timeout:
            raise TimeoutError(f"lease for {task_id} did not expire within {timeout}s")
        time.sleep(0.05)
    # The factory compares with a strict less-than, so land clear of the edge.
    time.sleep(0.1)
    return round(time.time() - started, 3)
