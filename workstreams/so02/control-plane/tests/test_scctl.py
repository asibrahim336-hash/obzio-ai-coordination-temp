from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/scctl.py"
SPEC = importlib.util.spec_from_file_location("scctl", MODULE_PATH)
scctl = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(scctl)


class ControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.control = scctl.read_json(self.root / "state/control-plane.json")

    def errors_for(self, value: dict) -> list[str]:
        errors: list[str] = []
        scctl.validate_control_plane(self.root, value, errors)
        return errors

    def test_seed_validates(self) -> None:
        self.assertEqual([], scctl.validate(self.root))

    def test_project_rebuilds_from_event_head(self) -> None:
        projection = scctl.project(self.root)
        self.assertEqual(20, projection["event_count"])
        self.assertEqual("ACTIVE_INTERIM", projection["subjects"]["SCF-01/CGPT-01"]["state"])

    def test_event_chain_is_valid(self) -> None:
        events = scctl.read_jsonl(self.root / "state/events.jsonl")
        errors: list[str] = []
        scctl.validate_events(events, errors)
        self.assertEqual([], errors)

    def test_tampered_event_is_rejected(self) -> None:
        events = scctl.read_jsonl(self.root / "state/events.jsonl")
        events[1]["subject"] = "tampered"
        errors: list[str] = []
        scctl.validate_events(events, errors)
        self.assertTrue(any("event hash mismatch" in item for item in errors))

    def test_broken_event_chain_is_rejected(self) -> None:
        events = scctl.read_jsonl(self.root / "state/events.jsonl")
        events[2]["previous_event_sha256"] = "0" * 64
        events[2]["event_sha256"] = scctl.canonical_event_hash(events[2])
        errors: list[str] = []
        scctl.validate_events(events, errors)
        self.assertTrue(any("broken hash chain" in item for item in errors))

    def test_strategy_change_without_binding_is_rejected(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["decision_changed"] = ["invented"]
        self.assertTrue(any("unbound strategy change" in item for item in self.errors_for(changed)))

    def test_cutover_before_gates_is_rejected(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["active_primary"] = "SCF-01/CUR-01"
        self.assertTrue(any("primary changed before" in item for item in self.errors_for(changed)))

    def test_cutover_after_all_gates_is_allowed(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["active_primary"] = "SCF-01/CUR-01"
        changed["cutover_evidence"] = {gate: True for gate in changed["cutover_gates"]}
        self.assertFalse(any("primary changed before" in item for item in self.errors_for(changed)))

    def test_cursor_cannot_be_promoted_without_two_route_evidence(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["orchestration_assignment"]["cursor_role_state"] = "MAJOR_ORCHESTRATION_LAYER_QUALIFIED"
        errors = self.errors_for(changed)
        self.assertTrue(any("promoted without two qualified routes" in item for item in errors))
        self.assertTrue(any("promoted without complete end-to-end evidence" in item for item in errors))

    def test_chatgpt_projects_ui_cannot_be_made_promotion_gate(self) -> None:
        changed = copy.deepcopy(self.control)
        qualification = changed["orchestration_assignment"]["cursor_control_surface_qualification"]
        qualification["projects_ui_probe_required_for_promotion"] = True
        self.assertTrue(any("artificial promotion gate" in item for item in self.errors_for(changed)))

    def test_unqualified_second_cursor_group_is_rejected(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["orchestration_assignment"]["cursor_control_surface_qualification"]["maximum_cursor_top_level_agents"] = 8
        self.assertTrue(any("second Cursor top-level agent" in item for item in self.errors_for(changed)))

    def test_execution_claim_without_locator_is_rejected(self) -> None:
        changed = copy.deepcopy(self.control)
        cursor = next(item for item in changed["runtime_bindings"] if item["binding_id"] == "SCF-01/CUR-01")
        cursor["state"] = "EXECUTING"
        cursor["provider_locator"] = None
        self.assertTrue(any("operational state without locator" in item for item in self.errors_for(changed)))

    def test_execution_claim_without_launch_receipt_is_rejected(self) -> None:
        changed = copy.deepcopy(self.control)
        cursor = next(item for item in changed["runtime_bindings"] if item["binding_id"] == "SCF-01/CUR-01")
        cursor["state"] = "EXECUTING"
        cursor["provider_locator"] = "agent/test"
        cursor["launch_receipt"] = None
        self.assertTrue(any("without launch receipt" in item for item in self.errors_for(changed)))

    def test_durable_claim_without_commit_is_rejected(self) -> None:
        changed = copy.deepcopy(self.control)
        cursor = next(item for item in changed["runtime_bindings"] if item["binding_id"] == "SCF-01/CUR-01")
        cursor.update({"state":"DURABLE","provider_locator":"agent/test","launch_receipt":"receipt/test"})
        self.assertTrue(any("without result commit" in item for item in self.errors_for(changed)))

    def test_durable_claim_without_readback_is_rejected(self) -> None:
        changed = copy.deepcopy(self.control)
        cursor = next(item for item in changed["runtime_bindings"] if item["binding_id"] == "SCF-01/CUR-01")
        cursor.update({"state":"DURABLE","provider_locator":"agent/test","launch_receipt":"receipt/test","result_commit":"abc"})
        self.assertTrue(any("without read-back" in item for item in self.errors_for(changed)))

    def test_durable_claim_without_parent_ingestion_is_rejected(self) -> None:
        changed = copy.deepcopy(self.control)
        cursor = next(item for item in changed["runtime_bindings"] if item["binding_id"] == "SCF-01/CUR-01")
        cursor.update({"state":"DURABLE","provider_locator":"agent/test","launch_receipt":"receipt/test","result_commit":"abc","remote_readback_sha256":"1" * 64})
        self.assertTrue(any("without parent ingestion" in item for item in self.errors_for(changed)))

    def test_provider_memory_cannot_be_canonical(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["canonical_store"]["provider_memory_is_canonical"] = True
        self.assertTrue(any("provider memory cannot" in item for item in self.errors_for(changed)))

    def test_runtime_binding_denominator_is_enforced(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["runtime_bindings"].pop()
        self.assertTrue(any("binding denominator" in item for item in self.errors_for(changed)))

    def test_runtime_binding_unknown_surface_locator_is_rejected(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["runtime_bindings"][0]["surface_locator_ids"] = ["LOC-NOT-REAL"]
        self.assertTrue(any("unknown surface locator" in item for item in self.errors_for(changed)))

    def test_po01_non_interference_is_enforced(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["protected_workstreams"][0]["contact_or_mutation_allowed"] = True
        self.assertTrue(any("PO-01 non-interference" in item for item in self.errors_for(changed)))

    def test_global_pointer_conflict_cannot_be_hidden(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["global_pointer_state"]["state"] = "RESOLVED"
        self.assertTrue(any("global pointer conflict" in item for item in self.errors_for(changed)))

    def test_founder_action_requires_nondelegable_reason(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["current_founder_actions"][0]["nondelegable_reason"] = "convenient"
        self.assertTrue(any("unqualified founder action" in item for item in self.errors_for(changed)))

    def test_founder_action_cannot_gate_programme(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["current_founder_actions"][0]["blocking_scope"] = "global"
        self.assertTrue(any("incorrectly gates" in item for item in self.errors_for(changed)))

    def test_multi_parent_requires_exactly_one_shared_writer(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["multi_parent_execution_contract"]["root_shared_writer_count"] = 8
        self.assertTrue(any("exactly one shared-state writer" in item for item in self.errors_for(changed)))

    def test_multi_parent_requires_isolated_parent_namespaces(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["multi_parent_execution_contract"]["isolated_parent_branch_and_namespace_required"] = False
        self.assertTrue(any("isolated parent branches" in item for item in self.errors_for(changed)))

    def test_nested_agent_lineage_denominator_is_enforced(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["multi_parent_execution_contract"]["nested_lineage_fields"].remove("parent_id")
        self.assertTrue(any("nested lineage denominator" in item for item in self.errors_for(changed)))

    def test_founder_cannot_be_candidate_merge_layer(self) -> None:
        changed = copy.deepcopy(self.control)
        changed["multi_parent_execution_contract"]["founder_is_comparison_retrieval_or_merge_layer"] = True
        self.assertTrue(any("founder cannot be" in item for item in self.errors_for(changed)))

    def test_sources_are_hash_bound(self) -> None:
        sources = scctl.read_json(self.root / "sources/SOURCE-REGISTER.json")
        sources["sources"][0]["sha256"] = "bad"
        errors: list[str] = []
        scctl.validate_sources(sources, errors)
        self.assertTrue(any("invalid SHA-256" in item for item in errors))

    def test_plan_denominator_is_enforced(self) -> None:
        plan = scctl.read_json(self.root / "state/PLAN-DURABILITY-MANIFEST.json")
        plan["items"] = plan["items"][:5]
        errors: list[str] = []
        scctl.validate_plan(plan, errors)
        self.assertTrue(any("denominator" in item for item in errors))

    def test_founder_reported_sw_space_locator_is_preserved(self) -> None:
        locators = scctl.read_json(self.root / "state/runtime-surface-locators.json")
        errors: list[str] = []
        scctl.validate_locators(locators, errors)
        self.assertEqual([], errors)
        sw = next(item for item in locators["records"] if item["locator_id"] == "LOC-SW-SPACE")
        self.assertEqual("sw:space:1054976614269477", sw["stable_locator"])

    def test_captured_surface_without_locator_is_rejected(self) -> None:
        locators = scctl.read_json(self.root / "state/runtime-surface-locators.json")
        sw = next(item for item in locators["records"] if item["locator_id"] == "LOC-SW-SPACE")
        sw["stable_locator"] = None
        errors: list[str] = []
        scctl.validate_locators(locators, errors)
        self.assertTrue(any("captured surface without stable locator" in item for item in errors))

    def test_pending_surface_cannot_contain_invented_locator(self) -> None:
        locators = scctl.read_json(self.root / "state/runtime-surface-locators.json")
        browser = next(item for item in locators["records"] if item["locator_id"] == "LOC-BROWSER-PLAYWRIGHT-CANARY")
        browser["stable_locator"] = "https://example.invalid/invented"
        errors: list[str] = []
        scctl.validate_locators(locators, errors)
        self.assertTrue(any("pending surface contains invented locator" in item for item in errors))

    def test_cursor_launch_is_observed_but_not_promoted(self) -> None:
        cursor = next(item for item in self.control["runtime_bindings"] if item["binding_id"] == "SCF-01/CUR-01")
        qualification = self.control["orchestration_assignment"]["cursor_control_surface_qualification"]
        self.assertEqual("FOUNDER_REPORTED_LAUNCHED_RUNNING_QUALIFICATION_PENDING", cursor["state"])
        self.assertEqual("https://cursor.com/t/meta-ai4p/agents/bc-7137a066-3242-43a2-a30e-9a352047b759", cursor["provider_locator"])
        self.assertEqual(0, qualification["qualified_route_count"])
        self.assertFalse(any(qualification["required_end_to_end_evidence"].values()))

    def test_sw_pause_is_fail_closed_before_message(self) -> None:
        sw = next(item for item in self.control["runtime_bindings"] if item["binding_id"] == "SCF-01/SW-01")
        launch = (self.root / "launch/SW-LAUNCH-NOW.md").read_text(encoding="utf-8")
        self.assertEqual("FOUNDER_PAUSED_BEFORE_COMMISSION_PENDING_OPEN_WEIGHT_CONTROL", sw["state"])
        self.assertIn("SW is paused — do not send a message", launch)
        self.assertIn("not active; do not paste", launch)

    def test_browser_selection_cannot_be_called_acceptance(self) -> None:
        changed = copy.deepcopy(self.control)
        browser = changed["orchestration_assignment"]["browser_control_replacement"]
        browser["selection_is_acceptance"] = True
        self.assertTrue(any("selection or installation treated as acceptance" in item for item in self.errors_for(changed)))

    def test_browser_first_canary_is_owned_deterministic_route(self) -> None:
        browser = self.control["orchestration_assignment"]["browser_control_replacement"]
        self.assertEqual("MICROSOFT_PLAYWRIGHT_EXTENSION_PLUS_LOCAL_GOOSE_OPEN_WEIGHT_MCP_CLIENT", browser["first_canary"])
        self.assertIn("PROPRIETARY_CLOUD_RELAY", browser["cloud_route_tradeoff"])
        self.assertFalse(browser["selection_is_acceptance"])

    def test_claude_capacity_is_not_quality_evidence(self) -> None:
        observation = self.control["provider_capacity_observations"][0]
        self.assertEqual("TOKEN_CAPACITY_EXHAUSTED_ROUTE_UNAVAILABLE", observation["state"])
        self.assertFalse(observation["quality_inference_allowed"])
        self.assertFalse(observation["retry_or_refill_required_now"])

    def test_known_error_controls_have_mechanisms_and_checks(self) -> None:
        controls = scctl.read_json(self.root / "errors/recurrence-controls.json")
        enforced = next(item for item in controls["controls"] if item["control_state"] == "ENFORCED")
        enforced["old_behaviour_probe"] = ""
        errors: list[str] = []
        scctl.validate_controls(controls, errors)
        self.assertTrue(any("enforced without old_behaviour_probe" in item for item in errors))

    def test_open_result_ref_fence_cannot_be_called_enforced(self) -> None:
        controls = scctl.read_json(self.root / "errors/recurrence-controls.json")
        lost_result = next(item for item in controls["controls"] if item["error_id"] == "ERR-LOST-RESULT")
        self.assertEqual("UNCONTROLLED", lost_result["control_state"])
        self.assertIn("result-ref fencing remains open", lost_result["uncontrolled_reason"])

    def test_po03_collision_remains_durable_after_bounded_isolated_route_reactivation(self) -> None:
        po03 = next(item for item in self.control["protected_workstreams"] if item["workstream_id"] == "PO-03")
        self.assertIn("SHARED_WORKTREE_COLLISION", po03["state"])
        self.assertIn("SHARED_ROUTE_REACTIVATED_ISOLATED_CLONES_ONLY_CEILING_TWO", po03["state"])
        self.assertIn("ROUTE_ISOLATION_EVIDENCE_INDEPENDENTLY_ACCEPTED_WITH_LIMITATIONS", po03["state"])
        self.assertIn("RESULT_REF_FENCING_OPEN", po03["state"])
        self.assertIn("NINE_PARENT_INGESTED", po03["state"])
        self.assertIn("TWO_REACTIVATED_ISOLATED_CLONE_UNITS_RUNNING", po03["state"])
        self.assertIn("54_CREATED_NOT_DISPATCHED", po03["state"])
        self.assertIn("INDEPENDENT_PO03_ACCEPTANCE_PENDING", po03["state"])
        controls = scctl.read_json(self.root / "errors/recurrence-controls.json")
        shared_writer = next(item for item in controls["controls"] if item["error_id"] == "ERR-MULTI-PARENT-SHARED-WRITER")
        self.assertEqual("UNCONTROLLED", shared_writer["control_state"])
        self.assertIn("historical collision", shared_writer["uncontrolled_reason"])
        self.assertIn("result-ref fencing is open", shared_writer["uncontrolled_reason"])

    def test_typed_maturity_labels_are_rejected(self) -> None:
        controls = scctl.read_json(self.root / "errors/recurrence-controls.json")
        controls["controls"][0]["mechanism_maturity"] = "LIVE_CANARY"
        errors: list[str] = []
        scctl.validate_controls(controls, errors)
        self.assertTrue(any("typed maturity is prohibited" in item for item in errors))

    def test_uncontrolled_control_requires_reason_and_next_control(self) -> None:
        controls = scctl.read_json(self.root / "errors/recurrence-controls.json")
        uncontrolled = next(item for item in controls["controls"] if item["control_state"] == "UNCONTROLLED")
        uncontrolled["uncontrolled_reason"] = ""
        errors: list[str] = []
        scctl.validate_controls(controls, errors)
        self.assertTrue(any("uncontrolled without uncontrolled_reason" in item for item in errors))

    def test_repository_native_founder_content_is_complete(self) -> None:
        errors: list[str] = []
        scctl.validate_durable_directives(self.root, errors)
        self.assertEqual([], errors)

    def test_event_triggered_automation_old_behaviour_is_rejected(self) -> None:
        receipt = scctl.read_json(self.root.parent.parent.parent / "receipts/so02/2026-08-22/po03-automation-reshape-20260822T0924Z.json")
        receipt["replacement_job"]["trigger"] = "github_pull_request_event"
        errors: list[str] = []
        scctl.validate_automation_receipt(receipt, errors)
        self.assertTrue(any("replacement can still fire per event" in item for item in errors))

    def test_independent_evaluation_file_and_active_lane_prompts_are_required(self) -> None:
        evaluation = (self.root / "evaluations/INDEPENDENT-PO02-PO03-20260822.md").read_text(encoding="utf-8")
        lanes = (self.root / "launch/CHATGPT-LANES-NOW.md").read_text(encoding="utf-8")
        self.assertIn("eight kill positions PASS", evaluation)
        self.assertIn("seven executable tests PASS", evaluation)
        self.assertGreaterEqual(lanes.count("## CGPT-"), 12)

    def test_strategy_decision_event_requires_founder_binding(self) -> None:
        events = scctl.read_jsonl(self.root / "state/events.jsonl")
        event = copy.deepcopy(events[-1])
        event["sequence"] = 5
        event["previous_event_sha256"] = events[-1]["event_sha256"]
        event["event_id"] = "SCF01-EVT-0005"
        event["idempotency_key"] = "SCF01-EVT-0005"
        event["event_type"] = "STRATEGY_DECISION"
        event["event_sha256"] = scctl.canonical_event_hash(event)
        errors: list[str] = []
        scctl.validate_events(events + [event], errors)
        self.assertTrue(any("strategy decision lacks founder binding" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
