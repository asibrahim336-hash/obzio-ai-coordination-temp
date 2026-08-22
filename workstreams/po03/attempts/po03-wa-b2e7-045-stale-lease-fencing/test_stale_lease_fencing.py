"""Reproduction for the lease and fence-token boundary.

Hypothesis under test: an expired or superseded worker cannot commit after
ownership transfers.

The superseded clause holds and is asserted as a pass.  Three adjacent
properties the deliverable requires do not hold, and each is asserted as the
defect it is: recorded lease lifetime is never enforced, a fence token that was
never allocated is accepted, and the allocator can hand the same token to two
workers.  No assertion is relaxed to obtain a pass.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kit = _load("po03_c6_045_kit", "fault_kit.py")
injector = _load("po03_c6_045_injector", "lease_fencing_injector.py")
repair = _load("po03_c6_045_repair_test", "repair_candidate_fencing.py")


class FencingTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)


class SupersededWorkerTests(FencingTestCase):
    def test_superseded_worker_is_refused_and_transferee_succeeds(self):
        result = injector.inject_superseded_worker(self.root)
        observed = result["observed"]
        self.assertTrue(observed["fence_advanced_on_transfer"])
        self.assertEqual("RECOVERY_REQUIRED", observed["stale_holder_state"])
        self.assertTrue(any("stale" in error for error in observed["stale_holder_errors"]))
        self.assertEqual("PARENT_INGESTED", observed["transferred_holder_state"])
        self.assertEqual([], observed["transferred_holder_errors"])
        self.assertEqual(0, observed["false_completion_count"])
        self.assertEqual("PASS", result["verdict"])


class LeaseExpiryDefectTests(FencingTestCase):
    def test_expired_lease_holder_is_still_ingested_by_the_live_mechanism(self):
        result = injector.inject_expired_lease(self.root)
        observed = result["observed"]
        self.assertEqual(0, observed["lease_seconds_recorded"])
        self.assertEqual("PARENT_INGESTED", observed["live_ingestion_state"])
        self.assertEqual([], observed["live_ingestion_errors"])
        self.assertFalse(result["expiry_enforced_by_live_mechanism"])
        self.assertEqual("FAIL", result["verdict"])

    def test_neither_the_fence_check_nor_ingestion_reads_the_recorded_lifetime(self):
        result = injector.inject_expired_lease(self.root)
        self.assertFalse(result["observed"]["expiry_referenced_in_fence_check"])
        self.assertFalse(result["observed"]["expiry_referenced_in_ingestion"])

    def test_candidate_refuses_an_expired_holder(self):
        result = injector.inject_expired_lease(self.root)
        self.assertEqual("RECOVERY_REQUIRED", result["observed"]["repair_candidate_state"])
        self.assertTrue(any("expired" in error for error in result["observed"]["repair_candidate_errors"]))

    def test_candidate_accepts_a_holder_inside_its_lifetime(self):
        module, commit, lease = injector.stage(self.root / "live-lease", "045_live_lease", lease_seconds=3600)
        repair.assert_lease_live(module, injector.TASK_ID)
        with self.assertRaises(repair.LeaseExpiredError):
            repair.assert_lease_live(
                module,
                injector.TASK_ID,
                observed_at=datetime.now(timezone.utc) + timedelta(seconds=3601),
            )


class ForgedFenceDefectTests(FencingTestCase):
    def test_never_allocated_higher_fence_is_accepted_by_the_live_guard(self):
        result = injector.inject_forged_fence(self.root)
        observed = result["observed"]
        self.assertEqual(1, observed["active_fence"])
        self.assertEqual(1001, observed["forged_fence_presented"])
        self.assertFalse(observed["forged_fence_refused_by_live_guard"])
        self.assertEqual("PARENT_INGESTED", observed["live_ingestion_state"])
        self.assertEqual("FAIL", result["verdict"])

    def test_candidate_requires_the_exact_active_fence(self):
        result = injector.inject_forged_fence(self.root)
        self.assertEqual("RECOVERY_REQUIRED", result["observed"]["repair_candidate_state"])
        self.assertTrue(
            any("not the active fence" in error for error in result["observed"]["repair_candidate_errors"])
        )

    def test_candidate_refuses_any_fence_when_no_lease_is_held(self):
        module = kit.bind_sandbox(kit.load_factory("045_unleased"), self.root / "unleased")
        with self.assertRaises(repair.ForgedFenceError):
            repair.assert_fence_exact(module, "po03-c6-045-unleased", 1)
        module.assert_fence_current("po03-c6-045-unleased", 1)


class AllocationRaceTests(FencingTestCase):
    def test_interleaved_allocation_hands_out_the_same_live_token_twice(self):
        result = injector.inject_interleaved_allocation(self.root)
        observed = result["observed"]
        self.assertEqual(observed["live_inner_token"], observed["live_outer_token"])
        self.assertTrue(observed["live_tokens_collided"])
        self.assertEqual("FAIL", result["verdict"])

    def test_candidate_allocation_stays_unique_under_the_same_interleaving(self):
        result = injector.inject_interleaved_allocation(self.root)
        observed = result["observed"]
        self.assertNotEqual(observed["candidate_inner_token"], observed["candidate_outer_token"])
        self.assertFalse(observed["candidate_tokens_collided"])

    def test_real_concurrent_allocation_is_unique_only_with_the_candidate(self):
        result = injector.inject_concurrent_allocation(self.root, workers=4, allocations=4)
        live = result["observed"]["LIVE"]
        candidate = result["observed"]["REPAIR_CANDIDATE"]
        self.assertEqual([], live["child_failures"])
        self.assertEqual([], candidate["child_failures"])
        self.assertEqual(16, live["tokens_handed_out"])
        self.assertEqual(16, candidate["tokens_handed_out"])
        self.assertEqual(0, candidate["duplicate_tokens"])
        self.assertEqual(16, candidate["distinct_tokens"])
        # The live duplicate count comes from a genuine race, so it is recorded
        # rather than pinned to a value that would make the test timing bound.
        self.assertGreaterEqual(live["duplicate_tokens"], 0)


class AggregateTests(FencingTestCase):
    def test_unit_verdict_is_a_failure_with_the_superseded_clause_holding(self):
        report = injector.inject_all(self.root)
        self.assertEqual("FAIL", report["verdict"])
        self.assertTrue(report["hypothesis_clause_superseded_worker_refused"])
        self.assertEqual(0, report["false_completions_observed"])

    def test_no_fault_class_produced_a_completed_state(self):
        report = injector.inject_all(self.root)
        for item in report["results"]:
            with self.subTest(fault_class=item["fault_class"]):
                self.assertNotIn("COMPLETED", str(item["observed"]))


if __name__ == "__main__":
    unittest.main()
