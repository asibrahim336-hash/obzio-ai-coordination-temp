#!/usr/bin/env python3
"""a7-u02: emit one ledger-derived measurement row per counted work unit.

Every field in the emitted rows is derived from the append-only ledger
(``workstreams/po03/control/events/ledger.jsonl``), the immutable dispatch
records, ``wave-a-spec.json`` and ``path-ownership.json``. No field is
self-reported by a worker. Regenerating this file against an unchanged
ledger must produce byte-identical output except for the single
``generated_at`` timestamp in the leading metadata row, per
``workstreams/po03/metrics/metric-definitions.json``.

Dependency-free standard-library Python 3.12, run as
``python3 emit_runs.py --root <repo-root> --out <path>``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


TERMINAL_EVENTS = {
    "RESULT_COMMITTED",
    "PARENT_INGESTED",
    "COMPLETED",
    "FAILED_TERMINAL",
    "CANCELLED",
    "PROVIDER_COMPLETED_UNCOMMITTED",
}
COMMITTED_EVENTS = {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"}


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_ts(value: str | None):
    if not value:
        return None
    from datetime import datetime, timezone

    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def seconds_between(start: str | None, end: str | None):
    a, b = parse_ts(start), parse_ts(end)
    if a is None or b is None:
        return None
    return (b - a).total_seconds()


def build_row(
    unit_id: str,
    unit_spec: dict[str, Any],
    dispatch: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    owner_branch: dict[str, str],
    function_descriptions: dict[str, str],
) -> dict[str, Any]:
    created_ts = None
    leased_events: list[dict[str, Any]] = []
    terminal_event = None
    terminal_ts = None
    review_event = None
    checkpoint_seq = 0
    retry_count = 0
    rejected_count = 0
    founder_rows: list[dict[str, Any]] = []
    provider_block_rows: list[dict[str, Any]] = []
    recovery_rows: list[dict[str, Any]] = []
    fence_token = 0
    obzio_state = "CREATED"
    provider_state = "UNKNOWN"
    last_event_seq = None
    last_event_ts = None
    result_commit_id = None
    result_locator = None
    artifact_count = 0
    total_bytes = 0
    disposition = "NOT_TESTED"
    disposition_event = None
    first_leased_seen_before_terminal_retry_free = True
    seen_retry_or_fence_reject_before_terminal = False

    for row in rows:
        event = row["event"]
        last_event_seq = row["seq"]
        last_event_ts = row["ts"]
        if row.get("fence_token") is not None:
            fence_token = max(fence_token, int(row["fence_token"]))
        if row.get("provider_state"):
            provider_state = row["provider_state"]
        payload = row.get("payload") or {}

        if event == "CREATED" and created_ts is None:
            created_ts = row["ts"]
        if event == "LEASED":
            leased_events.append(row)
        if event == "CHECKPOINTED":
            checkpoint_seq = max(checkpoint_seq, int(payload.get("checkpoint_seq", 0)))
        if event == "RETRY_SCHEDULED":
            retry_count += 1
            if terminal_event is None:
                seen_retry_or_fence_reject_before_terminal = True
        if event == "FENCE_REJECTED":
            provider_block_rows.append(row)
            if terminal_event is None:
                seen_retry_or_fence_reject_before_terminal = True
        if event == "LEASE_EXPIRED":
            provider_block_rows.append(row)
            recovery_rows.append(row)
        if event in {"RECOVERY_REQUIRED", "DUPLICATE_IGNORED", "FAULT_INJECTED"}:
            recovery_rows.append(row)
        if event in COMMITTED_EVENTS:
            result_commit_id = payload.get("result_commit_id") or result_commit_id
            result_locator = payload.get("result_locator") or result_locator
            artifact_count = payload.get("artifact_count", artifact_count)
            total_bytes = payload.get("total_bytes", total_bytes)
        if event in TERMINAL_EVENTS and terminal_event is None:
            terminal_event = event
            terminal_ts = row["ts"]
        if event in {"ACCEPTED", "REJECTED"}:
            disposition = event
            disposition_event = row
            if event == "REJECTED":
                rejected_count += 1
        if str(row.get("actor", "")).lower() == "founder":
            founder_rows.append(row)
        if event in EVENT_KIND_ALLOWLIST:
            obzio_state = row.get("obzio_state") or event

    queue_time = seconds_between(created_ts, leased_events[0]["ts"]) if leased_events else None
    active_time = None
    if leased_events and terminal_ts:
        active_time = seconds_between(leased_events[-1]["ts"], terminal_ts)
    wall_time = seconds_between(created_ts, terminal_ts) if terminal_ts else None
    review_time = None
    if disposition_event is not None:
        completed_rows = [r for r in rows if r["event"] == "COMPLETED"]
        if completed_rows:
            review_time = seconds_between(completed_rows[-1]["ts"], disposition_event["ts"])

    if terminal_event is None:
        first_pass_outcome = "NOT_YET_TERMINAL"
    elif terminal_event in COMMITTED_EVENTS and fence_token == 1 and not seen_retry_or_fence_reject_before_terminal:
        first_pass_outcome = "PASS"
    else:
        first_pass_outcome = "FAIL"

    model = dispatch["model"] if dispatch else unit_spec.get("model")
    owner = dispatch["owner"] if dispatch else unit_spec.get("owner")
    function_id = dispatch["function_id"] if dispatch else unit_spec.get("function_id")
    cohort_id = dispatch["cohort_id"] if dispatch else unit_spec.get("cohort_id")
    commission_id = dispatch["commission_id"] if dispatch else unit_spec.get("commission_id")
    immutable_input_manifest_sha256 = (
        dispatch["immutable_input_manifest_sha256"] if dispatch else None
    )
    acceptance_contract_sha256 = dispatch["acceptance_contract_sha256"] if dispatch else None
    source_hashes = dispatch.get("source_hashes") if dispatch else None

    return {
        "record_type": "unit_run",
        "unit_id": unit_id,
        "commission_id": commission_id,
        "cohort_id": cohort_id,
        "function_id": function_id,
        "function_description": function_descriptions.get(function_id),
        "owner": owner,
        "exact_model_and_reasoning": model,
        "runtime": {"provider": "Cursor Cloud", "branch": owner_branch.get(owner)},
        "hashes": {
            "immutable_input_manifest_sha256": immutable_input_manifest_sha256,
            "acceptance_contract_sha256": acceptance_contract_sha256,
            "source_hashes": source_hashes,
        },
        "token_and_cost_data": "NOT_SUPPORTED",
        "timestamps": {
            "created_at": created_ts,
            "first_leased_at": leased_events[0]["ts"] if leased_events else None,
            "last_leased_at": leased_events[-1]["ts"] if leased_events else None,
            "terminal_at": terminal_ts,
            "terminal_event": terminal_event,
        },
        "queue_time_seconds": queue_time,
        "active_time_seconds": active_time,
        "wall_time_seconds": wall_time,
        "review_time_seconds": review_time,
        "tools_and_effects": {
            "artifact_count": artifact_count,
            "total_bytes": total_bytes,
            "result_locator": result_locator,
        },
        "checkpoints": checkpoint_seq,
        "retries": retry_count,
        "result_commit_and_readback": {
            "result_commit_id": result_commit_id,
            "result_locator": result_locator,
            "readback_proved": any(r["event"] == "PARENT_INGESTED" for r in rows),
        },
        "first_pass_outcome": first_pass_outcome,
        "independent_disposition": disposition,
        "defects_and_rework": {"rejected_count": rejected_count, "retry_count": retry_count},
        "founder_action": (
            "NONE_OBSERVED"
            if not founder_rows
            else [{"seq": r["seq"], "ts": r["ts"], "event": r["event"]} for r in founder_rows]
        ),
        "provider_block": [
            {"seq": r["seq"], "ts": r["ts"], "event": r["event"], "payload": r.get("payload") or {}}
            for r in provider_block_rows
        ],
        "collision_events": [
            {"seq": r["seq"], "ts": r["ts"], "event": r["event"], "payload": r.get("payload") or {}}
            for r in rows
            if r["event"] == "FENCE_REJECTED"
        ],
        "recovery_events": [
            {"seq": r["seq"], "ts": r["ts"], "event": r["event"], "payload": r.get("payload") or {}}
            for r in recovery_rows
        ],
        "current_obzio_state": obzio_state,
        "current_provider_state": provider_state,
        "current_fence_token": fence_token,
        "last_event_seq": last_event_seq,
        "last_event_ts": last_event_ts,
        "attempts": len(leased_events),
    }


EVENT_KIND_ALLOWLIST = {
    "CREATED",
    "LEASED",
    "RUNNING",
    "CHECKPOINTED",
    "RESULT_STAGING",
    "RESULT_STAGED",
    "RESULT_VERIFIED",
    "RESULT_COMMITTED",
    "PARENT_INGESTED",
    "COMPLETED",
    "PROVIDER_COMPLETED_UNCOMMITTED",
    "RECOVERY_REQUIRED",
    "RETRY_SCHEDULED",
    "FAILED_TERMINAL",
    "CANCELLED",
    "LEASE_EXPIRED",
}


def load_dispatch_records(po03_control_root: Path) -> dict[str, dict[str, Any]]:
    dispatch_dir = po03_control_root / "dispatch"
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(dispatch_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        records[doc["unit_id"]] = doc
    return records


def emit(root: Path, out_path: Path, generated_at: str) -> tuple[list[str], dict[str, Any]]:
    control_plane = _load_module(root / "workstreams/po03/tools/control_plane.py", "control_plane_ro")
    rows = control_plane.ledger_rows()
    chain_errors = control_plane.verify_chain(rows)
    if chain_errors:
        raise SystemExit("ledger chain invalid: " + "; ".join(chain_errors))

    wave_spec = json.loads((root / "workstreams/po03/control/wave-a-spec.json").read_text(encoding="utf-8"))
    path_ownership = json.loads((root / "workstreams/po03/control/path-ownership.json").read_text(encoding="utf-8"))
    dispatch_records = load_dispatch_records(root / "workstreams/po03/control")

    function_descriptions = wave_spec.get("functions", {})
    owner_branch = {
        owner: entry.get("branch") for owner, entry in path_ownership.get("owners", {}).items()
    }

    rows_by_unit: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_unit.setdefault(row["unit_id"], []).append(row)

    unit_specs = {unit["unit_id"]: unit for unit in wave_spec["units"]}
    all_unit_ids = sorted(set(unit_specs) | set(dispatch_records) | set(rows_by_unit))

    lines: list[str] = []
    meta = {
        "record_type": "generation_metadata",
        "generated_at": generated_at,
        "ledger_head_sha256": rows[-1]["row_sha256"] if rows else ("0" * 64),
        "ledger_rows": len(rows),
        "declared_units": wave_spec.get("declared_units"),
        "minimum_required_units": wave_spec.get("minimum_required_units"),
        "counted_unit_count": len(all_unit_ids),
        "spec_id": wave_spec.get("spec_id"),
        "generator": "workstreams/po03/metrics/emit_runs.py",
    }
    lines.append(canonical(meta))

    for unit_id in all_unit_ids:
        row = build_row(
            unit_id,
            unit_specs.get(unit_id, {}),
            dispatch_records.get(unit_id),
            rows_by_unit.get(unit_id, []),
            owner_branch,
            function_descriptions,
        )
        lines.append(canonical(row))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines, meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="workstreams/po03/metrics/work-unit-runs.jsonl")
    parser.add_argument(
        "--generated-at",
        default=None,
        help="Override the generation timestamp (for deterministic tests); defaults to current UTC time.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out_path = root / args.out if not Path(args.out).is_absolute() else Path(args.out)

    if args.generated_at:
        generated_at = args.generated_at
    else:
        from datetime import datetime, timezone

        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines, meta = emit(root, out_path, generated_at)
    print(
        canonical(
            {
                "wrote": str(out_path),
                "rows": len(lines) - 1,
                "ledger_head_sha256": meta["ledger_head_sha256"],
                "ledger_rows": meta["ledger_rows"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
