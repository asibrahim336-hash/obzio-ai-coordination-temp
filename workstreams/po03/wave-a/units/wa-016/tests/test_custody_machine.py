"""Custody guards: what the machine refuses, and what survives a crash."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from harness import custody_invariants, fixtures
from harness.custody_machine import (
    Clock,
    Coordinator,
    CustodyRefused,
    CustodyStore,
    ExternalWorld,
    IllegalTransition,
    LEGAL_TRANSITIONS,
    STATES,
    to_transactional_result,
)
from harness.durable_io import sha256_bytes
from harness.fault_injector import (
    ExternalUnavailable,
    FencedOut,
    IdempotencyConflict,
    ProcessLoss,
    quiet,
    single,
)

TASK = fixtures.TASK_ID


class StoreCase(unittest.TestCase):
    """A store driven to a requested lifecycle state, ready to be faulted."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="po03-wa016-machine-")
        self.root = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)
        self.injector = quiet()
        self.clock = Clock()
        self.world = ExternalWorld(self.injector)
        self.store = CustodyStore(self.root, self.injector, self.clock)
        self.coordinator = Coordinator(self.store)
        self.input = fixtures.immutable_input_stub()

    def drive(self, upto: str, *, store: CustodyStore | None = None, fence: int = 1) -> CustodyStore:
        store = store or self.store
        store.create(TASK, self.input)
        if upto == "CREATED":
            return store
        store.lease(TASK, self.input["attempt_id"], fence, self.input["idempotency_key"], self.input["lease_id"])
        if upto == "LEASED":
            return store
        store.start(TASK, fence)
        if upto == "RUNNING":
            return store
        store.checkpoint(TASK, fence, 1)
        if upto == "CHECKPOINTED":
            return store
        store.begin_staging(TASK, fence)
        if upto == "RESULT_STAGING":
            return store
        store.stage_artifacts(TASK, fence, fixtures.default_payload())
        if upto == "RESULT_STAGED":
            return store
        store.verify_staged(TASK, fence)
        if upto == "RESULT_VERIFIED":
            return store
        store.commit_result(TASK, fence, self.world)
        if upto == "RESULT_COMMITTED":
            return store
        store.verify_readback(TASK, self.world)
        store.relay(TASK, self.coordinator)
        if upto == "PARENT_INGESTED":
            return store
        self.coordinator.complete(TASK, self.world)
        return store

    def arm(self, injector):
        """Swap in a fault schedule everywhere the live store can reach it.

        The store, its write layer and the external world each hold their own
        reference, so replacing only one of them would arm nothing.
        """
        self.injector = injector
        self.store.injector = injector
        self.store.io.injector = injector
        self.world.injector = injector
        return injector

    def reopen(self, injector=None) -> CustodyStore:
        """Rebuild the store from disk, as a restarted worker would."""
        self.injector = injector or self.injector
        self.store = CustodyStore(self.root, self.injector, self.clock)
        self.world.injector = self.injector
        self.coordinator = Coordinator(self.store)
        self.coordinator.restart()
        return self.store


class TransitionTableTests(unittest.TestCase):
    def test_every_state_has_a_declared_transition_set(self):
        self.assertEqual(set(STATES), set(LEGAL_TRANSITIONS))

    def test_every_target_is_a_declared_state(self):
        for source, targets in LEGAL_TRANSITIONS.items():
            for target in targets:
                self.assertIn(target, STATES, f"{source} -> {target}")

    def test_terminal_states_have_no_exit(self):
        for terminal in ("COMPLETED", "FAILED_TERMINAL", "CANCELLED"):
            self.assertEqual(frozenset(), LEGAL_TRANSITIONS[terminal])

    def test_completed_is_reachable_only_from_parent_ingested(self):
        sources = [s for s, targets in LEGAL_TRANSITIONS.items() if "COMPLETED" in targets]
        self.assertEqual(["PARENT_INGESTED"], sources)


class GuardTests(StoreCase):
    def test_skipping_the_lifecycle_is_refused(self):
        self.drive("LEASED")
        with self.assertRaises(IllegalTransition):
            self.store.begin_staging(TASK, 1)
        self.assertIn("ILLEGAL_TRANSITION", {r["reason"] for r in self.store.state(TASK).refusals})

    def test_a_stale_fence_token_is_refused(self):
        self.drive("RUNNING")
        self.store.bump_fence(TASK, 5)
        with self.assertRaises(FencedOut):
            self.store.checkpoint(TASK, 1, 2)
        self.assertIn("FENCED_OUT", {r["reason"] for r in self.store.state(TASK).refusals})

    def test_a_fence_token_must_increase_strictly(self):
        self.drive("RUNNING")
        self.store.bump_fence(TASK, 2)
        with self.assertRaises(CustodyRefused):
            self.store.bump_fence(TASK, 2)

    def test_checkpoints_must_increase_strictly(self):
        self.drive("CHECKPOINTED")
        with self.assertRaises(CustodyRefused):
            self.store.checkpoint(TASK, 1, 1)
        self.assertIn("NON_MONOTONIC_CHECKPOINT", {r["reason"] for r in self.store.state(TASK).refusals})

    def test_readback_before_a_commit_is_refused(self):
        self.drive("RESULT_VERIFIED")
        with self.assertRaises(CustodyRefused):
            self.store.verify_readback(TASK, self.world)

    def test_every_refusal_is_journaled_rather_than_swallowed(self):
        self.drive("LEASED")
        with self.assertRaises(IllegalTransition):
            self.store.begin_staging(TASK, 1)
        reopened = self.reopen()
        self.assertIn("ILLEGAL_TRANSITION", {r["reason"] for r in reopened.state(TASK).refusals})


class ProviderClaimTests(StoreCase):
    def test_provider_completion_without_a_commit_is_not_completion(self):
        self.drive("RUNNING")
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", self.store.observe_provider(TASK, "COMPLETED"))
        state = self.store.state(TASK)
        self.assertNotIn("COMPLETED", state.history)
        self.assertIsNone(state.result_commit_id)

    def test_provider_completion_after_a_commit_leaves_the_state_alone(self):
        self.drive("RESULT_COMMITTED")
        self.assertEqual("RESULT_COMMITTED", self.store.observe_provider(TASK, "COMPLETED"))

    def test_the_provider_claim_is_recorded_even_when_it_changes_nothing(self):
        self.drive("RESULT_COMMITTED")
        self.store.observe_provider(TASK, "COMPLETED")
        self.assertEqual("COMPLETED", self.reopen().state(TASK).provider_state)


class CompletionGateTests(StoreCase):
    def test_completion_requires_the_coordinator(self):
        self.drive("PARENT_INGESTED")
        self.assertEqual("REFUSED", self.coordinator.complete(TASK, self.world, actor="worker"))
        self.assertNotIn("COMPLETED", self.store.state(TASK).history)

    def test_completion_requires_a_full_readback(self):
        self.drive("RESULT_COMMITTED")
        self.store.relay(TASK, self.coordinator)
        self.assertEqual("PARENT_INGESTED", self.store.state(TASK).obzio_state)
        self.assertEqual("REFUSED", self.coordinator.complete(TASK, self.world))

    def test_completion_refuses_when_the_remote_artifact_no_longer_reconciles(self):
        self.drive("PARENT_INGESTED")
        state = self.store.state(TASK)
        self.world.corrupt(state.result_commit_id, "canary.txt")
        self.assertEqual("REFUSED", self.coordinator.complete(TASK, self.world))
        self.assertIn("READBACK_FAILED", {r["reason"] for r in self.store.state(TASK).refusals})

    def test_a_fully_evidenced_result_completes_once(self):
        self.drive("COMPLETED")
        state = self.store.state(TASK)
        self.assertEqual("COMPLETED", state.obzio_state)
        self.assertEqual("coordinator", state.completion_actor)
        self.assertEqual(1, state.history.count("COMPLETED"))

    def test_ingestion_without_a_durable_commit_is_refused(self):
        self.drive("RUNNING")
        outcome = self.coordinator.ingest(
            TASK,
            {"outbox_id": "ob-forged-1", "idempotency_key": self.input["idempotency_key"], "kind": "RESULT_READY"},
        )
        self.assertEqual("REFUSED_NO_COMMIT", outcome)
        self.assertIn("INGEST_WITHOUT_COMMIT", {r["reason"] for r in self.store.state(TASK).refusals})


class StagingVerificationTests(StoreCase):
    def test_staged_verification_rejects_corrupted_bytes(self):
        self.drive("RESULT_STAGED")
        path = self.store.io.path(f"staging/{TASK}/canary.txt")
        path.write_bytes(path.read_bytes() + b"\x00corrupted")
        with self.assertRaises(CustodyRefused):
            self.store.verify_staged(TASK, 1)
        self.assertEqual("RECOVERY_REQUIRED", self.store.state(TASK).obzio_state)

    def test_staged_verification_rejects_a_missing_artifact(self):
        self.drive("RESULT_STAGED")
        self.store.io.path(f"staging/{TASK}/canary.txt").unlink()
        with self.assertRaises(CustodyRefused):
            self.store.verify_staged(TASK, 1)
        self.assertEqual(
            [{"logical_name": "canary.txt", "reason": "MISSING"}],
            [m for m in self.store.reconcile_staged(TASK) if m["logical_name"] == "canary.txt"],
        )

    def test_damage_between_verify_and_commit_is_refused(self):
        """Recurrence test for M3.

        The manifest is frozen at verification, so damage landing afterwards was
        published under the earlier digest and the spent idempotency key then
        blocked the repair.
        """
        self.drive("RESULT_VERIFIED")
        path = self.store.io.path(f"staging/{TASK}/canary.txt")
        path.write_bytes(b"substituted bytes\n")
        with self.assertRaises(CustodyRefused):
            self.store.commit_result(TASK, 1, self.world)
        state = self.store.state(TASK)
        self.assertEqual("RECOVERY_REQUIRED", state.obzio_state)
        self.assertIn("PRE_COMMIT_RECONCILIATION_FAILED", {r["reason"] for r in state.refusals})
        # Nothing was published, so the effect key is still spendable by a repair.
        self.assertEqual(0, self.world.distinct_effect_count)
        self.assertIsNone(state.result_commit_id)


class ExternalEffectTests(StoreCase):
    def test_a_replayed_commit_produces_one_durable_effect(self):
        self.drive("RESULT_COMMITTED")
        first = self.store.state(TASK).result_commit_id
        self.assertEqual(first, self.store.commit_result(TASK, 1, self.world))
        self.assertEqual(1, self.world.distinct_effect_count)
        self.assertEqual(1, self.store.state(TASK).history.count("RESULT_COMMITTED"))

    def test_divergent_bytes_under_one_key_raise_a_conflict(self):
        self.drive("RESULT_COMMITTED")
        self.store.record_event("TRANSITION", TASK, **{"from": "RESULT_COMMITTED", "to": "RECOVERY_REQUIRED"})
        self.store.begin_staging(TASK, 1)
        self.store.stage_artifacts(
            TASK,
            1,
            [("canary.txt", b"different\n"), ("unit-result.json", fixtures.unit_result_payload())],
        )
        self.store.verify_staged(TASK, 1)
        with self.assertRaises(IdempotencyConflict):
            self.store.commit_result(TASK, 1, self.world)
        self.assertEqual(1, self.world.distinct_effect_count)

    def test_a_lost_acknowledgement_still_leaves_the_effect_durable(self):
        self.drive("RESULT_VERIFIED")
        self.arm(single("NETWORK_INTERRUPTION", "post_external_effect"))
        with self.assertRaises(ExternalUnavailable):
            self.store.commit_result(TASK, 1, self.world)
        # The world holds the commit; the worker never learned its id.
        self.assertIsNotNone(self.world.lookup(self.store.result_ref(TASK)))
        self.assertIsNone(self.store.state(TASK).result_commit_id)

    def test_an_interruption_before_the_effect_leaves_the_world_untouched(self):
        self.drive("RESULT_VERIFIED")
        self.arm(single("NETWORK_INTERRUPTION", "pre_external_effect"))
        with self.assertRaises(ExternalUnavailable):
            self.store.commit_result(TASK, 1, self.world)
        self.assertIsNone(self.world.lookup(self.store.result_ref(TASK)))
        self.assertEqual(0, self.world.distinct_effect_count)

    def test_identical_trees_converge_on_one_commit_id(self):
        tree = {"a.txt": b"alpha", "b.txt": b"beta"}
        ref = "refs/po03/probe"
        self.assertEqual(
            ExternalWorld.commit_id_for(ref, tree),
            ExternalWorld.commit_id_for(ref, dict(reversed(list(tree.items())))),
        )
        self.assertNotEqual(
            ExternalWorld.commit_id_for(ref, tree),
            ExternalWorld.commit_id_for(ref, {**tree, "b.txt": b"gamma"}),
        )


class CallbackTests(StoreCase):
    def test_the_outbox_entry_lands_with_the_commit_record(self):
        self.drive("RESULT_COMMITTED")
        pending = self.store.pending_callbacks(TASK)
        self.assertEqual(1, len(pending))
        self.assertEqual(self.store.state(TASK).result_commit_id, pending[0]["result_commit_id"])
        # It survives a restart, because it was journaled with the transition.
        self.assertEqual(1, len(self.reopen().pending_callbacks(TASK)))

    def test_a_lost_callback_leaves_the_entry_pending(self):
        self.drive("RESULT_COMMITTED")
        self.arm(single("CALLBACK_LOSS", "pre_callback_send"))
        outcome = self.store.relay(TASK, self.coordinator)
        self.assertEqual(["LOST_IN_TRANSIT"], [o["outcome"] for o in outcome])
        self.assertEqual(1, len(self.store.pending_callbacks(TASK)))
        self.assertNotIn("PARENT_INGESTED", self.store.state(TASK).history)

    def test_a_duplicated_callback_ingests_once(self):
        self.drive("RESULT_COMMITTED")
        self.arm(single("DUPLICATE_CALLBACK", "pre_callback_send"))
        delivered = self.store.relay(TASK, self.coordinator)
        self.assertEqual(["INGESTED", "DUPLICATE_IGNORED"], delivered[0]["deliveries"])
        self.assertEqual(1, self.store.state(TASK).history.count("PARENT_INGESTED"))

    def test_a_parent_restart_rebuilds_idempotency_from_the_journal(self):
        self.drive("PARENT_INGESTED")
        self.coordinator.restart()
        self.assertTrue(self.coordinator.seen_keys)
        replay = self.coordinator.ingest(TASK, self.store.state(TASK).outbox[0])
        self.assertEqual("DUPLICATE_IGNORED", replay)
        self.assertEqual(1, self.store.state(TASK).history.count("PARENT_INGESTED"))


class JournalIsTruthTests(StoreCase):
    def test_state_rebuilds_from_the_journal_alone(self):
        self.drive("RESULT_VERIFIED")
        before = self.store.describe(TASK)
        self.store.io.path("state.json").unlink()
        self.assertEqual(before, self.reopen().describe(TASK))

    def test_a_lost_snapshot_write_does_not_lose_the_transition(self):
        self.drive("RUNNING")
        self.arm(single("SNAPSHOT_ROLLBACK", "pre_snapshot_write"))
        with self.assertRaises(ProcessLoss):
            self.store.checkpoint(TASK, 1, 1)
        reopened = self.reopen(quiet())
        self.assertEqual("CHECKPOINTED", reopened.state(TASK).obzio_state)
        self.assertEqual(1, reopened.state(TASK).checkpoint_seq)

    def test_checkpoint_sequence_lands_atomically_with_the_transition(self):
        """Recurrence test for M7.

        The sequence number used to travel in a second journal record, so a
        crash in between produced a task claiming CHECKPOINTED at sequence 0.
        """
        self.drive("RUNNING")
        self.arm(single("SNAPSHOT_ROLLBACK", "pre_snapshot_write"))
        with self.assertRaises(ProcessLoss):
            self.store.checkpoint(TASK, 1, 1)
        reopened = self.reopen(quiet())
        state = reopened.state(TASK)
        self.assertEqual("CHECKPOINTED", state.obzio_state)
        self.assertEqual(1, state.checkpoint_seq)
        # Whatever survived, the pair is consistent: never checkpointed at zero.
        self.assertNotEqual(("CHECKPOINTED", 0), (state.obzio_state, state.checkpoint_seq))

    def test_a_crash_before_the_journal_append_loses_the_transition_cleanly(self):
        self.drive("RUNNING")
        self.arm(single("PRE_WRITE_LOSS", "pre_journal_append"))
        with self.assertRaises(ProcessLoss):
            self.store.begin_staging(TASK, 1)
        self.assertEqual("RUNNING", self.reopen(quiet()).state(TASK).obzio_state)

    def test_a_torn_tail_is_healed_and_reported(self):
        self.drive("RUNNING")
        self.arm(single("PARTIAL_WRITE", "journal_append_partial"))
        with self.assertRaises(ProcessLoss):
            self.store.checkpoint(TASK, 1, 1)
        reopened = self.reopen(quiet())
        self.assertEqual("RUNNING", reopened.state(TASK).obzio_state)
        self.assertTrue(reopened.journal_heals)
        self.assertFalse(reopened.io.read_records("journal.jsonl").torn)

    def test_journal_sequence_numbers_stay_gapless(self):
        self.drive("COMPLETED")
        seqs = [int(r["seq"]) for r in self.store.io.read_records("journal.jsonl").records]
        self.assertEqual(list(range(1, len(seqs) + 1)), seqs)


class DocumentTests(StoreCase):
    def test_a_completed_run_emits_a_document_both_layers_accept(self):
        self.drive("COMPLETED")
        document = to_transactional_result(
            self.store,
            TASK,
            commission_id=fixtures.COMMISSION_ID,
            immutable_input_manifest_sha256="b574ca414864bec359a8edef86f13f064a31a4304eed5c5b95fab83eae88a824",
            acceptance_contract_sha256="b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a",
            provider_run_id="bc-b1956656-b897-4889-aeab-82c4556c1a9f",
            worker_id="best-of-n-runner-bc-b1956656-wa-016-a01",
        )
        self.assertEqual([], custody_invariants.validate_result_strict(document))
        self.assertEqual("INGESTED", document["result_transaction"]["state"])
        self.assertEqual("coordinator", document["completion_actor"])
        self.assertTrue(all(a["readback_verified_at"] for a in document["artifacts"]))

    def test_an_uncommitted_provider_claim_emits_an_uncommitted_document(self):
        self.drive("RUNNING")
        self.store.observe_provider(TASK, "COMPLETED")
        document = to_transactional_result(
            self.store,
            TASK,
            commission_id=fixtures.COMMISSION_ID,
            immutable_input_manifest_sha256="b574ca414864bec359a8edef86f13f064a31a4304eed5c5b95fab83eae88a824",
            acceptance_contract_sha256="b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a",
            provider_run_id="bc-b1956656-b897-4889-aeab-82c4556c1a9f",
            worker_id="best-of-n-runner-bc-b1956656-wa-016-a01",
        )
        self.assertEqual("PROVIDER_COMPLETED_UNCOMMITTED", document["obzio_state"])
        self.assertEqual("COMPLETED", document["provider_state"])
        self.assertIsNone(document["result_transaction"]["result_commit_id"])
        self.assertIsNone(document["completion_actor"])
        self.assertEqual([], custody_invariants.validate_result_strict(document))

    def test_the_manifest_digest_covers_exactly_the_staged_artifacts(self):
        self.drive("RESULT_VERIFIED")
        manifest = self.store.manifest_document(TASK)
        state = self.store.state(TASK)
        self.assertEqual(state.artifact_count, manifest["artifact_count"])
        self.assertEqual(state.total_bytes, manifest["total_bytes"])
        for entry in manifest["artifacts"]:
            staged = self.store.io.read_artifact(f"staging/{TASK}/{entry['logical_name']}")
            self.assertEqual(entry["sha256"], sha256_bytes(staged))
            self.assertEqual(entry["bytes"], len(staged))


if __name__ == "__main__":
    unittest.main()
