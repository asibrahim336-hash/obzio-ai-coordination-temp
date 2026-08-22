"""Hand-rolled, seeded property/metamorphic harness for validate_result.

No third-party property-based testing package is installed in this
dependency-free stdlib runtime (see the scope_limitation recorded against
a5-u06 in sources.json), so this is a small generator/checker pair written
directly against the standard library ``random`` module, in the same spirit
as (but not using) libraries such as Hypothesis.
"""

from __future__ import annotations

import copy
import random
from typing import Any, Callable

H = "a" * 64

ValidateFn = Callable[[dict[str, Any]], list[str]]


def base_committed_result() -> dict[str, Any]:
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": "a5-u06-property-1",
        "commission_id": "COM-PO03",
        "immutable_input_manifest_sha256": H,
        "acceptance_contract_sha256": H,
        "provider_state": "COMPLETED",
        "obzio_state": "COMPLETED",
        "attempt": {
            "attempt_id": "attempt-1",
            "idempotency_key": "a5-u06-property-1:1",
            "lease_id": "lease-1",
            "fence_token": 1,
            "provider_run_id": "provider-run-1",
            "worker_id": "producer-1",
            "heartbeat_at": "2026-08-22T06:00:00Z",
            "checkpoint_seq": 4,
        },
        "result_transaction": {
            "result_txn_id": "result-1",
            "state": "INGESTED",
            "manifest_uri": "git:po03/run/a5-u06-property-1@abc:manifest.json",
            "manifest_sha256": H,
            "artifact_count": 1,
            "total_bytes": 7,
            "committed_at": "2026-08-22T06:01:00Z",
            "verified_at": "2026-08-22T06:02:00Z",
            "parent_ingested_at": "2026-08-22T06:03:00Z",
            "result_commit_id": "abc123",
        },
        "artifacts": [
            {
                "artifact_id": "artifact-1",
                "logical_name": "result.json",
                "content_uri": "git:po03/run/a5-u06-property-1@abc:result.json",
                "sha256": H,
                "bytes": 7,
                "media_type": "application/json",
                "readback_verified_at": "2026-08-22T06:02:00Z",
            }
        ],
        "completion_actor": "coordinator",
        "independent_acceptance": {
            "state": "ACCEPTED",
            "reviewer_id": "reviewer-2",
            "receipt_uri": "git:po03/review@def:receipt.json",
        },
    }


def property_nonpositive_bytes_always_rejected(validate: ValidateFn, rng: random.Random, trials: int) -> list[dict]:
    """Property: any artifact whose byte count is <= 0 must be rejected,
    regardless of every other field being otherwise valid."""
    violations = []
    for _ in range(trials):
        doc = copy.deepcopy(base_committed_result())
        bad_bytes = rng.choice([0, -1, -rng.randint(1, 1000)])
        doc["artifacts"][0]["bytes"] = bad_bytes
        doc["result_transaction"]["total_bytes"] = bad_bytes  # keep reconciliation consistent
        errors = validate(doc)
        caught = any("bytes" in e for e in errors)
        if not caught:
            violations.append({"bad_bytes": bad_bytes, "errors": errors})
    return violations


def property_total_bytes_mismatch_always_rejected(validate: ValidateFn, rng: random.Random, trials: int) -> list[dict]:
    """Property: ANY nonzero mismatch between total_bytes and the sum of
    artifact byte counts must be rejected -- not only a mismatch of exactly
    the magnitude used in the fixed example suite."""
    violations = []
    for _ in range(trials):
        doc = copy.deepcopy(base_committed_result())
        true_sum = doc["artifacts"][0]["bytes"]
        offset = rng.choice([o for o in range(-20, 21) if o != 0])
        doc["result_transaction"]["total_bytes"] = true_sum + offset
        errors = validate(doc)
        caught = any("total_bytes" in e for e in errors)
        if not caught:
            violations.append({"offset": offset, "errors": errors})
    return violations


def property_terminal_review_requires_completed(validate: ValidateFn, rng: random.Random, trials: int) -> list[dict]:
    """Property: a terminal ACCEPTED/REJECTED independent_acceptance decision
    must be rejected unless obzio_state is COMPLETED, for every other
    terminal-ish committed state, not only the one example the fixed suite
    happens to try."""
    violations = []
    non_completed_states = ["RESULT_COMMITTED", "PARENT_INGESTED", "RESULT_VERIFIED", "RUNNING"]
    for _ in range(trials):
        doc = copy.deepcopy(base_committed_result())
        state = rng.choice(non_completed_states)
        doc["obzio_state"] = state
        doc["completion_actor"] = None
        if state in {"RESULT_COMMITTED", "PARENT_INGESTED"}:
            doc["result_transaction"]["parent_ingested_at"] = (
                "2026-08-22T06:03:00Z" if state == "PARENT_INGESTED" else None
            )
        decision = rng.choice(["ACCEPTED", "REJECTED"])
        doc["independent_acceptance"] = {
            "state": decision,
            "reviewer_id": "reviewer-2",
            "receipt_uri": "git:po03/review@def:receipt.json",
        }
        errors = validate(doc)
        caught = any("COMPLETED" in e for e in errors)
        if not caught:
            violations.append({"obzio_state": state, "decision": decision, "errors": errors})
    return violations


PROPERTIES = {
    "nonpositive_bytes_always_rejected": property_nonpositive_bytes_always_rejected,
    "total_bytes_mismatch_always_rejected": property_total_bytes_mismatch_always_rejected,
    "terminal_review_requires_completed": property_terminal_review_requires_completed,
}


def run_all_properties(validate: ValidateFn, seed: int, trials_per_property: int = 40) -> dict[str, Any]:
    rng = random.Random(seed)
    report = {}
    for name, prop_fn in PROPERTIES.items():
        violations = prop_fn(validate, rng, trials_per_property)
        report[name] = {"trials": trials_per_property, "violations": violations, "passed": len(violations) == 0}
    return report
