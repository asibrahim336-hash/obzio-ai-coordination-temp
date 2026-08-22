"""Executable A2 recovery proofs and frozen control-plane defect cases."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


PO03_ROOT = Path(__file__).resolve().parents[1]
LAB_PATH = PO03_ROOT / "faults" / "fault_lab.py"
SPEC = importlib.util.spec_from_file_location("a2_fault_lab_tests", LAB_PATH)
LAB = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(LAB)


def outcome(unit_id: str) -> dict:
    path = PO03_ROOT / "faults" / "outcomes" / f"{unit_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class MeasuredEvidenceTests(unittest.TestCase):
    def test_every_fault_class_has_an_executable_injector(self):
        for unit_id, script in LAB.SCRIPT_NAMES.items():
            with self.subTest(unit_id=unit_id):
                path = PO03_ROOT / "faults" / script
                self.assertTrue(path.is_file())
                self.assertIn("LAB.cli", path.read_text(encoding="utf-8"))

    def test_every_outcome_covers_every_lifecycle_transition(self):
        expected = set(LAB.LIFECYCLE)
        for unit_id in sorted(LAB.RUNNERS):
            with self.subTest(unit_id=unit_id):
                document = outcome(unit_id)
                observed = {row["transition"] for row in document["measurements"]}
                self.assertEqual(expected, observed)
                self.assertGreater(document["recovery_time"]["wall_total"], 0)
                self.assertEqual([], document["decision_changed"])
                self.assertEqual(0, document["founder_relay_count"])

    def test_partial_write_detection_passes_all_injections(self):
        document = outcome("a2-u03")
        self.assertEqual("PASS", document["status"])
        self.assertEqual(document["detections"]["injected"], document["detections"]["detected"])
        self.assertEqual(0, document["false_completion_count"])
        self.assertTrue(document["complete_hash_coverage"])

    def test_parent_projection_rebuild_is_byte_equal(self):
        document = outcome("a2-u10")
        self.assertEqual(
            document["projection_rebuilds"]["attempted"],
            document["projection_rebuilds"]["byte_equal"],
        )

    def test_network_boundary_is_honestly_not_supported(self):
        document = outcome("a2-u09")
        self.assertEqual("NOT_SUPPORTED", document["status"])
        self.assertTrue(all(row["status"] == "NOT_SUPPORTED" for row in document["measurements"]))
        self.assertIn("no push, fetch, remote read-back", document["limitations"][0])

    def test_code2_fixture_wording_is_frozen(self):
        document = outcome("a2-u12")
        for row in document["measurements"]:
            self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", row["fixture_state"])
            self.assertEqual("UNRECOVERED_AFTER_FOUR_REPORTED_ROUTES", row["fixture_result_state"])
            self.assertEqual("NOT_ACCEPTED", row["fixture_acceptance"])

    def test_two_hundred_concurrent_interleavings_were_measured(self):
        document = outcome("a2-u07")
        self.assertGreaterEqual(document["interleavings"], 200)


class FrozenControlPlaneDefects(unittest.TestCase):
    """Desired invariants; expectedFailure freezes each current reproducer."""

    @unittest.expectedFailure
    def test_defect_scanner_must_automatically_transfer_an_expired_lease(self):
        with LAB.Sandbox("a2-u06", "test-expiry") as sb:
            sb.seed("RUNNING", expired_lease=True)
            sb.cp.scan_recovery()
            unit = sb.cp.project_units()[sb.unit_id]
            events = {row["event"] for row in unit["history"]}
            self.assertIn("LEASE_EXPIRED", events)
            self.assertGreater(unit["fence_token"], 1)

    @unittest.expectedFailure
    def test_defect_scanner_must_reconcile_a_lost_committed_return(self):
        with LAB.Sandbox("a2-u02", "test-lost-return") as sb:
            sb.seed("RUNNING")
            result, _ = sb.committed_result(commit_id="durable-but-callback-lost")
            slot = sb.repo / sb.dispatch()["result_slot"]["unit_record"]
            slot.parent.mkdir(parents=True)
            slot.write_text(json.dumps(result), encoding="utf-8")
            sb.cp.scan_recovery()
            unit = sb.cp.project_units()[sb.unit_id]
            self.assertEqual("durable-but-callback-lost", unit["result_commit_id"])
            self.assertEqual("PARENT_INGESTED", unit["obzio_state"])

    @unittest.expectedFailure
    def test_defect_ingestion_must_reject_a_nonexistent_remote_commit(self):
        with LAB.Sandbox("a2-u05", "test-missing-remote") as sb:
            sb.seed("RUNNING")
            result, _ = sb.committed_result(commit_id="does-not-exist-in-any-remote")
            with self.assertRaises(sb.cp.ControlPlaneError):
                sb.cp.ingest_result(result, artifact_root=sb.repo)

    @unittest.expectedFailure
    def test_defect_ingestion_must_reject_uncommitted_code2_fixture(self):
        with LAB.Sandbox("a2-u12", "test-code2") as sb:
            sb.seed("RUNNING")
            with self.assertRaises(sb.cp.ControlPlaneError):
                sb.cp.ingest_result(sb.uncommitted_result(), artifact_root=sb.repo)

    @unittest.expectedFailure
    def test_defect_concurrent_duplicate_ingestion_must_be_atomic(self):
        measurement = LAB._concurrent_trial("RUNNING", 1)
        self.assertEqual(1, measurement["parent_ingested_rows"])
        self.assertTrue(measurement["ledger_chain_valid"])

    @unittest.expectedFailure
    def test_defect_ingestion_rejection_must_transition_to_recovery_required(self):
        with LAB.Sandbox("a2-u08", "test-corrupt") as sb:
            sb.seed("RUNNING")
            result, artifact = sb.committed_result()
            artifact.write_bytes(b"corrupt")
            with self.assertRaises(sb.cp.ControlPlaneError):
                sb.cp.ingest_result(result, artifact_root=sb.repo)
            self.assertEqual("RECOVERY_REQUIRED", sb.cp.project_units()[sb.unit_id]["obzio_state"])

    @unittest.expectedFailure
    def test_defect_unissued_future_fence_must_be_rejected(self):
        with LAB.Sandbox("a2-u06", "test-future-fence") as sb:
            sb.seed("RUNNING")
            result, _ = sb.committed_result(fence_token=999)
            with self.assertRaises(sb.cp.ControlPlaneError):
                sb.cp.ingest_result(result, artifact_root=sb.repo)

    @unittest.expectedFailure
    def test_defect_worker_event_must_not_set_completed(self):
        with LAB.Sandbox("a2-u01", "test-worker-complete") as sb:
            sb.seed("CREATED")
            with self.assertRaises(sb.cp.ControlPlaneError):
                sb.cp.append_event(
                    sb.unit_id,
                    "COMPLETED",
                    actor="po03-worker-a2",
                    provider_state="COMPLETED",
                )


if __name__ == "__main__":
    unittest.main()
