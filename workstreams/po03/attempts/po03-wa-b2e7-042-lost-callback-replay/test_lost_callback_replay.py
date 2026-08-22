"""Reproduction for the lost-callback replay gap in the live custody mechanism.

Hypothesis under test: a lost return message is replayed from durable state
rather than losing the result.

These tests assert the observed behaviour of the unmodified mechanism.  Where
the observed behaviour misses the cohort bar (100 percent recovery of committed
results) the test asserts the defect and is named for it, so the defect cannot
be silently fixed by weakening an assertion.
"""

from __future__ import annotations

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


kit = _load("po03_c6_042_kit", "fault_kit.py")
injector = _load("po03_c6_042_injector", "lost_callback_injector.py")
repair = _load("po03_c6_042_repair", "repair_candidate_replay_scan.py")


class LostCallbackTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.sandbox = Path(self.temporary.name) / "repository"
        self.module = kit.bind_sandbox(kit.load_factory("042_test"), self.sandbox)
        self.staged = injector.stage_committed_result(self.module, self.sandbox)

    def _registry_rows(self):
        registry = self.module.CONTROL_ROOT / "work-unit-registry.jsonl"
        if not registry.is_file():
            return []
        return [
            json.loads(line)
            for line in registry.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class DefectReproductionTests(LostCallbackTestCase):
    def test_committed_result_is_durable_after_the_callback_is_lost(self):
        body = self.module.read_object_bytes(
            f"git:{self.staged['result_commit']}:{injector.RESULT_PATH}"
        )
        self.assertEqual(self.staged["result_document_sha256"], self.module.sha256_bytes(body))

    def test_live_scanner_does_not_recover_a_committed_but_unreported_result(self):
        observed = injector.observe_recovery(self.module, self.staged)
        self.assertEqual(0, observed["ingestion_records"])
        self.assertFalse(observed["scanner_ingested_flag"])
        self.assertFalse(observed["committed_result_referenced_by_scanner"])
        self.assertEqual(
            "RESUME_OR_RERUN_FROM_IMMUTABLE_INPUT", observed["scanner_recovery_action"]
        )

    def test_lost_callback_produces_no_false_completion(self):
        observed = injector.observe_recovery(self.module, self.staged)
        self.assertEqual(0, observed["false_completion_count"])
        self.assertFalse(
            (self.module.CONTROL_ROOT / "tasks" / injector.TASK_ID / "transaction-completed.json").is_file()
        )

    def test_event_chain_survives_the_lost_callback(self):
        self.assertEqual([], self.module.verify_chain(injector.TASK_ID))

    def test_immutable_input_remains_available_for_a_rerun(self):
        capsule = self.module.CONTROL_ROOT / "tasks" / injector.TASK_ID / "input.json"
        self.assertTrue(capsule.is_file())
        document = json.loads(capsule.read_text(encoding="utf-8"))
        self.assertEqual(injector.TASK_ID, document["task_id"])

    def test_injector_reports_the_defect_as_a_failure(self):
        report = injector.inject(Path(self.temporary.name) / "injector-repository")
        self.assertEqual("FAIL", report["verdict"])
        self.assertTrue(report["prescribed_action_discards_committed_result"])
        self.assertFalse(report["false_completion_observed"])


class RepairCandidateTests(LostCallbackTestCase):
    def test_candidate_discovers_the_committed_result_from_git_alone(self):
        discovered = repair.discover_committed_results(self.module)
        self.assertEqual([injector.TASK_ID], [item["task_id"] for item in discovered])
        self.assertEqual(
            self.staged["result_document_sha256"], discovered[0]["document_sha256"]
        )

    def test_candidate_replays_the_lost_result_into_parent_ingested(self):
        replay = repair.replay_scan(self.module)
        self.assertEqual(1, replay["candidates"])
        self.assertEqual("PARENT_INGESTED", replay["replayed"][0]["outcome"])
        self.assertEqual([], replay["replayed"][0]["errors"])
        state = self.module.scan_recovery("c6-sandbox", "0" * 40)
        self.assertTrue(state["units"][injector.TASK_ID]["ingested"])
        self.assertEqual(
            "AWAIT_COORDINATOR_COMPLETION",
            state["units"][injector.TASK_ID]["recovery_action"],
        )

    def test_candidate_replay_is_idempotent_across_repeated_scans(self):
        repair.replay_scan(self.module)
        rows_after_first = len(self._registry_rows())
        second = repair.replay_scan(self.module)
        self.assertEqual("ALREADY_INGESTED_NO_REPLAY", second["replayed"][0]["outcome"])
        self.assertEqual(rows_after_first, len(self._registry_rows()))
        ingestions = sorted(
            (self.module.CONTROL_ROOT / "tasks" / injector.TASK_ID).glob("ingestion-*.json")
        )
        self.assertEqual(1, len(ingestions))

    def test_candidate_refuses_a_result_with_no_immutable_capsule(self):
        orphan = self.sandbox / "workstreams/po03/attempts/po03-c6-042-orphan/result.json"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(self.module.canonical_json({"task_id": "po03-c6-042-orphan"}))
        kit.commit_all(self.sandbox, "po03: sandbox orphan result")
        outcomes = {
            item.get("task_id"): item["outcome"] for item in repair.replay_scan(self.module)["replayed"]
        }
        self.assertEqual("NO_IMMUTABLE_CAPSULE", outcomes["po03-c6-042-orphan"])

    def test_candidate_never_completes_a_unit(self):
        repair.replay_scan(self.module)
        task_directory = self.module.CONTROL_ROOT / "tasks" / injector.TASK_ID
        self.assertFalse((task_directory / "transaction-completed.json").is_file())
        states = [
            json.loads(path.read_text(encoding="utf-8"))["state"]
            for path in sorted((self.module.CONTROL_ROOT / "events" / injector.TASK_ID).glob("*.json"))
        ]
        self.assertNotIn("COMPLETED", states)
        self.assertIn("PARENT_INGESTED", states)

    def test_candidate_refuses_a_stale_worker_after_ownership_transfer(self):
        self.module.grant_lease(injector.TASK_ID, holder="worker-b", lease_seconds=60, attempt=2)
        replay = repair.replay_scan(self.module)
        self.assertEqual("RECOVERY_REQUIRED", replay["replayed"][0]["outcome"])
        self.assertTrue(any("stale" in error for error in replay["replayed"][0]["errors"]))


if __name__ == "__main__":
    unittest.main()
