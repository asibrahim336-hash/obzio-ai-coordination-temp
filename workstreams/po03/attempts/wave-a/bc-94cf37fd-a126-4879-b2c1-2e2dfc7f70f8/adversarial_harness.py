#!/usr/bin/env python3
"""Executable adversarial reproductions for eight PO-03 Wave A hypotheses."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Iterator


sys.dont_write_bytecode = True

RUN_ID = "bc-94cf37fd-a126-4879-b2c1-2e2dfc7f70f8"
PINNED_COMMIT = "7b9ee3e29f2d364cff5cdf2383dd512a0a6603e0"
EXPECTED_SOURCE_HASHES = {
    "workstreams/po03/tools/transactional_factory.py": "46c57f433c7f074ae6ae159429df3d3a1d38dadc95ac6a5ce34c343edf516199",
    "workstreams/po03/tools/validate_contracts.py": "ead7d6c78c1f60aaf5440db7fc00fc2ae57d773647ed3b24c279d1a59b43da03",
    "workstreams/po03/tools/check_path_scope.py": "6e5eaa3a6aff410847b95aa8b306c51903285b75da358c16958b4dc4c8ac0a8e",
    "workstreams/po03/contracts/transactional-result.schema.json": "bca86858131cf1644f88fcbe615f4ca7a4ef44b7464eebc086c84e39b77301f1",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def load_sources(repository: Path) -> tuple[ModuleType, ModuleType, ModuleType]:
    for relative, expected in EXPECTED_SOURCE_HASHES.items():
        observed = _sha256(repository / relative)
        if observed != expected:
            raise RuntimeError(
                f"source drift at {relative}: expected {expected}, observed {observed}"
            )
    transactional = _load(
        "po03_pinned_transactional_factory",
        repository / "workstreams/po03/tools/transactional_factory.py",
    )
    validator = _load(
        "po03_pinned_validate_contracts",
        repository / "workstreams/po03/tools/validate_contracts.py",
    )
    path_guard = _load(
        "po03_pinned_check_path_scope",
        repository / "workstreams/po03/tools/check_path_scope.py",
    )
    return transactional, validator, path_guard


def valid_committed_result() -> dict[str, Any]:
    digest = "a" * 64
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": "po03-adversarial-fixture",
        "commission_id": "COM-PO03",
        "immutable_input_manifest_sha256": digest,
        "acceptance_contract_sha256": digest,
        "provider_state": "COMPLETED",
        "obzio_state": "COMPLETED",
        "attempt": {
            "attempt_id": "attempt-1",
            "idempotency_key": "fixture:1",
            "lease_id": "lease-1",
            "fence_token": 1,
            "provider_run_id": "provider-1",
            "worker_id": "producer-1",
            "heartbeat_at": "2026-08-22T06:00:00Z",
            "checkpoint_seq": 1,
        },
        "result_transaction": {
            "result_txn_id": "result-1",
            "state": "INGESTED",
            "manifest_uri": "git:manifest",
            "manifest_sha256": digest,
            "artifact_count": 1,
            "total_bytes": 1,
            "committed_at": "2026-08-22T06:01:00Z",
            "verified_at": "2026-08-22T06:02:00Z",
            "parent_ingested_at": "2026-08-22T06:03:00Z",
            "result_commit_id": "b" * 40,
        },
        "artifacts": [
            {
                "artifact_id": "artifact-1",
                "logical_name": "result.txt",
                "content_uri": "git:result.txt",
                "sha256": digest,
                "bytes": 1,
                "media_type": "text/plain",
                "readback_verified_at": "2026-08-22T06:02:00Z",
            }
        ],
        "completion_actor": "coordinator",
        "independent_acceptance": {
            "state": "PENDING",
            "reviewer_id": None,
            "receipt_uri": None,
        },
    }


@contextlib.contextmanager
def isolated_controller_roots(
    module: ModuleType, root: Path
) -> Iterator[tuple[Path, Path]]:
    originals = {
        key: getattr(module, key)
        for key in ("REPO_ROOT", "PO03_ROOT", "CONTROL_ROOT", "RECEIPT_ROOT")
    }
    repository = root / "repository"
    po03 = repository / "workstreams" / "po03"
    (po03 / "contracts").mkdir(parents=True)
    (po03 / "COMMISSION.md").write_text("commission\n", encoding="utf-8")
    (po03 / "contracts" / "transactional-result.schema.json").write_text(
        "{}\n", encoding="utf-8"
    )
    module.REPO_ROOT = repository
    module.PO03_ROOT = po03
    module.CONTROL_ROOT = po03 / "control"
    module.RECEIPT_ROOT = repository / "receipts" / "po03" / "2026-08-22"
    try:
        yield repository, po03
    finally:
        for key, value in originals.items():
            setattr(module, key, value)


def create_capsule(
    module: ModuleType,
    task_id: str,
    *,
    nonce: str = "c" * 64,
) -> dict[str, str]:
    return module.task_capsule(
        task_id=task_id,
        head_sha="a" * 40,
        run_id=RUN_ID,
        model="gpt-5.6-sol-max-fast",
        reasoning="provider-encoded-max-fast",
        hypothesis="A control remains correct under an adversarial reproduction.",
        prompt="Execute the frozen adversarial reproduction.",
        owned_paths=[f"workstreams/po03/attempts/{task_id}/**"],
        result_slot=f"workstreams/po03/attempts/{task_id}",
        acceptance={"criteria": ["executable evidence"], "decision_changed": []},
        lease_seconds=300,
        fence_token=1,
        nonce=nonce,
    )


def attempt_schema_validator_drift(
    repository: Path, validator: ModuleType
) -> dict[str, Any]:
    schema = json.loads(
        (
            repository
            / "workstreams/po03/contracts/transactional-result.schema.json"
        ).read_text(encoding="utf-8")
    )
    root_properties = set(schema["properties"])
    base = valid_committed_result()

    unknown_property = json.loads(json.dumps(base))
    unknown_property["unexpected_root_property"] = True
    unknown_errors = validator.validate_result(unknown_property)

    invalid_provider = json.loads(json.dumps(base))
    invalid_provider["provider_state"] = "PROVIDER_SAID_TRUST_ME"
    provider_errors = validator.validate_result(invalid_provider)

    schema_rejects_unknown = (
        schema.get("additionalProperties") is False
        and bool(set(unknown_property) - root_properties)
    )
    defect_confirmed = (
        schema_rejects_unknown and not unknown_errors and not provider_errors
    )
    return {
        "task_id": "po03-wa-adv-001",
        "attempt_disposition": "PASS",
        "mechanism_outcome": "DEFECT_CONFIRMED" if defect_confirmed else "CONTROL_HELD",
        "observations": {
            "schema_rejects_unknown_root_property": schema_rejects_unknown,
            "validator_unknown_property_errors": unknown_errors,
            "validator_invalid_provider_state_errors": provider_errors,
        },
        "assertion": defect_confirmed,
    }


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def attempt_source_lock_immutability(
    transactional: ModuleType,
) -> dict[str, Any]:
    paths = (
        "workstreams/po03/COMMISSION.md",
        "workstreams/po03/contracts/transactional-result.schema.json",
        "workstreams/po03/contracts/wave-compounding.schema.json",
        "workstreams/po03/tools/validate_contracts.py",
        "workstreams/po03/tests/test_validate_contracts.py",
        ".github/workflows/po03-contracts.yml",
    )
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with isolated_controller_roots(transactional, root) as (repository, _):
            for relative in paths:
                destination = repository / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(f"committed:{relative}\n", encoding="utf-8")
            _git(repository, "init", "-q")
            _git(repository, "add", ".")
            _git(
                repository,
                "-c",
                "user.name=PO03",
                "-c",
                "user.email=po03@example.invalid",
                "commit",
                "-q",
                "-m",
                "fixture",
            )
            head = _git(repository, "rev-parse", "HEAD")
            target = repository / paths[0]
            committed_bytes = target.read_bytes()
            target.write_text("dirty worktree bytes\n", encoding="utf-8")
            document = transactional.source_lock(head)
            recorded = document["sources"][0]
            committed_sha = hashlib.sha256(committed_bytes).hexdigest()
            dirty_sha = _sha256(target)
            defect_confirmed = (
                recorded["git_blob_sha"] == _git(repository, "rev-parse", f"{head}:{paths[0]}")
                and recorded["sha256"] == dirty_sha
                and recorded["sha256"] != committed_sha
            )
            return {
                "task_id": "po03-wa-adv-002",
                "attempt_disposition": "PASS",
                "mechanism_outcome": (
                    "DEFECT_CONFIRMED" if defect_confirmed else "CONTROL_HELD"
                ),
                "observations": {
                    "pinned_head": head,
                    "recorded_git_blob_sha": recorded["git_blob_sha"],
                    "recorded_sha256": recorded["sha256"],
                    "committed_sha256": committed_sha,
                    "dirty_worktree_sha256": dirty_sha,
                },
                "assertion": defect_confirmed,
            }


def _concurrent_event_worker(
    source_path: str,
    repository: str,
    barrier: Any,
    results: Any,
    worker_number: int,
) -> None:
    module = _load(f"po03_event_worker_{worker_number}", Path(source_path))
    repository_path = Path(repository)
    module.REPO_ROOT = repository_path
    module.PO03_ROOT = repository_path / "workstreams" / "po03"
    module.CONTROL_ROOT = module.PO03_ROOT / "control"
    module.RECEIPT_ROOT = repository_path / "receipts" / "po03" / "2026-08-22"
    original_write_once = module.write_once

    def synchronized_write(path: Path, payload: bytes) -> None:
        barrier.wait(timeout=10)
        original_write_once(path, payload)

    module.write_once = synchronized_write
    try:
        path = module.hash_chain_event(
            "po03-concurrency-fixture",
            "CHECKPOINTED",
            actor=f"worker-{worker_number}",
            observed_at="2026-08-22T07:00:00Z",
        )
        results.put({"worker": worker_number, "state": "COMMITTED", "path": str(path)})
    except Exception as exc:  # fault result is the reproduction evidence
        results.put(
            {
                "worker": worker_number,
                "state": "FAILED",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )


def attempt_concurrent_event_collision(
    repository: Path, transactional: ModuleType
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with isolated_controller_roots(transactional, root) as (fixture_repository, _):
            event_directory = (
                transactional.CONTROL_ROOT / "events" / "po03-concurrency-fixture"
            )
            event_directory.mkdir(parents=True)
            process_count = 8
            context = multiprocessing.get_context("fork")
            barrier = context.Barrier(process_count)
            queue = context.Queue()
            source_path = str(
                repository / "workstreams/po03/tools/transactional_factory.py"
            )
            processes = [
                context.Process(
                    target=_concurrent_event_worker,
                    args=(
                        source_path,
                        str(fixture_repository),
                        barrier,
                        queue,
                        index,
                    ),
                )
                for index in range(process_count)
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=20)
            rows = [queue.get(timeout=2) for _ in range(process_count)]
            committed = [row for row in rows if row["state"] == "COMMITTED"]
            failed = [row for row in rows if row["state"] == "FAILED"]
            files = sorted(path.name for path in event_directory.glob("*.json"))
            defect_confirmed = len(committed) == 1 and len(failed) == process_count - 1
            return {
                "task_id": "po03-wa-adv-003",
                "attempt_disposition": "PASS",
                "mechanism_outcome": (
                    "DEFECT_CONFIRMED" if defect_confirmed else "CONTROL_HELD"
                ),
                "observations": {
                    "writers": process_count,
                    "committed": len(committed),
                    "failed": len(failed),
                    "error_types": sorted(
                        {row.get("error_type") for row in failed if row.get("error_type")}
                    ),
                    "event_files": files,
                },
                "assertion": defect_confirmed,
            }


def attempt_atomic_write_faults(transactional: ModuleType) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with isolated_controller_roots(transactional, root):
            link_target = transactional.CONTROL_ROOT / "atomic-link.json"
            original_link = transactional.os.link
            transactional.os.link = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected link failure")
            )
            try:
                try:
                    transactional.write_once(link_target, b"link\n")
                except OSError:
                    pass
            finally:
                transactional.os.link = original_link
            link_failure_left_destination = link_target.exists()
            transactional.write_once(link_target, b"link\n")
            link_retry_succeeded = link_target.read_bytes() == b"link\n"

            fsync_target = transactional.CONTROL_ROOT / "atomic-fsync.json"
            original_fsync = transactional.os.fsync
            calls = {"count": 0}

            def fail_directory_fsync(descriptor: int) -> None:
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("injected directory fsync failure")
                original_fsync(descriptor)

            transactional.os.fsync = fail_directory_fsync
            fsync_raised = False
            try:
                try:
                    transactional.write_once(fsync_target, b"fsync\n")
                except OSError:
                    fsync_raised = True
            finally:
                transactional.os.fsync = original_fsync
            destination_survived_failed_fsync = fsync_target.exists()
            transactional.write_once(fsync_target, b"fsync\n")
            retry_returned_without_repair_evidence = fsync_target.read_bytes() == b"fsync\n"

            defect_confirmed = (
                not link_failure_left_destination
                and link_retry_succeeded
                and fsync_raised
                and destination_survived_failed_fsync
                and retry_returned_without_repair_evidence
            )
            return {
                "task_id": "po03-wa-adv-004",
                "attempt_disposition": "PASS",
                "mechanism_outcome": (
                    "DEFECT_CONFIRMED" if defect_confirmed else "CONTROL_HELD"
                ),
                "observations": {
                    "link_failure_left_destination": link_failure_left_destination,
                    "link_retry_succeeded": link_retry_succeeded,
                    "directory_fsync_failure_raised": fsync_raised,
                    "destination_survived_failed_directory_fsync": (
                        destination_survived_failed_fsync
                    ),
                    "retry_returned_without_repair_evidence": (
                        retry_returned_without_repair_evidence
                    ),
                },
                "assertion": defect_confirmed,
            }


def attempt_path_guard_reachability(
    repository: Path, path_guard: ModuleType
) -> dict[str, Any]:
    escape_matrix = [
        "state/escape.json",
        "workstreams/po01/result.json",
        ".cursor/environment.json",
        ".github/workflows/not-po03.yml",
        "workstreams/po03/../po01/result.json",
        "workstreams\\po03\\escape.json",
    ]
    direct_violations = path_guard.violations(escape_matrix)
    workflow = (
        repository / ".github/workflows/po03-contracts.yml"
    ).read_text(encoding="utf-8")
    pull_request_has_restrictive_filter = (
        "pull_request:" in workflow
        and "paths:" in workflow
        and '"workstreams/po03/**"' in workflow
        and '"**"' not in workflow
    )
    push_excludes_subordinate_branch = (
        '      - "po03/**"' in workflow and '      - "cursor/**"' not in workflow
    )
    defect_confirmed = (
        set(direct_violations) == set(escape_matrix)
        and pull_request_has_restrictive_filter
        and push_excludes_subordinate_branch
    )
    return {
        "task_id": "po03-wa-adv-005",
        "attempt_disposition": "PASS",
        "mechanism_outcome": "DEFECT_CONFIRMED" if defect_confirmed else "CONTROL_HELD",
        "observations": {
            "direct_escape_fixture_count": len(escape_matrix),
            "direct_rejections": direct_violations,
            "out_of_scope_only_pull_request_can_skip_guard": (
                pull_request_has_restrictive_filter
            ),
            "subordinate_cursor_branch_push_can_skip_guard": (
                push_excludes_subordinate_branch
            ),
        },
        "assertion": defect_confirmed,
    }


def attempt_remote_readback_gap(transactional: ModuleType) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with isolated_controller_roots(transactional, root):
            create_capsule(transactional, "po03-local-verify-fixture")
            return_code = transactional.verify(
                SimpleNamespace(task_id="po03-local-verify-fixture")
            )
            created_transaction = json.loads(
                (
                    transactional.CONTROL_ROOT
                    / "tasks/po03-local-verify-fixture/transaction-created.json"
                ).read_text(encoding="utf-8")
            )
            remote_evidence_files = list(
                (
                    transactional.CONTROL_ROOT
                    / "tasks/po03-local-verify-fixture"
                ).glob("*remote*")
            )
            defect_confirmed = (
                return_code == 0
                and created_transaction["result_transaction"]["result_commit_id"]
                is None
                and not remote_evidence_files
            )
            return {
                "task_id": "po03-wa-adv-006",
                "attempt_disposition": "PASS",
                "mechanism_outcome": (
                    "DEFECT_CONFIRMED" if defect_confirmed else "CONTROL_HELD"
                ),
                "observations": {
                    "local_verify_return_code": return_code,
                    "result_commit_id": created_transaction["result_transaction"][
                        "result_commit_id"
                    ],
                    "remote_readback_evidence_count": len(remote_evidence_files),
                },
                "assertion": defect_confirmed,
            }


def attempt_stale_fence_semantics(transactional: ModuleType) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with isolated_controller_roots(transactional, root):
            create_capsule(transactional, "po03-stale-fence-fixture")
            transactional.hash_chain_event(
                "po03-stale-fence-fixture",
                "COMPLETED",
                actor="stale-worker",
                details={
                    "fence_token": 0,
                    "lease_expired": True,
                    "result_commit_id": None,
                },
                observed_at="2026-08-22T08:00:00Z",
            )
            chain_errors = transactional.verify_chain(
                "po03-stale-fence-fixture"
            )
            defect_confirmed = chain_errors == []
            return {
                "task_id": "po03-wa-adv-007",
                "attempt_disposition": "PASS",
                "mechanism_outcome": (
                    "DEFECT_CONFIRMED" if defect_confirmed else "CONTROL_HELD"
                ),
                "observations": {
                    "stale_worker_completed_event_admitted": True,
                    "semantic_chain_errors": chain_errors,
                    "fence_token_checked_by_event_writer": False,
                },
                "assertion": defect_confirmed,
            }


def attempt_provider_loss_replay(
    transactional: ModuleType, validator: ModuleType
) -> dict[str, Any]:
    recovery_fixture = valid_committed_result()
    recovery_fixture["obzio_state"] = "PROVIDER_COMPLETED_UNCOMMITTED"
    recovery_fixture["result_transaction"].update(
        state="RESERVED",
        manifest_uri=None,
        manifest_sha256=None,
        artifact_count=0,
        total_bytes=0,
        committed_at=None,
        verified_at=None,
        parent_ingested_at=None,
        result_commit_id=None,
    )
    recovery_fixture["artifacts"] = []
    recovery_fixture["completion_actor"] = None
    recovery_fixture["independent_acceptance"] = {
        "state": "NOT_TESTED",
        "reviewer_id": None,
        "receipt_uri": None,
    }
    classification_errors = validator.validate_result(recovery_fixture)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with isolated_controller_roots(transactional, root):
            original_utc_now = transactional.utc_now
            transactional.utc_now = lambda: "2026-08-22T08:00:00Z"
            try:
                create_capsule(transactional, "po03-replay-fixture")
                transactional.utc_now = lambda: "2026-08-22T08:01:00Z"
                replay_error: str | None = None
                try:
                    create_capsule(transactional, "po03-replay-fixture")
                except Exception as exc:
                    replay_error = f"{type(exc).__name__}: {exc}"
            finally:
                transactional.utc_now = original_utc_now
            parser_commands = set(
                transactional.build_parser()._subparsers._group_actions[0].choices
            )
            has_recovery_command = bool(
                parser_commands & {"recover", "resume", "replay", "scan"}
            )
            defect_confirmed = (
                classification_errors == []
                and replay_error is not None
                and not has_recovery_command
            )
            return {
                "task_id": "po03-wa-adv-008",
                "attempt_disposition": "PASS",
                "mechanism_outcome": (
                    "DEFECT_CONFIRMED" if defect_confirmed else "CONTROL_HELD"
                ),
                "observations": {
                    "provider_completed_uncommitted_classification_errors": (
                        classification_errors
                    ),
                    "same_idempotency_key_replay_error": replay_error,
                    "controller_commands": sorted(parser_commands),
                    "has_executable_recovery_command": has_recovery_command,
                },
                "assertion": defect_confirmed,
            }


def run(repository: Path) -> dict[str, Any]:
    transactional, validator, path_guard = load_sources(repository)
    attempts = [
        attempt_schema_validator_drift(repository, validator),
        attempt_source_lock_immutability(transactional),
        attempt_concurrent_event_collision(repository, transactional),
        attempt_atomic_write_faults(transactional),
        attempt_path_guard_reachability(repository, path_guard),
        attempt_remote_readback_gap(transactional),
        attempt_stale_fence_semantics(transactional),
        attempt_provider_loss_replay(transactional, validator),
    ]
    return {
        "result_version": "PO03-WAVE-A-ADVERSARIAL-RESULT-v1",
        "controller_source_commit": PINNED_COMMIT,
        "producer_run_id": RUN_ID,
        "attempt_count": len(attempts),
        "attempts_with_executable_evidence": sum(
            item["attempt_disposition"] == "PASS" for item in attempts
        ),
        "defects_confirmed": sum(
            item["mechanism_outcome"] == "DEFECT_CONFIRMED" for item in attempts
        ),
        "attempts": attempts,
        "producer_completion_claim": "READY_TO_COMMIT",
        "independent_acceptance": "NOT_TESTED",
        "decision_changed": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository",
        type=Path,
        default=Path(__file__).resolve().parents[5],
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.repository.resolve())
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if all(item["assertion"] for item in result["attempts"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
