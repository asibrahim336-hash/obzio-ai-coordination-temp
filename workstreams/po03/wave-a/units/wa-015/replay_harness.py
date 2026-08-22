#!/usr/bin/env python3
"""Fault-injecting replay harness for the PO-03 transactional outbox.

Each fixture scenario is a sequence of phases.  A phase opens the durable store,
delivers a list of sanitized callbacks, optionally drains the outbox, and may
arm a fault that aborts the phase at a named durability boundary.  A phase that
crashes loses all in-memory state; the next phase reopens the store from bytes
on disk, exactly as a restarted process would.

After the last phase the harness reopens the store without faults, runs the
recovery scanner, drains whatever remains, audits structural invariants, and
compares the observed outcome against the expectations frozen in the fixture.

No wall-clock, path or environment value enters the report, so the compiled
report is byte-identical across runs, machines and clean clones.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

_UNIT_ROOT = Path(__file__).resolve().parent
if str(_UNIT_ROOT) not in sys.path:
    sys.path.insert(0, str(_UNIT_ROOT))

import outbox_processor as mechanism  # noqa: E402
from outbox_processor import (  # noqa: E402
    InjectedCrash,
    OutboxProcessor,
    canonical_bytes,
    load_workload,
)


REPORT_PROTOCOL = "OBZIO-WA015-REPLAY-REPORT-v1"
FIXTURE_PROTOCOL = "OBZIO-WA015-SCENARIOS-v1"

FAULT_POINTS = frozenset(
    {
        "before_journal_append",
        "after_journal_append",
        "journal_torn_write",
        "before_sink_apply",
        "after_sink_apply",
        "after_dispatch_record",
        "before_sink_write",
        "sink_torn_write",
        "after_sink_write",
    }
)

FAULT_MODES = frozenset({"crash", "tear"})

SCENARIO_CLASSES = frozenset({"duplicate", "lost"})

#: Expectation keys a fixture may freeze, mapped to their observation path.
EXPECT_KEYS: dict[str, tuple[str, ...]] = {
    "decisions": ("decisions",),
    "reject_codes": ("reject_codes",),
    "crashes": ("crashes",),
    "final_states": ("final", "states"),
    "transition_counts": ("final", "transition_counts"),
    "sink_effects": ("final", "sink_effects"),
    "effect_receipts": ("final", "effect_receipts"),
    "pending_effects": ("final", "pending_effects"),
    "repairs": ("repairs",),
    "provider_completed_uncommitted": ("recovery", "provider_completed_uncommitted"),
}

INVARIANTS = (
    "single_transition_per_delivery",
    "single_effect_per_key",
    "dense_journal_sequence",
    "monotonic_checkpoints",
    "legal_state_path",
    "no_dispatch_without_enqueue",
    "no_effect_without_transition",
    "admitted_fence_is_current",
    "no_completion_without_result_commit",
    "no_producer_self_acceptance",
)


class _Fault:
    """Arms a crash or torn write at the Nth arrival at a named boundary."""

    def __init__(self, specs: list[dict[str, Any]]) -> None:
        self.specs = specs
        self.arrivals: dict[str, int] = {}
        self.fired: list[dict[str, Any]] = []

    def _match(self, point: str, mode: str) -> dict[str, Any] | None:
        count = self.arrivals.get(point, 0) + 1
        self.arrivals[point] = count
        for spec in self.specs:
            if (
                spec["point"] == point
                and spec.get("mode", "crash") == mode
                and int(spec.get("occurrence", 1)) == count
            ):
                self.fired.append({"point": point, "mode": mode, "occurrence": count})
                return spec
        return None

    def trip(self, point: str) -> None:
        if self._match(point, "crash") is not None:
            raise InjectedCrash(point)

    def tear(self, point: str) -> int | None:
        spec = self._match(point, "tear")
        if spec is None:
            return None
        return int(spec.get("keep_bytes", 9))


def _callback_index(workload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        entry["ref"]: {key: value for key, value in entry.items() if key != "ref"}
        for entry in workload["callbacks"]
    }


def validate_fixture(document: Any, index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Reject a scenario fixture that could silently under-test the mechanism."""
    if not isinstance(document, dict):
        raise ValueError("fixture: root must be an object")
    if document.get("protocol_version") != FIXTURE_PROTOCOL:
        raise ValueError("fixture: unsupported protocol_version")
    scenarios = document.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("fixture: scenarios must be a non-empty array")
    seen: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError("fixture: scenario must be an object")
        scenario_id = scenario.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            raise ValueError("fixture: scenario_id must be a non-empty string")
        if scenario_id in seen:
            raise ValueError(f"fixture: duplicate scenario_id {scenario_id}")
        seen.add(scenario_id)
        if scenario.get("class") not in SCENARIO_CLASSES:
            raise ValueError(f"{scenario_id}: class must be one of {sorted(SCENARIO_CLASSES)}")
        if not isinstance(scenario.get("title"), str) or not scenario["title"].strip():
            raise ValueError(f"{scenario_id}: title must be a non-empty string")
        phases = scenario.get("phases")
        if not isinstance(phases, list) or not phases:
            raise ValueError(f"{scenario_id}: phases must be a non-empty array")
        for phase in phases:
            if not isinstance(phase, dict):
                raise ValueError(f"{scenario_id}: phase must be an object")
            deliveries = phase.get("deliveries", [])
            if not isinstance(deliveries, list):
                raise ValueError(f"{scenario_id}: deliveries must be an array")
            for ref in deliveries:
                if ref not in index:
                    raise ValueError(f"{scenario_id}: unknown callback ref {ref!r}")
            for spec in phase.get("faults", []):
                if not isinstance(spec, dict):
                    raise ValueError(f"{scenario_id}: fault must be an object")
                if spec.get("point") not in FAULT_POINTS:
                    raise ValueError(f"{scenario_id}: unknown fault point {spec.get('point')!r}")
                if spec.get("mode", "crash") not in FAULT_MODES:
                    raise ValueError(f"{scenario_id}: unknown fault mode {spec.get('mode')!r}")
                if int(spec.get("occurrence", 1)) < 1:
                    raise ValueError(f"{scenario_id}: fault occurrence must be >= 1")
        expect = scenario.get("expect")
        if not isinstance(expect, dict) or not expect:
            raise ValueError(f"{scenario_id}: expect must be a non-empty object")
        unknown = sorted(set(expect) - set(EXPECT_KEYS))
        if unknown:
            raise ValueError(f"{scenario_id}: unknown expectation keys {unknown}")
    return document


# --------------------------------------------------------------------------- #
# structural audit
# --------------------------------------------------------------------------- #


def audit(processor: OutboxProcessor) -> dict[str, list[str]]:
    """Check the invariants the hypothesis depends on; return violations."""
    violations: dict[str, list[str]] = {name: [] for name in INVARIANTS}
    records = processor.records

    transitions: dict[str, int] = {}
    for record in records:
        if record["kind"] in {"callback_admitted", "lease_transferred", "provider_observed"}:
            delivery_id = record.get("delivery_id")
            if isinstance(delivery_id, str):
                transitions[delivery_id] = transitions.get(delivery_id, 0) + 1
    for delivery_id, count in sorted(transitions.items()):
        if count > 1:
            violations["single_transition_per_delivery"].append(
                f"{delivery_id} committed {count} times"
            )

    payloads, _, torn = processor.sink.journal.read()
    if torn is not None:
        violations["single_effect_per_key"].append(f"sink tail torn: {torn}")
    sink_counts: dict[str, int] = {}
    sink_seqs: list[int] = []
    for payload in payloads:
        row = json.loads(payload)
        sink_counts[row["effect_key"]] = sink_counts.get(row["effect_key"], 0) + 1
        sink_seqs.append(row["receipt_seq"])
    for key, count in sorted(sink_counts.items()):
        if count > 1:
            violations["single_effect_per_key"].append(f"{key} applied {count} times")
    if sink_seqs != list(range(1, len(sink_seqs) + 1)):
        violations["single_effect_per_key"].append("sink receipt sequence is not dense")

    if [record["seq"] for record in records] != list(range(1, len(records) + 1)):
        violations["dense_journal_sequence"].append("journal seq is not 1..n")

    checkpoints: dict[str, int] = {}
    states: dict[str, str] = {}
    fences: dict[str, int] = {}
    producers: dict[str, Any] = {}
    committed: set[str] = set()
    enqueued: dict[str, str] = {}
    for record in records:
        kind = record["kind"]
        if kind == "task_registered":
            task = record["task"]
            states[record["task_id"]] = task["state"]
            fences[record["task_id"]] = task["fence_token"]
            checkpoints[record["task_id"]] = task["checkpoint_seq"]
            producers[record["task_id"]] = task["producer_id"]
            continue
        if kind == "effect_dispatched":
            if record["effect_key"] not in enqueued:
                violations["no_dispatch_without_enqueue"].append(record["effect_key"])
            continue
        if kind in {"callback_rejected", "recovery_truncation"}:
            continue
        task_id = record["task_id"]
        entry = record.get("outbox_entry")
        if entry is not None:
            enqueued[entry["effect_key"]] = task_id
        current = fences.get(task_id)
        expected = current + 1 if kind == "lease_transferred" and current is not None else current
        if record["fence_token"] != expected:
            violations["admitted_fence_is_current"].append(
                f"{record['delivery_id']} used fence {record['fence_token']}"
            )
        if kind == "lease_transferred":
            fences[task_id] = record["fence_token"]
            producers[task_id] = record["new_producer_id"]
            continue
        if kind == "provider_observed":
            continue
        if record["from_state"] != states.get(task_id):
            violations["legal_state_path"].append(
                f"{record['delivery_id']} left {record['from_state']} from {states.get(task_id)}"
            )
        if (record["from_state"], record["to_state"]) not in mechanism.TRANSITIONS:
            violations["legal_state_path"].append(
                f"{record['delivery_id']} used illegal edge"
            )
        if record["checkpoint_seq"] < checkpoints.get(task_id, 0):
            violations["monotonic_checkpoints"].append(
                f"{record['delivery_id']} regressed checkpoint"
            )
        if record["to_state"] in {"ACCEPTED", "REJECTED"} and record["actor"].endswith(
            f":{producers.get(task_id)}"
        ):
            violations["no_producer_self_acceptance"].append(record["delivery_id"])
        if record["to_state"] == "COMPLETED" and task_id not in committed:
            violations["no_completion_without_result_commit"].append(task_id)
        if record["to_state"] == "RESULT_COMMITTED":
            committed.add(task_id)
        if record["to_state"] == "LEASED":
            producers[task_id] = record["task"]["producer_id"]
        states[task_id] = record["to_state"]
        checkpoints[task_id] = record["checkpoint_seq"]

    for key in sorted(sink_counts):
        if key not in enqueued:
            violations["no_effect_without_transition"].append(key)

    return {name: rows for name, rows in violations.items() if rows}


# --------------------------------------------------------------------------- #
# scenario execution
# --------------------------------------------------------------------------- #


def run_scenario(
    scenario: dict[str, Any],
    workload: dict[str, Any],
    index: dict[str, dict[str, Any]],
    store: Path,
) -> dict[str, Any]:
    phases: list[dict[str, Any]] = []
    decisions: list[str] = []
    reject_codes: list[str] = []
    repairs: list[dict[str, Any]] = []
    crashes = 0

    def record_repair(opened: str, processor: OutboxProcessor) -> None:
        found = processor.recovery
        if found["journal_torn_reason"] is None and found["sink_torn_reason"] is None:
            return
        repairs.append({"observed_at": opened, **found})

    for position, phase in enumerate(scenario["phases"], start=1):
        fault = _Fault(list(phase.get("faults", [])))
        processor = OutboxProcessor(store)
        record_repair(phase.get("phase", f"phase-{position}"), processor)
        processor.register_workload(workload)
        processor.fault = fault
        processor.sink.fault = fault
        phase_decisions: list[str] = []
        dispatched: list[dict[str, Any]] = []
        crash_point: str | None = None
        for ref in phase.get("deliveries", []):
            try:
                outcome = processor.handle(index[ref])
            except InjectedCrash as exc:
                crash_point = str(exc)
                break
            phase_decisions.append(outcome["decision"])
            decisions.append(outcome["decision"])
            if outcome["decision"] == "REJECTED":
                reject_codes.append(outcome["code"])
        if crash_point is None and phase.get("drain", False):
            try:
                dispatched = processor.drain()
            except InjectedCrash as exc:
                crash_point = str(exc)
        if crash_point is not None:
            crashes += 1
        phases.append(
            {
                "phase": phase.get("phase", f"phase-{position}"),
                "decisions": phase_decisions,
                "dispatched": dispatched,
                "crash_point": crash_point,
                "faults_fired": fault.fired,
            }
        )

    processor = OutboxProcessor(store)
    record_repair("recovery-scan", processor)
    recovery = processor.scan_recovery()
    final_dispatched = processor.drain()
    snapshot = processor.snapshot()
    violations = audit(processor)

    return {
        "scenario_id": scenario["scenario_id"],
        "class": scenario["class"],
        "title": scenario["title"],
        "phases": phases,
        "crashes": crashes,
        "decisions": decisions,
        "reject_codes": reject_codes,
        "repairs": repairs,
        "recovery": recovery,
        "final": {
            "dispatched": final_dispatched,
            "states": {task["task_id"]: task["state"] for task in snapshot["tasks"]},
            "transition_counts": {
                task["task_id"]: task["transition_count"] for task in snapshot["tasks"]
            },
            "fence_tokens": {
                task["task_id"]: task["fence_token"] for task in snapshot["tasks"]
            },
            "sink_effects": snapshot["sink_effects"],
            "effect_receipts": {
                receipt["effect_key"]: receipt["receipt_seq"]
                for receipt in snapshot["sink_receipts"]
            },
            "pending_effects": snapshot["pending_outbox"],
            "journal_records": snapshot["journal_records"],
            "record_kinds": snapshot["record_kinds"],
        },
        "invariant_violations": violations,
        "invariants": "PASS" if not violations else "FAIL",
    }


def _observed(observation: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = observation
    for key in path:
        value = value[key]
    return value


def compare(scenario: dict[str, Any], observation: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for key, path in sorted(EXPECT_KEYS.items()):
        if key not in scenario["expect"]:
            continue
        expected = scenario["expect"][key]
        actual = _observed(observation, path)
        if expected != actual:
            mismatches.append(f"{key}: expected {expected!r}, observed {actual!r}")
    return mismatches


def run_fixture(
    fixture_path: Path, workload: dict[str, Any], index: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    document = validate_fixture(
        json.loads(Path(fixture_path).read_text(encoding="utf-8")), index
    )
    scenarios: list[dict[str, Any]] = []
    for scenario in document["scenarios"]:
        with tempfile.TemporaryDirectory(prefix="wa015-") as tmp:
            observation = run_scenario(
                scenario, workload, index, Path(tmp) / "store"
            )
        observation["mismatches"] = compare(scenario, observation)
        observation["outcome"] = (
            "PASS"
            if not observation["mismatches"] and observation["invariants"] == "PASS"
            else "FAIL"
        )
        scenarios.append(observation)
    return {
        "fixture": Path(fixture_path).name,
        "fixture_id": document.get("fixture_id", Path(fixture_path).stem),
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
    }


def run_fixtures(
    workload_path: Path, fixture_paths: list[Path]
) -> dict[str, Any]:
    workload = load_workload(workload_path)
    index = _callback_index(workload)
    fixtures = [run_fixture(path, workload, index) for path in fixture_paths]
    scenarios = [s for fixture in fixtures for s in fixture["scenarios"]]
    failures = [s["scenario_id"] for s in scenarios if s["outcome"] != "PASS"]
    return {
        "protocol_version": REPORT_PROTOCOL,
        "mechanism_protocol": mechanism.PROTOCOL_VERSION,
        "workload": Path(workload_path).name,
        "workload_id": workload.get("workload_id", Path(workload_path).stem),
        "task_count": len(workload["tasks"]),
        "callback_count": len(workload["callbacks"]),
        "fixtures": fixtures,
        "scenario_count": len(scenarios),
        "duplicate_scenarios": sum(1 for s in scenarios if s["class"] == "duplicate"),
        "lost_scenarios": sum(1 for s in scenarios if s["class"] == "lost"),
        "injected_crashes": sum(s["crashes"] for s in scenarios),
        "reject_codes_exercised": sorted(
            {code for s in scenarios for code in s["reject_codes"]}
        ),
        "duplicates_suppressed": sum(
            s["decisions"].count("DUPLICATE_SUPPRESSED") for s in scenarios
        ),
        "external_effects_applied": sum(
            s["final"]["sink_effects"] for s in scenarios
        ),
        "invariants_checked": list(INVARIANTS),
        "failures": failures,
        "outcome": "PASS" if not failures else "FAIL",
    }


DEFAULT_WORKLOAD = _UNIT_ROOT / "fixtures" / "sanitized-workload.json"
DEFAULT_FIXTURES = (
    _UNIT_ROOT / "fixtures" / "duplicate-callbacks.json",
    _UNIT_ROOT / "fixtures" / "lost-callbacks.json",
)


def compile_report() -> dict[str, Any]:
    return run_fixtures(DEFAULT_WORKLOAD, list(DEFAULT_FIXTURES))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument("--fixture", type=Path, action="append", default=None)
    args = parser.parse_args(argv)
    report = run_fixtures(args.workload, args.fixture or list(DEFAULT_FIXTURES))
    sys.stdout.buffer.write(canonical_bytes(report) + b"\n")
    return 0 if report["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
