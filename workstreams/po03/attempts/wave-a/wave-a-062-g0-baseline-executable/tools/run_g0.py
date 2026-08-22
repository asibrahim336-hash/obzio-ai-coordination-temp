#!/usr/bin/env python3
"""Execute the frozen G0 controller against the deterministic comparison suite."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


UNIT_ROOT = Path(__file__).resolve().parents[1]
FACTORY_PATH = UNIT_ROOT / "historical_controller" / "tools" / "transactional_factory.py"
VALIDATOR_PATH = UNIT_ROOT / "historical_controller" / "tools" / "validate_contracts.py"
DEFAULT_SUITE = UNIT_ROOT / "fixtures" / "g0-suite.json"
DEFAULT_SOURCE_MANIFEST = UNIT_ROOT / "frozen_inputs" / "source-manifest.json"
FIXED_TIME = "2026-08-22T09:00:00Z"
H = "a" * 64


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_frozen_sources(source_manifest_path: Path) -> dict[str, Any]:
    manifest_bytes = source_manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    errors: list[str] = []
    for source in manifest["sources"]:
        path = UNIT_ROOT / source["path"]
        if not path.is_file():
            errors.append(f"missing:{source['path']}")
            continue
        content = path.read_bytes()
        if len(content) != source["bytes"]:
            errors.append(f"bytes:{source['path']}")
        if sha256_bytes(content) != source["sha256"]:
            errors.append(f"sha256:{source['path']}")
        git_blob = hashlib.sha1(
            b"blob " + str(len(content)).encode("ascii") + b"\0" + content
        ).hexdigest()
        if git_blob != source["git_blob_sha"]:
            errors.append(f"git_blob_sha:{source['path']}")
    if errors:
        raise ValueError("frozen source verification failed: " + ",".join(errors))
    return {
        "manifest": manifest,
        "sha256": sha256_bytes(manifest_bytes),
        "source_count": len(manifest["sources"]),
    }


@contextmanager
def baseline_environment(factory) -> Iterator[Path]:
    original = {
        name: getattr(factory, name)
        for name in ("REPO_ROOT", "PO03_ROOT", "CONTROL_ROOT", "RECEIPT_ROOT", "utc_now")
    }
    with tempfile.TemporaryDirectory() as temporary:
        repository = Path(temporary) / "repository"
        po03 = repository / "workstreams" / "po03"
        (po03 / "contracts").mkdir(parents=True)
        (po03 / "COMMISSION.md").write_text("frozen commission\n", encoding="utf-8")
        (po03 / "contracts" / "transactional-result.schema.json").write_text(
            "{}\n", encoding="utf-8"
        )
        factory.REPO_ROOT = repository
        factory.PO03_ROOT = po03
        factory.CONTROL_ROOT = po03 / "control"
        factory.RECEIPT_ROOT = repository / "receipts" / "po03" / "2026-08-22"
        factory.utc_now = lambda: FIXED_TIME
        try:
            yield repository
        finally:
            for name, value in original.items():
                setattr(factory, name, value)


def create_task(factory) -> None:
    factory.task_capsule(
        task_id="g0-fixture-task",
        head_sha="a" * 40,
        run_id="bc-g0-fixture",
        model="frozen-g0",
        reasoning="fixture",
        hypothesis="The fixture exposes a falsifiable controller decision.",
        prompt="Execute the local fixture.",
        owned_paths=["workstreams/po03/attempts/g0-fixture/**"],
        result_slot="workstreams/po03/attempts/g0-fixture",
        acceptance={"criteria": ["deterministic"], "decision_changed": []},
        lease_seconds=300,
        fence_token=1,
    )


def committed_result() -> dict[str, Any]:
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": "g0-fixture-task",
        "commission_id": "COM-PO03",
        "immutable_input_manifest_sha256": H,
        "acceptance_contract_sha256": H,
        "provider_state": "COMPLETED",
        "obzio_state": "COMPLETED",
        "attempt": {
            "attempt_id": "attempt-1",
            "idempotency_key": "g0-fixture-task:1",
            "lease_id": "lease-1",
            "fence_token": 1,
            "provider_run_id": "provider-run-1",
            "worker_id": "producer-1",
            "heartbeat_at": "2026-08-22T08:00:00Z",
            "checkpoint_seq": 4,
        },
        "result_transaction": {
            "result_txn_id": "result-1",
            "state": "INGESTED",
            "manifest_uri": "git:result@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:manifest.json",
            "manifest_sha256": H,
            "artifact_count": 1,
            "total_bytes": 7,
            "committed_at": "2026-08-22T08:01:00Z",
            "verified_at": "2026-08-22T08:02:00Z",
            "parent_ingested_at": "2026-08-22T08:03:00Z",
            "result_commit_id": "a" * 40,
        },
        "artifacts": [
            {
                "artifact_id": "artifact-1",
                "logical_name": "result.json",
                "content_uri": "git:result@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:result.json",
                "sha256": H,
                "bytes": 7,
                "media_type": "application/json",
                "readback_verified_at": "2026-08-22T08:02:00Z",
            }
        ],
        "completion_actor": "coordinator",
        "independent_acceptance": {
            "state": "ACCEPTED",
            "reviewer_id": "reviewer-2",
            "receipt_uri": "git:review@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb:receipt.json",
        },
    }


def validator_decision(validator, document: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    errors = validator.validate_result(document)
    return (
        ("REJECT" if errors else "ALLOW"),
        {"validator_error_count": len(errors), "validator_errors": errors},
    )


def advance_to_running(factory) -> None:
    factory.advance_task(
        "g0-fixture-task",
        state="LEASED",
        actor="integration-controller",
        fence_token=1,
        details={"worker_id": "worker-1", "provider_run_id": "provider-1"},
    )
    factory.advance_task(
        "g0-fixture-task",
        state="RUNNING",
        actor="worker-1",
        fence_token=1,
        details={"callback_id": "callback-1"},
    )


def execute_operation(operation: str, factory, validator, case: dict[str, Any]):
    if operation == "canonical_json":
        observed = factory.canonical_json({"b": 2, "a": 1})
        return (
            "ALLOW" if observed == b'{"a":1,"b":2}\n' else "REJECT",
            {"observed_sha256": sha256_bytes(observed)},
        )

    if operation == "baseline_evidence_gate":
        missing = sorted(key for key, value in case["input"].items() if value is None)
        return (
            "NOT_YET" if missing else "ALLOW",
            {"missing_evidence": missing, "historical_success_inferred": False},
        )

    if operation in {
        "short_commit_id",
        "unexpected_property",
        "reversed_timestamps",
        "zero_byte_artifact",
        "provider_completed_uncommitted",
    }:
        document = committed_result()
        if operation == "short_commit_id":
            document["result_transaction"]["result_commit_id"] = "abc123"
        elif operation == "unexpected_property":
            document["producer_claim"] = "complete"
        elif operation == "reversed_timestamps":
            document["result_transaction"].update(
                committed_at="2026-08-22T08:03:00Z",
                verified_at="2026-08-22T08:02:00Z",
                parent_ingested_at="2026-08-22T08:01:00Z",
            )
        elif operation == "zero_byte_artifact":
            document["result_transaction"]["total_bytes"] = 0
            document["artifacts"][0].update(
                bytes=0,
                sha256=hashlib.sha256(b"").hexdigest(),
                logical_name="empty.txt",
            )
        elif operation == "provider_completed_uncommitted":
            document["obzio_state"] = "PROVIDER_COMPLETED_UNCOMMITTED"
            document["result_transaction"].update(
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
            document["artifacts"] = []
            document["completion_actor"] = None
            document["independent_acceptance"] = {
                "state": "NOT_TESTED",
                "reviewer_id": None,
                "receipt_uri": None,
            }
        return validator_decision(validator, document)

    with baseline_environment(factory) as repository:
        if operation == "immutable_divergent_replay":
            destination = factory.CONTROL_ROOT / "immutable.json"
            factory.write_once(destination, b"one\n")
            factory.write_once(destination, b"one\n")
            try:
                factory.write_once(destination, b"two\n")
            except (FileExistsError, ValueError) as exc:
                return "REJECT", {"error_type": type(exc).__name__}
            return "ALLOW", {"error_type": None}

        if operation == "scope_escape":
            try:
                factory.write_once(repository / "state" / "escape.json", b"{}\n")
            except (OSError, ValueError) as exc:
                return "REJECT", {"error_type": type(exc).__name__}
            return "ALLOW", {"error_type": None}

        if operation in {
            "tampered_event",
            "spoofed_event_task",
            "stale_fence",
            "duplicate_callback",
            "commit_without_artifacts",
        }:
            create_task(factory)

        if operation == "tampered_event":
            event_path = (
                factory.CONTROL_ROOT
                / "events"
                / "g0-fixture-task"
                / "000001-created.json"
            )
            document = json.loads(event_path.read_text(encoding="utf-8"))
            document["details"]["fence_token"] = 99
            event_path.write_bytes(canonical_json(document))
            errors = factory.verify_chain("g0-fixture-task")
            return (
                ("REJECT" if errors else "ALLOW"),
                {"chain_error_count": len(errors), "detected_hash_mismatch": any(
                    "event hash mismatch" in error for error in errors
                )},
            )

        if operation == "spoofed_event_task":
            event_path = (
                factory.CONTROL_ROOT
                / "events"
                / "g0-fixture-task"
                / "000001-created.json"
            )
            document = json.loads(event_path.read_text(encoding="utf-8"))
            document.pop("event_sha256")
            document["task_id"] = "different-task"
            document["event_sha256"] = factory.sha256_bytes(factory.canonical_json(document))
            event_path.write_bytes(factory.canonical_json(document))
            errors = factory.verify_chain("g0-fixture-task")
            return (
                ("REJECT" if errors else "ALLOW"),
                {
                    "chain_error_count": len(errors),
                    "stored_task_id": "g0-fixture-task",
                    "event_task_id": "different-task",
                },
            )

        if operation == "stale_fence":
            advance_to_running(factory)
            factory.advance_task(
                "g0-fixture-task",
                state="RECOVERY_REQUIRED",
                actor="integration-controller",
                fence_token=1,
            )
            factory.advance_task(
                "g0-fixture-task",
                state="RETRY_SCHEDULED",
                actor="integration-controller",
                fence_token=1,
            )
            factory.advance_task(
                "g0-fixture-task",
                state="LEASED",
                actor="integration-controller",
                fence_token=2,
                details={"worker_id": "worker-2", "provider_run_id": "provider-2"},
            )
            try:
                factory.advance_task(
                    "g0-fixture-task",
                    state="RUNNING",
                    actor="worker-1",
                    fence_token=1,
                )
            except ValueError as exc:
                return "REJECT", {"error_type": type(exc).__name__, "stale_fence": 1}
            return "ALLOW", {"error_type": None}

        if operation == "duplicate_callback":
            advance_to_running(factory)
            try:
                factory.advance_task(
                    "g0-fixture-task",
                    state="RUNNING",
                    actor="worker-1",
                    fence_token=1,
                    details={"callback_id": "callback-1"},
                )
            except ValueError as exc:
                return "REJECT", {"error_type": type(exc).__name__}
            return "ALLOW", {"error_type": None}

        if operation == "commit_without_artifacts":
            advance_to_running(factory)
            for state in ("RESULT_STAGING", "RESULT_STAGED", "RESULT_VERIFIED"):
                factory.advance_task(
                    "g0-fixture-task",
                    state=state,
                    actor="worker-1",
                    fence_token=1,
                    details={},
                )
            try:
                factory.advance_task(
                    "g0-fixture-task",
                    state="RESULT_COMMITTED",
                    actor="integration-controller",
                    fence_token=1,
                    details={"result_commit_id": "a" * 40},
                )
            except ValueError as exc:
                return "REJECT", {"error_type": type(exc).__name__}
            latest = factory.task_events("g0-fixture-task")[-1]
            return "ALLOW", {
                "latest_state": latest["state"],
                "manifest_supplied": False,
                "artifacts_supplied": False,
                "readback_supplied": False,
            }

        if operation == "source_lock_worktree_drift":
            required = {
                "workstreams/po03/COMMISSION.md": b"commission\n",
                "workstreams/po03/contracts/transactional-result.schema.json": b"{}\n",
                "workstreams/po03/contracts/wave-compounding.schema.json": b"{}\n",
                "workstreams/po03/tools/validate_contracts.py": b"frozen\n",
                "workstreams/po03/tests/test_validate_contracts.py": b"tests\n",
                ".github/workflows/po03-contracts.yml": b"name: fixture\n",
            }
            for relative, content in required.items():
                path = repository / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            environment = {
                **os.environ,
                "GIT_AUTHOR_DATE": "2026-08-22T09:00:00Z",
                "GIT_COMMITTER_DATE": "2026-08-22T09:00:00Z",
            }
            commands = (
                ("init", "-q"),
                ("config", "user.name", "PO-03 Fixture"),
                ("config", "user.email", "fixture@example.invalid"),
                ("add", "-A"),
                ("commit", "-q", "-m", "frozen source"),
            )
            for command in commands:
                subprocess.run(
                    ("git", *command),
                    cwd=repository,
                    env=environment,
                    check=True,
                    capture_output=True,
                )
            head = subprocess.run(
                ("git", "rev-parse", "HEAD"),
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            drifted = repository / "workstreams/po03/tools/validate_contracts.py"
            drifted.write_bytes(b"changed after commit\n")
            source_lock = factory.source_lock(head)
            entry = next(
                item
                for item in source_lock["sources"]
                if item["path"] == "workstreams/po03/tools/validate_contracts.py"
            )
            historical_bytes = required["workstreams/po03/tools/validate_contracts.py"]
            mixed = (
                entry["git_blob_sha"]
                == subprocess.run(
                    ("git", "rev-parse", f"{head}:workstreams/po03/tools/validate_contracts.py"),
                    cwd=repository,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                and entry["sha256"] == sha256_bytes(b"changed after commit\n")
                and entry["sha256"] != sha256_bytes(historical_bytes)
            )
            return (
                "ALLOW",
                {
                    "mixed_git_and_worktree_provenance": mixed,
                    "source_lock_raised_error": False,
                },
            )

    raise ValueError(f"unsupported operation: {operation}")


def classify(expected: str, observed: str) -> str:
    if expected == observed:
        return "MATCH"
    if expected in {"REJECT", "NOT_YET"} and observed == "ALLOW":
        return "FALSE_GREEN"
    if expected == "ALLOW" and observed == "REJECT":
        return "FALSE_NEGATIVE"
    return "MISMATCH"


def run_suite(suite_path: Path, source_manifest_path: Path) -> dict[str, Any]:
    source_verification = verify_frozen_sources(source_manifest_path)
    suite_bytes = suite_path.read_bytes()
    suite = json.loads(suite_bytes)
    factory = load_module("po03_g0_frozen_factory", FACTORY_PATH)
    validator = load_module("po03_g0_frozen_validator", VALIDATOR_PATH)
    observations: list[dict[str, Any]] = []
    for case in suite["cases"]:
        observed, details = execute_operation(
            case["operation"], factory, validator, copy.deepcopy(case)
        )
        outcome = classify(case["expected_decision"], observed)
        observations.append(
            {
                "case_id": case["id"],
                "critical": case["critical"],
                "measurement_kind": (
                    "EVIDENCE_AVAILABILITY_FIXTURE"
                    if case["operation"] == "baseline_evidence_gate"
                    else "RECONSTRUCTION_EXECUTION"
                ),
                "expected_decision": case["expected_decision"],
                "observed_decision": observed,
                "outcome": outcome,
                "details": details,
            }
        )

    critical = [item for item in observations if item["critical"]]
    false_greens = [item["case_id"] for item in observations if item["outcome"] == "FALSE_GREEN"]
    false_negatives = [
        item["case_id"] for item in observations if item["outcome"] == "FALSE_NEGATIVE"
    ]
    critical_matches = sum(item["outcome"] == "MATCH" for item in critical)
    reason_codes: list[str] = []
    if critical_matches != len(critical):
        reason_codes.append("CRITICAL_CORRECTNESS_BELOW_100_PERCENT")
    if false_greens:
        reason_codes.append("FALSE_GREEN_BASELINE_BEHAVIOR")
    reason_codes.append("HISTORICAL_GENERATION_EVIDENCE_INSUFFICIENT")
    return {
        "contract_version": "PO03-GENERATION-RESULT-v1",
        "task_id": "wave-a-062-g0-baseline-executable",
        "generation": "G0",
        "suite": {
            "suite_id": suite["suite_id"],
            "sha256": sha256_bytes(suite_bytes),
            "case_count": len(observations),
        },
        "controller": {
            "historical_head": source_verification["manifest"]["historical_controller_head"],
            "source_manifest_sha256": source_verification["sha256"],
            "source_count": source_verification["source_count"],
            "source_integrity": "PASS",
            "execution_mode": "EXACT_FROZEN_SOURCE_WITH_TEMPORARY_ROOT_REBINDING",
        },
        "observations": observations,
        "metrics": {
            "case_count": len(observations),
            "match_count": sum(item["outcome"] == "MATCH" for item in observations),
            "false_green_count": len(false_greens),
            "false_green_case_ids": false_greens,
            "false_negative_count": len(false_negatives),
            "false_negative_case_ids": false_negatives,
            "critical_correctness": {
                "passed": critical_matches,
                "total": len(critical),
                "meets_100_percent": critical_matches == len(critical),
            },
        },
        "dispositions": {
            "reconstruction": "RETAIN",
            "historical_success_claim": "REJECT",
            "generation_lift_claim": "RETEST"
        },
        "reconstruction_status": "PASS",
        "baseline_quality_status": "FAIL" if false_greens else "PASS",
        "successor_lift_claim": "NOT_YET",
        "claim_reason_codes": reason_codes,
        "measured_behavior_scope": (
            "Fresh local re-execution of frozen source; not evidence of historical run behavior."
        ),
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_suite(args.suite, args.source_manifest)
        payload = canonical_json(result)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(payload)
            print(
                f"G0_EXECUTION_PASS output={args.output.as_posix()} "
                f"sha256={sha256_bytes(payload)}"
            )
        else:
            print(payload.decode("utf-8"), end="")
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"G0_EXECUTION_ERROR: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
