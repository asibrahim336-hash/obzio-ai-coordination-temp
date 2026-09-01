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
ROLE_SCOPE_DECISION = [
    "SO-02 founder browser/setup batch HALTED; strategic development and human-operator implementation guidance for this capability moves to Cursor"
]
ROLE_SCOPE_CORRECTION_ID = "FOUNDER-ROLE-SCOPE-20260822T173520Z"


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
            "control_plane_id", "revision", "strategy_snapshot_id", "role_scope_correction_id", "decision_changed",
            "migration_state", "active_primary", "canonical_store", "runtime_bindings",
            "protected_workstreams", "cutover_gates", "cutover_evidence",
            "current_founder_actions", "global_pointer_state", "multi_parent_execution_contract",
            "orchestration_assignment", "provider_capacity_observations"
        ],
        "control-plane"
    )
    add(errors, data.get("control_plane_id") == "SCF-01", "control-plane: wrong identity")
    add(errors, data.get("strategy_snapshot_id") == "CURRENT_ACTIVE_STRATEGY_SNAPSHOT_UNCHANGED", "control-plane: company strategy snapshot changed by role correction")
    add(errors, data.get("role_scope_correction_id") == ROLE_SCOPE_CORRECTION_ID, "control-plane: founder role/scope correction missing")
    add(errors, data.get("decision_changed") == ROLE_SCOPE_DECISION, "control-plane: unbound or incomplete role/scope change")

    orchestration = data.get("orchestration_assignment", {})
    require_keys(
        errors,
        orchestration,
        [
            "programme_coordinator", "cursor_binding", "cursor_role_state",
            "sw_binding", "sw_role_state", "chatgpt_binding", "chatgpt_role_state",
            "repository_remains_provider_independent", "chatgpt_project_api_equivalence_assumed",
            "cursor_control_surface_qualification", "founder_operating_environment_assignment"
        ],
        "orchestration-assignment"
    )
    add(errors, orchestration.get("programme_coordinator") == "SO-02", "orchestration: programme coordinator changed before cutover")
    add(errors, orchestration.get("cursor_binding") == "SCF-01/CUR-01", "orchestration: unexpected Cursor binding")
    add(errors, orchestration.get("cursor_role_state") == "CURRENT_STRATEGIC_OPERATOR_INTERFACE_FOR_FOUNDER_OPERATING_ENVIRONMENT_PORTABLE_NOT_PERMANENT", "orchestration: Cursor scoped role missing or made permanent")
    add(errors, orchestration.get("sw_role_state") == "PARALLEL_SPECIALIST_FACTORY_NOT_PRIMARY", "orchestration: SW incorrectly made central")
    add(errors, orchestration.get("chatgpt_role_state") == "FOUNDER_INTENT_CONTEXT_EVIDENCE_VERIFICATION_AND_ROUTING_SUPPORT_FOR_THIS_SCOPE", "orchestration: SO-02 escaped supporting role")
    add(errors, orchestration.get("repository_remains_provider_independent") is True, "orchestration: provider-independent canonical state lost")
    add(errors, orchestration.get("chatgpt_project_api_equivalence_assumed") is False, "orchestration: ChatGPT Projects UI conflated with API conversation state")

    qualification = orchestration.get("cursor_control_surface_qualification", {})
    require_keys(
        errors,
        qualification,
        [
            "qualification_id", "state", "current_entry_agent_id",
            "existing_operation_continuation_required", "capacity_and_fanout_authority",
            "role_assignment_not_contingent_on_route_acceptance", "qualified_route_count", "routes",
            "required_end_to_end_evidence", "projects_ui_probe_required_for_promotion",
            "capability_acceptance_rule", "role_assignment_does_not_admit", "global_promotion_rule"
        ],
        "cursor-orchestration-qualification"
    )
    add(errors, qualification.get("current_entry_agent_id") == "bc-7137a066-3242-43a2-a30e-9a352047b759", "orchestration: existing Cursor operation not preserved")
    add(errors, qualification.get("existing_operation_continuation_required") is True, "orchestration: correction restarts Cursor operation")
    add(errors, "INSPECT_AND_MEASURE" in qualification.get("capacity_and_fanout_authority", ""), "orchestration: SO-02 imposed or omitted Cursor topology evaluation")
    add(errors, qualification.get("role_assignment_not_contingent_on_route_acceptance") is True, "orchestration: scoped Cursor appointment made contingent on arbitrary route proof")
    add(errors, qualification.get("projects_ui_probe_required_for_promotion") is False, "orchestration: ChatGPT Projects UI made an artificial promotion gate")
    add(errors, qualification.get("routes", {}).get("chatgpt_projects_ui_via_browser") == "OPTIONAL_PROBE_NOT_A_PROMOTION_GATE", "orchestration: ChatGPT Projects browser route not optional")
    add(errors, "EACH_ROUTE_OR_CAPABILITY_IS_ACCEPTED_ONLY" in qualification.get("capability_acceptance_rule", ""), "orchestration: unproved route can be treated as accepted")
    add(errors, "THIS_SCOPED_ASSIGNMENT_IS_NOT_GLOBAL_PROMOTION" in qualification.get("global_promotion_rule", ""), "orchestration: scoped appointment conflated with global cutover")

    environment = orchestration.get("founder_operating_environment_assignment", {})
    require_keys(
        errors,
        environment,
        [
            "assignment_id", "state", "owner", "so02_role", "browser_setup_batch",
            "selected_stack", "named_tools_role", "no_named_tool_founder_bound",
            "architecture_frozen", "cursor_setup_inspection_first", "human_guidance_mode",
            "research_beyond_named_seeds_required",
            "portable_obzio_controlled_state_logic_and_interfaces_required",
            "model_and_runtime_replaceability_required", "discovery_seeds",
            "capability_scope", "delivery"
        ],
        "founder-operating-environment-assignment"
    )
    add(errors, environment.get("assignment_id") == "CUR-ENV-01", "operating-environment: wrong constituted lane")
    add(errors, environment.get("owner") == "SCF-01/CUR-01", "operating-environment: strategic development not owned by Cursor")
    add(errors, environment.get("so02_role") == "FOUNDER_INTENT_CAPTURE_CONTEXT_RECOVERY_RESEARCH_VERIFICATION_EVIDENCE_RECEIPTS_AND_ROUTING_SUPPORT", "operating-environment: SO-02 architecture prescription remains")
    add(errors, environment.get("browser_setup_batch") == "FOUNDER_HALTED_NO_ACTION_AUTHORISED", "operating-environment: old active browser batch not rejected")
    add(errors, environment.get("selected_stack") is None, "operating-environment: unbound named stack selected")
    add(errors, environment.get("named_tools_role") == "DISCOVERY_SEEDS_AND_CANDIDATE_EVIDENCE_ONLY", "operating-environment: discovery seeds converted to requirements")
    add(errors, environment.get("no_named_tool_founder_bound") is True, "operating-environment: named tool falsely founder-bound")
    add(errors, environment.get("architecture_frozen") is False, "operating-environment: architecture silently frozen")
    add(errors, environment.get("cursor_setup_inspection_first") is True, "operating-environment: Cursor setup inspection not first")
    add(errors, environment.get("research_beyond_named_seeds_required") is True, "operating-environment: research bounded to founder seed list")
    add(errors, environment.get("portable_obzio_controlled_state_logic_and_interfaces_required") is True, "operating-environment: portable Obzio custody missing")
    add(errors, environment.get("model_and_runtime_replaceability_required") is True, "operating-environment: model/runtime sovereignty missing")
    add(errors, "STAGED_IMPLEMENTATION" in environment.get("human_guidance_mode", ""), "operating-environment: human guidance reduced to architecture document")
    seeds = " ".join(environment.get("discovery_seeds", []))
    for seed in ("Cursor native", "Kimi", "HARPA", "Sider", "Aircrift", "Playwright", "Goose", "stronger alternatives"):
        add(errors, seed in seeds, f"operating-environment: missing discovery seed {seed}")
    scope = " ".join(environment.get("capability_scope", []))
    for capability in ("browser and computer control", "screen and context extraction", "knowledge graphs", "cross-model memory", "MCP", "voice-first", "MacBook", "durable external state", "privacy", "broader Obzio"):
        add(errors, capability in scope, f"operating-environment: missing capability scope {capability}")
    delivery = environment.get("delivery", {})
    add(errors, delivery.get("direct_submission_state") == "NOT_DELIVERED", "operating-environment: Cursor delivery claimed without provider acknowledgement")
    add(errors, delivery.get("message_typed_or_submitted") is False, "operating-environment: blocked browser delivery misreported")
    add(errors, "CLOUDFLARE_SECURITY_VERIFICATION_LOOP" in delivery.get("blocker", ""), "operating-environment: exact Cursor delivery blocker missing")

    capacity = data.get("provider_capacity_observations", [])
    claude = next((item for item in capacity if item.get("provider_route") == "Claude browser-extension account"), {})
    add(errors, claude.get("state") == "TOKEN_CAPACITY_EXHAUSTED_ROUTE_UNAVAILABLE", "provider-capacity: Claude exhaustion not recorded as route unavailability")
    add(errors, claude.get("quality_inference_allowed") is False, "provider-capacity: quota exhaustion treated as quality evidence")
    add(errors, claude.get("retry_or_refill_required_now") is False, "provider-capacity: quota refill incorrectly made immediate requirement")

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
    # EC-13 retired 2026-08-23. This asserted a named-target prohibition list, the
    # exact shape the founder voided, and it forbade state/** while the pointer sits
    # at RECONCILIATION_PENDING — forbidding the work whose completion expires it.
    # What replaces it is not a shorter list: a write must be reason-gated.
    gating = pointer.get("write_gating", {})
    add(errors, gating.get("model") == "REASON_AND_ROLLBACK", "control-plane: pointer writes must be reason-gated")
    add(
        errors,
        set(gating.get("gates", [])) == {"concurrency", "reversibility", "evidence"},
        "control-plane: the three write gates must all be present",
    )
    add(errors, "prohibited_paths" not in pointer, "control-plane: the voided prohibited-path list must not return")

    bindings = data.get("runtime_bindings", [])
    ids = [item.get("binding_id") for item in bindings if isinstance(item, dict)]
    required_ids = {"SCF-01/CUR-01", "SCF-01/SW-01", "SCF-01/CGPT-01", "SCF-01/OSS-01"}
    add(errors, set(ids) == required_ids, "control-plane: runtime binding denominator mismatch")
    add(errors, len(ids) == len(set(ids)), "control-plane: duplicate runtime binding")

    operational = {"EXECUTING", "OUTPUT_OBSERVED", "DURABLE", "INDEPENDENTLY_VALIDATED", "ACCEPTED", "ACTIVE_INTERIM", "FOUNDER_REPORTED_LAUNCHED_RUNNING_QUALIFICATION_PENDING", "FOUNDER_REPORTED_AGENT_RUNNING_SCOPE_TRANSFER_DELIVERY_PENDING"}
    durable = {"DURABLE", "INDEPENDENTLY_VALIDATED", "ACCEPTED"}
    for binding in bindings:
        if not isinstance(binding, dict):
            errors.append("control-plane: binding must be object")
            continue
        state = binding.get("state")
        prefix = f"binding {binding.get('binding_id')}"
        add(errors, bool(binding.get("surface_locator_ids")), f"{prefix}: surface locator denominator missing")
        if state in operational:
            add(errors, bool(binding.get("provider_locator")), f"{prefix}: operational state without locator")
            add(errors, bool(binding.get("launch_receipt")), f"{prefix}: operational state without launch receipt")
        if state in durable:
            add(errors, bool(binding.get("result_commit")), f"{prefix}: durable state without result commit")
            add(errors, bool(binding.get("remote_readback_sha256")), f"{prefix}: durable state without read-back hash")
            add(errors, binding.get("parent_ingested") is True, f"{prefix}: durable state without parent ingestion")

    locators = read_json(root / "state/runtime-surface-locators.json")
    locator_ids = {item.get("locator_id") for item in locators.get("records", []) if isinstance(item, dict)}
    for binding in bindings:
        for locator_id in binding.get("surface_locator_ids", []):
            add(errors, locator_id in locator_ids, f"binding {binding.get('binding_id')}: unknown surface locator {locator_id}")

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
        "provider_ui_existing_agent_followup_submission_security_verification_block",
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
    action_ids = {item.get("action_id") for item in data.get("current_founder_actions", [])}
    add(errors, "FA-BROWSER-CONTROL-CANARY" not in action_ids, "founder-actions: halted browser setup remains live")


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
    add(errors, data.get("strategy_snapshot_id") == "CURRENT_ACTIVE_STRATEGY_SNAPSHOT_UNCHANGED", "plan: company strategy snapshot changed by role correction")
    add(errors, data.get("role_scope_correction_id") == ROLE_SCOPE_CORRECTION_ID, "plan: founder role/scope correction missing")
    add(errors, data.get("decision_changed") == ROLE_SCOPE_DECISION, "plan: unbound or incomplete role/scope change")
    items = data.get("items", [])
    ids = [item.get("item_id") for item in items]
    add(errors, len(items) >= 20, "plan: prior programme denominator incompletely admitted")
    add(errors, len(ids) == len(set(ids)), "plan: duplicate item id")
    for item in items:
        for key in ("name", "state", "durable_owner", "next_executable"):
            add(errors, bool(item.get(key)), f"plan {item.get('item_id')}: missing {key}")
    by_id = {item.get("item_id"): item for item in items}
    add(errors, "HALTED" in by_id.get("PLAN-023", {}).get("state", ""), "plan: browser setup batch remains active")
    add(errors, "none from SO-02" in by_id.get("PLAN-023", {}).get("next_executable", ""), "plan: SO-02 still prescribes browser execution")
    add(errors, by_id.get("PLAN-024", {}).get("durable_owner") == "SCF-01/CUR-01", "plan: founder operating environment not owned by Cursor")


def validate_locators(data: dict[str, Any], errors: list[str]) -> None:
    add(errors, data.get("decision_changed") == [], "locators: unbound strategy change")
    add(errors, data.get("canonical_store") == "git_repository", "locators: provider state made canonical")
    records = data.get("records", [])
    ids = [item.get("locator_id") for item in records if isinstance(item, dict)]
    add(errors, len(records) >= 12, "locators: required surface denominator incomplete")
    add(errors, len(ids) == len(set(ids)), "locators: duplicate locator id")
    allowed_states = {
        "VERIFIED", "FOUNDER_REPORTED_CAPTURED", "AWAITING_PROVIDER_CREATION",
        "OWNER_CAPTURE_REQUIRED", "NOT_YET_CREATED", "ROUTE_QUALIFICATION_PENDING",
        "OPTIONAL_PROBE_NOT_REQUIRED", "FOUNDER_PAUSED_BEFORE_CREATION",
        "FOUNDER_HALTED_BEFORE_CREATION"
    }
    captured_states = {"VERIFIED", "FOUNDER_REPORTED_CAPTURED"}
    for record in records:
        prefix = f"locator {record.get('locator_id')}"
        require_keys(
            errors,
            record,
            [
                "locator_id", "runtime_binding_id", "surface_kind",
                "account_or_workspace_alias", "state", "stable_locator",
                "resume_checkpoint", "return_path", "last_verified_at", "capture_trigger"
            ],
            prefix
        )
        state = record.get("state")
        add(errors, state in allowed_states, f"{prefix}: invalid locator state")
        stable = record.get("stable_locator")
        if state in captured_states:
            add(errors, bool(stable), f"{prefix}: captured surface without stable locator")
            add(errors, bool(record.get("resume_checkpoint")), f"{prefix}: captured surface without resume checkpoint")
            add(errors, bool(record.get("last_verified_at")), f"{prefix}: captured surface without observation time")
        else:
            add(errors, stable is None, f"{prefix}: pending surface contains invented locator")
            add(errors, bool(record.get("capture_trigger")), f"{prefix}: pending surface lacks capture trigger")
        if isinstance(stable, str):
            lowered = stable.lower()
            add(errors, "current_project_conversation" not in lowered, f"{prefix}: display/session alias used as stable locator")
            add(errors, not any(secret in lowered for secret in ("token=", "api_key=", "bearer ", "x-ops-gate")), f"{prefix}: locator contains credential material")

    sw = next((item for item in records if item.get("locator_id") == "LOC-SW-SPACE"), {})
    add(errors, sw.get("stable_locator") == "sw:space:1054976614269477", "locators: founder-verified SW space ID not preserved")


def validate_controls(data: dict[str, Any], errors: list[str]) -> None:
    add(errors, data.get("decision_changed") == [], "controls: unbound strategy change")
    controls = data.get("controls", [])
    ids = [item.get("error_id") for item in controls]
    add(errors, len(controls) >= 19, "controls: known error denominator incomplete")
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


def validate_durable_directives(root: Path, errors: list[str]) -> None:
    path = root / "state/FOUNDER-OPERATING-DIRECTIVES-20260822.md"
    add(errors, path.is_file(), "directives: repository-native founder content missing")
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    compact = " ".join(text.split())
    required = [
        "one hundred coworkers and agents",
        "discover/create → real-operation test → validate → extract → package → redeploy",
        "Manus must receive full useful administrative enablement across multiple",
        "prior founder directive records Qwen",
        "Kimi and DeepSeek",
        "Grok on Cursor",
        "voice-first",
        "ten working projects",
        "ten to twenty next operators",
        "data and knowledge governance office",
        "founder activation and acquisition package",
        "SO-02 founder browser/setup batch is halted",
        "Cursor owns the complete capability problem",
        "discovery seeds, not a shopping list",
        "comprehensive staged programme",
        "portable, reconstructable, Obzio-controlled",
    ]
    for phrase in required:
        add(errors, phrase in compact, f"directives: missing executable content: {phrase}")


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


def validate_role_scope_receipt(root: Path, data: dict[str, Any], errors: list[str]) -> None:
    add(errors, data.get("authority", {}).get("class") == "FOUNDER_BOUND_ROLE_SCOPE_DECISION", "role-scope receipt: exact founder authority missing")
    add(errors, data.get("authority", {}).get("role_scope_correction_id") == ROLE_SCOPE_CORRECTION_ID, "role-scope receipt: correction ID missing")
    add(errors, data.get("decision_changed") == ROLE_SCOPE_DECISION, "role-scope receipt: decision incomplete")
    add(errors, data.get("named_tool_binding") == [], "role-scope receipt: tool silently bound")
    add(errors, data.get("prior_browser_setup_batch", {}).get("new_state") == "FOUNDER_HALTED_NO_ACTION_AUTHORISED_CANDIDATE_EVIDENCE_ONLY", "role-scope receipt: browser batch not halted")
    add(errors, data.get("scoped_assignment", {}).get("owner") == "SCF-01/CUR-01", "role-scope receipt: Cursor ownership missing")
    add(errors, data.get("scoped_assignment", {}).get("current_interface_not_permanent_brain") is True, "role-scope receipt: Cursor made permanent brain")
    delivery = data.get("cursor_delivery", {})
    add(errors, delivery.get("direct_submission_state") == "NOT_DELIVERED", "role-scope receipt: blocked Cursor delivery misreported")
    add(errors, delivery.get("provider_acknowledgement") is None, "role-scope receipt: provider acknowledgement invented")
    add(errors, delivery.get("message_typed_or_submitted") is False, "role-scope receipt: message submission invented")
    packet = root / "launch/CURSOR-LAUNCH-NOW.md"
    if packet.is_file():
        packet_hash = hashlib.sha256(packet.read_bytes()).hexdigest()
        add(errors, delivery.get("packet_sha256") == packet_hash, "role-scope receipt: Cursor packet hash mismatch")
    protected = data.get("protected_noninterference", {})
    add(errors, bool(protected) and all(value is False for value in protected.values()), "role-scope receipt: protected mutation or incomplete noninterference record")


def validate_instruction_contracts(root: Path, errors: list[str]) -> None:
    commission = (root / "commissions/CURSOR-SCP-01.md").read_text(encoding="utf-8")
    environment_commission = (root / "commissions/CURSOR-OPERATING-ENVIRONMENT-01.md").read_text(encoding="utf-8")
    environment_compact = " ".join(environment_commission.lower().split())
    chatgpt_commission = (root / "commissions/CHATGPT-SIR-01.md").read_text(encoding="utf-8")
    launch = (root / "launch/CURSOR-LAUNCH-NOW.md").read_text(encoding="utf-8")
    sw_launch = (root / "launch/SW-LAUNCH-NOW.md").read_text(encoding="utf-8")
    add(errors, "receipts/so02/**" in commission, "cursor commission: receipt allowlist missing")
    add(errors, "receipts/workstreams/so02/control-plane/**" not in commission, "cursor commission: obsolete receipt allowlist present")
    add(errors, "https://cursor.com/t/meta-ai4p/agents/bc-7137a066-3242-43a2-a30e-9a352047b759" in launch, "cursor launch: live agent locator missing")
    add(errors, "Continue the existing operation" in launch, "cursor launch: existing operation continuation missing")
    add(errors, "CURSOR-OPERATING-ENVIRONMENT-01.md" in launch, "cursor launch: superseding operating-environment commission missing")
    add(errors, "The SO-02 founder browser/setup batch is **HALTED**" in launch, "cursor launch: browser/setup halt missing")
    add(errors, "Inspect Cursor itself first" in launch, "cursor launch: Cursor self-inspection not first")
    add(errors, "Do not make a full authenticated view of ChatGPT Projects" in launch, "cursor launch: Projects UI incorrectly governs orchestration")
    add(errors, "Aircrift/Aircraft" in launch and "research beyond" in launch.lower(), "cursor launch: broad discovery and ambiguous seed resolution missing")
    add(errors, "staged implementation programme" in launch and "stop conditions" in launch, "cursor launch: staged human guidance contract missing")
    add(errors, "portable, reconstructable and Obzio-controlled" in launch and "models and runtimes replaceable" in launch, "cursor launch: portability or runtime sovereignty missing")
    add(errors, "cursor/operating-environment-return-20260822-v001" in launch, "cursor launch: isolated return branch missing")
    add(errors, "Do not touch PO-03, PR #9" in launch, "cursor launch: protected workstreams missing")
    add(errors, "No named browser, model, extension, runtime, memory system or orchestration topology is founder-bound" in launch, "cursor launch: named stack still bound")

    for phrase in (
        "Inspect Cursor's own operating setup first",
        "research beyond all named discovery seeds",
        "Guide staged human implementation",
        "portable founder operating environment",
        "Do not execute the halted SO-02 browser/setup batch",
    ):
        add(errors, phrase.lower() in environment_compact, f"cursor environment commission: missing {phrase}")
    add(errors, "supporting function" in chatgpt_commission and "does not independently select architecture" in chatgpt_commission, "chatgpt commission: narrower support role missing")
    add(errors, "capability-factory/return-20260822-v001" in sw_launch, "SW launch: isolated return branch missing")
    add(errors, "Treat the selected source branch as read-only" in sw_launch, "SW launch: shared source branch write not rejected")
    add(errors, "1054976614269477" in sw_launch, "SW launch: founder-verified space ID missing")
    add(errors, "SW is paused — do not send a message" in sw_launch and "do not paste" in sw_launch, "SW launch: founder pause not fail-closed")
    add(errors, "every operation, thread, coworker, automation and return-branch URL or exact provider ID" in sw_launch, "SW launch: stable provider locator capture missing")

    browser_launch = (root / "launch/BROWSER-CONTROL-CANARY-NOW.md").read_text(encoding="utf-8")
    add(errors, browser_launch.startswith("# HALTED"), "browser launch: founder halt is not unmistakable")
    add(errors, "This file has no executable founder steps" in browser_launch, "browser launch: executable status not revoked")
    add(errors, "candidate evidence" in " ".join(browser_launch.lower().split()), "browser launch: historical work not classified as candidate evidence")
    for prohibited in ("Add to Chrome", "npx -y @playwright/mcp", "GOOSE_MODE=", "goose configure", "SO2-BROWSER-QUAL"):
        add(errors, prohibited not in browser_launch, f"browser launch: halted packet still contains executable instruction {prohibited}")

    lanes = (root / "launch/CHATGPT-LANES-NOW.md").read_text(encoding="utf-8")
    add(errors, lanes.count("## CGPT-") >= 12, "chatgpt lanes: fewer than twelve launch sheets")
    add(errors, "Project:" in lanes and "Model/effort:" in lanes and "Acceptance:" in lanes, "chatgpt lanes: launch contract incomplete")
    add(errors, "stable project URL or ID" in lanes and "stable chat/Work-thread" in lanes, "chatgpt lanes: stable locator capture missing")

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
        is_role_scope_correction = event.get("event_type") == "FOUNDER_ROLE_SCOPE_CORRECTION_APPLIED"
        if is_role_scope_correction:
            add(errors, event.get("authority", {}).get("class") == "FOUNDER_BOUND_ROLE_SCOPE_DECISION", f"{prefix}: founder role/scope correction lacks exact authority")
            add(errors, event.get("role_scope_snapshot_id") == ROLE_SCOPE_CORRECTION_ID, f"{prefix}: founder role/scope snapshot missing")
            add(errors, payload.get("decision_changed") == ROLE_SCOPE_DECISION, f"{prefix}: founder role/scope decision incomplete")
            add(errors, payload.get("named_tool_binding") == [], f"{prefix}: founder role/scope correction silently binds a tool")
        else:
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
    locators = read_json(root / "state/runtime-surface-locators.json")
    events = read_jsonl(root / "state/events.jsonl")
    validate_control_plane(root, control, errors)
    validate_sources(sources, errors)
    validate_plan(plan, errors)
    validate_controls(controls, errors)
    validate_locators(locators, errors)
    validate_durable_directives(root, errors)
    automation = read_json(root.parent.parent.parent / "receipts/so02/2026-08-22/po03-automation-reshape-20260822T0924Z.json")
    validate_automation_receipt(automation, errors)
    role_scope_receipt = read_json(root.parent.parent.parent / "receipts/so02/2026-08-22/founder-operating-environment-role-correction-20260822T173520Z.json")
    validate_role_scope_receipt(root, role_scope_receipt, errors)
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
