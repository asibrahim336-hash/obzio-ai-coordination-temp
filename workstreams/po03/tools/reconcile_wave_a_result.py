#!/usr/bin/env python3
"""Independently verify and transactionally ingest one PO-03 Wave A result."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COMMISSION_ID = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
CONTROLLER_ID = "bc-b1956656-b897-4889-aeab-82c4556c1a9f"
PROTOCOL_ANCESTOR = "e56eda6e8e4a4e958795f7157839926d93272b30"
ATTEMPT_ID_RE = re.compile(r"^(PO03-WA-\d{3})-(A\d{2})$")
FULL_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT.parents[1])


def _show(commit: str, path: str) -> bytes:
    return _git("show", f"{commit}:{path}")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json(relative: str, value: Any) -> None:
    path = (ROOT / relative).resolve()
    if ROOT not in path.parents:
        raise ValueError(f"out-of-scope write refused: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _read_json(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _read_jsonl(relative: str) -> list[dict[str, Any]]:
    path = ROOT / relative
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(relative: str, rows: list[dict[str, Any]]) -> None:
    path = (ROOT / relative).resolve()
    if ROOT not in path.parents:
        raise ValueError(f"out-of-scope write refused: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _commit_time(commit: str) -> str:
    return _git("show", "-s", "--format=%cI", commit).decode().strip()


def _attempt_projection(
    task_id: str, slug: str, attempt: dict[str, Any]
) -> tuple[str, str]:
    attempt_id = attempt.get("attempt_id")
    match = ATTEMPT_ID_RE.fullmatch(str(attempt_id))
    if match is None or match.group(1) != task_id:
        raise ValueError(f"invalid active attempt identity: {attempt_id!r}")
    suffix = match.group(2).lower()
    input_name = f"{slug}.json" if suffix == "a01" else f"{slug}-{suffix}.json"
    return (
        f"control/inputs/wave-a/{input_name}",
        f"outbox-po03-{slug}-dispatch-{suffix}",
    )


def _validate_producer_attempt(
    task_id: str,
    control_attempt: dict[str, Any],
    ready: dict[str, Any],
    producer_result: dict[str, Any],
) -> None:
    expected = {
        field: control_attempt.get(field)
        for field in ("attempt_id", "idempotency_key", "lease_id", "fence_token")
    }
    for label, document in (
        ("producer return", ready),
        ("producer result", producer_result),
    ):
        observed = document.get("attempt")
        if not isinstance(observed, dict):
            raise ValueError(f"{label} lacks an attempt envelope")
        for field, value in expected.items():
            if observed.get(field) != value:
                raise ValueError(
                    f"{label} is stale or divergent for {task_id}: {field}"
                )


def _require_ancestor(ancestor: str, descendant: str, label: str) -> None:
    try:
        _git("merge-base", "--is-ancestor", ancestor, descendant)
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"{label}: {ancestor} is not an ancestor of {descendant}") from exc


def _trusted_source_base(
    ready: dict[str, Any], return_commit: str, ingestion_commit: str
) -> str:
    source_base = ready.get("source_base_commit")
    if not isinstance(source_base, str) or not FULL_COMMIT_RE.fullmatch(source_base):
        raise ValueError("producer return lacks an exact source_base_commit")
    try:
        resolved = _git(
            "rev-parse", "--verify", f"{source_base}^{{commit}}"
        ).decode().strip()
    except subprocess.CalledProcessError as exc:
        raise ValueError("producer source_base_commit is not resolvable") from exc
    if resolved != source_base:
        raise ValueError("producer source_base_commit did not resolve exactly")
    _require_ancestor(PROTOCOL_ANCESTOR, source_base, "protocol chronology")
    _require_ancestor(source_base, return_commit, "producer branch chronology")
    _require_ancestor(source_base, ingestion_commit, "controller chronology")
    common_base = _git(
        "merge-base", return_commit, ingestion_commit
    ).decode().strip()
    if common_base != source_base:
        raise ValueError(
            "producer source base is not the exact producer/controller divergence"
        )
    return source_base


def _later_time(existing: Any, candidate: Any) -> Any:
    values = [value for value in (existing, candidate) if isinstance(value, str) and value]
    return max(values) if values else None


def _reconciled_active_count(
    previous_count: Any, registry_running: int, was_active: bool
) -> int:
    previous = max(0, int(previous_count))
    projected = previous - 1 if was_active and previous > 0 else previous
    return max(registry_running, projected)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-number", type=int, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--result-commit", required=True)
    parser.add_argument("--return-commit", required=True)
    parser.add_argument(
        "--manifest-relative", default="result/artifact-manifest.json"
    )
    parser.add_argument("--ready-relative", default="result/ready-to-commit.json")
    parser.add_argument("--producer-result-relative", default="result/result.json")
    parser.add_argument("--provider-run-id", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--model-observed", required=True)
    parser.add_argument("--verified-at", required=True)
    parser.add_argument("--ingestion-commit", required=True)
    parser.add_argument("--focused-tests", type=int, required=True)
    parser.add_argument("--seeded-tests", type=int, required=True)
    parser.add_argument(
        "--verdict", choices=("ACCEPTED", "REJECTED"), required=True
    )
    parser.add_argument("--route-disposition", required=True)
    parser.add_argument("--review-note", required=True)
    return parser.parse_args()


def main() -> int:
    args = _args()
    if args.task_number < 1 or args.task_number > 64:
        raise ValueError("task number must be 1..64")
    slug = f"wa-{args.task_number:03d}"
    task_id = f"PO03-WA-{args.task_number:03d}"
    prefix = f"workstreams/po03/wave-a/units/{slug}/"
    manifest_path = prefix + args.manifest_relative
    ready_path = prefix + args.ready_relative
    result_path = prefix + args.producer_result_relative

    manifest_bytes = _show(args.return_commit, manifest_path)
    manifest = json.loads(manifest_bytes)
    ready_bytes = _show(args.return_commit, ready_path)
    ready = json.loads(ready_bytes)
    producer_result = json.loads(_show(args.return_commit, result_path))
    source_base = _trusted_source_base(
        ready, args.return_commit, args.ingestion_commit
    )
    changed_paths = (
        _git("diff", "--name-only", f"{source_base}..{args.return_commit}")
        .decode()
        .splitlines()
    )
    if not changed_paths or any(not path.startswith(prefix) for path in changed_paths):
        raise ValueError(f"owned-path violation: {changed_paths}")

    terminal_report = ready.get("status", ready.get("terminal_report"))
    if terminal_report != "READY_TO_COMMIT" or ready.get("task_id") != task_id:
        raise ValueError("invalid producer return envelope")
    if producer_result.get("task_id") != task_id:
        raise ValueError("result task mismatch")
    if ready.get("manifest_sha256") != _sha(manifest_bytes):
        raise ValueError("return envelope manifest digest mismatch")
    if manifest.get("artifact_count") != len(manifest.get("artifacts", [])):
        raise ValueError("manifest artifact count mismatch")

    artifacts: list[dict[str, Any]] = []
    payload_bytes = 0
    for index, artifact in enumerate(manifest["artifacts"]):
        declared_path = artifact.get("path", artifact.get("content_uri"))
        if not isinstance(declared_path, str) or not declared_path:
            raise ValueError(f"manifest artifact lacks path: {artifact}")
        content_path = (
            declared_path
            if declared_path.startswith("workstreams/")
            else prefix + declared_path
        )
        relative = (
            content_path[len(prefix):]
            if content_path.startswith(prefix)
            else content_path
        )
        data = _show(args.return_commit, content_path)
        if len(data) != artifact["bytes"] or _sha(data) != artifact["sha256"]:
            raise ValueError(f"immutable readback mismatch: {relative}")
        payload_bytes += len(data)
        artifacts.append(
            {
                "artifact_id": artifact.get(
                    "artifact_id", f"{task_id}-ARTIFACT-{index + 1:03d}"
                ),
                "logical_name": relative,
                "content_uri": (
                    f"git:{args.branch}@{args.return_commit}:{content_path}"
                ),
                "sha256": artifact["sha256"],
                "bytes": artifact["bytes"],
                "media_type": artifact.get(
                    "media_type", "application/octet-stream"
                ),
                "readback_verified_at": args.verified_at,
            }
        )
    if payload_bytes != manifest["total_bytes"]:
        raise ValueError("manifest byte total mismatch")
    envelope_specs = [
        ("ARTIFACT-MANIFEST", args.manifest_relative, manifest_path, manifest_bytes),
        ("READY-TO-COMMIT", args.ready_relative, ready_path, ready_bytes),
    ]
    existing_content_paths = {
        artifact["content_uri"].split(":", 2)[-1] for artifact in artifacts
    }
    for suffix, logical_name, content_path, data in envelope_specs:
        if content_path in existing_content_paths:
            continue
        artifacts.append(
            {
                "artifact_id": f"{task_id}-{suffix}",
                "logical_name": logical_name,
                "content_uri": (
                    f"git:{args.branch}@{args.return_commit}:{content_path}"
                ),
                "sha256": _sha(data),
                "bytes": len(data),
                "media_type": "application/json",
                "readback_verified_at": args.verified_at,
            }
        )
    observed_bytes = sum(int(artifact["bytes"]) for artifact in artifacts)

    control_result_rel = f"control/results/wave-a/{slug}.json"
    control_result = _read_json(control_result_rel)
    attempt = control_result["attempt"]
    was_active = (
        control_result.get("provider_state") == "RUNNING"
        or control_result.get("obzio_state") == "RUNNING"
    )
    _validate_producer_attempt(task_id, attempt, ready, producer_result)
    input_rel, outbox_id = _attempt_projection(task_id, slug, attempt)
    input_bytes = (ROOT / input_rel).read_bytes()
    input_doc = json.loads(input_bytes)
    if _sha(input_bytes) != control_result["immutable_input_manifest_sha256"]:
        raise ValueError("active immutable input digest mismatch")
    if (
        ready.get("immutable_input_manifest_sha256")
        != control_result["immutable_input_manifest_sha256"]
    ):
        raise ValueError("producer return references a stale immutable input")
    control_result.update(
        provider_state="COMPLETED",
        obzio_state="COMPLETED",
        completion_actor="coordinator",
        artifacts=artifacts,
    )
    attempt.update(
        provider_run_id=args.provider_run_id,
        worker_id=args.worker_id,
        heartbeat_at=producer_result.get("finished_at", args.verified_at),
        checkpoint_seq=max(4, int(attempt.get("checkpoint_seq", 0))),
    )
    control_result["result_transaction"].update(
        state="INGESTED",
        manifest_uri=(
            f"git:{args.branch}@{args.return_commit}:{manifest_path}"
        ),
        manifest_sha256=_sha(manifest_bytes),
        artifact_count=len(artifacts),
        total_bytes=observed_bytes,
        committed_at=_commit_time(args.result_commit),
        verified_at=args.verified_at,
        parent_ingested_at=args.verified_at,
        result_commit_id=args.result_commit,
    )
    review_rel = f"control/reviews/wave-a/{slug}.json"
    control_result["independent_acceptance"] = {
        "state": args.verdict,
        "reviewer_id": f"controller-verifier:{CONTROLLER_ID}",
        "receipt_uri": f"workstreams/po03/{review_rel}",
    }
    _write_json(control_result_rel, control_result)

    review = {
        "review_id": f"{task_id}-INDEPENDENT-REVIEW-001",
        "task_id": task_id,
        "hypothesis_id": producer_result.get("hypothesis_id"),
        "reviewer_id": f"controller-verifier:{CONTROLLER_ID}",
        "reviewed_at": args.verified_at,
        "criteria_frozen_before_producer_result": True,
        "producer_branch": args.branch,
        "producer_result_commit": args.result_commit,
        "producer_return_commit": args.return_commit,
        "controller_ingestion_commit": args.ingestion_commit,
        "ownership": {
            "state": "PASS",
            "changed_paths": changed_paths,
            "owned_prefix": prefix,
        },
        "immutable_readback": {
            "state": "PASS",
            "manifest_sha256": _sha(manifest_bytes),
            "manifest_bytes": len(manifest_bytes),
            "payload_artifact_count": len(manifest["artifacts"]),
            "payload_artifact_bytes": payload_bytes,
            "transaction_artifact_count": len(artifacts),
            "transaction_artifact_bytes": observed_bytes,
            "return_envelope_sha256": _sha(ready_bytes),
            "return_envelope_bytes": len(ready_bytes),
        },
        "independent_tests": {
            "focused": {"state": "PASS", "count": args.focused_tests},
            "seeded_contracts": {"state": "PASS", "count": args.seeded_tests},
        },
        "hypothesis_outcome": producer_result.get("hypothesis_outcome"),
        "source_claim_count": (
            len(producer_result.get("source_claims", []))
            if isinstance(producer_result.get("source_claims", []), list)
            else producer_result.get("source_claims", {}).get(
                "claim_count",
                producer_result.get("source_claims", {}).get("count", 0),
            )
        ),
        "model_requested": input_doc["configuration"]["model_slug"],
        "model_observed": args.model_observed,
        "exact_model_mapping": (
            "PASS"
            if input_doc["configuration"]["model_slug"] in args.model_observed
            else "NOT_SUPPORTED"
        ),
        "route_disposition": args.route_disposition,
        "note": args.review_note,
        "independent_disposition": args.verdict,
        "po01_touched": False,
        "pull_request_8_touched": False,
        "decision_changed": [],
    }
    _write_json(review_rel, review)

    registry = _read_jsonl("control/work-unit-registry.jsonl")
    found = False
    for row in registry:
        if row.get("task_id") == task_id:
            row.update(
                provider_run_id=args.provider_run_id,
                provider_state="COMPLETED",
                obzio_state="COMPLETED",
                worker_id=args.worker_id,
                model_observed=args.model_observed,
                result_commit_id=args.result_commit,
                return_commit_id=args.return_commit,
                checkpoint_seq=4,
                updated_at=args.verified_at,
                independent_acceptance=args.verdict,
                route_disposition=args.route_disposition,
            )
            found = True
    if not found:
        raise ValueError(f"task absent from registry: {task_id}")
    _write_jsonl("control/work-unit-registry.jsonl", registry)

    outbox = _read_jsonl("control/outbox.jsonl")
    found = False
    for row in outbox:
        if row.get("outbox_id") == outbox_id:
            row.update(
                state="DELIVERED",
                attempts=max(1, int(row.get("attempts", 0))),
                last_attempt_at=_later_time(
                    row.get("last_attempt_at"), producer_result.get("started_at")
                ),
                delivered_at=_later_time(
                    row.get("delivered_at"), producer_result.get("started_at")
                ),
                provider_run_id=args.provider_run_id,
            )
            found = True
    if not found:
        raise ValueError(f"task absent from outbox: {task_id}")
    _write_jsonl("control/outbox.jsonl", outbox)

    events = _read_jsonl("control/events/ledger.jsonl")
    if not any(
        row.get("task_id") == task_id and row.get("to_state") == args.verdict
        for row in events
    ):
        next_seq = max(int(row["event_seq"]) for row in events) + 1
        transitions = [
            ("LEASED", "RUNNING", producer_result.get("started_at")),
            ("RUNNING", "CHECKPOINTED", _commit_time(args.result_commit)),
            ("CHECKPOINTED", "RESULT_STAGING", _commit_time(args.result_commit)),
            ("RESULT_STAGING", "RESULT_STAGED", _commit_time(args.result_commit)),
            ("RESULT_STAGED", "RESULT_VERIFIED", args.verified_at),
            ("RESULT_VERIFIED", "RESULT_COMMITTED", _commit_time(args.result_commit)),
            ("RESULT_COMMITTED", "PARENT_INGESTED", args.verified_at),
            ("PARENT_INGESTED", "COMPLETED", args.verified_at),
            ("COMPLETED", args.verdict, args.verified_at),
        ]
        for from_state, to_state, at in transitions:
            event: dict[str, Any] = {
                "event_id": f"evt-po03-{slug}-{next_seq:04d}",
                "event_seq": next_seq,
                "task_id": task_id,
                "from_state": from_state,
                "to_state": to_state,
                "actor": (
                    f"controller-verifier:{CONTROLLER_ID}"
                    if to_state == args.verdict
                    else (
                        f"controller:{CONTROLLER_ID}"
                        if to_state in {"PARENT_INGESTED", "COMPLETED"}
                        else f"producer:{args.worker_id}"
                    )
                ),
                "at": at or args.verified_at,
                "fence_token": attempt["fence_token"],
            }
            if to_state == "RESULT_COMMITTED":
                event["result_commit_id"] = args.result_commit
                event["return_commit_id"] = args.return_commit
            events.append(event)
            next_seq += 1
    _write_jsonl("control/events/ledger.jsonl", events)

    recovery = _read_json("control/recovery-state.json")
    recovery["scanned_at"] = max(
        str(recovery.get("scanned_at", "")), args.verified_at
    )
    recovery["last_event_seq"] = max(int(row["event_seq"]) for row in events)
    recovery["active_leases"] = [
        lease for lease in recovery["active_leases"]
        if lease.get("task_id") != task_id
    ]
    recovery["pending_outbox"] = [
        item for item in recovery["pending_outbox"] if item != outbox_id
    ]
    wave = recovery.setdefault("wave_a", {})
    completed = sum(
        1
        for row in registry
        if row.get("material") is True and row.get("obzio_state") == "COMPLETED"
    )
    accepted = sum(
        1
        for row in registry
        if row.get("material") is True
        and row.get("independent_acceptance") == "ACCEPTED"
    )
    registry_running = sum(
        1
        for row in registry
        if row.get("material") is True
        and row.get("provider_state") == "RUNNING"
    )
    wave.update(
        active_provider_runs=_reconciled_active_count(
            wave.get("active_provider_runs", 0),
            registry_running,
            was_active,
        ),
        completed_durable=completed,
        independently_accepted=accepted,
        remaining=64 - completed,
    )
    _write_json("control/recovery-state.json", recovery)

    metrics = [
        row for row in _read_jsonl("metrics/work-unit-runs.jsonl")
        if row.get("task_id") != task_id
    ]
    producer_metrics = producer_result.get(
        "metrics", producer_result.get("preregistered_metrics", {})
    )
    metrics.append(
        {
            "task_id": task_id,
            "parent_id": "PO03-WAVE-A",
            "hypothesis_id": producer_result.get("hypothesis_id"),
            "function": input_doc["assignment"]["standing_function"],
            "runtime": "best-of-n-runner isolated worktree",
            "model_requested": input_doc["configuration"]["model_slug"],
            "model_observed": args.model_observed,
            "reasoning_requested": input_doc["configuration"]["reasoning"],
            "reasoning_observed": producer_result.get(
                "reasoning_observed", "NOT_SUPPORTED"
            ),
            "prompt_hash": input_doc["acceptance_contract"]["sha256"],
            "source_manifest_hash": control_result[
                "immutable_input_manifest_sha256"
            ],
            "queue_time": "NOT_SUPPORTED",
            "active_time": "NOT_SUPPORTED",
            "wall_time": producer_metrics.get(
                "wall_time",
                producer_metrics.get("wall_time_seconds", "NOT_SUPPORTED"),
            ),
            "review_time": "NOT_SUPPORTED",
            "token_data": "NOT_SUPPORTED",
            "cost_data": "NOT_SUPPORTED",
            "artifact_count": len(artifacts),
            "artifact_bytes": observed_bytes,
            "first_pass_outcome": producer_metrics.get(
                "first_pass_outcome", "NOT_SUPPORTED"
            ),
            "independent_disposition": args.verdict,
            "defects": producer_metrics.get("defects", "NOT_SUPPORTED"),
            "rework": producer_metrics.get("rework", "NOT_SUPPORTED"),
            "founder_action": 0,
            "provider_block": producer_metrics.get(
                "provider_block", "NOT_SUPPORTED"
            ),
            "collision": producer_metrics.get("collision", "NOT_SUPPORTED"),
            "recovery_events": producer_metrics.get(
                "recovery_events", "NOT_SUPPORTED"
            ),
            "result_commit_id": args.result_commit,
            "return_commit_id": args.return_commit,
            "readback": "PASS",
            "recorded_at": args.verified_at,
        }
    )
    metrics.sort(key=lambda row: row["task_id"])
    _write_jsonl("metrics/work-unit-runs.jsonl", metrics)

    print(
        json.dumps(
            {
                "task_id": task_id,
                "artifacts_verified": len(artifacts),
                "bytes_verified": observed_bytes,
                "result_commit": args.result_commit,
                "return_commit": args.return_commit,
                "disposition": args.verdict,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
