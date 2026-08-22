#!/usr/bin/env python3
"""Dependency-free transactional custody state machine for PO03-WA-012.

The engine validates one event at a time against an immutable snapshot.  It
fails closed on unknown edges, actor-role violations, stale/future fence
tokens, checkpoint regression, and missing custody evidence.  Provider state
is deliberately absent: a provider observation cannot advance Obzio state.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


MECHANISM_VERSION = "PO03-WA-012-STATE-MACHINE-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

# Each edge is explicit.  No ordinal comparison is used to infer permission.
TRANSITIONS: dict[str, dict[str, frozenset[str]]] = {
    "CREATED": {"LEASED": frozenset({"controller"})},
    "LEASED": {"RUNNING": frozenset({"worker"})},
    "RUNNING": {
        "CHECKPOINTED": frozenset({"worker"}),
        "RESULT_STAGING": frozenset({"worker"}),
    },
    "CHECKPOINTED": {
        "CHECKPOINTED": frozenset({"worker"}),
        "RESULT_STAGING": frozenset({"worker"}),
    },
    "RESULT_STAGING": {"RESULT_STAGED": frozenset({"worker"})},
    "RESULT_STAGED": {"RESULT_VERIFIED": frozenset({"verifier"})},
    "RESULT_VERIFIED": {"RESULT_COMMITTED": frozenset({"worker"})},
    "RESULT_COMMITTED": {"PARENT_INGESTED": frozenset({"coordinator"})},
    "PARENT_INGESTED": {"COMPLETED": frozenset({"coordinator"})},
    "COMPLETED": {
        "ACCEPTED": frozenset({"reviewer"}),
        "REJECTED": frozenset({"reviewer"}),
    },
    "ACCEPTED": {},
    "REJECTED": {},
}

EVIDENCE_DEFAULTS: dict[str, Any] = {
    "manifest_verified": False,
    "manifest_sha256": None,
    "artifact_count": 0,
    "total_bytes": 0,
    "result_commit_id": None,
    "remote_branch": None,
    "immutable_readback_verified": False,
    "ingestion_receipt": None,
}


class TransitionRejected(ValueError):
    """A deterministic, machine-readable transition rejection."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_int(value: Any, name: str, minimum: int) -> int:
    # bool is an int subclass but is not an admissible counter or fence.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TransitionRejected(
            "INVALID_EVENT",
            f"{name} must be an integer >= {minimum}",
        )
    return value


def _actor_parts(actor: Any) -> tuple[str, str]:
    if not _nonempty(actor) or ":" not in actor:
        raise TransitionRejected(
            "INVALID_ACTOR",
            "actor must use role:identity form",
        )
    role, identity = actor.split(":", 1)
    if not role or not identity:
        raise TransitionRejected(
            "INVALID_ACTOR",
            "actor must use role:identity form",
        )
    return role, identity


def _required_event_fields(event: dict[str, Any]) -> None:
    missing = [
        name
        for name in ("from_state", "to_state", "actor", "fence_token")
        if name not in event
    ]
    if missing:
        raise TransitionRejected(
            "INVALID_EVENT",
            f"missing event fields: {', '.join(missing)}",
        )


@dataclass(frozen=True)
class MachineSnapshot:
    """Immutable state needed to validate the next custody event."""

    state: str
    current_fence: int
    checkpoint_seq: int
    producer_id: str
    evidence: dict[str, Any]

    @classmethod
    def from_document(cls, value: dict[str, Any]) -> "MachineSnapshot":
        if not isinstance(value, dict):
            raise TransitionRejected("INVALID_SNAPSHOT", "snapshot must be an object")
        state = value.get("state")
        if state not in TRANSITIONS:
            raise TransitionRejected("INVALID_SNAPSHOT", f"unknown state: {state!r}")
        current_fence = _require_int(
            value.get("current_fence"),
            "current_fence",
            1,
        )
        checkpoint_seq = _require_int(
            value.get("checkpoint_seq", 0),
            "checkpoint_seq",
            0,
        )
        producer_id = value.get("producer_id")
        if not _nonempty(producer_id):
            raise TransitionRejected(
                "INVALID_SNAPSHOT",
                "producer_id must be non-empty",
            )
        supplied_evidence = value.get("evidence", {})
        if not isinstance(supplied_evidence, dict):
            raise TransitionRejected("INVALID_SNAPSHOT", "evidence must be an object")
        unknown = sorted(set(supplied_evidence) - set(EVIDENCE_DEFAULTS))
        if unknown:
            raise TransitionRejected(
                "INVALID_SNAPSHOT",
                f"unknown evidence fields: {', '.join(unknown)}",
            )
        evidence = {**EVIDENCE_DEFAULTS, **copy.deepcopy(supplied_evidence)}
        return cls(
            state=state,
            current_fence=current_fence,
            checkpoint_seq=checkpoint_seq,
            producer_id=producer_id,
            evidence=evidence,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "current_fence": self.current_fence,
            "checkpoint_seq": self.checkpoint_seq,
            "producer_id": self.producer_id,
            "evidence": copy.deepcopy(self.evidence),
        }


def _verify_edge(snapshot: MachineSnapshot, event: dict[str, Any]) -> tuple[str, str]:
    if event["from_state"] != snapshot.state:
        raise TransitionRejected(
            "STATE_MISMATCH",
            f"event starts at {event['from_state']!r}, snapshot is {snapshot.state!r}",
        )

    target = event["to_state"]
    allowed_roles = TRANSITIONS[snapshot.state].get(target)
    if allowed_roles is None:
        raise TransitionRejected(
            "ILLEGAL_TRANSITION",
            f"{snapshot.state} -> {target} is not an allowed edge",
        )

    role, identity = _actor_parts(event["actor"])
    if role not in allowed_roles:
        raise TransitionRejected(
            "ACTOR_NOT_AUTHORIZED",
            f"role {role!r} cannot perform {snapshot.state} -> {target}",
        )
    if role == "worker" and identity != snapshot.producer_id:
        raise TransitionRejected(
            "WORKER_IDENTITY_MISMATCH",
            "worker identity does not match the leased producer",
        )
    if role == "reviewer" and identity == snapshot.producer_id:
        raise TransitionRejected(
            "PRODUCER_SELF_REVIEW",
            "the producer cannot independently review its own result",
        )
    return role, identity


def _verify_fence(snapshot: MachineSnapshot, event: dict[str, Any]) -> None:
    event_fence = _require_int(event["fence_token"], "fence_token", 1)
    if event_fence < snapshot.current_fence:
        raise TransitionRejected(
            "STALE_FENCE",
            f"event fence {event_fence} is older than current fence {snapshot.current_fence}",
        )
    if event_fence > snapshot.current_fence:
        raise TransitionRejected(
            "FUTURE_FENCE",
            f"event fence {event_fence} has not been granted; current fence is {snapshot.current_fence}",
        )


def _advance_checkpoint(
    snapshot: MachineSnapshot,
    event: dict[str, Any],
) -> int:
    supplied = event.get("checkpoint_seq")
    if event["to_state"] == "CHECKPOINTED":
        checkpoint = _require_int(supplied, "checkpoint_seq", 1)
        if checkpoint <= snapshot.checkpoint_seq:
            raise TransitionRejected(
                "CHECKPOINT_REGRESSION",
                "checkpoint_seq must increase on every CHECKPOINTED edge",
            )
        return checkpoint
    if supplied is not None:
        checkpoint = _require_int(supplied, "checkpoint_seq", 0)
        if checkpoint < snapshot.checkpoint_seq:
            raise TransitionRejected(
                "CHECKPOINT_REGRESSION",
                "checkpoint_seq cannot decrease",
            )
        return checkpoint
    return snapshot.checkpoint_seq


def _advance_evidence(
    snapshot: MachineSnapshot,
    event: dict[str, Any],
) -> dict[str, Any]:
    evidence = copy.deepcopy(snapshot.evidence)
    target = event["to_state"]

    if target == "RESULT_VERIFIED":
        digest = event.get("manifest_sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise TransitionRejected(
                "VERIFICATION_EVIDENCE_REQUIRED",
                "RESULT_VERIFIED requires a lowercase manifest_sha256",
            )
        artifact_count = _require_int(
            event.get("artifact_count"),
            "artifact_count",
            1,
        )
        total_bytes = _require_int(event.get("total_bytes"), "total_bytes", 1)
        if total_bytes < artifact_count:
            raise TransitionRejected(
                "VERIFICATION_EVIDENCE_REQUIRED",
                "total_bytes cannot be smaller than artifact_count",
            )
        evidence.update(
            manifest_verified=True,
            manifest_sha256=digest,
            artifact_count=artifact_count,
            total_bytes=total_bytes,
        )

    if target == "RESULT_COMMITTED":
        if not evidence["manifest_verified"]:
            raise TransitionRejected(
                "VERIFICATION_EVIDENCE_REQUIRED",
                "RESULT_COMMITTED requires prior RESULT_VERIFIED evidence",
            )
        commit_id = event.get("result_commit_id")
        if not isinstance(commit_id, str) or not COMMIT_RE.fullmatch(commit_id):
            raise TransitionRejected(
                "COMMIT_EVIDENCE_REQUIRED",
                "RESULT_COMMITTED requires a 40- or 64-character commit id",
            )
        remote_branch = event.get("remote_branch")
        if not _nonempty(remote_branch):
            raise TransitionRejected(
                "COMMIT_EVIDENCE_REQUIRED",
                "RESULT_COMMITTED requires a remote_branch",
            )
        evidence.update(
            result_commit_id=commit_id,
            remote_branch=remote_branch,
        )

    if target == "PARENT_INGESTED":
        if not _nonempty(evidence["result_commit_id"]):
            raise TransitionRejected(
                "COMMIT_EVIDENCE_REQUIRED",
                "PARENT_INGESTED requires prior RESULT_COMMITTED evidence",
            )
        if event.get("immutable_readback_verified") is not True:
            raise TransitionRejected(
                "READBACK_EVIDENCE_REQUIRED",
                "PARENT_INGESTED requires immutable_readback_verified=true",
            )
        receipt = event.get("ingestion_receipt")
        if not _nonempty(receipt):
            raise TransitionRejected(
                "INGESTION_EVIDENCE_REQUIRED",
                "PARENT_INGESTED requires an ingestion_receipt",
            )
        evidence.update(
            immutable_readback_verified=True,
            ingestion_receipt=receipt,
        )

    if target == "COMPLETED":
        required = (
            evidence["manifest_verified"],
            _nonempty(evidence["result_commit_id"]),
            evidence["immutable_readback_verified"],
            _nonempty(evidence["ingestion_receipt"]),
        )
        if not all(required):
            raise TransitionRejected(
                "COMPLETION_EVIDENCE_REQUIRED",
                "COMPLETED requires verification, commit, readback, and ingestion evidence",
            )

    return evidence


def apply_transition(
    snapshot: MachineSnapshot,
    event: dict[str, Any],
) -> MachineSnapshot:
    """Return an advanced snapshot or raise TransitionRejected atomically."""

    if not isinstance(event, dict):
        raise TransitionRejected("INVALID_EVENT", "event must be an object")
    _required_event_fields(event)
    _verify_fence(snapshot, event)
    _verify_edge(snapshot, event)
    checkpoint_seq = _advance_checkpoint(snapshot, event)
    evidence = _advance_evidence(snapshot, event)
    return MachineSnapshot(
        state=event["to_state"],
        current_fence=snapshot.current_fence,
        checkpoint_seq=checkpoint_seq,
        producer_id=snapshot.producer_id,
        evidence=evidence,
    )


def validate_sequence(document: dict[str, Any]) -> dict[str, Any]:
    """Validate an event sequence, stopping at the first rejected event."""

    if not isinstance(document, dict):
        raise TransitionRejected("INVALID_SEQUENCE", "sequence must be an object")
    events = document.get("events")
    if not isinstance(events, list):
        raise TransitionRejected("INVALID_SEQUENCE", "events must be an array")
    snapshot = MachineSnapshot.from_document(document.get("initial_snapshot"))
    for index, event in enumerate(events):
        try:
            snapshot = apply_transition(snapshot, event)
        except TransitionRejected as exc:
            return {
                "status": "REJECTED",
                "failing_event_index": index,
                "error": exc.as_dict(),
                "snapshot": snapshot.as_dict(),
            }
    return {
        "status": "VALID",
        "event_count": len(events),
        "snapshot": snapshot.as_dict(),
    }


def matrix_document() -> dict[str, Any]:
    transitions = []
    for source in TRANSITIONS:
        for target, roles in TRANSITIONS[source].items():
            transitions.append(
                {
                    "from_state": source,
                    "to_state": target,
                    "allowed_actor_roles": sorted(roles),
                }
            )
    return {
        "mechanism_version": MECHANISM_VERSION,
        "failure_mode": "FAIL_CLOSED",
        "fence_rule": "event.fence_token == snapshot.current_fence",
        "actor_format": "role:identity",
        "transitions": transitions,
    }


def _case_matches(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    if expected.get("status") != observed.get("status"):
        return False
    if "final_state" in expected:
        if observed.get("snapshot", {}).get("state") != expected["final_state"]:
            return False
    if "error_code" in expected:
        if observed.get("error", {}).get("code") != expected["error_code"]:
            return False
    if "failing_event_index" in expected:
        if observed.get("failing_event_index") != expected["failing_event_index"]:
            return False
    return True


def run_reproduction(document: dict[str, Any]) -> dict[str, Any]:
    """Run a sanitized multi-case fixture and compare frozen expectations."""

    if not isinstance(document, dict) or not isinstance(document.get("cases"), list):
        raise TransitionRejected(
            "INVALID_REPRODUCTION",
            "reproduction must contain a cases array",
        )
    case_results = []
    for case in document["cases"]:
        if not isinstance(case, dict) or not _nonempty(case.get("case_id")):
            raise TransitionRejected(
                "INVALID_REPRODUCTION",
                "every reproduction case requires case_id",
            )
        expected = case.get("expected")
        if not isinstance(expected, dict):
            raise TransitionRejected(
                "INVALID_REPRODUCTION",
                f"{case['case_id']} requires expected",
            )
        observed = validate_sequence(
            {
                "initial_snapshot": case.get("initial_snapshot"),
                "events": case.get("events"),
            }
        )
        case_results.append(
            {
                "case_id": case["case_id"],
                "hypothesis_ids": case.get("hypothesis_ids", []),
                "expected": expected,
                "observed": observed,
                "matched": _case_matches(expected, observed),
            }
        )
    matched = sum(1 for item in case_results if item["matched"])
    return {
        "protocol_version": "OBZIO-SANITIZED-REPRODUCTION-v1",
        "mechanism_version": MECHANISM_VERSION,
        "fixture_id": document.get("fixture_id"),
        "sanitization": document.get("sanitization"),
        "case_results": case_results,
        "summary": {
            "case_count": len(case_results),
            "matched_count": matched,
            "all_expectations_matched": matched == len(case_results),
        },
        "hypothesis_outcome": (
            "SUPPORTED" if matched == len(case_results) else "REFUTED"
        ),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def _write_or_print(value: dict[str, Any], output: Path | None) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(payload)
    else:
        output.write_text(payload, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate PO-03 transactional custody transitions",
    )
    parser.add_argument("--version", action="version", version=MECHANISM_VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    matrix = subparsers.add_parser("matrix", help="emit the transition matrix")
    matrix.add_argument("--output", type=Path)

    sequence = subparsers.add_parser("sequence", help="validate one event sequence")
    sequence.add_argument("document", type=Path)
    sequence.add_argument("--output", type=Path)

    reproduce = subparsers.add_parser(
        "reproduce",
        help="run a sanitized multi-case reproduction",
    )
    reproduce.add_argument("document", type=Path)
    reproduce.add_argument("--output", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "matrix":
            result = matrix_document()
            exit_code = 0
        elif args.command == "sequence":
            result = validate_sequence(_read_json(args.document))
            exit_code = 0 if result["status"] == "VALID" else 1
        else:
            result = run_reproduction(_read_json(args.document))
            exit_code = 0 if result["summary"]["all_expectations_matched"] else 1
        _write_or_print(result, args.output)
        return exit_code
    except (OSError, ValueError, json.JSONDecodeError, TransitionRejected) as exc:
        if isinstance(exc, TransitionRejected):
            detail: Any = exc.as_dict()
        else:
            detail = {"code": "INVALID_INPUT", "message": str(exc)}
        _write_or_print({"status": "ERROR", "error": detail}, None)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
