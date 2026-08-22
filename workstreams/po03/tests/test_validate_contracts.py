import copy
import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "validate_contracts.py"
SPEC = importlib.util.spec_from_file_location("validate_contracts", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


H = "a" * 64


def committed_result():
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": "po03-test-1",
        "commission_id": "COM-PO03",
        "immutable_input_manifest_sha256": H,
        "acceptance_contract_sha256": H,
        "provider_state": "COMPLETED",
        "obzio_state": "COMPLETED",
        "attempt": {
            "attempt_id": "attempt-1",
            "idempotency_key": "po03-test-1:1",
            "lease_id": "lease-1",
            "fence_token": 1,
            "provider_run_id": "provider-run-1",
            "worker_id": "producer-1",
            "heartbeat_at": "2026-08-22T06:00:00Z",
            "checkpoint_seq": 4,
        },
        "result_transaction": {
            "result_txn_id": "result-1",
            "state": "INGESTED",
            "manifest_uri": "git:po03/run/po03-test-1@abc:manifest.json",
            "manifest_sha256": H,
            "artifact_count": 1,
            "total_bytes": 7,
            "committed_at": "2026-08-22T06:01:00Z",
            "verified_at": "2026-08-22T06:02:00Z",
            "parent_ingested_at": "2026-08-22T06:03:00Z",
            "result_commit_id": "abc123",
        },
        "artifacts": [
            {
                "artifact_id": "artifact-1",
                "logical_name": "result.json",
                "content_uri": "git:po03/run/po03-test-1@abc:result.json",
                "sha256": H,
                "bytes": 7,
                "media_type": "application/json",
                "readback_verified_at": "2026-08-22T06:02:00Z",
            }
        ],
        "completion_actor": "coordinator",
        "independent_acceptance": {
            "state": "ACCEPTED",
            "reviewer_id": "reviewer-2",
            "receipt_uri": "git:po03/review@def:receipt.json",
        },
    }


def wave_receipt():
    return {
        "protocol_version": "OBZIO-WAVE-COMPOUNDING-v1",
        "wave_id": "po03-wave-1",
        "baseline": {"metrics_uri": "git:baseline.json", "sha256": H},
        "observations": [{"id": "o1"}],
        "challenges": [{"id": "c1"}],
        "external_hypotheses": [{"id": "h1"}],
        "reproductions": [{"id": "r1"}],
        "live_mechanism_changes": [{"id": "m1"}],
        "independent_tests": [{"id": "t1"}],
        "dispositions": [{"subject": "m1", "decision": "RETAIN", "evidence_uri": "git:test.json"}],
        "successor_manifest_uri": "git:successor.json",
        "decision_changed": [],
    }


class TransactionalResultTests(unittest.TestCase):
    def assert_invalid(self, mutate, contains):
        doc = committed_result()
        mutate(doc)
        errors = MODULE.validate_result(doc)
        self.assertTrue(any(contains in error for error in errors), errors)

    def test_valid_committed_result(self):
        self.assertEqual([], MODULE.validate_result(committed_result()))

    def test_completed_without_commit_is_impossible(self):
        self.assert_invalid(
            lambda d: d["result_transaction"].update(result_commit_id=None),
            "result_commit_id",
        )

    def test_completed_without_parent_ingestion_is_impossible(self):
        self.assert_invalid(
            lambda d: d["result_transaction"].update(parent_ingested_at=None),
            "parent_ingested_at",
        )

    def test_worker_cannot_set_completed(self):
        self.assert_invalid(lambda d: d.update(completion_actor="worker"), "only coordinator")

    def test_provider_completion_without_commit_is_reclassified(self):
        doc = committed_result()
        doc["result_transaction"]["result_commit_id"] = None
        doc["obzio_state"] = "RUNNING"
        errors = MODULE.validate_result(doc)
        self.assertTrue(any("PROVIDER_COMPLETED_UNCOMMITTED" in error for error in errors), errors)

    def test_provider_completed_uncommitted_is_valid_recovery_state(self):
        doc = committed_result()
        doc["obzio_state"] = "PROVIDER_COMPLETED_UNCOMMITTED"
        doc["result_transaction"].update(
            state="RESERVED",
            manifest_uri=None,
            manifest_sha256=None,
            artifact_count=0,
            total_bytes=0,
            committed_at=None,
            verified_at=None,
            parent_ingested_at=None,
            result_commit_id=None,
        )
        doc["artifacts"] = []
        doc["completion_actor"] = None
        doc["independent_acceptance"] = {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None}
        self.assertEqual([], MODULE.validate_result(doc))

    def test_result_transaction_state_must_match_custody_state(self):
        self.assert_invalid(
            lambda d: d["result_transaction"].update(state="COMMITTED"),
            "incompatible with $.obzio_state",
        )

    def test_invalid_provider_state_is_rejected(self):
        self.assert_invalid(lambda d: d.update(provider_state="DONE"), "$.provider_state")

    def test_unknown_root_property_is_rejected(self):
        self.assert_invalid(lambda d: d.update(unreviewed_override=True), "$.unreviewed_override")

    def test_unknown_nested_property_is_rejected(self):
        self.assert_invalid(lambda d: d["attempt"].update(unreviewed_override=True), "$.attempt.unreviewed_override")

    def test_running_state_cannot_claim_committed_artifacts(self):
        self.assert_invalid(
            lambda d: d.update(obzio_state="RUNNING"),
            "uncommitted state cannot",
        )

    def test_manifest_required_after_commit(self):
        self.assert_invalid(lambda d: d["result_transaction"].update(manifest_uri=None), "manifest_uri")

    def test_artifact_readback_required_after_commit(self):
        self.assert_invalid(
            lambda d: d["artifacts"][0].update(readback_verified_at=None),
            "readback_verified_at",
        )

    def test_manifest_hash_must_be_sha256(self):
        self.assert_invalid(lambda d: d["result_transaction"].update(manifest_sha256="bad"), "manifest_sha256")

    def test_artifact_hash_must_be_sha256(self):
        self.assert_invalid(lambda d: d["artifacts"][0].update(sha256="bad"), "artifacts[0].sha256")

    def test_artifact_count_is_reconciled(self):
        self.assert_invalid(lambda d: d["result_transaction"].update(artifact_count=2), "artifact_count")

    def test_byte_count_is_reconciled(self):
        self.assert_invalid(lambda d: d["result_transaction"].update(total_bytes=8), "total_bytes")

    def test_duplicate_artifact_id_rejected(self):
        doc = committed_result()
        doc["artifacts"].append(copy.deepcopy(doc["artifacts"][0]))
        doc["result_transaction"]["artifact_count"] = 2
        doc["result_transaction"]["total_bytes"] = 14
        errors = MODULE.validate_result(doc)
        self.assertTrue(any("duplicate" in error for error in errors), errors)

    def test_fence_token_required(self):
        self.assert_invalid(lambda d: d["attempt"].update(fence_token=0), "fence_token")

    def test_idempotency_key_required(self):
        self.assert_invalid(lambda d: d["attempt"].update(idempotency_key=""), "idempotency_key")

    def test_producer_cannot_self_accept(self):
        self.assert_invalid(
            lambda d: d["independent_acceptance"].update(reviewer_id="producer-1"),
            "self-accept",
        )

    def test_acceptance_requires_receipt(self):
        self.assert_invalid(
            lambda d: d["independent_acceptance"].update(receipt_uri=None),
            "terminal review",
        )

    def test_acceptance_before_completion_rejected(self):
        self.assert_invalid(lambda d: d.update(obzio_state="RESULT_COMMITTED"), "requires COMPLETED")

    def test_parent_ingestion_cannot_claim_coordinator_completion(self):
        self.assert_invalid(
            lambda d: d.update(obzio_state="PARENT_INGESTED", completion_actor="coordinator"),
            "parent ingestion",
        )

    def test_post_provider_custody_requires_provider_completion(self):
        self.assert_invalid(
            lambda d: d.update(provider_state="RUNNING"),
            "custody after provider completion",
        )


class WaveCompoundingTests(unittest.TestCase):
    def test_valid_wave(self):
        self.assertEqual([], MODULE.validate_wave(wave_receipt()))

    def test_no_static_report_without_live_change(self):
        doc = wave_receipt()
        doc["live_mechanism_changes"] = []
        self.assertTrue(any("live_mechanism_changes" in e for e in MODULE.validate_wave(doc)))

    def test_no_change_without_independent_test(self):
        doc = wave_receipt()
        doc["independent_tests"] = []
        self.assertTrue(any("independent_tests" in e for e in MODULE.validate_wave(doc)))

    def test_successor_manifest_required(self):
        doc = wave_receipt()
        doc["successor_manifest_uri"] = ""
        self.assertTrue(MODULE.validate_wave(doc))

    def test_strategy_interlock_preserved(self):
        doc = wave_receipt()
        doc["decision_changed"] = ["new-strategy"]
        self.assertTrue(any("decision_changed" in e for e in MODULE.validate_wave(doc)))


if __name__ == "__main__":
    unittest.main()
