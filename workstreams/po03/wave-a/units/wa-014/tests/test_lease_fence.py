from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path


UNIT_ROOT = Path(__file__).resolve().parents[1]
MECHANISM = UNIT_ROOT / "mechanism"
sys.path.insert(0, str(MECHANISM))

from lease_fence import (  # noqa: E402
    AlreadyCommitted,
    IdempotencyConflict,
    InvalidRequest,
    LeaseBusy,
    LeaseExpired,
    LeaseFenceStore,
    StaleFence,
    StaleLease,
)
from run_concurrency_fixture import ManualClock, run_fixture  # noqa: E402
from run_recurrence import run_recurrence  # noqa: E402


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory(
            prefix=".wa014-test-", dir=UNIT_ROOT
        )
        self.clock = ManualClock(10_000)
        self.store = LeaseFenceStore(
            Path(self.scratch.name) / "lease.db", clock=self.clock
        )

    def tearDown(self) -> None:
        self.scratch.cleanup()

    def claim_a(self):
        return self.store.claim(
            "task-1", "worker-a", "lease-a", ttl_ns=100
        )

    def transfer_b(self):
        self.clock.advance(100)
        return self.store.claim(
            "task-1", "worker-b", "lease-b", ttl_ns=100
        )


class LeaseLifecycleTests(StoreTestCase):
    def test_first_claim_issues_fence_one(self):
        grant = self.claim_a()
        self.assertEqual(1, grant.fence_token)
        self.assertEqual(grant, self.store.current_lease("task-1"))

    def test_active_takeover_is_rejected(self):
        self.claim_a()
        with self.assertRaises(LeaseBusy):
            self.store.claim("task-1", "worker-b", "lease-b", ttl_ns=100)

    def test_active_same_identity_claim_is_idempotent_without_extension(self):
        first = self.claim_a()
        self.clock.advance(20)
        replay = self.claim_a()
        self.assertEqual(first, replay)
        self.assertEqual(10_100, replay.expires_at_ns)

    def test_transfer_after_expiry_increments_fence(self):
        first = self.claim_a()
        second = self.transfer_b()
        self.assertEqual((1, 2), (first.fence_token, second.fence_token))
        self.assertEqual("worker-b", self.store.current_lease("task-1").owner_id)

    def test_repeated_transfers_are_strictly_monotonic(self):
        grants = [self.claim_a(), self.transfer_b()]
        self.clock.advance(100)
        grants.append(
            self.store.claim("task-1", "worker-c", "lease-c", ttl_ns=100)
        )
        self.clock.advance(100)
        grants.append(
            self.store.claim("task-1", "worker-d", "lease-d", ttl_ns=100)
        )
        self.assertEqual([1, 2, 3, 4], [grant.fence_token for grant in grants])

    def test_expired_lease_id_cannot_be_reused_for_transfer(self):
        self.claim_a()
        self.clock.advance(100)
        with self.assertRaises(InvalidRequest):
            self.store.claim("task-1", "worker-b", "lease-a", ttl_ns=100)

    def test_only_positive_integer_ttl_is_accepted(self):
        for invalid in (0, -1, True, 1.5):
            with self.subTest(invalid=invalid):
                with self.assertRaises(InvalidRequest):
                    self.store.claim(
                        f"task-{invalid!r}", "worker", "lease", ttl_ns=invalid
                    )

    def test_stale_grant_cannot_renew_after_transfer(self):
        stale = self.claim_a()
        current = self.transfer_b()
        with self.assertRaises(StaleFence):
            self.store.renew(stale, ttl_ns=100)
        self.assertEqual(current, self.store.current_lease("task-1"))

    def test_two_transfer_contenders_issue_only_one_fence_two(self):
        self.claim_a()
        self.clock.advance(100)
        barrier = threading.Barrier(3)
        grants = []
        errors = []
        lock = threading.Lock()

        def contender(name):
            barrier.wait()
            try:
                grant = self.store.claim(
                    "task-1", name, f"lease-{name}", ttl_ns=100
                )
                with lock:
                    grants.append(grant)
            except BaseException as exc:
                with lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=contender, args=("worker-b",)),
            threading.Thread(target=contender, args=("worker-c",)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(1, len(grants))
        self.assertEqual(2, grants[0].fence_token)
        self.assertEqual(1, len(errors))
        self.assertIsInstance(errors[0], LeaseBusy)
        self.assertEqual(2, self.store.current_lease("task-1").fence_token)


class CommitAdversarialTests(StoreTestCase):
    def test_current_worker_commits_at_current_fence(self):
        current = self.claim_a()
        receipt = self.store.commit(
            current, idempotency_key="result-a", payload=b"payload-a"
        )
        self.assertEqual(1, receipt.fence_token)
        self.assertFalse(receipt.replayed)
        self.assertEqual(receipt, self.store.committed_result("task-1"))

    def test_expired_current_worker_cannot_commit_even_before_transfer(self):
        expired = self.claim_a()
        self.clock.advance(100)
        with self.assertRaises(LeaseExpired):
            self.store.commit(
                expired, idempotency_key="result-a", payload=b"payload-a"
            )
        self.assertIsNone(self.store.committed_result("task-1"))

    def test_stale_worker_cannot_commit_after_ownership_transfer(self):
        stale = self.claim_a()
        current = self.transfer_b()
        receipt = self.store.commit(
            current, idempotency_key="result-b", payload=b"successor"
        )
        with self.assertRaises(StaleFence):
            self.store.commit(
                stale, idempotency_key="result-a", payload=b"stale"
            )
        self.assertEqual(receipt, self.store.committed_result("task-1"))

    def test_guessed_future_token_is_rejected(self):
        current = self.claim_a()
        forged = replace(current, fence_token=current.fence_token + 99)
        with self.assertRaises(StaleFence):
            self.store.commit(
                forged, idempotency_key="forged", payload=b"forged"
            )

    def test_current_token_with_wrong_owner_is_rejected(self):
        current = self.claim_a()
        forged = replace(current, owner_id="worker-attacker")
        with self.assertRaises(StaleLease):
            self.store.commit(
                forged, idempotency_key="forged", payload=b"forged"
            )

    def test_current_token_with_wrong_lease_id_is_rejected(self):
        current = self.claim_a()
        forged = replace(current, lease_id="lease-forged")
        with self.assertRaises(StaleLease):
            self.store.commit(
                forged, idempotency_key="forged", payload=b"forged"
            )

    def test_exact_duplicate_callback_is_idempotent(self):
        current = self.claim_a()
        first = self.store.commit(
            current, idempotency_key="result-a", payload=b"payload"
        )
        replay = self.store.commit(
            current, idempotency_key="result-a", payload=b"payload"
        )
        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(first.payload_sha256, replay.payload_sha256)

    def test_duplicate_key_with_changed_payload_is_rejected(self):
        current = self.claim_a()
        self.store.commit(
            current, idempotency_key="result-a", payload=b"payload"
        )
        with self.assertRaises(IdempotencyConflict):
            self.store.commit(
                current, idempotency_key="result-a", payload=b"altered"
            )

    def test_different_second_commit_is_rejected(self):
        current = self.claim_a()
        self.store.commit(
            current, idempotency_key="result-a", payload=b"payload"
        )
        with self.assertRaises(AlreadyCommitted):
            self.store.commit(
                current, idempotency_key="result-b", payload=b"payload"
            )

    def test_stale_callback_cannot_replay_old_idempotency_after_transfer(self):
        stale = self.claim_a()
        self.store.commit(
            stale, idempotency_key="result-a", payload=b"payload"
        )
        self.transfer_b()
        with self.assertRaises(StaleFence):
            self.store.commit(
                stale, idempotency_key="result-a", payload=b"payload"
            )

    def test_non_bytes_payload_is_rejected(self):
        current = self.claim_a()
        with self.assertRaises(InvalidRequest):
            self.store.commit(
                current, idempotency_key="result-a", payload="not-bytes"
            )


class ConcurrencyFixtureTests(unittest.TestCase):
    def test_fixture_blocks_expired_worker_at_fence_one(self):
        report = run_fixture()
        self.assertEqual("SUPPORTED", report["hypothesis_outcome"])
        self.assertEqual(1, report["observed"]["initial_fence_token"])
        self.assertEqual(2, report["observed"]["transfer_fence_token"])
        self.assertFalse(report["observed"]["stale_commit_accepted"])
        self.assertEqual("StaleFence", report["observed"]["stale_rejection"])

    def test_recurrence_has_zero_false_acceptances(self):
        report = run_recurrence(8)
        self.assertEqual(8, report["stale_commit_attempts"])
        self.assertEqual(8, report["stale_commit_attempts_blocked"])
        self.assertEqual(0, report["false_acceptances"])
        self.assertEqual([[1, 2]], report["observed_token_sequences"])


if __name__ == "__main__":
    unittest.main()
