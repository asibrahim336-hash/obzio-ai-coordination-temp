"""a11-u03 recurrence tests: a fence token must be traceable to a lease.

Frozen hypothesis (dispatch a11-u03): "Ingestion rejects a fence token lower
than the current one but accepts an arbitrary higher one that the coordinator
never issued, so a worker can escalate its own ownership."  Cohort a2 measured
10 of 10 unissued higher fences accepted.

The pre-fix comparison was ``incoming_fence < unit['fence_token']``, which makes
a larger number strictly safer than the truth.  Fencing only works if the token
is a capability the coordinator issued, not a integer the worker chose.
"""

from __future__ import annotations

import unittest

import test_a11_support as support


class FenceIssuanceTests(support.ControlPlaneHarness):
    git_backed = True

    def setUp(self) -> None:
        super().setUp()
        self.seed("h-u01", fence=1)
        self.commit, self.sha, self.size = self.commit_artifact(
            f"{support.OWNED_PREFIX}h-u01.txt", b"durable-result\n"
        )

    def doc(self, fence: int):
        return self.result_doc(
            "h-u01", fence=fence, commit_id=self.commit, body=b"durable-result\n", write_artifact=False
        )

    def test_the_issued_current_fence_is_admitted(self):
        outcome = self.ingest(self.doc(1))
        self.assertEqual("PARENT_INGESTED", outcome["ingest_event"])

    def test_ten_unissued_higher_fences_are_all_rejected(self):
        """a2's exact measurement: 10 of 10 unissued higher fences were accepted."""
        rejected = 0
        for fence in (2, 3, 5, 8, 13, 21, 42, 99, 999, 1000000):
            with self.subTest(fence=fence):
                with self.assertRaises(self.cp.ControlPlaneError) as ctx:
                    self.ingest(self.doc(fence))
                self.assertIn("was never issued", str(ctx.exception))
                rejected += 1
        self.assertEqual(10, rejected)

    def test_a_stale_lower_fence_is_still_rejected(self):
        """The pre-existing protection must survive the new one."""
        self.cp.append_event(
            "h-u01",
            "LEASED",
            actor="coordinator",
            fence_token=2,
            payload={"lease_id": "lease-h-u01-2", "worker_id": support.OWNER,
                     "expires_at": "2099-01-01T00:00:00Z"},
        )
        with self.assertRaises(self.cp.ControlPlaneError) as ctx:
            self.ingest(self.doc(1))
        self.assertIn("stale fence", str(ctx.exception))

    def test_a_superseded_issued_fence_cannot_commit_after_ownership_transfers(self):
        self.cp.append_event(
            "h-u01",
            "LEASED",
            actor="coordinator",
            fence_token=2,
            payload={"lease_id": "lease-h-u01-2", "worker_id": "po03-worker-successor",
                     "expires_at": "2099-01-01T00:00:00Z"},
        )
        with self.assertRaises(self.cp.ControlPlaneError):
            self.ingest(self.doc(1))
        self.assertEqual("PARENT_INGESTED", self.ingest(self.doc(2))["ingest_event"])

    def test_a_rejected_fence_is_recorded_durably(self):
        with self.assertRaises(self.cp.ControlPlaneError):
            self.ingest(self.doc(777))
        rows = [row for row in self.cp.ledger_rows() if row["event"] == "FENCE_REJECTED"]
        self.assertEqual(1, len(rows))
        self.assertEqual(777, rows[-1]["payload"]["rejected_fence_token"])
        self.assertEqual([1], rows[-1]["payload"]["issued_fence_tokens"])
        self.assertIn("never issued", rows[-1]["payload"]["reason"])
        self.assertIn("RECOVERY_REQUIRED", self.events("h-u01"))

    def test_a_unit_that_was_never_leased_cannot_commit_at_all(self):
        self.seed("h-u02", lease=False)
        commit, _sha, _size = self.commit_artifact(f"{support.OWNED_PREFIX}h-u02.txt", b"never-leased\n")
        doc = self.result_doc(
            "h-u02", fence=1, commit_id=commit, body=b"never-leased\n", write_artifact=False
        )
        with self.assertRaises(self.cp.ControlPlaneError) as ctx:
            self.ingest(doc)
        self.assertIn("never issued", str(ctx.exception))

    def test_issued_tokens_are_rebuilt_from_the_ledger_alone(self):
        """A restarted parent must recover the fence history, not trust the worker."""
        self.cp.append_event(
            "h-u01",
            "LEASED",
            actor="coordinator",
            fence_token=2,
            payload={"lease_id": "lease-h-u01-2", "worker_id": support.OWNER,
                     "expires_at": "2099-01-01T00:00:00Z"},
        )
        fresh = self.fresh_control_plane()
        self.assertEqual([1, 2], fresh.project_units()["h-u01"]["issued_fence_tokens"])

    def test_a_forged_lease_row_from_a_worker_does_not_issue_a_fence(self):
        """Only a coordinator-authored LEASED row may mint a token."""
        with self.assertRaises(self.cp.ControlPlaneError):
            self.cp.append_event(
                "h-u01",
                "LEASED",
                actor=support.OWNER,
                fence_token=500,
                payload={"lease_id": "self-granted", "worker_id": support.OWNER,
                         "expires_at": "2099-01-01T00:00:00Z"},
            )
        self.assertEqual([1], self.cp.project_units()["h-u01"]["issued_fence_tokens"])
        with self.assertRaises(self.cp.ControlPlaneError):
            self.ingest(self.doc(500))


if __name__ == "__main__":
    unittest.main()
