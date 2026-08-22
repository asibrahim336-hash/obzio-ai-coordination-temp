"""Reproduction for duplicate-callback idempotence.

Hypothesis under test: a duplicated callback is harmless and cannot double-count
a unit or a metric row.

A byte-for-byte replay is harmless and is asserted as a pass.  Three duplicate
shapes that a real producer and a real coordinator can reach are not harmless,
and each is asserted as the defect it is.  No assertion is relaxed to obtain a
pass.
"""

from __future__ import annotations

import importlib.util
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


kit = _load("po03_c6_046_kit", "fault_kit.py")
injector = _load("po03_c6_046_injector", "duplicate_callback_injector.py")
repair = _load("po03_c6_046_repair_test", "repair_candidate_idempotence.py")


class DuplicateCallbackTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)


class IdenticalReplayTests(DuplicateCallbackTestCase):
    def test_five_identical_replays_leave_exactly_one_durable_effect(self):
        result = injector.inject_identical_replay(self.root)
        effects = result["observed"]["durable_effects"]
        self.assertEqual(1, effects["ingestion_files"])
        self.assertEqual(1, effects["registry_ingestion_rows"])
        self.assertEqual(1, effects["parent_ingested_events"])
        self.assertEqual([], effects["event_chain_errors"])
        self.assertEqual("PASS", result["verdict"])

    def test_only_the_first_identical_callback_is_not_suppressed(self):
        result = injector.inject_identical_replay(self.root)
        suppressed = [item["suppressed"] for item in result["observed"]["outcomes"]]
        self.assertEqual([False, True, True, True, True], suppressed)


class RegeneratedRetryDefectTests(DuplicateCallbackTestCase):
    def test_retry_with_new_timestamps_double_counts_the_unit(self):
        result = injector.inject_regenerated_retry(self.root)
        observed = result["observed"]
        self.assertTrue(observed["transaction_identity_is_unchanged"])
        self.assertTrue(observed["document_bytes_differ"])
        self.assertFalse(observed["second_callback_suppressed"])
        effects = observed["durable_effects"]
        self.assertEqual(2, effects["ingestion_files"])
        self.assertEqual(2, effects["registry_ingestion_rows"])
        self.assertEqual(2, effects["parent_ingested_events"])
        self.assertEqual("FAIL", result["verdict"])

    def test_the_real_emitter_regenerates_the_timestamps_that_break_suppression(self):
        result = injector.inject_regenerated_retry(self.root)
        self.assertTrue(result["observed"]["real_emitter_regenerates_readback_timestamp"])
        self.assertTrue(result["observed"]["real_emitter_regenerates_committed_timestamp"])


class ConcurrentDuplicateDefectTests(DuplicateCallbackTestCase):
    def test_interleaved_duplicate_with_one_clock_writes_two_registry_rows(self):
        result = injector.inject_concurrent_duplicate_same_clock(self.root)
        effects = result["observed"]["durable_effects"]
        self.assertEqual(1, effects["ingestion_files"])
        self.assertEqual(2, effects["registry_ingestion_rows"])
        self.assertEqual(2, effects["parent_ingested_events"])
        self.assertEqual("FAIL", result["verdict"])

    def test_interleaved_duplicate_with_skewed_clocks_crashes_the_coordinator(self):
        result = injector.inject_concurrent_duplicate_skewed_clock(self.root)
        self.assertTrue(result["coordinator_crashed"])
        self.assertIn("immutable file differs", result["observed"]["outer"]["raised"])
        self.assertEqual("PARENT_INGESTED", result["observed"]["inner_state"])
        self.assertEqual("FAIL", result["verdict"])

    def test_neither_race_produced_a_false_completion(self):
        for injection in (
            injector.inject_concurrent_duplicate_same_clock,
            injector.inject_concurrent_duplicate_skewed_clock,
        ):
            with self.subTest(injection=injection.__name__):
                result = injection(self.root)
                self.assertNotIn("COMPLETED", str(result["observed"]["durable_effects"]))


class MetricRowTests(DuplicateCallbackTestCase):
    def test_ingestion_writes_no_metric_row_at_all(self):
        report = injector.inject_all(self.root)
        for item in report["results"]:
            with self.subTest(fault_class=item["fault_class"]):
                self.assertEqual(0, item["observed"]["durable_effects"]["metric_rows_written_by_ingestion"])


class RepairCandidateTests(DuplicateCallbackTestCase):
    def test_candidate_collapses_identical_and_regenerated_duplicates(self):
        result = injector.inject_candidate_under_every_duplicate(self.root)
        self.assertEqual(
            [
                "INGESTED",
                "DUPLICATE_SUPPRESSED_BY_IDENTITY",
                "DUPLICATE_SUPPRESSED_BY_IDENTITY",
                "DUPLICATE_SUPPRESSED_BY_IDENTITY",
            ],
            result["observed"]["outcomes"],
        )
        effects = result["observed"]["durable_effects"]
        self.assertEqual(1, effects["ingestion_files"])
        self.assertEqual(1, effects["registry_ingestion_rows"])
        self.assertEqual(1, effects["parent_ingested_events"])
        self.assertEqual("PASS", result["verdict"])

    def test_identity_key_ignores_timestamps_but_not_the_transaction(self):
        module, commit, lease = injector.stage(self.root / "identity", "046_identity")
        first = injector.result_for(module, commit, fence_token=lease["fence_token"], timestamp="2026-08-22T07:00:00Z")
        second = injector.result_for(module, commit, fence_token=lease["fence_token"], timestamp="2026-08-22T09:59:59Z")
        self.assertEqual(repair.identity_key(module, first), repair.identity_key(module, second))
        different = injector.result_for(module, commit, fence_token=lease["fence_token"] + 1, timestamp="2026-08-22T07:00:00Z")
        self.assertNotEqual(repair.identity_key(module, first), repair.identity_key(module, different))

    def test_candidate_claim_is_created_exactly_once(self):
        module, commit, lease = injector.stage(self.root / "claim", "046_claim")
        document = injector.result_for(module, commit, fence_token=lease["fence_token"], timestamp="2026-08-22T07:00:00Z")
        key = repair.identity_key(module, document)
        self.assertTrue(repair.claim_identity(module, injector.TASK_ID, key, document))
        self.assertFalse(repair.claim_identity(module, injector.TASK_ID, key, document))

    def test_candidate_never_completes_a_unit(self):
        result = injector.inject_candidate_under_every_duplicate(self.root)
        self.assertNotIn("COMPLETED", str(result["observed"]))


class AggregateTests(DuplicateCallbackTestCase):
    def test_unit_verdict_is_a_failure_with_two_duplicate_external_effects(self):
        report = injector.inject_all(self.root)
        self.assertEqual("FAIL", report["verdict"])
        self.assertEqual(2, report["duplicate_external_effects_observed"])
        self.assertEqual(0, report["false_completions_observed"])


if __name__ == "__main__":
    unittest.main()
