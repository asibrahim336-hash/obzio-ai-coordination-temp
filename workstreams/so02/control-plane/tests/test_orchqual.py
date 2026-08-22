from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/orchqual.py"
SPEC = importlib.util.spec_from_file_location("orchqual", MODULE_PATH)
orchqual = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(orchqual)


class WriteScopeGuardTests(unittest.TestCase):
    """The guard must reject the wrong-target writes this commission forbids."""

    def test_allowlisted_paths_pass(self) -> None:
        paths = [
            "workstreams/so02/control-plane/state/CUR-ORCH-QUAL-01.json",
            "receipts/so02/2026-08-22/cur-orch-qual-01/EVIDENCE-MANIFEST.json",
            ".github/workflows/so02-control-plane-contracts.yml",
        ]
        self.assertEqual([], orchqual.guard_paths(paths, orchqual.QUALIFICATION_BRANCH))

    def test_po03_owned_path_is_refused(self) -> None:
        refusals = orchqual.guard_paths(["workstreams/po03/COMMISSION.md"], orchqual.QUALIFICATION_BRANCH)
        self.assertTrue(any("outside the SO-02 write allowlist" in item for item in refusals))

    def test_global_pointer_state_is_refused(self) -> None:
        refusals = orchqual.guard_paths(["state/ACTIVE_CONTROL_POINTER_CURRENT.json"], orchqual.QUALIFICATION_BRANCH)
        self.assertTrue(any("outside the SO-02 write allowlist" in item for item in refusals))

    def test_unscoped_workflow_is_refused(self) -> None:
        refusals = orchqual.guard_paths([".github/workflows/po03-contracts.yml"], orchqual.QUALIFICATION_BRANCH)
        self.assertTrue(any("outside the SO-02 write allowlist" in item for item in refusals))

    def test_escaping_path_is_refused(self) -> None:
        refusals = orchqual.guard_paths(["receipts/so02/../../etc/passwd"], orchqual.QUALIFICATION_BRANCH)
        self.assertTrue(any("non-portable or escaping path" in item for item in refusals))

    def test_selected_so02_source_branch_is_refused(self) -> None:
        refusals = orchqual.guard_paths([], "so02/strategic-control-plane-migration-20260822-v001")
        self.assertTrue(any("protected target" in item for item in refusals))

    def test_pr9_branch_and_po03_namespace_are_refused(self) -> None:
        self.assertTrue(any(
            "protected" in item
            for item in orchqual.guard_paths([], "po03/repository-engineering-portable-runtime-20260822-v001")
        ))
        self.assertTrue(any(
            "protected namespace" in item
            for item in orchqual.guard_paths([], "cursor/po03-wave-a-factory-6e19")
        ))

    def test_main_and_pr6_pr7_branches_are_refused(self) -> None:
        for branch in ("main", "soo/v003-currentness-repair-20260820",
                       "soo/v003-controlling-pointer-and-part-manifest-repair-20260820"):
            self.assertTrue(orchqual.guard_paths([], branch), f"{branch} should be refused")


class CapacityInterferenceTests(unittest.TestCase):
    """Any queue, pause, eviction or admission refusal on pre-existing PO-03 is a FAIL."""

    def base_observation(self) -> dict:
        agents = [
            {"bcId": "bc-po03-a", "status": "RUNNING", "isKilled": False, "updatedAtMs": 1},
            {"bcId": "bc-po03-b", "status": "IDLE", "isKilled": False, "updatedAtMs": 1},
        ]
        return {
            "orchestrator_bc_id": "bc-self",
            "capacity_observation_state": "CAPACITY_OBSERVATION_AVAILABLE",
            "snapshots": [
                {"label": "T0", "observed_at": "t0", "agents": copy.deepcopy(agents)},
                {"label": "T+60", "observed_at": "t1", "agents": copy.deepcopy(agents)},
                {"label": "completion", "observed_at": "t2", "agents": copy.deepcopy(agents)},
            ],
        }

    def test_unchanged_states_pass(self) -> None:
        verdict, findings = orchqual.capacity_verdict(self.base_observation())
        self.assertEqual("ZERO_PO03_CAPACITY_INTERFERENCE", verdict)
        self.assertEqual([], findings)

    def test_queued_transition_fails(self) -> None:
        observation = self.base_observation()
        observation["snapshots"][1]["agents"][0]["status"] = "QUEUED"
        verdict, findings = orchqual.capacity_verdict(observation)
        self.assertEqual("CAPACITY_INTERFERENCE_FAIL", verdict)
        self.assertTrue(any("RUNNING -> QUEUED" in item for item in findings))

    def test_paused_and_evicted_transitions_fail(self) -> None:
        for status in ("PAUSED", "EVICTED", "ADMISSION_REFUSED"):
            observation = self.base_observation()
            observation["snapshots"][2]["agents"][1]["status"] = status
            verdict, _ = orchqual.capacity_verdict(observation)
            self.assertEqual("CAPACITY_INTERFERENCE_FAIL", verdict, status)

    def test_disappearing_pre_existing_task_fails(self) -> None:
        observation = self.base_observation()
        observation["snapshots"][2]["agents"] = observation["snapshots"][2]["agents"][:1]
        verdict, findings = orchqual.capacity_verdict(observation)
        self.assertEqual("CAPACITY_INTERFERENCE_FAIL", verdict)
        self.assertTrue(any("disappeared" in item for item in findings))

    def test_killed_pre_existing_task_fails(self) -> None:
        observation = self.base_observation()
        observation["snapshots"][1]["agents"][0]["isKilled"] = True
        verdict, findings = orchqual.capacity_verdict(observation)
        self.assertEqual("CAPACITY_INTERFERENCE_FAIL", verdict)
        self.assertTrue(any("killed" in item for item in findings))

    def test_orchestrator_own_transitions_are_not_interference(self) -> None:
        observation = self.base_observation()
        for snapshot in observation["snapshots"]:
            snapshot["agents"].append({"bcId": "bc-self", "status": "RUNNING", "isKilled": False, "updatedAtMs": 1})
        observation["snapshots"][2]["agents"][-1]["status"] = "PAUSED"
        verdict, _ = orchqual.capacity_verdict(observation)
        self.assertEqual("ZERO_PO03_CAPACITY_INTERFERENCE", verdict)

    def test_missing_snapshots_are_incomplete_not_pass(self) -> None:
        observation = self.base_observation()
        observation["snapshots"] = observation["snapshots"][:2]
        verdict, _ = orchqual.capacity_verdict(observation)
        self.assertEqual("INCOMPLETE", verdict)

    def test_unavailable_observation_is_reported_not_assumed_clean(self) -> None:
        observation = self.base_observation()
        observation["capacity_observation_state"] = "CAPACITY_OBSERVATION_UNAVAILABLE"
        verdict, _ = orchqual.capacity_verdict(observation)
        self.assertEqual("CAPACITY_OBSERVATION_UNAVAILABLE", verdict)


class EvidenceBundleTests(unittest.TestCase):
    def test_seeded_evidence_verifies_offline(self) -> None:
        self.assertEqual([], orchqual.verify(offline=True))

    def test_manifest_covers_every_bundle_file(self) -> None:
        manifest = orchqual.read_json(orchqual.MANIFEST_PATH)
        manifested = {entry["path"] for entry in manifest["entries"]}
        observed = {path.relative_to(orchqual.REPO).as_posix() for path in orchqual.bundle_files()}
        self.assertEqual(observed, manifested)

    def test_recomputed_manifest_matches_the_committed_one(self) -> None:
        committed = orchqual.read_json(orchqual.MANIFEST_PATH)
        rebuilt = orchqual.build_manifest()
        self.assertEqual(committed["bundle_sha256"], rebuilt["bundle_sha256"])
        self.assertEqual(committed["entries"], rebuilt["entries"])

    def test_tampered_artifact_breaks_the_bundle_hash(self) -> None:
        manifest = orchqual.read_json(orchqual.MANIFEST_PATH)
        tampered = copy.deepcopy(manifest["entries"])
        tampered[0]["sha256"] = "0" * 64
        self.assertNotEqual(
            manifest["bundle_sha256"],
            orchqual.sha256_bytes(orchqual.canonical_bytes(tampered)),
        )

    def test_omitted_artifact_breaks_the_bundle_hash(self) -> None:
        manifest = orchqual.read_json(orchqual.MANIFEST_PATH)
        self.assertNotEqual(
            manifest["bundle_sha256"],
            orchqual.sha256_bytes(orchqual.canonical_bytes(manifest["entries"][:-1])),
        )

    def test_file_hash_is_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.txt"
            path.write_bytes(b"obzio")
            self.assertEqual(orchqual.sha256_bytes(b"obzio"), orchqual.sha256_file(path))


class RouteRegisterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = orchqual.read_json(orchqual.QUALIFICATION_PATH)

    def errors_for(self, value: dict) -> list[str]:
        original = orchqual.QUALIFICATION_PATH.read_text(encoding="utf-8")
        try:
            orchqual.QUALIFICATION_PATH.write_text(json.dumps(value), encoding="utf-8")
            errors: list[str] = []
            orchqual.verify_qualification(errors)
            return errors
        finally:
            orchqual.QUALIFICATION_PATH.write_text(original, encoding="utf-8")

    def with_one_qualified_route(self) -> tuple[dict, dict]:
        """A register carrying exactly one fully-evidenced qualified route.

        Synthesised rather than taken from live state so these invariants hold
        in the pre-read-back phase as well as the reconciled one.
        """
        changed = copy.deepcopy(self.data)
        changed["phase"] = orchqual.PHASE_COMPLETED
        route = changed["routes"][0]
        for other in changed["routes"][1:]:
            if other["availability"] == "QUALIFIED":
                other["availability"] = "AVAILABLE_NOT_QUALIFIED"
                other["evidence"]["remote_byte_for_byte_readback"] = False
        route["availability"] = "QUALIFIED"
        route["evidence"] = {key: True for key in orchqual.ROUTE_EVIDENCE_KEYS}
        route.setdefault("stable_locators", [])
        if not route["stable_locators"]:
            route["stable_locators"] = [{"kind": "probe", "locator": "https://example.invalid/probe"}]
        changed["qualified_route_count"] = 1
        changed["aggregate_classification"] = "PASS_ONE_ROUTE_PARTIAL"
        return changed, route

    def test_seeded_register_is_valid(self) -> None:
        errors: list[str] = []
        orchqual.verify_qualification(errors)
        self.assertEqual([], errors)

    def test_synthesised_single_qualified_route_register_is_accepted(self) -> None:
        changed, _ = self.with_one_qualified_route()
        self.assertEqual([], self.errors_for(changed))

    def test_at_least_two_independent_routes_are_qualified(self) -> None:
        if self.data["phase"] != orchqual.PHASE_COMPLETED:
            self.skipTest("route qualification is asserted only in the reconciled phase")
        qualified = [route for route in self.data["routes"] if route["availability"] == "QUALIFIED"]
        self.assertGreaterEqual(len(qualified), 2)
        transports = {route["transport"] for route in qualified}
        self.assertGreaterEqual(len(transports), 2, "qualified routes must not share one transport")

    def test_route_cannot_be_qualified_without_remote_readback(self) -> None:
        changed, route = self.with_one_qualified_route()
        route["evidence"]["remote_byte_for_byte_readback"] = False
        self.assertTrue(any("without complete end-to-end evidence" in item for item in self.errors_for(changed)))

    def test_route_cannot_be_qualified_without_stable_locator(self) -> None:
        changed, route = self.with_one_qualified_route()
        route["stable_locators"] = []
        self.assertTrue(any("without a stable locator" in item for item in self.errors_for(changed)))

    def test_locator_carrying_a_credential_is_rejected(self) -> None:
        changed, route = self.with_one_qualified_route()
        route["stable_locators"][0]["locator"] = "https://example.invalid/x?token=abcd"
        self.assertTrue(any("credential material" in item for item in self.errors_for(changed)))

    def test_blocked_route_requires_an_exact_owner_action(self) -> None:
        changed = copy.deepcopy(self.data)
        route = next(item for item in changed["routes"] if item["availability"] == "OWNER_REQUIRED")
        route["owner_required_action"] = ""
        self.assertTrue(any("without an exact owner action" in item for item in self.errors_for(changed)))

    def test_second_top_level_agent_is_rejected(self) -> None:
        changed = copy.deepcopy(self.data)
        changed["orchestrator"]["top_level_agent_count"] = 2
        self.assertTrue(any("more than one top-level agent" in item for item in self.errors_for(changed)))

    def test_subagent_or_group_use_is_rejected(self) -> None:
        changed = copy.deepcopy(self.data)
        changed["orchestrator"]["cursor_subagents_started"] = 1
        self.assertTrue(any("Cursor subagent was started" in item for item in self.errors_for(changed)))
        changed = copy.deepcopy(self.data)
        changed["orchestrator"]["multiple_agents_groups_started"] = 1
        self.assertTrue(any("Multiple Agents group was started" in item for item in self.errors_for(changed)))

    def test_auto_model_alias_is_rejected(self) -> None:
        changed = copy.deepcopy(self.data)
        changed["orchestrator"]["exact_model_configuration"] = "Auto"
        self.assertTrue(any("must not be Auto" in item for item in self.errors_for(changed)))

    def test_pass_cannot_admit_a_second_group_or_cutover(self) -> None:
        for key in ("additional_cursor_multiple_agents_group", "merge_promotion_or_cutover",
                    "exclusive_dependence_on_cursor_or_sw", "strategy_binding",
                    "chatgpt_projects_ui_required"):
            changed = copy.deepcopy(self.data)
            changed["admits"][key] = True
            self.assertTrue(self.errors_for(changed), key)

    def test_self_acceptance_is_rejected(self) -> None:
        changed = copy.deepcopy(self.data)
        changed["independent_acceptance"]["self_accepted"] = True
        self.assertTrue(any("self-acceptance is prohibited" in item for item in self.errors_for(changed)))

    def test_producing_run_cannot_be_the_acceptor(self) -> None:
        changed = copy.deepcopy(self.data)
        changed["independent_acceptance"]["acceptor"] = changed["orchestrator"]["provider_run_id"]
        self.assertTrue(any("acceptor must not be the producing run" in item for item in self.errors_for(changed)))

    def test_route_cannot_be_qualified_before_the_reconciled_phase(self) -> None:
        changed, _ = self.with_one_qualified_route()
        changed["phase"] = orchqual.PHASE_READY
        changed["aggregate_classification"] = "READY_TO_COMMIT_REMOTE_READBACK_PENDING"
        self.assertTrue(any("qualified before the reconciled phase" in item for item in self.errors_for(changed)))

    def test_ready_to_commit_phase_cannot_claim_a_pass(self) -> None:
        changed = copy.deepcopy(self.data)
        changed["phase"] = orchqual.PHASE_READY
        changed["aggregate_classification"] = "PASS_TWO_OR_MORE_ROUTES"
        errors = self.errors_for(changed)
        self.assertTrue(any("must be READY_TO_COMMIT_REMOTE_READBACK_PENDING" in item for item in errors))

    def test_capacity_interference_overrides_a_route_pass(self) -> None:
        changed = copy.deepcopy(self.data)
        changed["capacity_verdict"] = "CAPACITY_INTERFERENCE_FAIL"
        errors = self.errors_for(changed)
        self.assertTrue(any("must be CAPACITY_INTERFERENCE_FAIL" in item for item in errors))

    def test_unavailable_route_is_inventoried_rather_than_dropped(self) -> None:
        route_ids = {route["route_id"] for route in self.data["routes"]}
        for required in ("R4-OPENAI-RESPONSES-CONVERSATIONS", "R5-CHATGPT-PROJECTS-BROWSER", "R6-SW-RETURN-EXCHANGE"):
            self.assertIn(required, route_ids)

    def test_every_fallback_exercise_failed_closed(self) -> None:
        self.assertGreaterEqual(len(self.data["fallback_exercises"]), 1)
        for exercise in self.data["fallback_exercises"]:
            self.assertTrue(exercise["fail_closed"])
            self.assertTrue(exercise["programme_continued"])


class RemoteReadbackTests(unittest.TestCase):
    def errors_for(self, value: dict) -> list[str]:
        original = orchqual.READBACK_PATH.read_text(encoding="utf-8") if orchqual.READBACK_PATH.is_file() else None
        try:
            orchqual.READBACK_PATH.write_text(json.dumps(value), encoding="utf-8")
            errors: list[str] = []
            orchqual.verify_readback(errors)
            return errors
        finally:
            if original is None:
                orchqual.READBACK_PATH.unlink(missing_ok=True)
            else:
                orchqual.READBACK_PATH.write_text(original, encoding="utf-8")

    def sample(self) -> dict:
        return {
            "immutable_commit": "a" * 40,
            "bundle_sha256": "b" * 64,
            "entry_count": 1,
            "transports": ["git_protocol_fetch_by_immutable_sha", "github_rest_git_blobs_api"],
            "comparisons": [{
                "path": "receipts/so02/x.json",
                "local_sha256": "c" * 64,
                "remote_git_sha256": "c" * 64,
                "identical_git_transport": True,
            }],
            "mismatches": [],
            "result": "REMOTE_BYTE_FOR_BYTE_IDENTICAL",
        }

    def test_valid_readback_passes(self) -> None:
        self.assertEqual([], self.errors_for(self.sample()))

    def test_single_transport_readback_is_rejected(self) -> None:
        record = self.sample()
        record["transports"] = ["git_protocol_fetch_by_immutable_sha"]
        self.assertTrue(any("fewer than two independent transports" in item for item in self.errors_for(record)))

    def test_byte_divergence_is_rejected(self) -> None:
        record = self.sample()
        record["comparisons"][0]["remote_git_sha256"] = "d" * 64
        record["comparisons"][0]["identical_git_transport"] = False
        self.assertTrue(self.errors_for(record))

    def test_declared_pass_with_recorded_mismatch_is_rejected(self) -> None:
        record = self.sample()
        record["mismatches"] = ["receipts/so02/x.json: remote git bytes differ from local bytes"]
        self.assertTrue(any("unresolved byte mismatch" in item for item in self.errors_for(record)))

    def test_non_immutable_commit_reference_is_rejected(self) -> None:
        record = self.sample()
        record["immutable_commit"] = "HEAD"
        self.assertTrue(any("immutable commit not recorded" in item for item in self.errors_for(record)))

    def test_completed_phase_without_a_readback_record_is_rejected(self) -> None:
        original = orchqual.READBACK_PATH.read_text(encoding="utf-8") if orchqual.READBACK_PATH.is_file() else None
        if original is None:
            self.skipTest("read-back record not yet produced")
        try:
            orchqual.READBACK_PATH.unlink()
            errors: list[str] = []
            orchqual.verify_readback(errors)
            self.assertTrue(any("without a remote read-back record" in item for item in errors))
        finally:
            orchqual.READBACK_PATH.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
