"""Scratch harness for adversarially attacking the real control_plane.py.

Owned by po03-worker-a10 (workstreams/po03/review/sonnet/**). Every method here
invokes an unmodified byte-for-byte copy of the coordinator's real
``tools/control_plane.py`` and ``tools/validate_contracts.py`` as a subprocess,
exactly as a real actor would, inside an isolated scratch directory tree. The
real, shared ledger under ``workstreams/po03/control/events/ledger.jsonl`` is
never opened or written by this module.

Dependency-free standard library only, per the commission's portable-runtime
standard.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REAL_TOOLS_DIR = Path(__file__).resolve().parents[3] / "tools"
PYTHON = sys.executable


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ScratchControlPlane:
    """One isolated copy of the real control plane rooted at ``base / "repo"``.

    ``base`` is exposed so attack cases can plant decoy files *outside* the
    scratch repo root (siblings of ``repo/``) to test whether the real
    allowlist/ownership checks actually confine filesystem access to the
    repo root, or merely to a string that looks like it does.
    """

    def __init__(self, base: Path):
        self.base = base
        self.root = base / "repo"
        tools_dir = self.root / "workstreams" / "po03" / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        real_control_plane = REAL_TOOLS_DIR / "control_plane.py"
        real_validate = REAL_TOOLS_DIR / "validate_contracts.py"
        if not real_control_plane.is_file() or not real_validate.is_file():
            raise RuntimeError(f"real tools not found under {REAL_TOOLS_DIR}")
        self.control_plane_source_sha256 = sha256_bytes(real_control_plane.read_bytes())
        self.validate_source_sha256 = sha256_bytes(real_validate.read_bytes())
        shutil.copyfile(real_control_plane, tools_dir / "control_plane.py")
        shutil.copyfile(real_validate, tools_dir / "validate_contracts.py")
        self.script = tools_dir / "control_plane.py"
        self.control_dir = self.root / "workstreams" / "po03" / "control"
        self.control_dir.mkdir(parents=True, exist_ok=True)

    def write_ownership(self, owners: dict[str, Any]) -> None:
        payload = {"owners": owners}
        (self.control_dir / "path-ownership.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )

    def run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [PYTHON, "-I", str(self.script), *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def create_unit(
        self,
        unit_id: str,
        owner: str,
        owned_paths: list[str],
        cohort_id: str = "attack",
        function_id: str = "F0",
        hypothesis: str = "adversarial probe",
        acceptance: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        spec = {
            "commission_id": "COM-A10-ATTACK-TEST",
            "wave_id": "wave-attack-test",
            "source_hashes": {},
            "units": [
                {
                    "unit_id": unit_id,
                    "cohort_id": cohort_id,
                    "function_id": function_id,
                    "hypothesis": hypothesis,
                    "acceptance": acceptance or {"artifact": "x", "assertion": "y", "falsified_if": "z"},
                    "owner": owner,
                    "owned_paths": owned_paths,
                    "model": "test-model",
                    "result_slot": {"branch": "test-branch", "unit_record": f"units/{unit_id}.json"},
                }
            ],
        }
        spec_path = self.base / f"spec-{unit_id}.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        result = self.run("create", str(spec_path))
        if result.returncode != 0:
            raise AssertionError(f"create failed: {result.stdout} {result.stderr}")
        dispatch = json.loads((self.control_dir / "dispatch" / f"{unit_id}.json").read_text())
        return dispatch

    def lease(self, unit_id: str, worker: str, ttl: int = 5400) -> dict[str, Any]:
        result = self.run("lease", unit_id, "--worker", worker, "--ttl", str(ttl))
        if result.returncode != 0:
            raise AssertionError(f"lease failed: {result.stdout} {result.stderr}")
        return json.loads(result.stdout)

    def write_file_at(self, relative_to_root: str, content: bytes) -> Path:
        target = self.root / relative_to_root
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def write_file_outside(self, relative_to_base: str, content: bytes) -> Path:
        """Write a decoy file as a *sibling* of the scratch repo root, i.e.
        genuinely outside the repo/allowlist/owner subtree, to test whether
        traversal-style content_uri values can reach it."""
        target = self.base / relative_to_base
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def build_result_doc(
        self,
        dispatch: dict[str, Any],
        fence_token: int,
        artifacts: list[dict[str, Any]],
        provider_state: str = "COMPLETED",
        obzio_state: str = "RESULT_COMMITTED",
        result_commit_id: str = "d" * 40,
        worker_id: str | None = None,
        checkpoint_seq: int = 1,
        manifest_sha_override: str | None = None,
        acceptance_sha_override: str | None = None,
        task_id_override: str | None = None,
    ) -> dict[str, Any]:
        worker_id = worker_id or dispatch["owner"]
        committed = obzio_state != "PROVIDER_COMPLETED_UNCOMMITTED"
        artifact_entries = []
        total_bytes = 0
        for art in artifacts:
            artifact_entries.append(
                {
                    "artifact_id": art["artifact_id"],
                    "logical_name": art["logical_name"],
                    "content_uri": f"file:{art['content_uri']}",
                    "sha256": art["sha256"],
                    "bytes": art["bytes"],
                    "media_type": "application/json",
                    "readback_verified_at": "2026-08-22T00:00:00Z" if committed else None,
                }
            )
            total_bytes += art["bytes"]
        return {
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "task_id": task_id_override or dispatch["unit_id"],
            "commission_id": dispatch["commission_id"],
            "immutable_input_manifest_sha256": manifest_sha_override or dispatch["immutable_input_manifest_sha256"],
            "acceptance_contract_sha256": acceptance_sha_override or dispatch["acceptance_contract_sha256"],
            "provider_state": provider_state,
            "obzio_state": obzio_state,
            "attempt": {
                "attempt_id": f"attempt-{dispatch['unit_id']}-{fence_token}",
                "idempotency_key": dispatch["idempotency_key"],
                "lease_id": f"lease-{dispatch['unit_id']}-{fence_token}",
                "fence_token": fence_token,
                "provider_run_id": "run-1",
                "worker_id": worker_id,
                "checkpoint_seq": checkpoint_seq,
            },
            "result_transaction": {
                "result_txn_id": f"txn-{dispatch['unit_id']}-{fence_token}-{checkpoint_seq}",
                "state": "COMMITTED" if committed else "STAGED",
                "manifest_uri": f"file:manifest-{dispatch['unit_id']}.json" if committed else None,
                "manifest_sha256": "0" * 64 if committed else None,
                "artifact_count": len(artifact_entries),
                "total_bytes": total_bytes,
                "committed_at": "2026-08-22T00:00:00Z" if committed else None,
                "verified_at": "2026-08-22T00:00:00Z" if committed else None,
                "parent_ingested_at": None,
                "result_commit_id": result_commit_id if committed else None,
            },
            "artifacts": artifact_entries,
            "completion_actor": None,
            "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
        }

    def ingest(self, result_doc: dict[str, Any], tag: str = "") -> subprocess.CompletedProcess:
        result_path = self.base / f"result-{result_doc['task_id']}-{result_doc['attempt']['fence_token']}-{tag}.json"
        result_path.write_text(json.dumps(result_doc), encoding="utf-8")
        return self.run("ingest", str(result_path))

    def complete(self, unit_id: str) -> subprocess.CompletedProcess:
        return self.run("complete", unit_id)

    def review(self, unit_id: str, decision: str, reviewer: str, receipt: str = "receipt://x") -> subprocess.CompletedProcess:
        return self.run("review", unit_id, decision, "--reviewer", reviewer, "--receipt", receipt)

    def verify(self) -> subprocess.CompletedProcess:
        return self.run("verify")

    def ledger_path(self) -> Path:
        return self.control_dir / "events" / "ledger.jsonl"

    def ledger_rows(self) -> list[dict[str, Any]]:
        path = self.ledger_path()
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def write_ledger_rows(self, rows: list[dict[str, Any]]) -> None:
        text = "\n".join(canonical(row) for row in rows) + ("\n" if rows else "")
        self.ledger_path().write_text(text, encoding="utf-8")
