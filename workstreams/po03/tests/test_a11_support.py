"""Shared harness for the a11 custody-remediation recurrence tests.

Every a11 test drives the real ``control_plane.py`` module, not a copy, with its
mutable path globals redirected into a disposable tree.  Where a defect is about
git object resolution the harness builds a genuine throwaway repository, because
a test that stubs out ``git`` cannot prove that a declared locator resolves.

This module deliberately carries the ``test_a11_`` prefix: it is inside the only
test-file namespace this cohort owns, and unittest discovery imports it without
collecting anything because it defines no ``TestCase``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any

PO03_ROOT = Path(__file__).resolve().parents[1]
CONTROL_PLANE_PATH = PO03_ROOT / "tools" / "control_plane.py"
MAKE_RESULT_PATH = PO03_ROOT / "tools" / "make_result.py"
INGEST_WAVE_PATH = PO03_ROOT / "tools" / "ingest_wave.py"

COMMISSION_ID = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
OWNER = "po03-worker-a11test"
REVIEWER = "po03-worker-a6"
OWNED_PREFIX = "workstreams/po03/harness/"

GIT_AVAILABLE = shutil.which("git") is not None


def load_module(path: Path, name_hint: str):
    """Load one private instance of a tool module.

    Each instance gets a unique module name so two tests can redirect their path
    globals independently without leaking state through ``sys.modules``.
    """
    name = f"po03_a11_{name_hint}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_control_plane():
    return load_module(CONTROL_PLANE_PATH, "cp")


def git(*args: str, cwd: Path, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git("init", "--quiet", "--initial-branch", "main", cwd=path)
    git("config", "user.name", "PO03 A11 Harness", cwd=path)
    git("config", "user.email", "po03-a11@example.invalid", cwd=path)
    git("config", "commit.gpgsign", "false", cwd=path)


def commit_all(path: Path, message: str) -> str:
    git("add", "--all", cwd=path)
    git("commit", "--quiet", "-m", message, cwd=path)
    return git("rev-parse", "HEAD", cwd=path)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class ControlPlaneHarness(unittest.TestCase):
    """A control plane whose ledger, dispatch and ownership live in a scratch tree."""

    #: Subclasses that need artifacts resolvable as git objects set this True.
    git_backed = False

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="po03-a11-")
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.control = self.base / "control"
        self.repo = self.base / "repo"
        self.cp = self.fresh_control_plane()
        if self.git_backed:
            self.require_git()
            init_repo(self.repo)
        else:
            self.repo.mkdir(parents=True, exist_ok=True)
        self.write_ownership()

    def require_git(self) -> None:
        if not GIT_AVAILABLE:
            self.skipTest("git is not available: commit resolution cannot be exercised")

    def fresh_control_plane(self):
        """Return a control plane bound to this harness's scratch paths.

        Calling it twice models a parent process that restarted with no memory:
        the second instance sees only what the ledger durably holds.
        """
        module = load_control_plane()
        module.LEDGER_PATH = self.control / "events" / "ledger.jsonl"
        module.REGISTRY_PATH = self.control / "work-unit-registry.jsonl"
        module.RECOVERY_PATH = self.control / "recovery-state.json"
        module.DISPATCH_DIR = self.control / "dispatch"
        module.PATH_OWNERSHIP_PATH = self.control / "path-ownership.json"
        module.REPO_ROOT = self.repo
        return module

    def write_ownership(self) -> None:
        self.cp.write_json(
            self.cp.PATH_OWNERSHIP_PATH,
            {
                "owners": {
                    OWNER: {"owned_prefixes": [OWNED_PREFIX], "branch": "cursor/po03-a11-harness"},
                    REVIEWER: {"owned_prefixes": ["workstreams/po03/review/harness/"]},
                    "coordinator": {"owned_prefixes": ["workstreams/po03/control/"]},
                }
            },
        )

    # -- dispatch ---------------------------------------------------------

    def dispatch_record(self, unit_id: str, owner: str = OWNER) -> dict[str, Any]:
        manifest = {"unit_id": unit_id, "owner": owner}
        manifest_sha = self.cp.sha256_text(self.cp.canonical(manifest))
        acceptance_sha = self.cp.sha256_text(self.cp.canonical({"assertion": f"{unit_id} acceptance"}))
        record = {
            "unit_id": unit_id,
            "commission_id": COMMISSION_ID,
            "owner": owner,
            "immutable_input_manifest_sha256": manifest_sha,
            "acceptance_contract_sha256": acceptance_sha,
            "idempotency_key": f"{unit_id}:{manifest_sha[:16]}",
            "result_slot": {
                "branch": "cursor/po03-a11-harness",
                "unit_record": f"{OWNED_PREFIX}{unit_id}.json",
            },
        }
        self.cp.write_json(self.cp.DISPATCH_DIR / f"{unit_id}.json", record)
        return record

    def seed(self, unit_id: str = "h-u01", *, owner: str = OWNER, lease: bool = True,
             expires_at: str = "2099-01-01T00:00:00Z", fence: int = 1) -> dict[str, Any]:
        """Create a unit and optionally lease it, exactly as the coordinator would."""
        record = self.dispatch_record(unit_id, owner)
        self.cp.append_event(
            unit_id,
            "CREATED",
            actor="coordinator",
            provider_state="QUEUED",
            payload={
                "immutable_input_manifest_sha256": record["immutable_input_manifest_sha256"],
                "acceptance_contract_sha256": record["acceptance_contract_sha256"],
                "idempotency_key": record["idempotency_key"],
                "owner": owner,
            },
        )
        if lease:
            self.cp.append_event(
                unit_id,
                "LEASED",
                actor="coordinator",
                provider_state="RUNNING",
                fence_token=fence,
                payload={
                    "lease_id": f"lease-{unit_id}-{fence}",
                    "worker_id": owner,
                    "expires_at": expires_at,
                    "ttl_seconds": 3600,
                },
            )
        return record

    # -- artifacts and results -------------------------------------------

    def write_artifact(self, relative: str, body: bytes) -> tuple[str, int]:
        target = self.repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        return sha256_bytes(body), len(body)

    def commit_artifact(self, relative: str, body: bytes, message: str = "artifact") -> tuple[str, str, int]:
        """Write, commit and return (commit_sha, sha256, bytes)."""
        sha, size = self.write_artifact(relative, body)
        commit = commit_all(self.repo, message)
        return commit, sha, size

    def result_doc(
        self,
        unit_id: str = "h-u01",
        *,
        owner: str = OWNER,
        relative: str | None = None,
        body: bytes = b"durable-result\n",
        fence: int = 1,
        commit_id: str = "0" * 40,
        artifact_commit: str | None = None,
        branch: str = "cursor/po03-a11-harness",
        state: str = "RESULT_COMMITTED",
        write_artifact: bool = True,
    ) -> dict[str, Any]:
        """Build a schema-valid result document naming an explicit locator."""
        relative = relative if relative is not None else f"{OWNED_PREFIX}{unit_id}.txt"
        dispatch = json.loads((self.cp.DISPATCH_DIR / f"{unit_id}.json").read_text(encoding="utf-8"))
        if write_artifact:
            sha, size = self.write_artifact(relative, body)
        else:
            sha, size = sha256_bytes(body), len(body)
        artifact_commit = artifact_commit or commit_id
        committed = state == "RESULT_COMMITTED"
        now = "2026-08-22T07:00:00Z"
        artifacts = [
            {
                "artifact_id": f"{unit_id}-art-01",
                "logical_name": relative.rsplit("/", 1)[-1],
                "content_uri": f"git:{branch}@{artifact_commit}:{relative}",
                "sha256": sha,
                "bytes": size,
                "media_type": "text/plain",
                "readback_verified_at": now if committed else None,
            }
        ]
        return {
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "task_id": unit_id,
            "commission_id": dispatch["commission_id"],
            "immutable_input_manifest_sha256": dispatch["immutable_input_manifest_sha256"],
            "acceptance_contract_sha256": dispatch["acceptance_contract_sha256"],
            "provider_state": "COMPLETED" if committed else "UNKNOWN",
            "obzio_state": state,
            "attempt": {
                "attempt_id": f"{unit_id}-attempt-{fence}",
                "idempotency_key": dispatch["idempotency_key"],
                "lease_id": f"lease-{unit_id}-{fence}",
                "fence_token": fence,
                "provider_run_id": "po03-a11-harness",
                "worker_id": owner,
                "heartbeat_at": now,
                "checkpoint_seq": 1,
            },
            "result_transaction": {
                "result_txn_id": f"{unit_id}-txn-{fence}",
                "state": "COMMITTED" if committed else "RESERVED",
                "manifest_uri": f"git:{branch}@{commit_id}:{unit_id}" if committed else None,
                "manifest_sha256": sha256_bytes(f"{unit_id}:{commit_id}".encode()) if committed else None,
                "artifact_count": len(artifacts),
                "total_bytes": size,
                "committed_at": now if committed else None,
                "verified_at": now if committed else None,
                "parent_ingested_at": None,
                "result_commit_id": commit_id if committed else None,
            },
            "artifacts": artifacts,
            "completion_actor": None,
            "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
        }

    def ingest(self, doc: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("artifact_root", self.repo)
        return self.cp.ingest_result(doc, **kwargs)

    def forge_row(
        self,
        unit_id: str,
        event: str,
        actor: str,
        payload: dict[str, Any] | None = None,
        *,
        provider_state: str | None = "COMPLETED",
        fence_token: int | None = 1,
    ) -> dict[str, Any]:
        """Append a correctly chained row without going through append_event.

        This models a row written by the pre-fix code path, or by any process
        that bypasses the append guard.  Authority checks alone are not a
        sufficient defence for rows that already exist, so the scanner and the
        completion path are tested independently of them.
        """
        rows = self.cp.ledger_rows()
        body = {
            "seq": len(rows) + 1,
            "ts": "2026-08-22T07:30:00Z",
            "unit_id": unit_id,
            "event": event,
            "obzio_state": event,
            "provider_state": provider_state,
            "actor": actor,
            "fence_token": fence_token,
            "payload": payload or {},
            "prev_sha256": rows[-1]["row_sha256"] if rows else self.cp.GENESIS_HASH,
        }
        body["row_sha256"] = self.cp.sha256_text(self.cp.canonical(body))
        self.cp.LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with self.cp.LEDGER_PATH.open("a", encoding="utf-8") as handle:
            handle.write(self.cp.canonical(body) + "\n")
        return body

    def events(self, unit_id: str | None = None) -> list[str]:
        return [
            row["event"]
            for row in self.cp.ledger_rows()
            if unit_id is None or row["unit_id"] == unit_id
        ]

    def state_of(self, unit_id: str) -> str:
        return self.cp.project_units()[unit_id]["obzio_state"]


def env_without_git() -> dict[str, str]:
    """A PATH with no git, used to prove honest degradation rather than a stub."""
    env = dict(os.environ)
    env["PATH"] = ""
    return env
