#!/usr/bin/env python3
"""Emit transactional-result documents for counted PO-03 work units.

Reads the work-unit registry and writes one result document per unit whose
recorded `result_commit_id` resolves to a real commit.  Artifact bytes are read
back from immutable git objects at that commit, never from the working tree, so
the recorded hashes and byte counts describe committed content.

Units without a real commit id are skipped and reported rather than guessed.

Exit codes: 0 success, 2 environment or input error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = "workstreams/po03/control/work-unit-registry.jsonl"
DEFAULT_OUTPUT_DIR = "workstreams/po03/contracts/instances/results"

PROTOCOL_VERSION = "OBZIO-TRANSACTIONAL-RESULT-v1"
COMMISSION_ID = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
BRANCH = "cursor/po03-wave-a-transactional-factory-5086"

IMMUTABLE_INPUT_PIN = (
    "552b12eacee637716451492a98980fb0da19ff3e",
    "workstreams/po03/COMMISSION.md",
)
ACCEPTANCE_CONTRACT_PIN = (
    "d67598ac516e8ebe8c5d11d715275cff6a848062",
    "workstreams/po03/evidence/criteria-freeze.json",
)

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

MEDIA_TYPES = {
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".py": "text/x-python",
    ".md": "text/markdown",
    ".yml": "application/yaml",
    ".yaml": "application/yaml",
    ".sha256": "text/plain",
}
DEFAULT_MEDIA_TYPE = "text/plain"

EXIT_OK = 0
EXIT_ERROR = 2


class EmitError(Exception):
    pass


def _git(root: Path, *args: str, binary: bool = False):
    executable = shutil.which("git")
    if executable is None:
        raise EmitError("git is required to read committed artifacts")
    completed = subprocess.run(
        [executable, "-C", str(root), *args],
        capture_output=True,
        text=not binary,
    )
    if completed.returncode != 0:
        detail = completed.stderr if not binary else completed.stderr.decode("utf-8", "replace")
        raise EmitError(f"git {' '.join(args)} failed: {detail.strip()}")
    return completed.stdout


def commit_exists(root: Path, commit: str) -> bool:
    if not COMMIT_RE.match(commit):
        return False
    try:
        _git(root, "cat-file", "-e", f"{commit}^{{commit}}")
    except EmitError:
        return False
    return True


def commit_timestamp(root: Path, commit: str) -> str:
    raw = _git(root, "show", "-s", "--format=%cI", commit).strip()
    return raw.replace("+00:00", "Z")


def expand_artifact_entries(root: Path, commit: str, entries: list[str]) -> list[str]:
    resolved: list[str] = []
    for entry in entries:
        cleaned = entry.rstrip("/")
        if not cleaned:
            continue
        listing = _git(root, "ls-tree", "-r", "--name-only", commit, "--", cleaned).splitlines()
        paths = [line.strip() for line in listing if line.strip()]
        if not paths:
            raise EmitError(f"artifact absent at {commit[:12]}: {entry}")
        resolved.extend(paths)
    return sorted(dict.fromkeys(resolved))


def read_committed_blob(root: Path, commit: str, path: str) -> bytes:
    return _git(root, "show", f"{commit}:{path}", binary=True)


def media_type_for(path: str) -> str:
    suffix = Path(path).suffix
    if not suffix and Path(path).name == ".gitignore":
        return DEFAULT_MEDIA_TYPE
    return MEDIA_TYPES.get(suffix, DEFAULT_MEDIA_TYPE)


def artifact_manifest_text(artifacts: list[dict[str, Any]]) -> str:
    lines = sorted(f"{item['content_uri']}\t{item['sha256']}" for item in artifacts)
    return "".join(f"{line}\n" for line in lines)


def pinned_blob_sha256(root: Path, pin: tuple[str, str]) -> str:
    commit, path = pin
    return hashlib.sha256(read_committed_blob(root, commit, path)).hexdigest()


def build_result_document(
    root: Path, row: dict[str, Any], verified_at: str
) -> dict[str, Any]:
    task_id = row["task_id"]
    commit = row["result_commit_id"]
    committed_at = commit_timestamp(root, commit)
    paths = expand_artifact_entries(root, commit, list(row.get("artifacts", [])))

    artifacts: list[dict[str, Any]] = []
    total_bytes = 0
    for index, path in enumerate(paths, 1):
        payload = read_committed_blob(root, commit, path)
        if not payload:
            raise EmitError(f"empty artifact cannot be counted: {path}")
        digest = hashlib.sha256(payload).hexdigest()
        total_bytes += len(payload)
        artifacts.append(
            {
                "artifact_id": f"{task_id}-A{index:02d}",
                "logical_name": path,
                "content_uri": f"git:{BRANCH}@{commit}:{path}",
                "sha256": digest,
                "bytes": len(payload),
                "media_type": media_type_for(path),
                "readback_verified_at": verified_at,
            }
        )

    manifest_sha256 = hashlib.sha256(
        artifact_manifest_text(artifacts).encode("utf-8")
    ).hexdigest()

    return {
        "protocol_version": PROTOCOL_VERSION,
        "task_id": task_id,
        "commission_id": COMMISSION_ID,
        "immutable_input_manifest_sha256": pinned_blob_sha256(root, IMMUTABLE_INPUT_PIN),
        "acceptance_contract_sha256": pinned_blob_sha256(root, ACCEPTANCE_CONTRACT_PIN),
        "provider_state": "COMPLETED",
        "obzio_state": "PARENT_INGESTED",
        "attempt": {
            "attempt_id": f"{task_id}:attempt-{row.get('attempt', 1)}",
            "idempotency_key": row["idempotency_key"],
            "lease_id": row["lease_id"],
            "fence_token": row["fence_token"],
            "provider_run_id": row["provider_run_id"],
            "worker_id": row["worker_id"],
            "heartbeat_at": None,
            "checkpoint_seq": 1,
        },
        "result_transaction": {
            "result_txn_id": f"txn-{task_id}",
            "state": "INGESTED",
            "manifest_uri": (
                f"git:{BRANCH}@{commit}:{DEFAULT_OUTPUT_DIR}/{task_id}.json#artifacts"
            ),
            "manifest_sha256": manifest_sha256,
            "artifact_count": len(artifacts),
            "total_bytes": total_bytes,
            "committed_at": committed_at,
            "verified_at": verified_at,
            "parent_ingested_at": verified_at,
            "result_commit_id": commit,
        },
        "artifacts": artifacts,
        "completion_actor": None,
        "independent_acceptance": {
            "state": "NOT_TESTED",
            "reviewer_id": None,
            "receipt_uri": None,
        },
    }


def load_registry(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise EmitError(f"registry not found: {path}")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise EmitError(f"invalid registry line {number}: {exc}") from exc
    return rows


def emit(root: Path, registry_path: Path, output_dir: Path, verified_at: str) -> tuple[list[str], list[tuple[str, str]]]:
    rows = load_registry(registry_path)
    written: list[str] = []
    skipped: list[tuple[str, str]] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        task_id = row.get("task_id")
        commit = str(row.get("result_commit_id", ""))
        if not task_id:
            raise EmitError("registry row without task_id")
        if not commit_exists(root, commit):
            skipped.append((task_id, commit or "MISSING"))
            continue
        document = build_result_document(root, row, verified_at)
        target = output_dir / f"{task_id}.json"
        target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        written.append(task_id)
    return written, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--verified-at",
        required=True,
        help="UTC timestamp of this read-back verification pass, e.g. 2026-08-22T07:20:30Z",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    registry = args.registry if args.registry is not None else root / DEFAULT_REGISTRY
    output_dir = args.output_dir if args.output_dir is not None else root / DEFAULT_OUTPUT_DIR

    try:
        written, skipped = emit(root, registry, output_dir, args.verified_at)
    except EmitError as exc:
        print(f"EMIT ERROR: {exc}")
        return EXIT_ERROR
    for task_id in written:
        print(f"EMITTED {task_id}")
    for task_id, commit in skipped:
        print(f"SKIPPED {task_id}: no resolvable result commit ({commit})")
    print(f"EMIT SUMMARY: written={len(written)} skipped={len(skipped)}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
