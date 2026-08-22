#!/usr/bin/env python3
"""Focused tests for the WA-015 transactional outbox processor."""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from typing import Any

from _support import UNIT_ROOT, silenced  # noqa: F401  (path bootstrap)

import outbox_processor as mechanism
from outbox_processor import (
    EffectRebinding,
    FramedJournal,
    IdempotentEffectSink,
    InjectedCrash,
    MalformedCallback,
    OutboxProcessor,
    canonical_bytes,
    digest,
    encode_frame,
    load_workload,
    normalize_callback,
    scan_frames,
)


TASK = "T-CUSTODY"
COMMIT_EFFECT = {
    "effect_key": "ef-commit",
    "kind": "durable_result_commit",
    "payload": {"artifact_count": 2},
}
INGEST_EFFECT = {
    "effect_key": "ef-ingest",
    "kind": "parent_ingestion",
    "payload": {"parent_id": "PO03-WAVE-A"},
}


def cb(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"task_id": TASK, "fence_token": 1}
    base.update(overrides)
    return base


def happy_path() -> list[dict[str, Any]]:
    return [
        cb(
            delivery_id="d01",
            actor="controller:ctl",
            from_state="CREATED",
            to_state="LEASED",
            checkpoint_seq=0,
            producer_id="w1",
        ),
        cb(delivery_id="d02", actor="worker:w1", from_state="LEASED", to_state="RUNNING", checkpoint_seq=0),
        cb(delivery_id="d03", actor="worker:w1", from_state="RUNNING", to_state="CHECKPOINTED", checkpoint_seq=1),
        cb(delivery_id="d04", actor="worker:w1", from_state="CHECKPOINTED", to_state="CHECKPOINTED", checkpoint_seq=2),
        cb(delivery_id="d05", actor="worker:w1", from_state="CHECKPOINTED", to_state="RESULT_STAGING", checkpoint_seq=2),
        cb(delivery_id="d06", actor="worker:w1", from_state="RESULT_STAGING", to_state="RESULT_STAGED", checkpoint_seq=2),
        cb(delivery_id="d07", actor="controller:ctl", from_state="RESULT_STAGED", to_state="RESULT_VERIFIED", checkpoint_seq=2),
        cb(
            delivery_id="d08",
            actor="worker:w1",
            from_state="RESULT_VERIFIED",
            to_state="RESULT_COMMITTED",
            checkpoint_seq=2,
            effect=dict(COMMIT_EFFECT),
        ),
        cb(
            delivery_id="d09",
            actor="controller:ctl",
            from_state="RESULT_COMMITTED",
            to_state="PARENT_INGESTED",
            checkpoint_seq=2,
            effect=dict(INGEST_EFFECT),
        ),
        cb(delivery_id="d10", actor="coordinator:coord", from_state="PARENT_INGESTED", to_state="COMPLETED", checkpoint_seq=2),
        cb(delivery_id="d11", actor="reviewer:rev", from_state="COMPLETED", to_state="ACCEPTED", checkpoint_seq=2),
    ]


class StoreCase(unittest.TestCase):
    """A registered single-task store in a fresh temporary directory."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="wa015-test-")
        self.addCleanup(self._tmp.cleanup)
        self.store = Path(self._tmp.name) / "store"
        self.processor = self.open_store()
        self.processor.register({"task_id": TASK})

    def open_store(self, fault: Any = mechanism.NO_FAULT) -> OutboxProcessor:
        return OutboxProcessor(self.store, fault=fault)

    @property
    def task(self) -> dict[str, Any]:
        return self.processor.tasks[TASK]

    def apply(self, document: Any) -> dict[str, Any]:
        outcome = self.processor.handle(document)
        self.assertEqual(outcome["decision"], "APPLIED", outcome)
        return outcome

    def reject(self, document: Any, code: str) -> dict[str, Any]:
        outcome = self.processor.handle(document)
        self.assertEqual(outcome["decision"], "REJECTED", outcome)
        self.assertEqual(outcome["code"], code, outcome)
        return outcome

    def advance_to(self, state: str) -> None:
        for step in happy_path():
            if self.task["state"] == state:
                return
            if step.get("from_state") != self.task["state"]:
                continue
            self.apply(step)
        self.assertEqual(self.task["state"], state)


class TestCanonicalEncoding(unittest.TestCase):
    def test_key_order_does_not_change_bytes(self) -> None:
        self.assertEqual(
            canonical_bytes({"b": 1, "a": 2}), canonical_bytes({"a": 2, "b": 1})
        )

    def test_encoding_has_no_insignificant_whitespace(self) -> None:
        self.assertEqual(canonical_bytes({"a": [1, 2]}), b'{"a":[1,2]}')

    def test_digest_is_stable_across_equal_values(self) -> None:
        self.assertEqual(digest({"a": "ö"}), digest({"a": "ö"}))

    def test_digest_separates_distinct_values(self) -> None:
        self.assertNotEqual(digest({"a": 1}), digest({"a": "1"}))


class TestFraming(unittest.TestCase):
    def test_roundtrip_preserves_payload_order(self) -> None:
        data = encode_frame(b"one") + encode_frame(b"two")
        payloads, end, torn = scan_frames(data)
        self.assertEqual(payloads, [b"one", b"two"])
        self.assertEqual(end, len(data))
        self.assertIsNone(torn)

    def test_short_header_is_a_torn_tail(self) -> None:
        data = encode_frame(b"one") + b"OBZ"
        payloads, end, torn = scan_frames(data)
        self.assertEqual(payloads, [b"one"])
        self.assertEqual(torn, "SHORT_HEADER")
        self.assertEqual(end, len(encode_frame(b"one")))

    def test_bad_magic_is_a_torn_tail(self) -> None:
        data = encode_frame(b"one") + b"XXXXX" + struct.pack(">II", 1, 0) + b"z"
        self.assertEqual(scan_frames(data)[2], "BAD_MAGIC")

    def test_short_payload_is_a_torn_tail(self) -> None:
        frame = encode_frame(b"payload")
        self.assertEqual(scan_frames(frame[:-2])[2], "SHORT_PAYLOAD")

    def test_flipped_payload_byte_is_a_checksum_failure(self) -> None:
        frame = bytearray(encode_frame(b"payload"))
        frame[-1] ^= 0xFF
        self.assertEqual(scan_frames(bytes(frame))[2], "CRC_MISMATCH")

    def test_checksum_covers_the_declared_length(self) -> None:
        payload = b"payload"
        frame = encode_frame(payload)
        length, crc = struct.unpack(">II", frame[5:13])
        self.assertEqual(length, len(payload))
        self.assertEqual(crc, zlib.crc32(payload) & 0xFFFFFFFF)

    def test_empty_data_is_intact(self) -> None:
        self.assertEqual(scan_frames(b""), ([], 0, None))


class TestFramedJournal(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="wa015-journal-")
        self.addCleanup(self._tmp.cleanup)
        self.journal = FramedJournal(Path(self._tmp.name) / "nested" / "journal.log")

    def test_missing_file_reads_as_empty(self) -> None:
        self.assertEqual(self.journal.read(), ([], 0, None))

    def test_append_creates_parents_and_is_readable(self) -> None:
        self.journal.append(b"a")
        self.journal.append(b"b")
        self.assertEqual(self.journal.read()[0], [b"a", b"b"])

    def test_partial_append_is_detected_and_truncatable(self) -> None:
        self.journal.append(b"first")
        self.journal.append(b"second", keep_bytes=6)
        payloads, intact, torn = self.journal.read()
        self.assertEqual(payloads, [b"first"])
        self.assertEqual(torn, "SHORT_HEADER")
        self.journal.truncate(intact)
        self.assertEqual(self.journal.read(), ([b"first"], intact, None))


class TestEffectSink(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="wa015-sink-")
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "effects.log"

    def open_sink(self, fault: Any = mechanism.NO_FAULT) -> IdempotentEffectSink:
        return IdempotentEffectSink(self.path, fault=fault)

    def test_first_apply_is_applied_and_second_is_already_applied(self) -> None:
        sink = self.open_sink()
        self.assertEqual(sink.apply(TASK, COMMIT_EFFECT)["status"], "APPLIED")
        self.assertEqual(sink.apply(TASK, COMMIT_EFFECT)["status"], "ALREADY_APPLIED")
        self.assertEqual(sink.effect_count, 1)

    def test_idempotence_survives_reopen(self) -> None:
        self.open_sink().apply(TASK, COMMIT_EFFECT)
        reopened = self.open_sink()
        self.assertEqual(reopened.apply(TASK, COMMIT_EFFECT)["status"], "ALREADY_APPLIED")
        self.assertEqual(reopened.effect_count, 1)

    def test_receipt_sequence_is_dense_and_ordered(self) -> None:
        sink = self.open_sink()
        sink.apply(TASK, COMMIT_EFFECT)
        sink.apply(TASK, INGEST_EFFECT)
        self.assertEqual(
            [row["receipt_seq"] for row in sink.receipts()], [1, 2]
        )

    def test_reused_key_with_new_payload_is_refused(self) -> None:
        sink = self.open_sink()
        sink.apply(TASK, COMMIT_EFFECT)
        mutated = dict(COMMIT_EFFECT, payload={"artifact_count": 99})
        with self.assertRaises(EffectRebinding):
            sink.apply(TASK, mutated)

    def test_torn_record_is_truncated_and_reapplied_once(self) -> None:
        class Tear:
            def trip(self, point: str) -> None:
                return None

            def tear(self, point: str) -> int | None:
                return 7 if point == "sink_torn_write" else None

        with self.assertRaises(InjectedCrash):
            self.open_sink(fault=Tear()).apply(TASK, COMMIT_EFFECT)
        recovered = self.open_sink()
        self.assertEqual(recovered.torn_reason, "SHORT_HEADER")
        self.assertEqual(recovered.truncated_bytes, 7)
        self.assertEqual(recovered.effect_count, 0)
        self.assertEqual(recovered.apply(TASK, COMMIT_EFFECT)["status"], "APPLIED")
        self.assertEqual(self.open_sink().effect_count, 1)


class TestNormalizeCallback(unittest.TestCase):
    def test_minimal_transition_is_accepted(self) -> None:
        call = normalize_callback(
            cb(delivery_id="d", actor="worker:w1", from_state="LEASED", to_state="RUNNING")
        )
        self.assertEqual(call["checkpoint_seq"], 0)
        self.assertEqual(call["actor_role"], "worker")
        self.assertEqual(call["actor_id"], "w1")

    def test_digest_ignores_the_delivery_id(self) -> None:
        left = normalize_callback(
            cb(delivery_id="a", actor="worker:w1", from_state="LEASED", to_state="RUNNING")
        )
        right = normalize_callback(
            cb(delivery_id="b", actor="worker:w1", from_state="LEASED", to_state="RUNNING")
        )
        self.assertEqual(
            mechanism.callback_digest(left), mechanism.callback_digest(right)
        )

    def test_digest_separates_differing_payloads(self) -> None:
        left = normalize_callback(
            cb(delivery_id="a", actor="worker:w1", from_state="LEASED", to_state="RUNNING")
        )
        right = normalize_callback(
            cb(
                delivery_id="a",
                actor="worker:w1",
                from_state="LEASED",
                to_state="RUNNING",
                checkpoint_seq=1,
            )
        )
        self.assertNotEqual(
            mechanism.callback_digest(left), mechanism.callback_digest(right)
        )

    def _malformed(self, document: Any) -> None:
        with self.assertRaises(MalformedCallback):
            normalize_callback(document)

    def test_non_object_delivery_is_malformed(self) -> None:
        for document in ("string", 7, None, ["a"]):
            self._malformed(document)

    def test_unknown_field_is_malformed(self) -> None:
        self._malformed(
            cb(delivery_id="d", actor="worker:w1", from_state="LEASED", to_state="RUNNING", extra=1)
        )

    def test_missing_required_field_is_malformed(self) -> None:
        self._malformed({"task_id": TASK, "actor": "worker:w1", "fence_token": 1})
        self._malformed({"delivery_id": "d", "actor": "worker:w1", "fence_token": 1})
        self._malformed({"delivery_id": "d", "task_id": TASK, "fence_token": 1})
        self._malformed({"delivery_id": "d", "task_id": TASK, "actor": "worker:w1"})

    def test_blank_and_mistyped_fields_are_malformed(self) -> None:
        self._malformed(cb(delivery_id="  ", actor="worker:w1", from_state="LEASED", to_state="RUNNING"))
        self._malformed(cb(delivery_id="d", actor="worker:w1", from_state="LEASED", to_state="RUNNING", fence_token="1"))
        self._malformed(cb(delivery_id="d", actor="worker:w1", from_state="LEASED", to_state="RUNNING", fence_token=True))
        self._malformed(cb(delivery_id="d", actor="worker:w1", from_state="LEASED", to_state="RUNNING", fence_token=0))
        self._malformed(cb(delivery_id="d", actor="worker:w1", from_state="LEASED", to_state="RUNNING", checkpoint_seq=-1))

    def test_actor_outside_the_role_vocabulary_is_malformed(self) -> None:
        self._malformed(cb(delivery_id="d", actor="ghost:w1", from_state="LEASED", to_state="RUNNING"))
        self._malformed(cb(delivery_id="d", actor="worker:", from_state="LEASED", to_state="RUNNING"))
        self._malformed(cb(delivery_id="d", actor="w1", from_state="LEASED", to_state="RUNNING"))

    def test_unknown_kind_or_state_is_malformed(self) -> None:
        self._malformed(cb(delivery_id="d", actor="worker:w1", kind="gossip"))
        self._malformed(cb(delivery_id="d", actor="worker:w1", from_state="INVENTED", to_state="RUNNING"))
        self._malformed(cb(delivery_id="d", actor="worker:w1", from_state="LEASED", to_state="INVENTED"))

    def test_transition_requires_both_states(self) -> None:
        self._malformed(cb(delivery_id="d", actor="worker:w1", from_state="LEASED"))
        self._malformed(cb(delivery_id="d", actor="worker:w1", to_state="RUNNING"))

    def test_producer_id_is_confined_to_the_lease_edge(self) -> None:
        self._malformed(
            cb(delivery_id="d", actor="controller:ctl", from_state="CREATED", to_state="LEASED")
        )
        self._malformed(
            cb(
                delivery_id="d",
                actor="worker:w1",
                from_state="LEASED",
                to_state="RUNNING",
                producer_id="w1",
            )
        )

    def test_effect_shape_is_enforced(self) -> None:
        for effect in (
            "not-an-object",
            {"effect_key": "k", "kind": "k"},
            {"effect_key": "", "kind": "k", "payload": {}},
            {"effect_key": "k", "kind": "", "payload": {}},
            {"effect_key": "k", "kind": "k", "payload": []},
            {"effect_key": "k", "kind": "k", "payload": {}, "extra": 1},
        ):
            self._malformed(
                cb(
                    delivery_id="d",
                    actor="worker:w1",
                    from_state="RESULT_VERIFIED",
                    to_state="RESULT_COMMITTED",
                    effect=effect,
                )
            )

    def test_lease_transfer_field_discipline(self) -> None:
        self._malformed(cb(delivery_id="d", actor="controller:ctl", kind="lease_transfer"))
        self._malformed(
            cb(
                delivery_id="d",
                actor="controller:ctl",
                kind="lease_transfer",
                new_producer_id="w2",
                from_state="RUNNING",
            )
        )

    def test_provider_observation_field_discipline(self) -> None:
        self._malformed(cb(delivery_id="d", actor="provider:p", kind="provider_observation"))
        self._malformed(
            cb(delivery_id="d", actor="provider:p", kind="provider_observation", provider_state="DONE")
        )
        self._malformed(
            cb(
                delivery_id="d",
                actor="provider:p",
                kind="provider_observation",
                provider_state="COMPLETED",
                to_state="COMPLETED",
            )
        )


class TestWorkloadLoading(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="wa015-workload-")
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "workload.json"

    def write(self, document: Any) -> Path:
        self.path.write_text(json.dumps(document), encoding="utf-8")
        return self.path

    def valid(self) -> dict[str, Any]:
        return {
            "protocol_version": mechanism.WORKLOAD_PROTOCOL,
            "tasks": [{"task_id": TASK}],
            "callbacks": [{"ref": "one", "delivery_id": "d", "task_id": TASK, "actor": "worker:w1", "fence_token": 1}],
        }

    def test_valid_workload_loads(self) -> None:
        self.assertEqual(load_workload(self.write(self.valid()))["tasks"][0]["task_id"], TASK)

    def test_shipped_workload_loads(self) -> None:
        document = load_workload(UNIT_ROOT / "fixtures" / "sanitized-workload.json")
        self.assertGreaterEqual(len(document["tasks"]), 3)
        self.assertGreaterEqual(len(document["callbacks"]), 30)

    def _invalid(self, document: Any) -> None:
        with self.assertRaises(ValueError):
            load_workload(self.write(document))

    def test_protocol_and_shape_are_enforced(self) -> None:
        self._invalid(["not", "an", "object"])
        self._invalid(dict(self.valid(), protocol_version="OTHER"))
        self._invalid(dict(self.valid(), tasks=[]))
        self._invalid(dict(self.valid(), callbacks=[]))
        self._invalid(dict(self.valid(), tasks=[{"note": "no id"}]))
        self._invalid(dict(self.valid(), tasks=[{"task_id": TASK}, {"task_id": TASK}]))
        self._invalid(dict(self.valid(), callbacks=[{"delivery_id": "d"}]))
        self._invalid(
            dict(
                self.valid(),
                callbacks=[{"ref": "one", "delivery_id": "a"}, {"ref": "one", "delivery_id": "b"}],
            )
        )


class TestRegistration(StoreCase):
    def test_registration_seeds_the_initial_state(self) -> None:
        self.assertEqual(self.task["state"], "CREATED")
        self.assertEqual(self.task["fence_token"], 1)
        self.assertIsNone(self.task["producer_id"])
        self.assertEqual(self.task["transition_count"], 0)

    def test_registration_is_idempotent(self) -> None:
        before = self.processor.seq
        outcome = self.processor.register({"task_id": TASK})
        self.assertEqual(outcome["decision"], "DUPLICATE_SUPPRESSED")
        self.assertEqual(self.processor.seq, before)

    def test_registration_rejects_an_impossible_seed(self) -> None:
        with self.assertRaises(ValueError):
            self.processor.register({"task_id": "T-OTHER", "state": "INVENTED"})
        with self.assertRaises(ValueError):
            self.processor.register({"task_id": "T-OTHER", "fence_token": 0})

    def test_registration_survives_reopen(self) -> None:
        self.assertIn(TASK, self.open_store().tasks)


class TestTransactionalAppend(StoreCase):
    def test_transition_and_enqueue_share_one_frame(self) -> None:
        self.advance_to("RESULT_VERIFIED")
        before = self.processor.seq
        self.apply(happy_path()[7])
        self.assertEqual(self.processor.seq, before + 1)
        record = self.processor.records[-1]
        self.assertEqual(record["to_state"], "RESULT_COMMITTED")
        self.assertEqual(record["outbox_entry"]["effect_key"], "ef-commit")

    def test_crash_before_append_leaves_no_trace(self) -> None:
        class Fault:
            def trip(self, point: str) -> None:
                if point == "before_journal_append":
                    raise InjectedCrash(point)

            def tear(self, point: str) -> int | None:
                return None

        crashing = self.open_store(fault=Fault())
        with self.assertRaises(InjectedCrash):
            crashing.handle(happy_path()[0])
        reopened = self.open_store()
        self.assertEqual(reopened.tasks[TASK]["state"], "CREATED")
        self.assertEqual(reopened.handle(happy_path()[0])["decision"], "APPLIED")

    def test_crash_after_append_leaves_the_record_durable(self) -> None:
        class Fault:
            def trip(self, point: str) -> None:
                if point == "after_journal_append":
                    raise InjectedCrash(point)

            def tear(self, point: str) -> int | None:
                return None

        crashing = self.open_store(fault=Fault())
        with self.assertRaises(InjectedCrash):
            crashing.handle(happy_path()[0])
        reopened = self.open_store()
        self.assertEqual(reopened.tasks[TASK]["state"], "LEASED")
        self.assertEqual(
            reopened.handle(happy_path()[0])["decision"], "DUPLICATE_SUPPRESSED"
        )

    def test_torn_frame_is_truncated_rather_than_applied(self) -> None:
        class Fault:
            def trip(self, point: str) -> None:
                return None

            def tear(self, point: str) -> int | None:
                return 9 if point == "journal_torn_write" else None

        crashing = self.open_store(fault=Fault())
        with self.assertRaises(InjectedCrash):
            crashing.handle(happy_path()[0])
        reopened = self.open_store()
        self.assertEqual(reopened.recovery["journal_torn_reason"], "SHORT_HEADER")
        self.assertEqual(reopened.recovery["journal_truncated_bytes"], 9)
        self.assertEqual(reopened.tasks[TASK]["state"], "CREATED")
        self.assertEqual(reopened.handle(happy_path()[0])["decision"], "APPLIED")


class TestDuplicateSuppression(StoreCase):
    def test_exact_duplicate_adds_no_record(self) -> None:
        self.apply(happy_path()[0])
        before = self.processor.seq
        outcome = self.processor.handle(happy_path()[0])
        self.assertEqual(outcome["decision"], "DUPLICATE_SUPPRESSED")
        self.assertEqual(outcome["suppressed_decision"], "APPLIED")
        self.assertEqual(self.processor.seq, before)
        self.assertEqual(self.task["transition_count"], 1)

    def test_duplicate_survives_reopen(self) -> None:
        self.apply(happy_path()[0])
        reopened = self.open_store()
        self.assertEqual(
            reopened.handle(happy_path()[0])["decision"], "DUPLICATE_SUPPRESSED"
        )

    def test_reused_delivery_id_with_a_new_payload_is_refused(self) -> None:
        self.apply(happy_path()[0])
        self.apply(happy_path()[1])
        conflicting = dict(happy_path()[1], checkpoint_seq=5)
        self.reject(conflicting, "IDEMPOTENCY_PAYLOAD_CONFLICT")
        self.assertEqual(self.task["transition_count"], 2)

    def test_the_refusal_of_a_conflict_is_itself_idempotent(self) -> None:
        self.apply(happy_path()[0])
        self.apply(happy_path()[1])
        conflicting = dict(happy_path()[1], checkpoint_seq=5)
        self.reject(conflicting, "IDEMPOTENCY_PAYLOAD_CONFLICT")
        before = self.processor.seq
        outcome = self.processor.handle(conflicting)
        self.assertEqual(outcome["decision"], "DUPLICATE_SUPPRESSED")
        self.assertEqual(outcome["code"], "IDEMPOTENCY_PAYLOAD_CONFLICT")
        self.assertEqual(self.processor.seq, before)

    def test_repeated_malformed_delivery_is_suppressed(self) -> None:
        malformed = cb(delivery_id="dx", actor="ghost:w1", from_state="LEASED", to_state="RUNNING")
        self.reject(malformed, "MALFORMED_CALLBACK")
        before = self.processor.seq
        outcome = self.processor.handle(malformed)
        self.assertEqual(outcome["decision"], "DUPLICATE_SUPPRESSED")
        self.assertEqual(self.processor.seq, before)

    def test_a_terminal_rejection_permanently_claims_the_delivery_id(self) -> None:
        self.reject(
            cb(delivery_id="dz", actor="worker:w1", from_state="CREATED", to_state="LEASED", producer_id="w1"),
            "ROLE_NOT_PERMITTED",
        )
        outcome = self.processor.handle(
            cb(delivery_id="dz", actor="controller:ctl", from_state="CREATED", to_state="LEASED", producer_id="w1")
        )
        self.assertEqual(outcome["decision"], "REJECTED")
        self.assertEqual(outcome["code"], "IDEMPOTENCY_PAYLOAD_CONFLICT")

    def test_a_retriable_rejection_does_not_claim_the_delivery_id(self) -> None:
        outcome = self.reject(happy_path()[1], "STATE_MISMATCH")
        self.assertTrue(outcome["retriable"])
        self.apply(happy_path()[0])
        self.apply(happy_path()[1])
        self.assertEqual(self.task["state"], "RUNNING")


class TestCustodyGuards(StoreCase):
    def test_unknown_task_is_refused(self) -> None:
        self.reject(
            cb(delivery_id="dq", task_id="T-ABSENT", actor="worker:w1", from_state="LEASED", to_state="RUNNING"),
            "UNKNOWN_TASK",
        )

    def test_role_outside_the_edge_is_refused(self) -> None:
        self.reject(
            cb(delivery_id="dr", actor="worker:w1", from_state="CREATED", to_state="LEASED", producer_id="w1"),
            "ROLE_NOT_PERMITTED",
        )

    def test_state_mismatch_is_refused(self) -> None:
        self.reject(happy_path()[2], "STATE_MISMATCH")

    def test_illegal_edge_is_refused(self) -> None:
        self.advance_to("LEASED")
        self.reject(
            cb(delivery_id="ds", actor="worker:w1", from_state="LEASED", to_state="RESULT_STAGED"),
            "ILLEGAL_TRANSITION",
        )

    def test_future_fence_is_refused(self) -> None:
        self.reject(dict(happy_path()[0], delivery_id="dt", fence_token=9), "FUTURE_FENCE")

    def test_impostor_worker_is_refused(self) -> None:
        self.advance_to("RUNNING")
        self.reject(
            cb(delivery_id="du", actor="worker:w2", from_state="RUNNING", to_state="CHECKPOINTED", checkpoint_seq=1),
            "WORKER_IDENTITY_MISMATCH",
        )

    def test_checkpoint_regression_is_refused(self) -> None:
        self.advance_to("CHECKPOINTED")
        self.apply(happy_path()[3])
        self.reject(
            cb(delivery_id="dv", actor="worker:w1", from_state="CHECKPOINTED", to_state="CHECKPOINTED", checkpoint_seq=2),
            "CHECKPOINT_REGRESSION",
        )
        self.reject(
            cb(delivery_id="dw", actor="worker:w1", from_state="CHECKPOINTED", to_state="RESULT_STAGING", checkpoint_seq=1),
            "CHECKPOINT_REGRESSION",
        )

    def test_result_commit_requires_an_external_effect(self) -> None:
        self.advance_to("RESULT_VERIFIED")
        self.reject(
            cb(delivery_id="dx1", actor="worker:w1", from_state="RESULT_VERIFIED", to_state="RESULT_COMMITTED", checkpoint_seq=2),
            "MISSING_REQUIRED_EFFECT",
        )

    def test_effect_key_cannot_be_rebound(self) -> None:
        self.advance_to("RESULT_COMMITTED")
        self.reject(
            cb(
                delivery_id="dx2",
                actor="controller:ctl",
                from_state="RESULT_COMMITTED",
                to_state="PARENT_INGESTED",
                checkpoint_seq=2,
                effect=dict(COMMIT_EFFECT, payload={"artifact_count": 77}),
            ),
            "EFFECT_KEY_REBINDING",
        )

    def test_effect_key_cannot_be_rebound_after_dispatch(self) -> None:
        self.advance_to("RESULT_COMMITTED")
        self.processor.drain()
        self.reject(
            cb(
                delivery_id="dx3",
                actor="controller:ctl",
                from_state="RESULT_COMMITTED",
                to_state="PARENT_INGESTED",
                checkpoint_seq=2,
                effect=dict(COMMIT_EFFECT, payload={"artifact_count": 77}),
            ),
            "EFFECT_KEY_REBINDING",
        )

    def test_only_the_coordinator_may_record_completed(self) -> None:
        self.advance_to("PARENT_INGESTED")
        self.reject(
            cb(delivery_id="dx4", actor="worker:w1", from_state="PARENT_INGESTED", to_state="COMPLETED", checkpoint_seq=2),
            "COMPLETION_ACTOR_FORBIDDEN",
        )
        self.reject(
            cb(delivery_id="dx5", actor="controller:ctl", from_state="PARENT_INGESTED", to_state="COMPLETED", checkpoint_seq=2),
            "COMPLETION_ACTOR_FORBIDDEN",
        )

    def test_producer_cannot_accept_its_own_result(self) -> None:
        self.advance_to("COMPLETED")
        self.reject(
            cb(delivery_id="dx6", actor="reviewer:w1", from_state="COMPLETED", to_state="ACCEPTED", checkpoint_seq=2),
            "PRODUCER_SELF_REVIEW",
        )
        self.apply(happy_path()[10])
        self.assertEqual(self.task["state"], "ACCEPTED")

    def test_malformed_delivery_is_refused_without_a_task(self) -> None:
        outcome = self.reject("not a callback", "MALFORMED_CALLBACK")
        self.assertIsNone(outcome["delivery_id"])
        self.assertEqual(self.task["state"], "CREATED")

    def test_every_reject_code_is_registered_in_the_oracle(self) -> None:
        oracle = json.loads(
            (UNIT_ROOT / "reproduction" / "expected-report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            set(oracle["reject_codes_exercised"]), set(mechanism.REJECT_CODES)
        )

    def test_retriable_codes_are_a_strict_subset(self) -> None:
        self.assertTrue(
            mechanism.RETRIABLE_REJECT_CODES < set(mechanism.REJECT_CODES)
        )


class TestLeaseFencing(StoreCase):
    def transfer(self, delivery_id: str, fence_token: int, actor: str = "controller:ctl") -> dict[str, Any]:
        return {
            "delivery_id": delivery_id,
            "task_id": TASK,
            "kind": "lease_transfer",
            "actor": actor,
            "fence_token": fence_token,
            "new_producer_id": "w2",
        }

    def test_transfer_bumps_the_fence_and_rebinds_the_producer(self) -> None:
        self.advance_to("RUNNING")
        self.apply(self.transfer("t1", 2))
        self.assertEqual(self.task["fence_token"], 2)
        self.assertEqual(self.task["producer_id"], "w2")

    def test_duplicate_transfer_bumps_the_fence_once(self) -> None:
        self.advance_to("RUNNING")
        self.apply(self.transfer("t1", 2))
        self.assertEqual(
            self.processor.handle(self.transfer("t1", 2))["decision"],
            "DUPLICATE_SUPPRESSED",
        )
        self.assertEqual(self.task["fence_token"], 2)

    def test_displaced_worker_cannot_commit(self) -> None:
        self.advance_to("RUNNING")
        self.apply(self.transfer("t1", 2))
        self.reject(
            cb(delivery_id="t2", actor="worker:w1", from_state="RUNNING", to_state="RESULT_STAGING"),
            "STALE_FENCE",
        )
        self.assertEqual(self.task["state"], "RUNNING")

    def test_successor_commits_under_the_new_fence(self) -> None:
        self.advance_to("RUNNING")
        self.apply(self.transfer("t1", 2))
        self.apply(
            cb(delivery_id="t3", actor="worker:w2", fence_token=2, from_state="RUNNING", to_state="RESULT_STAGING")
        )
        self.assertEqual(self.task["state"], "RESULT_STAGING")

    def test_transfer_must_use_the_next_fence(self) -> None:
        self.advance_to("RUNNING")
        self.reject(self.transfer("t4", 1), "STALE_FENCE")
        self.reject(self.transfer("t5", 4), "FUTURE_FENCE")

    def test_only_the_controller_may_transfer_a_lease(self) -> None:
        self.advance_to("RUNNING")
        self.reject(self.transfer("t6", 2, actor="worker:w1"), "ROLE_NOT_PERMITTED")


class TestProviderObservation(StoreCase):
    def observation(self, delivery_id: str, provider_state: str) -> dict[str, Any]:
        return {
            "delivery_id": delivery_id,
            "task_id": TASK,
            "kind": "provider_observation",
            "actor": "provider:route",
            "fence_token": 1,
            "provider_state": provider_state,
        }

    def test_provider_completion_without_a_commit_is_uncommitted(self) -> None:
        self.advance_to("RUNNING")
        outcome = self.apply(self.observation("p1", "COMPLETED"))
        self.assertEqual(
            outcome["derived_obzio_state"], "PROVIDER_COMPLETED_UNCOMMITTED"
        )
        self.assertTrue(self.task["provider_completed_uncommitted"])
        self.assertEqual(self.task["state"], "RUNNING")
        self.assertEqual(self.task["transition_count"], 2)

    def test_provider_completion_after_a_commit_is_not_uncommitted(self) -> None:
        self.advance_to("RESULT_COMMITTED")
        outcome = self.apply(self.observation("p2", "COMPLETED"))
        self.assertEqual(outcome["derived_obzio_state"], "RESULT_COMMITTED")
        self.assertFalse(self.task["provider_completed_uncommitted"])

    def test_durable_commit_clears_an_earlier_uncommitted_flag(self) -> None:
        self.advance_to("RUNNING")
        self.apply(self.observation("p3", "COMPLETED"))
        self.advance_to("RESULT_COMMITTED")
        self.assertFalse(self.task["provider_completed_uncommitted"])

    def test_a_worker_may_not_report_provider_state(self) -> None:
        self.advance_to("RUNNING")
        observation = dict(self.observation("p4", "COMPLETED"), actor="worker:w1")
        self.reject(observation, "ROLE_NOT_PERMITTED")


class TestOutboxDrain(StoreCase):
    def test_drain_applies_each_effect_once(self) -> None:
        self.advance_to("PARENT_INGESTED")
        dispatched = self.processor.drain()
        self.assertEqual(
            [row["sink_status"] for row in dispatched], ["APPLIED", "APPLIED"]
        )
        self.assertEqual(self.processor.pending_outbox(), [])
        self.assertEqual(self.processor.drain(), [])
        self.assertEqual(self.processor.sink.effect_count, 2)

    def test_drain_order_is_deterministic(self) -> None:
        self.advance_to("PARENT_INGESTED")
        self.assertEqual(
            [row["effect_key"] for row in self.processor.drain()],
            ["ef-commit", "ef-ingest"],
        )

    def test_effect_lost_before_the_sink_write_replays_once(self) -> None:
        class Fault:
            def trip(self, point: str) -> None:
                if point == "before_sink_write":
                    raise InjectedCrash(point)

            def tear(self, point: str) -> int | None:
                return None

        self.advance_to("RESULT_COMMITTED")
        crashing = self.open_store(fault=Fault())
        with self.assertRaises(InjectedCrash):
            crashing.drain()
        reopened = self.open_store()
        self.assertEqual(reopened.sink.effect_count, 0)
        self.assertEqual(
            [row["sink_status"] for row in reopened.drain()], ["APPLIED"]
        )
        self.assertEqual(reopened.sink.effect_count, 1)

    def test_crash_between_sink_and_dispatch_record_replays_as_already_applied(self) -> None:
        class Fault:
            def trip(self, point: str) -> None:
                if point == "after_sink_apply":
                    raise InjectedCrash(point)

            def tear(self, point: str) -> int | None:
                return None

        self.advance_to("RESULT_COMMITTED")
        crashing = self.open_store(fault=Fault())
        with self.assertRaises(InjectedCrash):
            crashing.drain()
        reopened = self.open_store()
        self.assertEqual(reopened.sink.effect_count, 1)
        self.assertEqual(
            [row["sink_status"] for row in reopened.drain()], ["ALREADY_APPLIED"]
        )
        self.assertEqual(reopened.sink.effect_count, 1)
        self.assertEqual(self.open_store().sink.effect_count, 1)

    def test_dispatch_record_prevents_a_second_dispatch(self) -> None:
        self.advance_to("RESULT_COMMITTED")
        self.processor.drain()
        reopened = self.open_store()
        self.assertEqual(reopened.pending_outbox(), [])
        self.assertEqual(reopened.drain(), [])
        self.assertEqual(reopened.sink.effect_count, 1)


class TestRecoveryScanner(StoreCase):
    def test_scan_reports_uncommitted_work(self) -> None:
        self.advance_to("RUNNING")
        report = self.processor.scan_recovery()
        self.assertEqual(report["uncommitted_tasks"], [TASK])
        self.assertEqual(report["pending_effects"], [])
        self.assertIsNone(report["journal_torn_reason"])

    def test_scan_reports_pending_effects(self) -> None:
        self.advance_to("RESULT_COMMITTED")
        self.assertEqual(
            self.processor.scan_recovery()["pending_effects"], ["ef-commit"]
        )

    def test_scan_reports_provider_completed_uncommitted(self) -> None:
        self.advance_to("RUNNING")
        self.processor.handle(
            {
                "delivery_id": "p9",
                "task_id": TASK,
                "kind": "provider_observation",
                "actor": "provider:route",
                "fence_token": 1,
                "provider_state": "COMPLETED",
            }
        )
        self.assertEqual(
            self.processor.scan_recovery()["provider_completed_uncommitted"], [TASK]
        )

    def test_scan_on_an_intact_journal_writes_nothing(self) -> None:
        before = self.processor.seq
        self.processor.scan_recovery()
        self.processor.scan_recovery()
        self.assertEqual(self.processor.seq, before)

    def test_truncation_is_recorded_exactly_once(self) -> None:
        class Fault:
            def trip(self, point: str) -> None:
                return None

            def tear(self, point: str) -> int | None:
                return 9 if point == "journal_torn_write" else None

        crashing = self.open_store(fault=Fault())
        with self.assertRaises(InjectedCrash):
            crashing.handle(happy_path()[0])
        reopened = self.open_store()
        reopened.scan_recovery()
        reopened.scan_recovery()
        recoveries = [
            record for record in reopened.records if record["kind"] == "recovery_truncation"
        ]
        self.assertEqual(len(recoveries), 1)
        self.assertEqual(recoveries[0]["reason"], "SHORT_HEADER")
        self.assertEqual(recoveries[0]["truncated_bytes"], 9)


class TestSnapshotAndCli(StoreCase):
    def test_snapshot_is_canonical_and_free_of_environment_values(self) -> None:
        self.advance_to("PARENT_INGESTED")
        self.processor.drain()
        rendered = canonical_bytes(self.processor.snapshot()).decode("utf-8")
        self.assertNotIn(str(self.store), rendered)
        self.assertNotIn("/tmp", rendered)
        snapshot = self.processor.snapshot()
        self.assertEqual(snapshot["sink_effects"], 2)
        self.assertEqual(snapshot["pending_outbox"], [])
        self.assertEqual(snapshot["dispatched_effects"], ["ef-commit", "ef-ingest"])

    def test_replaying_the_journal_reproduces_the_snapshot(self) -> None:
        self.advance_to("PARENT_INGESTED")
        self.processor.drain()
        self.assertEqual(self.processor.snapshot(), self.open_store().snapshot())

    def test_cli_runs_the_shipped_workload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wa015-cli-") as tmp:
            with silenced():
                code = mechanism.main(
                    [
                        "--workload",
                        str(UNIT_ROOT / "fixtures" / "sanitized-workload.json"),
                        "--store",
                        str(Path(tmp) / "store"),
                    ]
                )
        self.assertEqual(code, 0)

    def test_record_kinds_are_registered(self) -> None:
        self.advance_to("PARENT_INGESTED")
        self.processor.drain()
        self.reject("not a callback", "MALFORMED_CALLBACK")
        for kind in self.processor.snapshot()["record_kinds"]:
            self.assertIn(kind, mechanism.RECORD_KINDS)


if __name__ == "__main__":
    unittest.main()
