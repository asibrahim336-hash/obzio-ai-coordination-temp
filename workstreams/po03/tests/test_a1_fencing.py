"""a1-u03 — monotonic fence tokens block an evicted leaseholder from committing.

Hypothesis (frozen in ``control/dispatch/a1-u03.json``): monotonic fence tokens
make it impossible for an evicted leaseholder to commit after ownership
transfers.

Acceptance, satisfied literally: after a lease is re-granted, a commit attempt
carrying the older fence token is rejected and recorded as ``FENCE_REJECTED``,
while the current holder commits successfully.  Falsified if a stale fence
commit is admitted or the rejection is not durably recorded.

"Durably recorded" is checked by re-reading the ledger from disk with a fresh
object, not by inspecting in-memory state, and the rejection must survive with
the hash chain still verifying.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from test_a1_support import PO03_ROOT, ScratchCase, load_isolated_module

from engine.canonical import sha256_file
from engine.lease import CheckpointRegression, FenceViolation, LeaseManager
from engine.ledger import HashChainedLedger

UNIT = "a1-u03-subject"
STALE_WORKER = "po03-worker-a1-process-1"
CURRENT_WORKER = "po03-worker-a1-process-2"


class FencingCase(ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        self.now = 1_800_000_000.0
        self.ledger = HashChainedLedger(self.scratch / "ledger.jsonl")
        self.leases = LeaseManager(self.ledger, clock=lambda: self.now)
        self.first = self.leases.grant(UNIT, STALE_WORKER, ttl_seconds=60)

    def reread(self) -> LeaseManager:
        """A fresh manager over a fresh ledger object: no in-memory carry-over."""
        return LeaseManager(HashChainedLedger(self.scratch / "ledger.jsonl"), clock=lambda: self.now)


class FenceTokenTests(FencingCase):
    def test_tokens_are_monotonic_across_grants(self):
        self.assertEqual(1, self.first.fence_token)
        second = self.leases.grant(UNIT, CURRENT_WORKER, ttl_seconds=60)
        third = self.leases.grant(UNIT, "po03-worker-a1-process-3", ttl_seconds=60)
        self.assertEqual([1, 2, 3], [self.first.fence_token, second.fence_token, third.fence_token])
        self.assertEqual(3, self.reread().current_fence(UNIT))

    def test_current_holder_commits_successfully(self):
        second = self.leases.grant(UNIT, CURRENT_WORKER, ttl_seconds=60)
        row = self.leases.commit_result(
            second,
            result_commit_id="deadbeef",
            manifest_uri="git:branch@deadbeef:manifest",
            manifest_sha256="a" * 64,
            artifact_count=2,
            total_bytes=100,
        )
        self.assertEqual("RESULT_COMMITTED", row["event"])
        self.assertTrue(self.reread().resume_point(UNIT).result_committed)

    def test_evicted_holder_cannot_commit_and_the_rejection_is_durable(self):
        self.leases.grant(UNIT, CURRENT_WORKER, ttl_seconds=60)
        with self.assertRaises(FenceViolation) as caught:
            self.leases.commit_result(
                self.first,
                result_commit_id="stale-commit",
                manifest_uri="git:branch@stale:manifest",
                manifest_sha256="b" * 64,
                artifact_count=1,
                total_bytes=10,
            )
        self.assertIn("fence token 1 is not the current token 2", str(caught.exception))

        fresh = self.reread()
        rejections = fresh.fence_rejections(UNIT)
        self.assertEqual(1, len(rejections))
        payload = rejections[0]["payload"]
        self.assertEqual(1, payload["rejected_fence_token"])
        self.assertEqual(2, payload["current_fence_token"])
        self.assertEqual("commit_result", payload["operation"])
        self.assertEqual(STALE_WORKER, payload["rejected_worker_id"])
        self.assertEqual("stale leaseholder after ownership transfer", payload["reason"])

        # The stale commit left no RESULT_COMMITTED row at all.
        events = [row["event"] for row in fresh.ledger.events_for(UNIT)]
        self.assertNotIn("RESULT_COMMITTED", events)
        self.assertFalse(fresh.resume_point(UNIT).result_committed)
        self.assertTrue(fresh.ledger.verify().ok)

    def test_full_acceptance_sequence_in_one_history(self):
        """Re-grant, stale commit refused, current commit admitted."""
        second = self.leases.grant(UNIT, CURRENT_WORKER, ttl_seconds=60)
        with self.assertRaises(FenceViolation):
            self.leases.commit_result(
                self.first,
                result_commit_id="stale",
                manifest_uri="uri",
                manifest_sha256="c" * 64,
                artifact_count=1,
                total_bytes=1,
            )
        self.leases.commit_result(
            second,
            result_commit_id="real-commit",
            manifest_uri="git:branch@real:manifest",
            manifest_sha256="d" * 64,
            artifact_count=1,
            total_bytes=5,
        )
        fresh = self.reread()
        events = [row["event"] for row in fresh.ledger.events_for(UNIT)]
        self.assertEqual(["LEASED", "LEASED", "FENCE_REJECTED", "RESULT_COMMITTED"], events)
        committed = [row for row in fresh.ledger.events_for(UNIT) if row["event"] == "RESULT_COMMITTED"]
        self.assertEqual(1, len(committed))
        self.assertEqual("real-commit", committed[0]["payload"]["result_commit_id"])
        self.assertEqual(2, committed[0]["fence_token"])

    def test_every_fenced_operation_refuses_a_stale_holder(self):
        self.leases.grant(UNIT, CURRENT_WORKER, ttl_seconds=60)
        operations = {
            "heartbeat": lambda: self.leases.heartbeat(self.first),
            "checkpoint": lambda: self.leases.checkpoint(self.first, 1),
            "commit_step": lambda: self.leases.commit_step(self.first, "step-1"),
            "commit_result": lambda: self.leases.commit_result(
                self.first,
                result_commit_id="x",
                manifest_uri="u",
                manifest_sha256="e" * 64,
                artifact_count=1,
                total_bytes=1,
            ),
        }
        for name, operation in operations.items():
            with self.subTest(operation=name):
                with self.assertRaises(FenceViolation):
                    operation()
        recorded = {row["payload"]["operation"] for row in self.reread().fence_rejections(UNIT)}
        self.assertEqual(set(operations), recorded)

    def test_a_token_that_was_never_issued_is_refused(self):
        forged = self.first.__class__(**{**self.first.as_dict(), "fence_token": 99})
        with self.assertRaises(FenceViolation):
            self.leases.commit_step(forged, "step-forged")
        rejection = self.reread().fence_rejections(UNIT)[0]
        self.assertEqual("fence token was never issued", rejection["payload"]["reason"])

    def test_heartbeat_extends_only_the_current_lease(self):
        renewed = self.leases.heartbeat(self.first, ttl_seconds=120)
        self.assertGreater(renewed.expires_at, self.first.expires_at)
        self.assertEqual(self.first.fence_token, renewed.fence_token)
        current = self.reread().current_lease(UNIT)
        self.assertEqual(renewed.expires_at, current.expires_at)

    def test_expired_lease_is_reported_for_recovery(self):
        self.assertEqual([], self.leases.expired_leases([UNIT]))
        self.now += 3600
        self.assertEqual([UNIT], self.leases.expired_leases([UNIT]))
        self.leases.expire(UNIT, reason="heartbeat stopped")
        self.assertIsNone(self.reread().current_lease(UNIT))

    def test_checkpoints_are_monotonic(self):
        self.leases.checkpoint(self.first, 1)
        self.leases.checkpoint(self.first, 2)
        with self.assertRaises(CheckpointRegression):
            self.leases.checkpoint(self.first, 2)
        with self.assertRaises(CheckpointRegression):
            self.leases.checkpoint(self.first, 1)
        self.assertEqual(2, self.reread().resume_point(UNIT).checkpoint_seq)


class NegativeControlTests(FencingCase):
    """Prove the fence is doing the work, not something incidental."""

    def test_without_the_fence_check_the_stale_commit_is_admitted(self):
        self.leases.grant(UNIT, CURRENT_WORKER, ttl_seconds=60)

        # Same write, with assert_current neutralised: this is the pre-fence
        # behaviour, and it succeeds.  That is what the guarded test forbids.
        original = LeaseManager.assert_current
        try:
            LeaseManager.assert_current = lambda self, lease, *, operation: None
            self.leases.commit_result(
                self.first,
                result_commit_id="stale-commit-admitted",
                manifest_uri="uri",
                manifest_sha256="f" * 64,
                artifact_count=1,
                total_bytes=1,
            )
        finally:
            LeaseManager.assert_current = original

        fresh = self.reread()
        committed = [row for row in fresh.ledger.events_for(UNIT) if row["event"] == "RESULT_COMMITTED"]
        self.assertEqual(1, len(committed))
        self.assertEqual(1, committed[0]["fence_token"], "the unguarded write committed with a stale token")
        self.assertEqual([], fresh.fence_rejections(UNIT))


class ControlPlaneFenceTests(ScratchCase):
    """The coordinator's ingestion path must refuse the same stale commit.

    A fence enforced only inside the engine would still let a stale worker
    reach shared custody through ``ingest``.  This drives the coordinator's real
    ``ingest_result`` against scratch state, so the assertion covers the live
    mechanism rather than a copy of it.
    """

    def setUp(self) -> None:
        super().setUp()
        self.plane = load_isolated_module(PO03_ROOT / "tools" / "control_plane.py", "a1_fence_control_plane")
        self.control = self.scratch / "control"
        self.plane.LEDGER_PATH = self.control / "events" / "ledger.jsonl"
        self.plane.REGISTRY_PATH = self.control / "work-unit-registry.jsonl"
        self.plane.RECOVERY_PATH = self.control / "recovery-state.json"
        self.plane.DISPATCH_DIR = self.control / "dispatch"
        self.plane.PATH_OWNERSHIP_PATH = self.control / "path-ownership.json"

        self.artifact_root = self.scratch / "tree"
        self.artifact_rel = "workstreams/po03/engine/subject.txt"
        target = self.artifact_root / self.artifact_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("custody engine artifact\n", encoding="utf-8")
        self.artifact_sha = sha256_file(target)
        self.artifact_bytes = target.stat().st_size

        self.plane.write_json(
            self.plane.PATH_OWNERSHIP_PATH,
            {"owners": {"po03-worker-a1": {"owned_prefixes": ["workstreams/po03/engine/"]}}},
        )
        self.dispatch = {
            "unit_id": "a1-u03-plane",
            "owner": "po03-worker-a1",
            "immutable_input_manifest_sha256": "1" * 64,
            "acceptance_contract_sha256": "2" * 64,
            "idempotency_key": "a1-u03-plane:key",
        }
        self.plane.write_json(self.plane.DISPATCH_DIR / "a1-u03-plane.json", self.dispatch)
        self.plane.append_event("a1-u03-plane", "CREATED", actor="coordinator", provider_state="QUEUED")

    def grant(self, worker: str) -> None:
        """Drive the plane's own lease command, keeping its stdout out of the run."""
        with contextlib.redirect_stdout(io.StringIO()):
            self.plane.cmd_lease(_Namespace(unit_id="a1-u03-plane", worker=worker, ttl=60))

    def result_doc(self, fence_token: int) -> dict:
        return {
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "task_id": "a1-u03-plane",
            "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
            "immutable_input_manifest_sha256": self.dispatch["immutable_input_manifest_sha256"],
            "acceptance_contract_sha256": self.dispatch["acceptance_contract_sha256"],
            "provider_state": "COMPLETED",
            "obzio_state": "RESULT_COMMITTED",
            "attempt": {
                "attempt_id": f"a1-u03-plane-attempt-{fence_token}",
                "idempotency_key": self.dispatch["idempotency_key"],
                "lease_id": f"lease-a1-u03-plane-{fence_token}",
                "fence_token": fence_token,
                "provider_run_id": "po03-a1-subagent",
                "worker_id": "po03-worker-a1",
                "heartbeat_at": "2026-08-22T07:00:00Z",
                "checkpoint_seq": 1,
            },
            "result_transaction": {
                "result_txn_id": f"a1-u03-plane-txn-{fence_token}",
                "state": "COMMITTED",
                "manifest_uri": f"git:branch@commit-{fence_token}:manifest",
                "manifest_sha256": "3" * 64,
                "artifact_count": 1,
                "total_bytes": self.artifact_bytes,
                "committed_at": "2026-08-22T07:01:00Z",
                "verified_at": "2026-08-22T07:01:00Z",
                "parent_ingested_at": None,
                "result_commit_id": f"commit-{fence_token}",
            },
            "artifacts": [
                {
                    "artifact_id": "a1-u03-plane-art-01",
                    "logical_name": "subject.txt",
                    "content_uri": f"git:branch@commit-{fence_token}:{self.artifact_rel}",
                    "sha256": self.artifact_sha,
                    "bytes": self.artifact_bytes,
                    "media_type": "text/plain",
                    "readback_verified_at": "2026-08-22T07:01:00Z",
                }
            ],
            "completion_actor": None,
            "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
        }

    def test_coordinator_ingestion_refuses_a_stale_fence_token(self):
        self.grant("worker-1")
        self.grant("worker-2")

        with self.assertRaises(self.plane.ControlPlaneError) as caught:
            self.plane.ingest_result(self.result_doc(1), artifact_root=self.artifact_root)
        self.assertIn("stale fence token", str(caught.exception))

        rows = self.plane.ledger_rows()
        rejections = [row for row in rows if row["event"] == "FENCE_REJECTED"]
        self.assertEqual(1, len(rejections))
        self.assertEqual(1, rejections[0]["payload"]["rejected_fence_token"])
        self.assertEqual([], [row for row in rows if row["event"] == "PARENT_INGESTED"])

        outcome = self.plane.ingest_result(self.result_doc(2), artifact_root=self.artifact_root)
        self.assertFalse(outcome["duplicate"])
        ingested = [row for row in self.plane.ledger_rows() if row["event"] == "PARENT_INGESTED"]
        self.assertEqual(1, len(ingested))
        self.assertEqual(2, ingested[0]["fence_token"])

    def test_engine_verifier_agrees_the_plane_ledger_is_intact(self):
        self.grant("worker-1")
        self.plane.ingest_result(self.result_doc(1), artifact_root=self.artifact_root)
        engine_view = HashChainedLedger(self.plane.LEDGER_PATH)
        verification = engine_view.verify(require_anchor=False)
        self.assertTrue(verification.ok, verification.as_dict())

    def test_duplicate_ingestion_of_the_same_result_is_a_harmless_no_op(self):
        self.grant("worker-1")
        document = self.result_doc(1)
        first = self.plane.ingest_result(document, artifact_root=self.artifact_root)
        second = self.plane.ingest_result(json.loads(json.dumps(document)), artifact_root=self.artifact_root)
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        ingested = [row for row in self.plane.ledger_rows() if row["event"] == "PARENT_INGESTED"]
        self.assertEqual(1, len(ingested))
        duplicates = [row for row in self.plane.ledger_rows() if row["event"] == "DUPLICATE_IGNORED"]
        self.assertEqual(1, len(duplicates))


class _Namespace:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


if __name__ == "__main__":
    unittest.main()
