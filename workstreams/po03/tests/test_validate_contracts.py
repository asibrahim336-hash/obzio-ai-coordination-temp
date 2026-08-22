import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "validate_contracts.py"
SPEC = importlib.util.spec_from_file_location("validate_contracts", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


H = "a" * 64
HARDENING_ROOT = (
    Path(__file__).parents[1]
    / "attempts"
    / "wave-a"
    / "wave-a-041-schema-adversarial-review"
)
HARDENING_CASES = {
    case["case_id"]: case
    for case in json.loads(
        (HARDENING_ROOT / "adversarial-cases.json").read_text(encoding="utf-8")
    )["cases"]
}
HARDENING_FIXTURES = json.loads(
    (HARDENING_ROOT / "candidate" / "hardened-fixtures.json").read_text(
        encoding="utf-8"
    )
)


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
            "attempt_id": "po03-test-1-attempt-1",
            "idempotency_key": "COM-PO03:po03-test-1:attempt-1",
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
            "artifact_count": 2,
            "total_bytes": 14,
            "committed_at": "2026-08-22T06:01:00Z",
            "verified_at": "2026-08-22T06:02:00Z",
            "parent_ingested_at": "2026-08-22T06:03:00Z",
            "result_commit_id": "b" * 40,
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
            },
            {
                "artifact_id": "artifact-manifest",
                "logical_name": "manifest.json",
                "content_uri": "git:po03/run/po03-test-1@abc:manifest.json",
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


def honest_result_ledger():
    spec = HARDENING_FIXTURES["honest_ledger"]
    documents = []
    for step in spec["steps"]:
        document = copy.deepcopy(spec["base"])
        document["obzio_state"] = step["obzio_state"]
        document["provider_state"] = step["provider_state"]
        document["attempt"]["checkpoint_seq"] = step["checkpoint_seq"]
        document["result_transaction"]["state"] = step["transaction_state"]
        if step.get("artifacts") == "staged":
            document["artifacts"] = copy.deepcopy(spec["staged_artifacts"])
            document["result_transaction"].update(spec["staged_manifest"])
        elif step.get("artifacts") == "committed":
            document["artifacts"] = copy.deepcopy(spec["committed_artifacts"])
        document["result_transaction"]["artifact_count"] = len(document["artifacts"])
        document["result_transaction"]["total_bytes"] = sum(
            artifact["bytes"] for artifact in document["artifacts"]
        )
        if step.get("committed"):
            evidence = dict(spec["commit_evidence"])
            if not step.get("ingested"):
                evidence.pop("parent_ingested_at")
            document["result_transaction"].update(evidence)
        if step.get("completion_actor"):
            document["completion_actor"] = step["completion_actor"]
        documents.append(document)
    return documents


class TransactionalResultTests(unittest.TestCase):
    def assert_invalid(self, mutate, contains):
        doc = committed_result()
        mutate(doc)
        errors = MODULE.validate_result(doc)
        self.assertTrue(any(contains in error for error in errors), errors)

    def test_valid_committed_result(self):
        self.assertEqual([], MODULE.validate_result(committed_result()))

    def test_zero_byte_artifact_is_valid_and_reconciled(self):
        doc = committed_result()
        doc["artifacts"][0]["bytes"] = 0
        doc["result_transaction"]["total_bytes"] = 7
        self.assertEqual([], MODULE.validate_result(doc))

    def test_negative_artifact_size_is_rejected(self):
        self.assert_invalid(
            lambda d: d["artifacts"][0].update(bytes=-1),
            "must be an integer >= 0",
        )

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
        self.assert_invalid(lambda d: d["result_transaction"].update(artifact_count=3), "artifact_count")

    def test_byte_count_is_reconciled(self):
        self.assert_invalid(lambda d: d["result_transaction"].update(total_bytes=8), "total_bytes")

    def test_duplicate_artifact_id_rejected(self):
        doc = committed_result()
        doc["artifacts"].append(copy.deepcopy(doc["artifacts"][0]))
        doc["result_transaction"]["artifact_count"] = 3
        doc["result_transaction"]["total_bytes"] = 21
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


class AdversarialHardeningTests(unittest.TestCase):
    def test_each_snapshot_exploit_is_closed_for_its_own_reason(self):
        expectations = HARDENING_FIXTURES["expected_hardened_rejection"]
        for case_id, expectation in sorted(expectations.items()):
            if expectation["level"] == "ledger":
                continue
            with self.subTest(case=case_id, closed_by=expectation["closed_by"]):
                errors = []
                for document in HARDENING_CASES[case_id]["documents"]:
                    errors.extend(
                        MODULE.validate_result(
                            copy.deepcopy(document),
                            expectation.get("context"),
                        )
                    )
                self.assertTrue(errors, f"{case_id}: exploit was accepted")
                self.assertTrue(
                    any(
                        expectation["error_substring"] in error
                        for error in errors
                    ),
                    (
                        f"{case_id}: not rejected for "
                        f"{expectation['error_substring']!r}: {errors}"
                    ),
                )

    def test_ledger_exploits_require_and_fail_sequence_validation(self):
        probes = {
            case_id: probe
            for case_id, probe in HARDENING_FIXTURES["ledger_probes"].items()
            if isinstance(probe, dict)
        }
        self.assertEqual(2, len(probes))
        for case_id, probe in sorted(probes.items()):
            with self.subTest(case=case_id):
                documents = copy.deepcopy(probe["documents"])
                for document in documents:
                    self.assertEqual([], MODULE.validate_result(document))
                errors = MODULE.validate_result_sequence(documents)
                self.assertTrue(
                    any(probe["error_substring"] in error for error in errors),
                    errors,
                )

    def test_truthful_states_and_full_ledger_remain_representable(self):
        self.assertEqual(
            [],
            MODULE.validate_result(
                copy.deepcopy(HARDENING_FIXTURES["honest_control_v2"])
            ),
        )
        self.assertEqual(
            [],
            MODULE.validate_result(
                copy.deepcopy(
                    HARDENING_FIXTURES["truthful_staged_provider_loss"]
                )
            ),
        )
        self.assertEqual(
            [],
            MODULE.validate_result(
                copy.deepcopy(HARDENING_FIXTURES["truthful_zero_byte_artifact"])
            ),
        )
        self.assertEqual([], MODULE.validate_result_sequence(honest_result_ledger()))

    def test_duplicate_terminal_callback_is_idempotent_but_fork_is_rejected(self):
        ledger = honest_result_ledger()
        replayed = ledger + [copy.deepcopy(ledger[-1]), copy.deepcopy(ledger[-1])]
        self.assertEqual([], MODULE.validate_result_sequence(replayed))
        forked = copy.deepcopy(ledger[-1])
        forked["result_transaction"]["result_commit_id"] = "0" * 40
        errors = MODULE.validate_result_sequence(ledger + [forked])
        self.assertTrue(any("cannot also produce" in error for error in errors), errors)

    def test_identity_normalisation_closes_human_equivalent_aliases(self):
        normalise = MODULE.normalise_identity
        self.assertEqual(normalise("producer-1"), normalise("producer-1 "))
        self.assertEqual(normalise("producer-1"), normalise("Producer-1"))
        self.assertEqual(normalise("producer-1"), normalise("producer-1\u200b"))
        self.assertEqual(normalise("produc\u00e9r-1"), normalise("produce\u0301r-1"))
        self.assertNotEqual(normalise("producer-1"), normalise("reviewer-1"))


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
