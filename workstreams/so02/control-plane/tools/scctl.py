#!/usr/bin/env python3
"""Dependency-free seed validator and projector for OCP-INT-01."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number}: event must be an object")
        result.append(value)
    return result


def canonical_event_hash(event: dict[str, Any]) -> str:
    payload = copy.deepcopy(event)
    payload.pop("event_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def add(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def require_keys(errors: list[str], value: dict[str, Any], keys: Iterable[str], prefix: str) -> None:
    for key in keys:
        add(errors, key in value, f"{prefix}: missing {key}")


def validate_control_plane(root: Path, data: dict[str, Any], errors: list[str]) -> None:
    require_keys(
        errors,
        data,
        [
            "control_plane_id", "revision", "strategy_snapshot_id", "decision_changed",
            "migration_state", "active_primary", "canonical_store", "runtime_bindings",
            "protected_workstreams", "cutover_gates", "cutover_evidence",
            "current_founder_actions", "global_pointer_state", "multi_parent_execution_contract"
        ],
        "control-plane"
    )
    add(errors, data.get("control_plane_id") == "SCF-01", "control-plane: wrong identity")
    add(errors, data.get("decision_changed") == [], "control-plane: unbound strategy change")

    store = data.get("canonical_store", {})
    add(errors, store.get("kind") == "git_repository", "control-plane: canonical store must be Git")
    add(errors, store.get("provider_memory_is_canonical") is False, "control-plane: provider memory cannot be canonical")
    add(errors, store.get("branch") == "so02/strategic-control-plane-migration-20260822-v001", "control-plane: unexpected branch")

    multi_parent = data.get("multi_parent_execution_contract", {})
    require_keys(
        errors,
        multi_parent,
        [
            "state", "topology", "root_shared_writer_count", "parent_registration_required",
            "declared_parent_denominator_required", "isolated_parent_branch_and_namespace_required",
            "nested_lineage_fields", "candidate_integration_requires_remote_readback",
            "candidate_integration_requires_independent_criteria",
            "founder_is_comparison_retrieval_or_merge_layer", "failure_mode_without_single_writer"
        ],
        "multi-parent-contract"
    )
    add(
        errors,
        multi_parent.get("state") in {"UNIT_TESTED_NOT_LIVE", "LIVE_CANARY", "OPERATIONAL", "INDEPENDENTLY_ACCEPTED"},
        "multi-parent-contract: invalid maturity state"
    )
    add(errors, multi_parent.get("root_shared_writer_count") == 1, "multi-parent-contract: exactly one shared-state writer required")
    add(errors, multi_parent.get("parent_registration_required") is True, "multi-parent-contract: parent registration must be required")
    add(errors, multi_parent.get("declared_parent_denominator_required") is True, "multi-parent-contract: parent denominator must be declared")
    add(errors, multi_parent.get("isolated_parent_branch_and_namespace_required") is True, "multi-parent-contract: isolated parent branches and namespaces required")
    required_lineage = {
        "group_run_id", "parent_id", "work_unit_id", "attempt_id",
        "exact_model_configuration", "owned_paths", "result_transaction_id"
    }
    add(errors, set(multi_parent.get("nested_lineage_fields", [])) == required_lineage, "multi-parent-contract: nested lineage denominator mismatch")
    add(errors, multi_parent.get("candidate_integration_requires_remote_readback") is True, "multi-parent-contract: integration requires remote read-back")
    add(errors, multi_parent.get("candidate_integration_requires_independent_criteria") is True, "multi-parent-contract: integration requires independent criteria")
    add(errors, multi_parent.get("founder_is_comparison_retrieval_or_merge_layer") is False, "multi-parent-contract: founder cannot be the candidate comparison, retrieval or merge layer")
    add(
        errors,
        multi_parent.get("failure_mode_without_single_writer") == "ISOLATED_WORK_CONTINUES_SHARED_WRITES_FAIL_CLOSED",
        "multi-parent-contract: unsafe no-writer failure mode"
    )

    pointer = data.get("global_pointer_state", {})
    add(errors, pointer.get("state") == "RECONCILIATION_PENDING", "control-plane: global pointer conflict must remain explicit")
    add(errors, "state/**" in pointer.get("prohibited_paths", []), "control-plane: state/** must remain protected")

    bindings = data.get("runtime_bindings", [])
    ids = [item.get("binding_id") for item in bindings if isinstance(item, dict)]
    required_ids = {"SCF-01/CUR-01", "SCF-01/SW-01", "SCF-01/CGPT-01", "SCF-01/OSS-01"}
    add(errors, set(ids) == required_ids, "control-plane: runtime binding denominator mismatch")
    add(errors, len(ids) == len(set(ids)), "control-plane: duplicate runtime binding")

    operational = {"EXECUTING", "OUTPUT_OBSERVED", "DURABLE", "INDEPENDENTLY_VALIDATED", "ACCEPTED", "ACTIVE_INTERIM"}
    durable = {"DURABLE", "INDEPENDENTLY_VALIDATED", "ACCEPTED"}
    for binding in bindings:
        if not isinstance(binding, dict):
            errors.append("control-plane: binding must be object")
            continue
        state = binding.get("state")
        prefix = f"binding {binding.get('binding_id')}"
        if state in operational:
            add(errors, bool(binding.get("provider_locator")), f"{prefix}: operational state without locator")
            add(errors, bool(binding.get("launch_receipt")), f"{prefix}: operational state without launch receipt")
        if state in durable:
            add(errors, bool(binding.get("result_commit")), f"{prefix}: durable state without result commit")
            add(errors, bool(binding.get("remote_readback_sha256")), f"{prefix}: durable state without read-back hash")
            add(errors, binding.get("parent_ingested") is True, f"{prefix}: durable state without parent ingestion")

    gates = data.get("cutover_gates", [])
    evidence = data.get("cutover_evidence", {})
    all_cutover = bool(gates) and all(evidence.get(gate) is True for gate in gates)
    if data.get("active_primary") != "SO-02":
        add(errors, all_cutover, "control-plane: primary changed before all cutover gates passed")

    protected = {item.get("workstream_id"): item for item in data.get("protected_workstreams", []) if isinstance(item, dict)}
    add(errors, protected.get("PO-01", {}).get("contact_or_mutation_allowed") is False, "control-plane: PO-01 non-interference missing")

    valid_reasons = {
        "provider_ui_model_selection_and_instruction_submission",
        "provider_ui_agent_creation_model_selection_and_instruction_submission",
        "SW surface requires founder-authenticated client with TLS certificate",
        "founder_held_ops_gate_and_provider_action_approval",
        "provider_ui_stop_run"
    }
    for action in data.get("current_founder_actions", []):
        prefix = f"founder-action {action.get('action_id')}"
        require_keys(errors, action, ["action_id", "state", "nondelegable_reason", "blocking_scope", "instruction_path", "delegated_parallel_work"], prefix)
        add(errors, action.get("nondelegable_reason") in valid_reasons, f"{prefix}: unqualified founder action")
        add(errors, action.get("blocking_scope") not in {"global", "all work", "programme"}, f"{prefix}: founder action incorrectly gates the programme")
        instruction_path = str(action.get("instruction_path", ""))
        if instruction_path.startswith("workstreams/so02/control-plane/"):
            linked = root.parent.parent.parent / instruction_path
            add(errors, linked.is_file(), f"{prefix}: instruction path missing")
        else:
            add(errors, instruction_path == "workstreams/po03/LAUNCH-NOW.md", f"{prefix}: unexpected inherited instruction path")


def validate_sources(data: dict[str, Any], errors: list[str]) -> None:
    add(errors, data.get("decision_changed") == [], "sources: unbound strategy change")
    sources = data.get("sources", [])
    ids = [item.get("source_id") for item in sources]
    add(errors, len(ids) == len(set(ids)), "sources: duplicate source id")
    add(errors, len(sources) >= 6, "sources: expected admitted source denominator")
    for source in sources:
        add(errors, bool(SHA256_RE.fullmatch(str(source.get("sha256", "")))), f"source {source.get('source_id')}: invalid SHA-256")
        add(errors, bool(source.get("admission_state")), f"source {source.get('source_id')}: missing admission state")
        add(errors, bool(source.get("authority")), f"source {source.get('source_id')}: missing authority class")


def validate_plan(data: dict[str, Any], errors: list[str]) -> None:
    add(errors, data.get("decision_changed") == [], "plan: unbound strategy change")
    items = data.get("items", [])
    ids = [item.get("item_id") for item in items]
    add(errors, len(items) >= 20, "plan: prior programme denominator incompletely admitted")
    add(errors, len(ids) == len(set(ids)), "plan: duplicate item id")
    for item in items:
        for key in ("name", "state", "durable_owner", "next_executable"):
            add(errors, bool(item.get(key)), f"plan {item.get('item_id')}: missing {key}")


def validate_controls(data: dict[str, Any], errors: list[str]) -> None:
    add(errors, data.get("decision_changed") == [], "controls: unbound strategy change")
    controls = data.get("controls", [])
    ids = [item.get("error_id") for item in controls]
    add(errors, len(controls) >= 21, "controls: known error denominator incomplete")
    add(errors, len(ids) == len(set(ids)), "controls: duplicate error id")
    for control in controls:
        for key in ("failure", "control_state", "owner"):
            add(errors, bool(control.get(key)), f"control {control.get('error_id')}: missing {key}")
        add(errors, "mechanism_maturity" not in control, f"control {control.get('error_id')}: typed maturity is prohibited")
        state = control.get("control_state")
        add(errors, state in {"ENFORCED", "UNCONTROLLED"}, f"control {control.get('error_id')}: invalid control state")
        if state == "ENFORCED":
            for key in ("fail_closed_mechanism", "old_behaviour_probe", "probe_result"):
                add(errors, bool(control.get(key)), f"control {control.get('error_id')}: enforced without {key}")
            add(errors, control.get("probe_result") == "PASS_OLD_BEHAVIOUR_REJECTED", f"control {control.get('error_id')}: old behaviour not rejected")
        if state == "UNCONTROLLED":
            for key in ("uncontrolled_reason", "next_control"):
                add(errors, bool(control.get(key)), f"control {control.get('error_id')}: uncontrolled without {key}")


STRICT_EXTERNAL_FORBIDDEN = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bobzio\b",
        r"asibrahim336-hash",
        r"\b(?:SCF|SO|PO)-\d+\b",
        r"decision_changed",
        r"strategy_snapshot",
        r"workstreams/",
    )
]


def strict_external_violations(text: str) -> list[str]:
    return [pattern.pattern for pattern in STRICT_EXTERNAL_FORBIDDEN if pattern.search(text)]


def validate_durable_directives(root: Path, errors: list[str]) -> None:
    path = root / "state/FOUNDER-OPERATING-DIRECTIVES-20260822.md"
    add(errors, path.is_file(), "directives: repository-native founder content missing")
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    required = [
        "one hundred coworkers and agents",
        "discover/create → real-operation test → validate → extract → package → redeploy",
        "Manus must receive full useful administrative enablement across multiple",
        "Qwen is locked",
        "Kimi and DeepSeek",
        "Grok is qualified on Cursor",
        "voice-first",
        "ten working projects",
        "ten to twenty next operators",
        "data and knowledge governance office",
        "founder activation and acquisition package",
    ]
    for phrase in required:
        add(errors, phrase in text, f"directives: missing executable content: {phrase}")


def validate_automation_receipt(data: dict[str, Any], errors: list[str]) -> None:
    add(errors, data.get("decision_changed") == [], "automation: unbound strategy change")
    old = data.get("old_job", {})
    replacement = data.get("replacement_job", {})
    add(errors, old.get("state") == "DISABLED", "automation: event-triggered predecessor still enabled")
    add(errors, old.get("trigger") == "github_pull_request_event", "automation: old event premise not recorded")
    add(errors, replacement.get("trigger") == "hourly_schedule", "automation: replacement can still fire per event")
    add(errors, replacement.get("state") == "ENABLED", "automation: replacement not enabled")
    add(errors, "at most one" in replacement.get("job_shape", ""), "automation: job fanout not bounded")
    add(errors, bool(replacement.get("cost_shape")), "automation: cost shape missing")
    add(errors, data.get("probe_result") == "PASS_OLD_BEHAVIOUR_REJECTED", "automation: old behavior not rejected")


def validate_instruction_contracts(root: Path, errors: list[str]) -> None:
    commission = (root / "commissions/CURSOR-SCP-01.md").read_text(encoding="utf-8")
    launch = (root / "launch/CURSOR-LAUNCH-NOW.md").read_text(encoding="utf-8")
    add(errors, "receipts/so02/**" in commission, "cursor commission: receipt allowlist missing")
    add(errors, "receipts/workstreams/so02/control-plane/**" not in commission, "cursor commission: obsolete receipt allowlist present")
    add(errors, "Multiple Agents" in launch, "cursor launch: multi-agent mode not explicit")
    add(errors, "only writer of shared projections" in launch, "cursor launch: root single-writer rule missing")
    add(errors, "group→parent→child→attempt" in launch, "cursor launch: nested lineage reconciliation missing")
    add(errors, "INTERNAL_AUTHORISED_RUNTIME" in launch, "cursor launch: disclosure classification missing")
    add(errors, "do not write PR #9" in launch, "cursor launch: PO-03 write prohibition missing")

    for relative in ("launch/SW-LAUNCH-NOW.md", "commissions/SW-SDF-01.md"):
        text = (root / relative).read_text(encoding="utf-8")
        violations = strict_external_violations(text)
        add(errors, not violations, f"strict external packet {relative}: forbidden disclosure tokens {violations}")
        add(errors, "EXTERNAL_STRICT_CODED" in text, f"strict external packet {relative}: classification missing")

    lanes = (root / "launch/CHATGPT-LANES-NOW.md").read_text(encoding="utf-8")
    add(errors, lanes.count("## CGPT-") >= 12, "chatgpt lanes: fewer than twelve launch sheets")
    add(errors, "Project:" in lanes and "Model/effort:" in lanes and "Acceptance:" in lanes, "chatgpt lanes: launch contract incomplete")

    evaluation = (root / "evaluations/INDEPENDENT-PO02-PO03-20260822.md").read_text(encoding="utf-8")
    add(errors, "eight kill positions PASS" in evaluation, "evaluation: PO-02 replay absent")
    add(errors, "seven executable tests PASS" in evaluation, "evaluation: PO-03 replay absent")


def validate_events(events: list[dict[str, Any]], errors: list[str]) -> None:
    ids: set[str] = set()
    keys: set[str] = set()
    previous: str | None = None
    for expected_sequence, event in enumerate(events, 1):
        prefix = f"event {event.get('event_id')}"
        require_keys(
            errors,
            event,
            [
                "event_id", "aggregate_type", "aggregate_id", "sequence", "previous_event_sha256",
                "event_sha256", "event_type", "occurred_at", "recorded_at", "actor", "authority",
                "strategy_snapshot_id", "subject", "payload", "idempotency_key"
            ],
            prefix
        )
        add(errors, event.get("event_id") not in ids, f"{prefix}: duplicate event id")
        ids.add(str(event.get("event_id")))
        add(errors, event.get("idempotency_key") not in keys, f"{prefix}: duplicate idempotency key")
        keys.add(str(event.get("idempotency_key")))
        add(errors, event.get("sequence") == expected_sequence, f"{prefix}: non-monotonic sequence")
        add(errors, event.get("previous_event_sha256") == previous, f"{prefix}: broken hash chain")
        expected_hash = canonical_event_hash(event)
        add(errors, event.get("event_sha256") == expected_hash, f"{prefix}: event hash mismatch")
        payload = event.get("payload", {})
        add(errors, payload.get("decision_changed") == [], f"{prefix}: unbound strategy change")
        if event.get("event_type") == "STRATEGY_DECISION":
            add(errors, event.get("authority", {}).get("class") == "FOUNDER_BOUND_DECISION", f"{prefix}: strategy decision lacks founder binding")
        previous = str(event.get("event_sha256"))


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    control = read_json(root / "state/control-plane.json")
    sources = read_json(root / "sources/SOURCE-REGISTER.json")
    plan = read_json(root / "state/PLAN-DURABILITY-MANIFEST.json")
    controls = read_json(root / "errors/recurrence-controls.json")
    events = read_jsonl(root / "state/events.jsonl")
    validate_control_plane(root, control, errors)
    validate_sources(sources, errors)
    validate_plan(plan, errors)
    validate_controls(controls, errors)
    validate_durable_directives(root, errors)
    automation = read_json(root.parent.parent.parent / "receipts/so02/2026-08-22/po03-automation-reshape-20260822T0924Z.json")
    validate_automation_receipt(automation, errors)
    validate_events(events, errors)
    validate_instruction_contracts(root, errors)
    return errors


def project(root: Path = ROOT) -> dict[str, Any]:
    events = read_jsonl(root / "state/events.jsonl")
    subjects: dict[str, dict[str, Any]] = {}
    for event in events:
        subjects[event["subject"]] = {
            "state": event["payload"]["new_state"],
            "event_id": event["event_id"],
            "event_sha256": event["event_sha256"],
            "sequence": event["sequence"]
        }
    return {
        "aggregate_id": "SCF-01",
        "event_head": events[-1]["event_sha256"] if events else None,
        "event_count": len(events),
        "subjects": subjects
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "project"))
    args = parser.parse_args(argv)
    if args.command == "project":
        print(json.dumps(project(), indent=2, sort_keys=True))
        return 0
    errors = validate()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: SCF-01 seed contracts and state invariants")
    return 0


if __name__ == "__main__":
    sys.exit(main())
