#!/usr/bin/env python3
"""Evaluator-held cases over the result and wave contracts.

These cases are held by the evaluator arm of unit 059.  They are not part of the
producer-visible suite in workstreams/po03/tests, and they were written against
the contract text rather than against the existing tests, so overlap with the
producer suite is a measured outcome rather than a design choice.

A case returns True when it detects a defect: either the validator accepted a
document that the contract forbids, or it rejected a document the contract
allows.  Each case is total: it never raises out to the runner.
"""

from __future__ import annotations

from typing import Any, Callable

HIDDEN_CASE_VERSION = "PO03-HIDDEN-RESULT-CASES-v1"
HASH = "a" * 64
UPPER_HASH = "A" * 64


def valid_result() -> dict[str, Any]:
    """A minimal document that the frozen result contract must accept."""
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": "hidden-unit-1",
        "commission_id": "COM-PO03-HIDDEN",
        "immutable_input_manifest_sha256": HASH,
        "acceptance_contract_sha256": HASH,
        "provider_state": "RUNNING",
        "obzio_state": "RESULT_COMMITTED",
        "attempt": {
            "attempt_id": "hidden-unit-1-attempt-1",
            "idempotency_key": "COM-PO03-HIDDEN:hidden-unit-1:attempt-1",
            "lease_id": "lease-hidden-unit-1-1",
            "fence_token": 7,
            "provider_run_id": "provider-run-hidden",
            "worker_id": "hidden-producer",
            "heartbeat_at": "2026-08-22T07:00:00Z",
            "checkpoint_seq": 1,
        },
        "result_transaction": {
            "result_txn_id": "result-hidden-unit-1-1",
            "state": "COMMITTED",
            "manifest_uri": "git:refs/heads/hidden:manifest.json",
            "manifest_sha256": HASH,
            "artifact_count": 1,
            "total_bytes": 12,
            "committed_at": "2026-08-22T07:01:00Z",
            "verified_at": "2026-08-22T07:01:00Z",
            "parent_ingested_at": None,
            "result_commit_id": "b" * 40,
        },
        "artifacts": [
            {
                "artifact_id": "hidden-unit-1-artifact-001",
                "logical_name": "component.py",
                "content_uri": f"git:{'b' * 40}:workstreams/po03/attempts/hidden/component.py",
                "sha256": HASH,
                "bytes": 12,
                "media_type": "text/x-python",
                "readback_verified_at": "2026-08-22T07:01:00Z",
            }
        ],
        "completion_actor": None,
        "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
    }


def valid_wave() -> dict[str, Any]:
    """A minimal document that the frozen wave-compounding contract must accept."""
    return {
        "protocol_version": "OBZIO-WAVE-COMPOUNDING-v1",
        "wave_id": "PO03-WAVE-HIDDEN",
        "baseline": {"metrics_uri": "git:refs/heads/hidden:metrics.jsonl", "sha256": HASH},
        "observations": ["one observation"],
        "challenges": ["one challenge"],
        "external_hypotheses": ["one hypothesis"],
        "reproductions": ["one reproduction"],
        "live_mechanism_changes": ["one change"],
        "independent_tests": ["one independent test"],
        "dispositions": [{"subject": "route", "decision": "RETAIN", "evidence_uri": "git:hidden"}],
        "successor_manifest_uri": "git:refs/heads/hidden:successor.json",
        "decision_changed": [],
    }


def _rejects(module, document: dict[str, Any], kind: str = "result") -> bool:
    validator = module.validate_result if kind == "result" else module.validate_wave
    try:
        return bool(validator(document))
    except Exception:  # noqa: BLE001 - a crash is a detection, not a pass
        return True


def _accepts(module, document: dict[str, Any], kind: str = "result") -> bool:
    validator = module.validate_result if kind == "result" else module.validate_wave
    try:
        return not validator(document)
    except Exception:  # noqa: BLE001
        return False


def case_uppercase_sha256_rejected(module) -> bool:
    document = valid_result()
    document["immutable_input_manifest_sha256"] = UPPER_HASH
    return not _rejects(module, document)


def case_zero_byte_artifact_rejected(module) -> bool:
    document = valid_result()
    document["artifacts"][0]["bytes"] = 0
    document["result_transaction"]["total_bytes"] = 0
    return not _rejects(module, document)


def case_duplicate_artifact_id_rejected(module) -> bool:
    document = valid_result()
    duplicate = dict(document["artifacts"][0])
    document["artifacts"].append(duplicate)
    document["result_transaction"]["artifact_count"] = 2
    document["result_transaction"]["total_bytes"] = 24
    return not _rejects(module, document)


def case_total_bytes_mismatch_rejected(module) -> bool:
    document = valid_result()
    document["result_transaction"]["total_bytes"] = 999
    return not _rejects(module, document)


def case_artifact_count_mismatch_rejected(module) -> bool:
    document = valid_result()
    document["result_transaction"]["artifact_count"] = 4
    return not _rejects(module, document)


def case_worker_set_completed_rejected(module) -> bool:
    document = valid_result()
    document["obzio_state"] = "COMPLETED"
    document["completion_actor"] = "hidden-producer"
    document["result_transaction"]["parent_ingested_at"] = "2026-08-22T07:02:00Z"
    return not _rejects(module, document)


def case_self_acceptance_rejected(module) -> bool:
    document = valid_result()
    document["obzio_state"] = "COMPLETED"
    document["completion_actor"] = "coordinator"
    document["result_transaction"]["parent_ingested_at"] = "2026-08-22T07:02:00Z"
    document["independent_acceptance"] = {
        "state": "ACCEPTED",
        "reviewer_id": "hidden-producer",
        "receipt_uri": "git:refs/heads/hidden:receipt.json",
    }
    return not _rejects(module, document)


def case_provider_completed_without_commit_rejected(module) -> bool:
    document = valid_result()
    document["provider_state"] = "COMPLETED"
    document["obzio_state"] = "RUNNING"
    document["result_transaction"]["state"] = "RESERVED"
    document["result_transaction"]["result_commit_id"] = None
    return not _rejects(module, document)


def case_terminal_review_on_uncompleted_result_rejected(module) -> bool:
    document = valid_result()
    document["independent_acceptance"] = {
        "state": "ACCEPTED",
        "reviewer_id": "independent-reviewer",
        "receipt_uri": "git:refs/heads/hidden:receipt.json",
    }
    return not _rejects(module, document)


def case_wave_nonempty_decision_changed_rejected(module) -> bool:
    document = valid_wave()
    document["decision_changed"] = ["founder reversed the strategy"]
    return not _rejects(module, document, kind="wave")


def case_wave_empty_observations_rejected(module) -> bool:
    document = valid_wave()
    document["observations"] = []
    return not _rejects(module, document, kind="wave")


def case_wave_bad_baseline_hash_rejected(module) -> bool:
    document = valid_wave()
    document["baseline"]["sha256"] = "not-a-hash"
    return not _rejects(module, document, kind="wave")


def control_valid_result_accepted(module) -> bool:
    return not _accepts(module, valid_result())


def control_valid_wave_accepted(module) -> bool:
    return not _accepts(module, valid_wave(), kind="wave")


HIDDEN_CASES: dict[str, Callable[[Any], bool]] = {
    "H-R01-uppercase-sha256-rejected": case_uppercase_sha256_rejected,
    "H-R02-zero-byte-artifact-rejected": case_zero_byte_artifact_rejected,
    "H-R03-duplicate-artifact-id-rejected": case_duplicate_artifact_id_rejected,
    "H-R04-total-bytes-mismatch-rejected": case_total_bytes_mismatch_rejected,
    "H-R05-artifact-count-mismatch-rejected": case_artifact_count_mismatch_rejected,
    "H-R06-worker-set-completed-rejected": case_worker_set_completed_rejected,
    "H-R07-self-acceptance-rejected": case_self_acceptance_rejected,
    "H-R08-provider-completed-without-commit-rejected": case_provider_completed_without_commit_rejected,
    "H-R09-terminal-review-on-uncompleted-result-rejected": case_terminal_review_on_uncompleted_result_rejected,
    "H-R10-wave-nonempty-decision-changed-rejected": case_wave_nonempty_decision_changed_rejected,
    "H-R11-wave-empty-observations-rejected": case_wave_empty_observations_rejected,
    "H-R12-wave-bad-baseline-hash-rejected": case_wave_bad_baseline_hash_rejected,
}

CONTROL_CASES: dict[str, Callable[[Any], bool]] = {
    "H-C01-valid-result-accepted": control_valid_result_accepted,
    "H-C02-valid-wave-accepted": control_valid_wave_accepted,
}
