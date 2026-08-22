#!/usr/bin/env python3
"""Derive sanitized queue/verification parameters from repository-native PO-03 evidence.

The calibrator reads only committed control and metrics files at one immutable
commit through ``git show``, so it never depends on a warm working tree. It emits
numeric aggregates and repository-native task identifiers only: no narrative
text, no provider identifiers, no model names, no environment values.

Usage:
    calibrate_from_repository.py --commit <sha> [--repo <path>] [--out <file>]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import statistics
import subprocess
from pathlib import Path
from typing import Any

CAPSULE_VERSION = "OBZIO-WA-018-CALIBRATION-CAPSULE-v1"

LEDGER = "workstreams/po03/control/events/ledger.jsonl"
REGISTRY = "workstreams/po03/control/work-unit-registry.jsonl"
RUNS = "workstreams/po03/metrics/work-unit-runs.jsonl"
RECOVERY = "workstreams/po03/control/recovery-state.json"

PRODUCER_STATES = ("RUNNING", "CHECKPOINTED", "RESULT_COMMITTED")
TERMINAL_STATES = ("PARENT_INGESTED", "COMPLETED", "ACCEPTED", "REJECTED")
FAULT_STATES = ("RECOVERY_REQUIRED", "RETRY_SCHEDULED")
MATERIAL_PREFIX = "PO03-WA-0"


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def _blob(repo: Path, commit: str, path: str) -> bytes:
    return _git(repo, "show", "--no-textconv", f"{commit}:{path}")


def _jsonl(data: bytes) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in data.decode("utf-8").splitlines()
        if line.strip()
    ]


def _seconds(start: str, end: str) -> int:
    a = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
    b = dt.datetime.fromisoformat(end.replace("Z", "+00:00"))
    return int(round((b - a).total_seconds()))


def _is_material(task_id: str) -> bool:
    return task_id.startswith(MATERIAL_PREFIX)


def _unit_timeline(events: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Collapse the append-only ledger into one timeline per task.

    The earliest RUNNING is kept because a duplicate producer callback replays
    the same transition; every later state keeps its latest timestamp because
    the controller may re-ingest idempotently.
    """
    timeline: dict[str, dict[str, str]] = {}
    for event in events:
        task_id = event.get("task_id")
        to_state = event.get("to_state")
        at = event.get("at")
        if not task_id or not to_state or not at:
            continue
        slot = timeline.setdefault(task_id, {})
        if to_state == "RUNNING":
            slot.setdefault(to_state, at)
        else:
            slot[to_state] = at
    return timeline


def _distribution(samples: list[int]) -> dict[str, Any]:
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "min": ordered[0],
        "p25": ordered[max(0, (len(ordered) - 1) // 4)],
        "median": int(round(statistics.median(ordered))),
        "p75": ordered[min(len(ordered) - 1, (3 * (len(ordered) - 1)) // 4)],
        "max": ordered[-1],
        "mean": round(statistics.fmean(ordered), 3),
        "samples": ordered,
    }


def _numeric(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        for key in ("value", "in_own_work_found_and_repaired", "cycles"):
            inner = value.get(key)
            if isinstance(inner, int) and not isinstance(inner, bool):
                return inner
    return None


def build_capsule(repo: Path, commit: str) -> dict[str, Any]:
    resolved = _git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()
    sources: dict[str, dict[str, Any]] = {}
    blobs: dict[str, bytes] = {}
    for path in (LEDGER, REGISTRY, RUNS, RECOVERY):
        data = _blob(repo, resolved, path)
        blobs[path] = data
        sources[path] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }

    events = _jsonl(blobs[LEDGER])
    registry = _jsonl(blobs[REGISTRY])
    runs = _jsonl(blobs[RUNS])
    recovery = json.loads(blobs[RECOVERY].decode("utf-8"))

    timeline = _unit_timeline(events)

    produce_seconds: list[int] = []
    commit_to_ingest_seconds: list[int] = []
    per_unit: list[dict[str, Any]] = []
    verifier_decision_times: list[str] = []
    rejected = 0
    accepted = 0

    for task_id in sorted(timeline):
        slot = timeline[task_id]
        if "CHECKPOINTED" not in slot or "RUNNING" not in slot:
            continue
        produce = _seconds(slot["RUNNING"], slot["CHECKPOINTED"])
        ingest = None
        if "RESULT_COMMITTED" in slot and "PARENT_INGESTED" in slot:
            ingest = _seconds(slot["RESULT_COMMITTED"], slot["PARENT_INGESTED"])
        verdict = "ACCEPTED" if "ACCEPTED" in slot else (
            "REJECTED" if "REJECTED" in slot else "NONE"
        )
        if verdict == "ACCEPTED":
            accepted += 1
            verifier_decision_times.append(slot["ACCEPTED"])
        elif verdict == "REJECTED":
            rejected += 1
            verifier_decision_times.append(slot["REJECTED"])
        material = _is_material(task_id)
        if material and produce > 0:
            produce_seconds.append(produce)
        if material and ingest is not None and ingest > 0:
            commit_to_ingest_seconds.append(ingest)
        per_unit.append(
            {
                "task_id": task_id,
                "material": material,
                "produce_seconds": produce,
                "commit_to_ingest_seconds": ingest,
                "verifier_verdict": verdict,
            }
        )

    verifier_actors = sorted(
        {
            event["actor"]
            for event in events
            if str(event.get("actor", "")).startswith("controller-verifier")
        }
    )
    decision_times = sorted(
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        for value in verifier_decision_times
    )
    inter_decision = [
        int(round((b - a).total_seconds()))
        for a, b in zip(decision_times, decision_times[1:])
    ]

    fault_events = [
        {
            "task_id": event.get("task_id"),
            "to_state": event.get("to_state"),
            "remote_branch_readback": event.get("remote_branch_readback"),
            "has_result_commit": bool(event.get("result_commit_id")),
        }
        for event in events
        if event.get("to_state") in FAULT_STATES
    ]

    first_pass_pass = 0
    first_pass_fail = 0
    producer_self_defects: list[int] = []
    producer_rework: list[int] = []
    escaped_declared: list[int] = []
    for row in runs:
        outcome = str(row.get("first_pass_outcome", ""))
        if outcome == "PASS":
            first_pass_pass += 1
        elif outcome.startswith("FAIL"):
            first_pass_fail += 1
        defects = _numeric(row.get("defects"))
        if defects is not None:
            producer_self_defects.append(defects)
        rework = _numeric(row.get("rework"))
        if rework is not None:
            producer_rework.append(rework)
        if isinstance(row.get("defects"), dict) and "escaped" in row["defects"]:
            escaped = _numeric(row["defects"].get("escaped"))
            if escaped is not None:
                escaped_declared.append(escaped)

    material_registry = [row for row in registry if row.get("material") is True]
    wave = recovery.get("wave_a", {})

    verifier_decisions = accepted + rejected
    capsule: dict[str, Any] = {
        "capsule_version": CAPSULE_VERSION,
        "task_id": "PO03-WA-018",
        "immutable_commit": resolved,
        "sanitization": {
            "included": [
                "integer durations derived from ledger timestamps",
                "repository-native task identifiers",
                "integer counts and enumerated state names",
            ],
            "excluded": [
                "narrative fields",
                "provider run identifiers and URLs",
                "model and reasoning identifiers",
                "environment variables, paths and secrets",
            ],
            "secret_material": "NONE_READ",
        },
        "sources": sources,
        "observed": {
            "producer_concurrency_ceiling": wave.get("observed_provider_concurrency"),
            "active_provider_runs_at_snapshot": wave.get("active_provider_runs"),
            "registered_material_units": wave.get("registered"),
            "completed_durable": wave.get("completed_durable"),
            "independently_accepted": wave.get("independently_accepted"),
            "registry_material_rows": len(material_registry),
            "distinct_verifier_actors": len(verifier_actors),
            "verifier_decisions": verifier_decisions,
            "verifier_accepted": accepted,
            "verifier_rejected": rejected,
            "verifier_rejection_fraction": (
                round(rejected / verifier_decisions, 6) if verifier_decisions else None
            ),
            "producer_first_pass_pass": first_pass_pass,
            "producer_first_pass_fail": first_pass_fail,
            "producer_self_detected_defects_total": sum(producer_self_defects),
            "producer_rework_cycles_total": sum(producer_rework),
            "producer_declared_escaped_defects": escaped_declared,
            "controller_fault_events": len(fault_events),
            "controller_fault_detail": fault_events,
        },
        "distributions": {
            "producer_produce_seconds": _distribution(produce_seconds),
            "verifier_commit_to_ingest_seconds": _distribution(
                commit_to_ingest_seconds
            ),
            "verifier_inter_decision_seconds": _distribution(inter_decision)
            if inter_decision
            else None,
        },
        "per_unit": per_unit,
        "derived": _derived(
            produce_seconds, commit_to_ingest_seconds, rejected, verifier_decisions
        ),
        "limitations": [
            "commit_to_ingest_seconds bounds verification service time from above "
            "because it contains any queue wait at the single controller verifier; "
            "pure service time is not separately observable in the ledger and is "
            "recorded as NOT_SEPARATELY_OBSERVABLE.",
            "Ledger timestamps are second-resolution and some producer transitions "
            "were recorded at minute precision, so short durations carry up to "
            "60 seconds of quantisation error.",
            "Twelve material units plus two canaries is a small sample; the "
            "empirical distributions are used as a bootstrap population and not "
            "as a fitted parametric law.",
            "The verifier rejection fraction is a single observed rejection over "
            "all verifier decisions and is therefore a coarse point estimate with "
            "a wide interval; the simulation sweeps it rather than trusting it.",
        ],
    }
    return capsule


def _derived(
    produce_seconds: list[int],
    commit_to_ingest_seconds: list[int],
    rejected: int,
    verifier_decisions: int,
) -> dict[str, Any]:
    mean_produce = statistics.fmean(produce_seconds) if produce_seconds else None
    mean_verify = (
        statistics.fmean(commit_to_ingest_seconds) if commit_to_ingest_seconds else None
    )
    derived: dict[str, Any] = {
        "mean_produce_seconds": round(mean_produce, 3) if mean_produce else None,
        "mean_verify_upper_bound_seconds": (
            round(mean_verify, 3) if mean_verify else None
        ),
        "verify_service_floor_seconds": (
            min(commit_to_ingest_seconds) if commit_to_ingest_seconds else None
        ),
        "verify_service_time_status": "NOT_SEPARATELY_OBSERVABLE",
    }
    if mean_produce and mean_verify:
        derived["producer_units_per_hour_per_slot"] = round(3600.0 / mean_produce, 4)
        derived["verifier_units_per_hour_per_slot"] = round(3600.0 / mean_verify, 4)
        derived["balanced_producer_slots_per_verifier_slot"] = round(
            mean_produce / mean_verify, 4
        )
    if verifier_decisions:
        derived["latent_defect_point_estimate"] = round(
            rejected / verifier_decisions, 6
        )
    return derived


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--out", default="-")
    args = parser.parse_args()
    capsule = build_capsule(Path(args.repo).resolve(), args.commit)
    payload = json.dumps(capsule, indent=2, sort_keys=True) + "\n"
    if args.out == "-":
        print(payload, end="")
    else:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(
            json.dumps(
                {
                    "wrote": args.out,
                    "bytes": len(payload.encode("utf-8")),
                    "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
