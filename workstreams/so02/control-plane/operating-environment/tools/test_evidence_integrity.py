from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parent / "evidence_integrity.py"
SPEC = importlib.util.spec_from_file_location("evidence_integrity", MODULE_PATH)
ei = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ei)


class ForgedReadbackTests(unittest.TestCase):
    """The exact forgery an independent acceptor used to defeat the old verifier."""

    def forged(self) -> dict:
        return {
            "immutable_commit": "0" * 40,
            "bundle_sha256": "1" * 64,
            "entry_count": 1,
            "transports": ["totally_made_up_transport_a", "totally_made_up_transport_b"],
            "comparisons": [{
                "path": "receipts/so02/2026-08-22/cur-orch-qual-01/LAUNCH-RECEIPT.json",
                "local_sha256": "2" * 64,
                "remote_git_sha256": "2" * 64,
                "identical_git_transport": True,
            }],
            "mismatches": [],
            "result": "REMOTE_BYTE_FOR_BYTE_IDENTICAL",
        }

    def test_forged_readback_naming_a_nonexistent_commit_is_rejected(self) -> None:
        errors = ei.verify_readback_truth(self.forged(), "https://example.invalid/repo.git", Path("."))
        self.assertTrue(errors, "a fabricated read-back must not verify")

    def test_a_non_sha_commit_reference_is_rejected_without_network(self) -> None:
        record = self.forged()
        record["immutable_commit"] = "HEAD"
        errors = ei.verify_readback_truth(record, "https://example.invalid/repo.git", Path("."))
        self.assertTrue(any("immutable commit SHA" in item for item in errors))

    def test_internal_self_consistency_alone_does_not_pass(self) -> None:
        """The defect in one sentence: a perfectly self-consistent record is not evidence."""
        record = self.forged()
        self.assertEqual(record["comparisons"][0]["local_sha256"],
                         record["comparisons"][0]["remote_git_sha256"])
        self.assertEqual([], record["mismatches"])
        errors = ei.verify_readback_truth(record, "https://example.invalid/repo.git", Path("."))
        self.assertTrue(errors)


class AllowlistCapacityTests(unittest.TestCase):
    """A denylist of harmful states fails open on every state nobody enumerated."""

    def observation(self, final_status: str) -> dict:
        agents = [{"bcId": "bc-po03-a", "status": "IDLE", "isKilled": False, "updatedAtMs": 1}]
        obs = {
            "orchestrator_bc_id": "bc-self",
            "capacity_observation_state": "CAPACITY_OBSERVATION_AVAILABLE",
            "snapshots": [
                {"label": "T0", "observed_at": "t0", "agents": copy.deepcopy(agents)},
                {"label": "T1", "observed_at": "t1", "agents": copy.deepcopy(agents)},
                {"label": "end", "observed_at": "t2", "agents": copy.deepcopy(agents)},
            ],
        }
        obs["snapshots"][2]["agents"][0]["status"] = final_status
        return obs

    def test_error_transition_now_fails(self) -> None:
        verdict, findings = ei.capacity_verdict(self.observation("ERROR"))
        self.assertEqual("CAPACITY_INTERFERENCE_FAIL", verdict)
        self.assertTrue(any("IDLE -> ERROR" in item for item in findings))

    def test_failed_transition_now_fails(self) -> None:
        self.assertEqual("CAPACITY_INTERFERENCE_FAIL", ei.capacity_verdict(self.observation("FAILED"))[0])

    def test_previously_enumerated_states_still_fail(self) -> None:
        for status in ("QUEUED", "PAUSED", "EVICTED", "ADMISSION_REFUSED", "PENDING"):
            self.assertEqual("CAPACITY_INTERFERENCE_FAIL",
                             ei.capacity_verdict(self.observation(status))[0], status)

    def test_an_unheard_of_future_status_fails_closed(self) -> None:
        """The structural point: unknown states must not pass silently."""
        self.assertEqual("CAPACITY_INTERFERENCE_FAIL",
                         ei.capacity_verdict(self.observation("THROTTLED_BY_SOME_FUTURE_MECHANISM"))[0])

    def test_benign_transitions_still_pass(self) -> None:
        for status in ("RUNNING", "COMPLETED", "IDLE"):
            self.assertEqual("ZERO_PO03_CAPACITY_INTERFERENCE",
                             ei.capacity_verdict(self.observation(status))[0], status)

    def test_disappearance_still_fails(self) -> None:
        obs = self.observation("IDLE")
        obs["snapshots"][2]["agents"] = []
        verdict, findings = ei.capacity_verdict(obs)
        self.assertEqual("CAPACITY_INTERFERENCE_FAIL", verdict)
        self.assertTrue(any("disappeared" in item for item in findings))

    def test_orchestrator_own_state_is_exempt(self) -> None:
        agents = [{"bcId": "bc-self", "status": "RUNNING", "isKilled": False, "updatedAtMs": 1}]
        obs = {
            "orchestrator_bc_id": "bc-self",
            "capacity_observation_state": "CAPACITY_OBSERVATION_AVAILABLE",
            "snapshots": [
                {"label": "T0", "observed_at": "t0", "agents": copy.deepcopy(agents)},
                {"label": "T1", "observed_at": "t1", "agents": copy.deepcopy(agents)},
                {"label": "end", "observed_at": "t2", "agents": [{"bcId": "bc-self", "status": "ERROR", "isKilled": False, "updatedAtMs": 2}]},
            ],
        }
        self.assertEqual("ZERO_PO03_CAPACITY_INTERFERENCE", ei.capacity_verdict(obs)[0])

    def test_unavailable_observation_is_not_reported_as_clean(self) -> None:
        obs = self.observation("IDLE")
        obs["capacity_observation_state"] = "CAPACITY_OBSERVATION_UNAVAILABLE"
        self.assertEqual("CAPACITY_OBSERVATION_UNAVAILABLE", ei.capacity_verdict(obs)[0])


class ManifestClosureTests(unittest.TestCase):
    """An excluded file is an unbound file, however good the reason for excluding it."""

    def manifest(self) -> dict:
        entries = [{"path": "a.json", "size_bytes": 1, "sha256": "a" * 64}]
        return {
            "entries": entries,
            "bundle_sha256": ei.sha256_bytes(
                __import__("json").dumps(entries, sort_keys=True, separators=(",", ":")).encode()
            ),
        }

    def test_full_coverage_passes(self) -> None:
        self.assertEqual([], ei.verify_manifest_closure(self.manifest(), ["a.json"]))

    def test_an_uncovered_present_file_is_rejected(self) -> None:
        errors = ei.verify_manifest_closure(self.manifest(), ["a.json", "REMOTE-READBACK.json"])
        self.assertTrue(any("REMOTE-READBACK.json" in item for item in errors))

    def test_tampered_bundle_hash_is_rejected(self) -> None:
        manifest = self.manifest()
        manifest["bundle_sha256"] = "0" * 64
        self.assertTrue(any("does not bind" in item for item in ei.verify_manifest_closure(manifest, ["a.json"])))


if __name__ == "__main__":
    unittest.main()
