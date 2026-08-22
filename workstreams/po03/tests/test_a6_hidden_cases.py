import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[3]
VALIDATOR_PATH = ROOT / "workstreams" / "po03" / "tools" / "validate_contracts.py"
SPEC = importlib.util.spec_from_file_location("po03_validate_contracts", VALIDATOR_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VALIDATOR)

H = "a" * 64


def committed_result():
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": "a6-hidden-fixture",
        "commission_id": "COM-PO03",
        "immutable_input_manifest_sha256": H,
        "acceptance_contract_sha256": H,
        "provider_state": "COMPLETED",
        "obzio_state": "COMPLETED",
        "attempt": {
            "attempt_id": "attempt-1",
            "idempotency_key": "a6-hidden-fixture:1",
            "lease_id": "lease-1",
            "fence_token": 1,
            "provider_run_id": "provider-1",
            "worker_id": "producer-1",
            "heartbeat_at": "2026-08-22T06:00:00Z",
            "checkpoint_seq": 1,
        },
        "result_transaction": {
            "result_txn_id": "txn-1",
            "state": "INGESTED",
            "manifest_uri": "git:fixture@abc:manifest.json",
            "manifest_sha256": H,
            "artifact_count": 1,
            "total_bytes": 7,
            "committed_at": "2026-08-22T06:01:00Z",
            "verified_at": "2026-08-22T06:02:00Z",
            "parent_ingested_at": "2026-08-22T06:03:00Z",
            "result_commit_id": "abc",
        },
        "artifacts": [
            {
                "artifact_id": "artifact-1",
                "logical_name": "result.json",
                "content_uri": "git:fixture@abc:result.json",
                "sha256": H,
                "bytes": 7,
                "media_type": "application/json",
                "readback_verified_at": "2026-08-22T06:02:00Z",
            }
        ],
        "completion_actor": "coordinator",
        "independent_acceptance": {
            "state": "NOT_TESTED",
            "reviewer_id": None,
            "receipt_uri": None,
        },
    }


class HiddenCaseExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        case_path = (
            ROOT
            / "workstreams"
            / "po03"
            / "review"
            / "luna"
            / "hidden-cases"
            / "cases.json"
        )
        cls.case_set = json.loads(case_path.read_text(encoding="utf-8"))

    def assert_invalid(self, mutate, expected_fragment):
        document = committed_result()
        mutate(document)
        errors = VALIDATOR.validate_result(document)
        self.assertTrue(
            any(expected_fragment in error for error in errors),
            f"expected {expected_fragment!r}, got {errors!r}",
        )

    def test_case_set_is_withheld_and_complete(self):
        self.assertTrue(self.case_set["authored_before_producer_read"])
        self.assertEqual([], self.case_set["producer_test_hashes_seen_at_authoring"])
        self.assertEqual(10, len(self.case_set["cases"]))

    def test_h01_provider_completion_without_commit(self):
        self.assert_invalid(
            lambda doc: doc["result_transaction"].update(result_commit_id=None),
            "result_commit_id",
        )

    def test_h02_noncoordinator_completion(self):
        self.assert_invalid(lambda doc: doc.update(completion_actor="worker"), "only coordinator")

    def test_h03_terminal_without_readback(self):
        self.assert_invalid(
            lambda doc: doc["artifacts"][0].update(readback_verified_at=None),
            "readback_verified_at",
        )

    def test_h04_accounting_drift(self):
        self.assert_invalid(
            lambda doc: doc["result_transaction"].update(total_bytes=999),
            "total_bytes",
        )

    def test_h05_duplicate_artifact_id(self):
        def mutate(doc):
            doc["artifacts"].append(copy.deepcopy(doc["artifacts"][0]))
            doc["result_transaction"].update(artifact_count=2, total_bytes=14)

        self.assert_invalid(mutate, "duplicate")

    def test_h06_self_acceptance(self):
        self.assert_invalid(
            lambda doc: doc["independent_acceptance"].update(
                state="ACCEPTED", reviewer_id="producer-1", receipt_uri="git:receipt"
            ),
            "self-accept",
        )


if __name__ == "__main__":
    unittest.main()
