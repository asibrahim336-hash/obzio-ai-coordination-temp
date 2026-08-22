#!/usr/bin/env python3
"""PO03-WA-007 -- provider completion without a durable commit is reclassified.

Frozen hypothesis
-----------------
"Provider completion without a durable commit is reclassified automatically."

This is the false-completion defect in its purest form.  A provider run finishes
and reports ``COMPLETED``.  That statement is true *about the provider* and says
nothing about whether Obzio holds a durable, verifiable result.  Treating the
two as the same fact is what produced the recorded PO-02 Code-2 outcome: a unit
counted as complete with no locator anyone could open.

Design -- two state axes that never merge
-----------------------------------------
``provider_state`` and ``obzio_state`` are separate inputs and stay separate.
Obzio state is *derived*, never accepted from the provider, and the derivation
is a total function over the observable facts:

* provider ``COMPLETED`` + no verifiable commit -> ``PROVIDER_COMPLETED_UNCOMMITTED``
* provider ``COMPLETED`` + a commit that fails verification -> the same, with
  the verification failure recorded as the reason
* provider ``COMPLETED`` + a verified commit -> ``RESULT_COMMITTED``, and no
  further, because ``COMPLETED`` belongs to the coordinator after independent
  acceptance
* provider ``FAILED``/``CANCELLED``/``UNKNOWN`` -> classified on their own terms

"Durable commit" is not a boolean the caller may assert.  It is a locator that
is *resolved* against a commit resolver: absent locator, unresolvable locator,
and locator whose content hash disagrees are three distinct observations, and
all three are non-durable.

The reclassifier also cross-checks its verdict against the seeded repository
validator ``workstreams/po03/tools/validate_contracts.py`` when that file is
reachable, so this component cannot drift from the contract it must satisfy.

Executable entry point::

    python3 reclassifier.py --demo
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROVIDER_STATES = ("QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "UNKNOWN")

#: Obzio states this component may derive.  ``COMPLETED`` is deliberately absent:
#: a producer-side classifier can never mint coordinator completion.
DERIVABLE = (
    "RUNNING",
    "RESULT_COMMITTED",
    "PROVIDER_COMPLETED_UNCOMMITTED",
    "RECOVERY_REQUIRED",
    "FAILED_TERMINAL",
    "CANCELLED",
)


class CommitResolver:
    """Resolves a result locator to durable bytes, or fails to."""

    def __init__(self, commits: dict[str, bytes] | None = None) -> None:
        self.commits = dict(commits or {})
        self.lookups = 0

    def add(self, locator: str, payload: bytes) -> str:
        self.commits[locator] = payload
        return hashlib.sha256(payload).hexdigest()

    def resolve(self, locator: str) -> bytes | None:
        self.lookups += 1
        return self.commits.get(locator)


@dataclass
class Observation:
    """Everything observable about one attempt, with no derived conclusions."""

    task_id: str
    provider_state: str
    result_commit_id: str | None = None
    declared_manifest_sha256: str | None = None
    artifact_count: int = 0
    completion_actor: str | None = None
    independent_acceptance: str = "NOT_TESTED"


@dataclass
class Classification:
    """The derived verdict plus the evidence it was derived from."""

    task_id: str
    provider_state: str
    obzio_state: str
    durable_commit: bool
    reason: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "provider_state": self.provider_state,
            "obzio_state": self.obzio_state,
            "durable_commit": self.durable_commit,
            "reason": self.reason,
            "detail": self.detail,
            "evidence": self.evidence,
        }


class Reclassifier:
    """Derives Obzio state from observable facts; never accepts it as input."""

    def __init__(self, resolver: CommitResolver) -> None:
        self.resolver = resolver

    def _verify_commit(self, observation: Observation) -> tuple[bool, str, str, dict[str, Any]]:
        locator = observation.result_commit_id
        if locator is None or not str(locator).strip():
            return False, "NO_RESULT_COMMIT_LOCATOR", "no locator was recorded for this attempt", {}
        payload = self.resolver.resolve(locator)
        if payload is None:
            return (
                False,
                "LOCATOR_UNRESOLVABLE",
                f"locator {locator!r} does not resolve to durable bytes",
                {"locator": locator},
            )
        observed = hashlib.sha256(payload).hexdigest()
        if observation.declared_manifest_sha256 is None:
            return (
                False,
                "NO_DECLARED_MANIFEST_HASH",
                "the locator resolves but nothing pins its content",
                {"locator": locator, "observed_sha256": observed},
            )
        if observed != observation.declared_manifest_sha256:
            return (
                False,
                "MANIFEST_HASH_MISMATCH",
                "the resolved bytes do not match the declared manifest hash",
                {
                    "locator": locator,
                    "declared_sha256": observation.declared_manifest_sha256,
                    "observed_sha256": observed,
                },
            )
        if observation.artifact_count < 1:
            return (
                False,
                "NO_ARTIFACTS",
                "a durable commit must carry at least one artifact",
                {"locator": locator, "artifact_count": observation.artifact_count},
            )
        return True, "COMMIT_VERIFIED", "locator resolved and content hash matched", {
            "locator": locator,
            "observed_sha256": observed,
        }

    def classify(self, observation: Observation) -> Classification:
        if observation.provider_state not in PROVIDER_STATES:
            raise ValueError(f"unknown provider_state {observation.provider_state!r}")

        durable, reason, detail, evidence = self._verify_commit(observation)

        if observation.provider_state in ("QUEUED", "RUNNING"):
            state = "RESULT_COMMITTED" if durable else "RUNNING"
        elif observation.provider_state == "COMPLETED":
            # The whole point: provider truth does not become Obzio truth.
            state = "RESULT_COMMITTED" if durable else "PROVIDER_COMPLETED_UNCOMMITTED"
        elif observation.provider_state == "FAILED":
            state = "RESULT_COMMITTED" if durable else "FAILED_TERMINAL"
        elif observation.provider_state == "CANCELLED":
            state = "RESULT_COMMITTED" if durable else "CANCELLED"
        else:  # UNKNOWN
            state = "RESULT_COMMITTED" if durable else "RECOVERY_REQUIRED"

        assert state in DERIVABLE, state
        return Classification(
            task_id=observation.task_id,
            provider_state=observation.provider_state,
            obzio_state=state,
            durable_commit=durable,
            reason=reason,
            detail=detail,
            evidence=evidence,
        )

    def to_result_document(self, observation: Observation, classification: Classification) -> dict[str, Any]:
        """Emit a document in the seeded transactional-result contract shape."""
        committed = classification.durable_commit
        return {
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "task_id": observation.task_id,
            "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
            "immutable_input_manifest_sha256": "f" * 64,
            "acceptance_contract_sha256": "e" * 64,
            "provider_state": observation.provider_state,
            "obzio_state": classification.obzio_state,
            "attempt": {
                "attempt_id": f"{observation.task_id}-attempt-1",
                "idempotency_key": f"{observation.task_id}:1",
                "lease_id": f"lease-{observation.task_id}-1",
                "fence_token": 1,
                "provider_run_id": "provider-run-1",
                "worker_id": "worker-1",
                "heartbeat_at": None,
                "checkpoint_seq": 0,
            },
            "result_transaction": {
                "result_txn_id": f"rtxn-{observation.task_id}",
                "state": "COMMITTED" if committed else "RESERVED",
                "manifest_uri": observation.result_commit_id if committed else None,
                "manifest_sha256": observation.declared_manifest_sha256 if committed else None,
                "artifact_count": observation.artifact_count if committed else 0,
                "total_bytes": 1 if committed else 0,
                "committed_at": "2026-08-22T07:00:00Z" if committed else None,
                "verified_at": "2026-08-22T07:00:00Z" if committed else None,
                "parent_ingested_at": None,
                "result_commit_id": observation.result_commit_id if committed else None,
            },
            "artifacts": (
                [
                    {
                        "artifact_id": f"{observation.task_id}-a1",
                        "logical_name": "manifest.json",
                        "content_uri": str(observation.result_commit_id),
                        "sha256": observation.declared_manifest_sha256 or "0" * 64,
                        "bytes": 1,
                        "media_type": "application/json",
                        "readback_verified_at": "2026-08-22T07:00:00Z",
                    }
                ]
                if committed
                else []
            ),
            "completion_actor": None,
            "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
        }


def load_repository_validator() -> Any | None:
    """Load the seeded contract validator if this clone provides it."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "workstreams/po03/tools/validate_contracts.py"
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("po03_validate_contracts", candidate)
            module = importlib.util.module_from_spec(spec)
            sys.modules["po03_validate_contracts"] = module
            spec.loader.exec_module(module)
            return module
    return None


def reproduce_po02_code2() -> dict[str, Any]:
    """The recorded lost PO-02 Code-2 fixture: completed provider, no locator."""
    resolver = CommitResolver()
    reclassifier = Reclassifier(resolver)
    observation = Observation(
        task_id="PO02-CODE-2",
        provider_state="COMPLETED",
        result_commit_id=None,
        declared_manifest_sha256=None,
        artifact_count=0,
    )
    classification = reclassifier.classify(observation)
    document = reclassifier.to_result_document(observation, classification)
    validator = load_repository_validator()
    errors = validator.validate_result(document) if validator else None
    return {
        "classification": classification.as_dict(),
        "seeded_validator_available": validator is not None,
        "seeded_validator_errors": errors,
    }


def sweep_matrix() -> dict[str, Any]:
    """Every provider state crossed with every commit-durability observation."""
    resolver = CommitResolver()
    good_sha = resolver.add("commit:good", b"durable-manifest-bytes")
    reclassifier = Reclassifier(resolver)
    validator = load_repository_validator()

    commit_shapes = {
        "no_locator": {"result_commit_id": None, "declared_manifest_sha256": None, "artifact_count": 0},
        "unresolvable_locator": {
            "result_commit_id": "commit:missing",
            "declared_manifest_sha256": good_sha,
            "artifact_count": 1,
        },
        "unpinned_content": {
            "result_commit_id": "commit:good",
            "declared_manifest_sha256": None,
            "artifact_count": 1,
        },
        "hash_mismatch": {
            "result_commit_id": "commit:good",
            "declared_manifest_sha256": "a" * 64,
            "artifact_count": 1,
        },
        "no_artifacts": {
            "result_commit_id": "commit:good",
            "declared_manifest_sha256": good_sha,
            "artifact_count": 0,
        },
        "verified": {
            "result_commit_id": "commit:good",
            "declared_manifest_sha256": good_sha,
            "artifact_count": 1,
        },
    }

    rows = []
    for provider_state in PROVIDER_STATES:
        for shape_name, shape in commit_shapes.items():
            observation = Observation(task_id=f"T-{provider_state}-{shape_name}", provider_state=provider_state, **shape)
            classification = reclassifier.classify(observation)
            document = reclassifier.to_result_document(observation, classification)
            rows.append(
                {
                    "provider_state": provider_state,
                    "commit_shape": shape_name,
                    "obzio_state": classification.obzio_state,
                    "durable_commit": classification.durable_commit,
                    "reason": classification.reason,
                    "contract_errors": (validator.validate_result(document) if validator else None),
                }
            )
    return {
        "rows": rows,
        "false_completions": [row for row in rows if row["obzio_state"] == "COMPLETED"],
        "completed_provider_without_commit": sorted(
            {
                row["obzio_state"]
                for row in rows
                if row["provider_state"] == "COMPLETED" and not row["durable_commit"]
            }
        ),
        "contract_violations": [row for row in rows if row["contract_errors"]],
    }


def demo() -> int:
    report = {"po02_code2_fixture": reproduce_po02_code2(), "matrix": sweep_matrix()}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv)
    if args.demo:
        return demo()
    parser.error("use --demo")
    return 2


if __name__ == "__main__":
    sys.exit(main())
