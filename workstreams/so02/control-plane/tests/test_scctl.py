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
        self.assertEqual(16, projection["event_count"])
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

    def test_execution_claim_without_locator_is_rejected(self) -> None:
        changed = copy.deepcopy(self.control)
        cursor = next(item for item in changed["runtime_bindings"] if item["binding_id"] == "SCF-01/CUR-01")
        cursor["state"] = "EXECUTING"
        self.assertTrue(any("operational state without locator" in item for item in self.errors_for(changed)))

    def test_execution_claim_without_launch_receipt_is_rejected(self) -> None:
        changed = copy.deepcopy(self.control)
        cursor = next(item for item in changed["runtime_bindings"] if item["binding_id"] == "SCF-01/CUR-01")
        cursor["state"] = "EXECUTING"
        cursor["provider_locator"] = "agent/test"
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

    def test_known_error_controls_have_mechanisms_and_checks(self) -> None:
        controls = scctl.read_json(self.root / "errors/recurrence-controls.json")
        controls["controls"][0]["executable_check"] = ""
        errors: list[str] = []
        scctl.validate_controls(controls, errors)
        self.assertTrue(any("missing executable_check" in item for item in errors))

    def test_lost_result_control_reached_live_canary_after_worker_ingestion(self) -> None:
        controls = scctl.read_json(self.root / "errors/recurrence-controls.json")
        lost_result = next(item for item in controls["controls"] if item["error_id"] == "ERR-LOST-RESULT")
        self.assertEqual("LIVE_CANARY", lost_result["mechanism_maturity"])

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
        self.assertEqual("INDEPENDENTLY_ACCEPTED", shared_writer["mechanism_maturity"])
        self.assertEqual(
            "PO03_CONCURRENT_SHARED_WORKTREE_INDEX_BRANCH_COLLISION_OBSERVED",
            shared_writer["latest_live_defect"]["state"],
        )
        self.assertIn("independently verified and reactivated only at the proven two-unit ceiling", shared_writer["latest_live_defect"]["control_not_promoted_reason"])
        self.assertIn("result-ref fencing remains open", shared_writer["latest_live_defect"]["control_not_promoted_reason"])

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
