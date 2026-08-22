"""Reproduction for total provider-runtime loss and the frozen Code-2 fixture.

Hypothesis under test: entire provider-runtime loss produces
PROVIDER_COMPLETED_UNCOMMITTED, never COMPLETED, and the lost PO-02 Code-2
return is a permanent fault fixture rather than a deliverable.

The runtime loss is a real SIGKILL of the whole child worker.  The fixture is
checked against its commissioned states and against the recorded evidence it
corroborates, including the two places where the recorded labels differ; both
labels are held verbatim rather than reconciled away.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kit = _load("po03_c6_048_kit", "fault_kit.py")
injector = _load("po03_c6_048_injector", "provider_loss_injector.py")


class ProviderLossTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)


class RuntimeLossTests(ProviderLossTestCase):
    def test_loss_after_a_reported_completion_never_reaches_completed(self):
        result = injector.inject_runtime_loss(
            self.root, "AFTER_PROVIDER_REPORTED_COMPLETION_BEFORE_ANY_COMMIT"
        )
        observed = result["observed"]
        self.assertTrue(result["crash"]["killed_by_sigkill"])
        self.assertEqual(
            ["CREATED", "LEASED", "RUNNING", "PROVIDER_COMPLETED_UNCOMMITTED"],
            observed["event_states"],
        )
        self.assertTrue(observed["provider_reported_completion"])
        self.assertFalse(observed["obzio_completed_event_present"])
        self.assertFalse(observed["completion_file_present"])
        self.assertEqual([], observed["durable_result_committed"])
        self.assertEqual(0, observed["ingestion_records"])
        self.assertEqual(0, observed["false_completion_count"])
        self.assertEqual("PASS", result["verdict"])

    def test_loss_after_a_reported_completion_is_resumable_from_immutable_input(self):
        result = injector.inject_runtime_loss(
            self.root, "AFTER_PROVIDER_REPORTED_COMPLETION_BEFORE_ANY_COMMIT"
        )
        observed = result["observed"]
        self.assertEqual("RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT", observed["recovery_action"])
        self.assertTrue(observed["immutable_input_available_for_rerun"])
        self.assertEqual([], observed["event_chain_errors"])

    def test_loss_before_any_report_leaves_no_provider_claim_at_all(self):
        result = injector.inject_runtime_loss(self.root, "AFTER_STAGING_BEFORE_PROVIDER_REPORT")
        observed = result["observed"]
        self.assertEqual(["CREATED", "LEASED", "RUNNING"], observed["event_states"])
        self.assertFalse(observed["provider_reported_completion"])
        self.assertEqual(0, observed["false_completion_count"])
        self.assertEqual("PASS", result["verdict"])


class ContractRefusalTests(ProviderLossTestCase):
    def test_a_completed_claim_without_a_result_commit_is_refused(self):
        result = injector.inject_contract_refusal(self.root)
        observed = result["observed"]
        self.assertTrue(observed["completed_claim_refused"])
        self.assertIn(
            "$.obzio_state: provider completion without result commit must be PROVIDER_COMPLETED_UNCOMMITTED",
            observed["completed_claim_errors"],
        )

    def test_provider_completed_uncommitted_is_the_only_legal_state_for_that_shape(self):
        result = injector.inject_contract_refusal(self.root)
        self.assertTrue(result["observed"]["provider_completed_uncommitted_is_the_only_legal_state"])

    def test_a_producer_cannot_self_accept(self):
        result = injector.inject_contract_refusal(self.root)
        self.assertIn(
            "$.independent_acceptance.reviewer_id: producer cannot self-accept",
            result["observed"]["self_acceptance_errors"],
        )

    def test_completion_is_refused_before_parent_ingested(self):
        result = injector.inject_contract_refusal(self.root)
        self.assertEqual(
            "po03-c6-048-contract-unit: cannot complete before PARENT_INGESTED",
            result["observed"]["complete_unit_refusal"],
        )

    def test_a_result_with_no_artifacts_cannot_be_ingested(self):
        result = injector.inject_contract_refusal(self.root)
        self.assertEqual("RECOVERY_REQUIRED", result["observed"]["ingestion_state"])
        self.assertIn(
            "result carries no artifacts; nothing durable to ingest",
            result["observed"]["ingestion_errors"],
        )


class FrozenFixtureTests(ProviderLossTestCase):
    def test_the_fixture_carries_exactly_the_four_commissioned_states(self):
        fixture = injector.load_fixture()
        self.assertEqual(
            {
                "provider_state": "COMPLETION_REPORTED_OR_LIVE_CONFLICT",
                "obzio_state": "PROVIDER_COMPLETED_UNCOMMITTED",
                "result_state": "UNRECOVERED_AFTER_FOUR_REPORTED_ROUTES",
                "acceptance_state": "NOT_ACCEPTED",
            },
            fixture["frozen_states"],
        )
        self.assertEqual(4, fixture["reported_routes_count"])

    def test_the_fixture_is_never_described_as_a_completed_deliverable(self):
        fixture = injector.load_fixture()
        self.assertFalse(fixture["is_a_completed_deliverable"])
        self.assertFalse(fixture["may_be_described_as_a_deliverable"])
        self.assertEqual("PERMANENT_FAULT_FIXTURE", fixture["classification"])
        serialised = json.dumps(fixture)
        for claim in injector.FORBIDDEN_CLAIMS:
            with self.subTest(claim=claim):
                self.assertNotIn(claim, serialised)

    def test_the_fixture_carries_no_durable_result(self):
        fixture = injector.load_fixture()
        self.assertIsNone(fixture["durable_result_commit_id"])
        self.assertEqual([], fixture["durable_artifacts"])

    def test_the_fixture_matches_the_recorded_evidence_it_cites(self):
        fixture = injector.load_fixture()
        evidence_bytes = injector.EVIDENCE.read_bytes()
        citation = fixture["corroborating_recorded_evidence"]
        self.assertEqual(hashlib.sha256(evidence_bytes).hexdigest(), citation["sha256"])
        self.assertEqual(len(evidence_bytes), citation["bytes"])
        rulings = json.loads(evidence_bytes.decode("utf-8"))["evidence_rulings"]
        self.assertEqual(
            {
                "code2_provider_state": rulings["code2_provider_state"],
                "code2_obzio_state": rulings["code2_obzio_state"],
                "code2_result_state": rulings["code2_result_state"],
                "code2_acceptance_state": rulings["code2_acceptance_state"],
            },
            citation["recorded_values_verbatim"],
        )

    def test_the_two_label_differences_are_recorded_rather_than_reconciled_away(self):
        fixture = injector.load_fixture()
        by_field = {item["field"]: item for item in fixture["state_reconciliation"]}
        self.assertEqual("SAME_MEANING_DIFFERENT_LABEL", by_field["result_state"]["agreement"])
        self.assertEqual(
            "UNRECOVERED_AFTER_FOUR_FOUNDER_REPORTED_ROUTES",
            by_field["result_state"]["recorded_evidence_value"],
        )
        self.assertEqual("NARROWER_IN_THE_FIXTURE", by_field["acceptance_state"]["agreement"])
        self.assertEqual("NOT_TESTED", by_field["acceptance_state"]["recorded_evidence_value"])

    def test_the_fixture_inspection_passes_every_check(self):
        result = injector.inspect_fixture()
        self.assertEqual("PASS", result["verdict"])
        self.assertTrue(result["observed"]["frozen_states_match_commission"])
        self.assertTrue(result["observed"]["evidence_hash_matches"])


class FounderRelayTests(ProviderLossTestCase):
    def test_recovery_needs_no_founder_relay(self):
        result = injector.inspect_founder_relay(self.root)
        observed = result["observed"]
        self.assertEqual(["run_id", "head_sha"], observed["scan_recovery_parameters"])
        self.assertTrue(observed["scan_recovery_reads_only_repository_state"])
        self.assertEqual([], observed["founder_supplied_inputs"])
        self.assertEqual("PASS", result["verdict"])

    def test_the_fixture_declares_no_founder_relay_requirement(self):
        fixture = injector.load_fixture()
        self.assertFalse(fixture["founder_relay_required_for_recovery"])
        self.assertIn("immutable input capsule", fixture["recovery_route_without_founder_relay"])


class AggregateTests(ProviderLossTestCase):
    def test_unit_passes_with_no_false_completion(self):
        report = injector.inject_all(self.root)
        self.assertEqual(5, report["fault_classes"])
        self.assertEqual("PASS", report["verdict"])
        self.assertEqual(0, report["false_completions_observed"])
        self.assertFalse(report["code2_is_a_completed_deliverable"])


if __name__ == "__main__":
    unittest.main()
