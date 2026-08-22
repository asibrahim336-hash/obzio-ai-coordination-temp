import copy
import importlib.util
import io
import json
import sys
import tempfile
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


class CliCaptureMixin:
    def run_main(self, argv):
        buffer = io.StringIO()
        original = sys.stdout
        sys.stdout = buffer
        try:
            code = MODULE.main(argv)
        finally:
            sys.stdout = original
        return code, buffer.getvalue()

    def write(self, directory, name, payload):
        target = Path(directory) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return target


class SingleDocumentCliTests(CliCaptureMixin, unittest.TestCase):
    def test_valid_wave_document_reports_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.write(tmp, "wave.json", wave_receipt())
            code, output = self.run_main(["wave", str(target)])
            self.assertEqual(0, code)
            self.assertIn("VALID wave sha256=", output)

    def test_valid_result_document_reports_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.write(tmp, "result.json", committed_result())
            code, output = self.run_main(["result", str(target)])
            self.assertEqual(0, code)
            self.assertIn("VALID result sha256=", output)

    def test_invalid_document_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = wave_receipt()
            doc["decision_changed"] = ["drift"]
            target = self.write(tmp, "wave.json", doc)
            code, output = self.run_main(["wave", str(target)])
            self.assertEqual(1, code)
            self.assertIn("INVALID: $.decision_changed", output)

    def test_missing_document_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self.run_main(["wave", str(Path(tmp) / "absent.json")])
            self.assertEqual(2, code)
            self.assertIn("INVALID:", output)

    def test_non_object_root_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "list.json"
            target.write_text("[]\n", encoding="utf-8")
            code, output = self.run_main(["wave", str(target)])
            self.assertEqual(2, code)
            self.assertIn("root must be a JSON object", output)


class DirectoryDiscoveryTests(unittest.TestCase):
    def test_json_documents_are_found_recursively_and_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b").mkdir()
            for relative in ("z.json", "a.json", "b/c.json"):
                target = root / relative
                target.write_text("{}\n", encoding="utf-8")
            (root / "notes.txt").write_text("ignored\n", encoding="utf-8")
            found = [path.relative_to(root).as_posix() for path in MODULE.iter_json_documents(root)]
            self.assertEqual(["a.json", "b/c.json", "z.json"], found)

    def test_bytecode_caches_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "x.json").write_text("{}\n", encoding="utf-8")
            (root / "real.json").write_text("{}\n", encoding="utf-8")
            found = [path.name for path in MODULE.iter_json_documents(root)]
            self.assertEqual(["real.json"], found)


class ValidateDirectoryTests(CliCaptureMixin, unittest.TestCase):
    def test_all_valid_directory_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "one.json", wave_receipt())
            self.write(tmp, "nested/two.json", wave_receipt())
            code, output = self.run_main(["validate-dir", "wave", tmp])
            self.assertEqual(0, code)
            self.assertIn("scanned=2 valid=2 invalid=0", output)
            self.assertEqual(2, output.count("sha256="))

    def test_one_invalid_document_fails_the_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "good.json", wave_receipt())
            bad = wave_receipt()
            bad["live_mechanism_changes"] = []
            self.write(tmp, "bad.json", bad)
            code, output = self.run_main(["validate-dir", "wave", tmp])
            self.assertEqual(1, code)
            self.assertIn("scanned=2 valid=1 invalid=1", output)
            self.assertIn("INVALID", output)
            self.assertIn("live_mechanism_changes", output)

    def test_only_the_first_error_is_reported_per_invalid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "bad.json", {"protocol_version": "OBZIO-WAVE-COMPOUNDING-v1"})
            code, output = self.run_main(["validate-dir", "wave", tmp])
            self.assertEqual(1, code)
            invalid_lines = [line for line in output.splitlines() if line.startswith("INVALID")]
            self.assertEqual(1, len(invalid_lines))

    def test_unreadable_document_counts_as_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "broken.json").write_text("{not json", encoding="utf-8")
            code, output = self.run_main(["validate-dir", "wave", tmp])
            self.assertEqual(1, code)
            self.assertIn("unreadable document", output)

    def test_result_documents_are_validated_with_the_result_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "r.json", committed_result())
            code, output = self.run_main(["validate-dir", "result", tmp])
            self.assertEqual(0, code)
            self.assertIn("scanned=1 valid=1 invalid=0", output)

    def test_kind_mismatch_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "r.json", committed_result())
            code, output = self.run_main(["validate-dir", "wave", tmp])
            self.assertEqual(1, code)
            self.assertIn("invalid=1", output)

    def test_empty_directory_is_an_error_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self.run_main(["validate-dir", "wave", tmp])
            self.assertEqual(2, code)
            self.assertIn("no *.json documents", output)

    def test_empty_directory_can_be_allowed_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self.run_main(["validate-dir", "wave", tmp, "--allow-empty"])
            self.assertEqual(0, code)
            self.assertIn("scanned=0 valid=0 invalid=0", output)

    def test_missing_directory_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self.run_main(["validate-dir", "wave", str(Path(tmp) / "absent")])
            self.assertEqual(2, code)
            self.assertIn("not a directory", output)

    def test_directory_summary_counts_match_document_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index in range(4):
                self.write(tmp, f"w{index}.json", wave_receipt())
            outcomes = MODULE.validate_directory("wave", Path(tmp))
            self.assertEqual(4, len(outcomes))
            self.assertTrue(all(errors == [] for _, errors in outcomes))


class ShippedDocumentTests(unittest.TestCase):
    def test_shipped_result_instances_are_valid(self):
        directory = Path(__file__).parents[1] / "contracts" / "instances" / "results"
        if not directory.is_dir():
            self.skipTest("no shipped result instances in this tree")
        outcomes = MODULE.validate_directory("result", directory)
        self.assertTrue(outcomes, "results directory exists but holds no documents")
        for path, errors in outcomes:
            self.assertEqual([], errors, f"{path}: {errors}")

    def test_shipped_wave_receipt_is_valid(self):
        target = Path(__file__).parents[1] / "evidence" / "wave-a-compounding-receipt.json"
        if not target.is_file():
            self.skipTest("wave receipt has not been written yet in this tree")
        self.assertEqual([], MODULE.validate_document("wave", target))


if __name__ == "__main__":
    unittest.main()
