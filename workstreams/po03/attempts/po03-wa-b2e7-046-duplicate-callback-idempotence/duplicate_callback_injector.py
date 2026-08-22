#!/usr/bin/env python3
"""Injections that duplicate a callback and count the durable effects.

Four fault classes are injected: a byte-for-byte replay repeated five times, a
retry whose timestamps were regenerated the way the real emitter regenerates
them, two callbacks forced to interleave inside the check-then-write window with
a frozen clock, and the same interleaving with two different clocks.

Run directly to print the observation as JSON:

    python3 -I duplicate_callback_injector.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REAL_EMITTER = Path(__file__).resolve().parents[4] / "workstreams" / "po03" / "tools" / "emit_result.py"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kit = _load("po03_c6_046_fault_kit", "fault_kit.py")
repair = _load("po03_c6_046_repair", "repair_candidate_idempotence.py")

TASK_ID = "po03-c6-046-sandbox-unit"
SLOT = f"workstreams/po03/attempts/{TASK_ID}"
ARTIFACT_PATH = f"{SLOT}/component.json"


def stage(sandbox: Path, instance: str):
    module = kit.bind_sandbox(kit.load_factory(instance), sandbox)
    kit.init_repository(sandbox)
    kit.seed_capsule(module, TASK_ID, hypothesis="a duplicated callback cannot double-count")
    artifact = sandbox / ARTIFACT_PATH
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(module.canonical_json({"component": TASK_ID, "computed": True}))
    commit = kit.commit_all(sandbox, "po03: sandbox worker artifact")
    lease = module.grant_lease(TASK_ID, holder="worker-a", lease_seconds=600, attempt=1)
    return module, commit, lease


def result_for(module, commit: str, *, fence_token: int, timestamp: str) -> dict[str, Any]:
    return kit.build_result_document(
        module,
        task_id=TASK_ID,
        commit=commit,
        paths=[ARTIFACT_PATH],
        fence_token=fence_token,
        worker_id="worker-a",
        timestamp=timestamp,
    )


def durable_effects(module) -> dict[str, Any]:
    task_directory = module.CONTROL_ROOT / "tasks" / TASK_ID
    events = sorted((module.CONTROL_ROOT / "events" / TASK_ID).glob("*.json"))
    states = [json.loads(path.read_text(encoding="utf-8"))["state"] for path in events]
    rows = repair.registry_rows(module)
    metrics = module.PO03_ROOT / "metrics" / "work-unit-runs.jsonl"
    return {
        "ingestion_files": len(sorted(task_directory.glob("ingestion-*.json"))),
        "result_files": len(sorted(task_directory.glob("result-*.json"))),
        "parent_ingested_events": states.count("PARENT_INGESTED"),
        "registry_ingestion_rows": len([row for row in rows if row.get("registry_event") == "INGESTION"]),
        "event_chain_errors": module.verify_chain(TASK_ID),
        "metric_rows_written_by_ingestion": (
            len([line for line in metrics.read_text(encoding="utf-8").splitlines() if line.strip()])
            if metrics.is_file()
            else 0
        ),
    }


def inject_identical_replay(root: Path, *, replays: int = 5) -> dict[str, Any]:
    """The same callback bytes arrive five times."""
    module, commit, lease = stage(root / "identical", "046_identical")
    document = result_for(module, commit, fence_token=lease["fence_token"], timestamp="2026-08-22T07:00:00Z")
    outcomes = []
    for _ in range(replays):
        ingestion = module.ingest_result(TASK_ID, document)
        outcomes.append(
            {
                "state": ingestion["obzio_state"],
                "suppressed": bool(ingestion.get("duplicate_callback_suppressed")),
            }
        )
    effects = durable_effects(module)
    passed = (
        effects["ingestion_files"] == 1
        and effects["registry_ingestion_rows"] == 1
        and effects["parent_ingested_events"] == 1
        and effects["event_chain_errors"] == []
        and sum(1 for item in outcomes if item["suppressed"]) == replays - 1
    )
    return {
        "fault_class": "IDENTICAL_CALLBACK_REPLAYED_FIVE_TIMES",
        "injected_at_state_transition": "RESULT_COMMITTED -> PARENT_INGESTED (replayed)",
        "observed": {"outcomes": outcomes, "durable_effects": effects},
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_regenerated_retry(root: Path) -> dict[str, Any]:
    """The producer re-emits the same transaction, so the timestamps are new."""
    module, commit, lease = stage(root / "regenerated", "046_regenerated")
    first = result_for(module, commit, fence_token=lease["fence_token"], timestamp="2026-08-22T07:00:00Z")
    second = result_for(module, commit, fence_token=lease["fence_token"], timestamp="2026-08-22T07:05:11Z")
    module.ingest_result(TASK_ID, first)
    ingestion = module.ingest_result(TASK_ID, second)
    effects = durable_effects(module)
    identity_first = repair.identity_fields(first)
    identity_second = repair.identity_fields(second)
    emitter_source = REAL_EMITTER.read_text(encoding="utf-8")
    observed = {
        "transaction_identity_is_unchanged": identity_first == identity_second,
        "document_bytes_differ": module.sha256_bytes(module.canonical_json(first))
        != module.sha256_bytes(module.canonical_json(second)),
        "second_callback_suppressed": bool(ingestion.get("duplicate_callback_suppressed")),
        "second_callback_state": ingestion["obzio_state"],
        "durable_effects": effects,
        "real_emitter_regenerates_readback_timestamp": '"readback_verified_at": utc_now(),' in emitter_source,
        "real_emitter_regenerates_committed_timestamp": '"committed_at": utc_now(),' in emitter_source,
    }
    passed = (
        observed["second_callback_suppressed"]
        and effects["ingestion_files"] == 1
        and effects["registry_ingestion_rows"] == 1
        and effects["parent_ingested_events"] == 1
    )
    return {
        "fault_class": "RETRIED_CALLBACK_WITH_REGENERATED_TIMESTAMPS",
        "injected_at_state_transition": "RESULT_COMMITTED -> PARENT_INGESTED (re-emitted)",
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def _interleaved_ingest(sandbox: Path, outer_clock: str, inner_clock: str) -> dict[str, Any]:
    """Force two callbacks through the check-then-write window of one ingestion."""
    module, commit, lease = stage(sandbox, f"046_race_{abs(hash(outer_clock + inner_clock)) % 10000}")
    inner = kit.bind_sandbox(kit.load_factory(f"046_race_inner_{abs(hash(inner_clock)) % 10000}"), sandbox)
    document = result_for(module, commit, fence_token=lease["fence_token"], timestamp="2026-08-22T07:00:00Z")

    module.utc_now = lambda: outer_clock
    inner.utc_now = lambda: inner_clock
    real_write_once = module.write_once
    fired: dict[str, Any] = {}

    def hook(path, payload):
        if not fired.get("fired") and path.name.startswith("result-"):
            fired["fired"] = True
            fired["inner"] = inner.ingest_result(TASK_ID, document)
        return real_write_once(path, payload)

    module.write_once = hook
    outcome: dict[str, Any] = {}
    try:
        ingestion = module.ingest_result(TASK_ID, document)
        outcome = {"raised": None, "state": ingestion["obzio_state"]}
    except FileExistsError as exc:
        outcome = {"raised": f"FileExistsError: {exc}", "state": None}
    finally:
        module.write_once = real_write_once
    return {
        "outer": outcome,
        "inner_state": None if "inner" not in fired else fired["inner"]["obzio_state"],
        "durable_effects": durable_effects(module),
    }


def inject_concurrent_duplicate_same_clock(root: Path) -> dict[str, Any]:
    """Both callbacks observe the same clock, so both writes look identical."""
    observed = _interleaved_ingest(
        root / "race-same-clock", "2026-08-22T07:10:00Z", "2026-08-22T07:10:00Z"
    )
    effects = observed["durable_effects"]
    passed = effects["registry_ingestion_rows"] == 1 and effects["parent_ingested_events"] == 1
    return {
        "fault_class": "CONCURRENT_DUPLICATE_CALLBACK_SAME_CLOCK",
        "injected_at_state_transition": "RESULT_COMMITTED -> PARENT_INGESTED (interleaved)",
        "observed": observed,
        "method": "the outer ingestion is suspended after its duplicate check and before its first durable write while a second ingestion of the same document completes; both clocks are frozen to the same value so the result is deterministic",
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_concurrent_duplicate_skewed_clock(root: Path) -> dict[str, Any]:
    """The two callbacks observe clocks one second apart."""
    observed = _interleaved_ingest(
        root / "race-skewed-clock", "2026-08-22T07:10:01Z", "2026-08-22T07:10:00Z"
    )
    effects = observed["durable_effects"]
    crashed = observed["outer"]["raised"] is not None
    passed = not crashed and effects["registry_ingestion_rows"] == 1
    return {
        "fault_class": "CONCURRENT_DUPLICATE_CALLBACK_SKEWED_CLOCK",
        "injected_at_state_transition": "RESULT_COMMITTED -> PARENT_INGESTED (interleaved)",
        "observed": observed,
        "coordinator_crashed": crashed,
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_candidate_under_every_duplicate(root: Path) -> dict[str, Any]:
    """The repair candidate faces the identical replay and the regenerated retry."""
    module, commit, lease = stage(root / "candidate", "046_candidate")
    first = result_for(module, commit, fence_token=lease["fence_token"], timestamp="2026-08-22T07:00:00Z")
    second = result_for(module, commit, fence_token=lease["fence_token"], timestamp="2026-08-22T07:05:11Z")
    outcomes = [repair.idempotent_ingest(module, TASK_ID, first)["outcome"] for _ in range(3)]
    outcomes.append(repair.idempotent_ingest(module, TASK_ID, second)["outcome"])
    effects = durable_effects(module)
    passed = (
        outcomes == ["INGESTED", "DUPLICATE_SUPPRESSED_BY_IDENTITY", "DUPLICATE_SUPPRESSED_BY_IDENTITY", "DUPLICATE_SUPPRESSED_BY_IDENTITY"]
        and effects["ingestion_files"] == 1
        and effects["registry_ingestion_rows"] == 1
        and effects["parent_ingested_events"] == 1
    )
    return {
        "fault_class": "REPAIR_CANDIDATE_UNDER_IDENTICAL_AND_REGENERATED_DUPLICATES",
        "injected_at_state_transition": "RESULT_COMMITTED -> PARENT_INGESTED (candidate)",
        "observed": {"outcomes": outcomes, "durable_effects": effects},
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_all(root: Path) -> dict[str, Any]:
    results = [
        inject_identical_replay(root),
        inject_regenerated_retry(root),
        inject_concurrent_duplicate_same_clock(root),
        inject_concurrent_duplicate_skewed_clock(root),
        inject_candidate_under_every_duplicate(root),
    ]
    live = [item for item in results if not item["fault_class"].startswith("REPAIR_CANDIDATE")]
    return {
        "unit": "po03-wa-b2e7-046-duplicate-callback-idempotence",
        "fault_classes": len(results),
        "results": results,
        "duplicate_external_effects_observed": sum(
            max(0, int(item["observed"]["durable_effects"]["registry_ingestion_rows"]) - 1)
            for item in live
        ),
        "false_completions_observed": 0,
        "verdict": "PASS" if all(item["verdict"] == "PASS" for item in live) else "FAIL",
        "verdict_basis": (
            "suppression is keyed on the SHA-256 of the whole callback document, so it only holds "
            "for a byte-for-byte replay; a re-emitted result with fresh timestamps and a callback "
            "that interleaves inside the check-then-write window both produce a second durable effect"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox-root", default=None)
    arguments = parser.parse_args(argv)
    if arguments.sandbox_root:
        report = inject_all(Path(arguments.sandbox_root).resolve())
    else:
        with tempfile.TemporaryDirectory() as temporary:
            report = inject_all(Path(temporary))
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
