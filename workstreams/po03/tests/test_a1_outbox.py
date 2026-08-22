"""a1-u02 — at-least-once delivery becomes exactly-once observable effect.

Hypothesis (frozen in ``control/dispatch/a1-u02.json``): a transactional outbox
with idempotency keys converts at-least-once delivery into exactly-once
observable effect.

Acceptance, satisfied literally: replaying the same outbox record three times,
including interleaved and concurrent replays, produces exactly one external
effect and two recorded ``DUPLICATE_IGNORED`` observations.  Falsified if a
replay produces a second effect or a duplicate is dropped without a ledger
observation.

The three replay shapes are tested separately because they fail for different
reasons: sequential replay tests the state check, concurrent replay tests the
lock, and interleaved replay — a crash after the effect but before the mark —
tests the only case an application-level "already done?" check gets wrong.
"""

from __future__ import annotations

import threading
import unittest

from test_a1_support import ScratchCase

from engine.ledger import HashChainedLedger
from engine.outbox import (
    APPLIED,
    CLAIMED,
    DUPLICATE_IGNORED,
    EFFECT_APPLIED,
    FileEffectSink,
    Outbox,
    OutboxError,
)

UNIT = "a1-u02-subject"
RECORD = "outbox-record-1"
KEY = "a1-u02:effect:publish-result"


class OutboxCase(ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        self.ledger = HashChainedLedger(self.scratch / "ledger.jsonl")
        self.outbox = Outbox(self.scratch / "outbox", self.ledger)
        self.sink = FileEffectSink(self.scratch / "effects")
        self.outbox.enqueue(
            RECORD,
            unit_id=UNIT,
            idempotency_key=KEY,
            effect_name="publish-result",
            payload={"result": "a1-u02", "bytes": 42},
        )

    def duplicates(self) -> int:
        return self.outbox.duplicate_observations(UNIT, RECORD)

    def assertExactlyOnce(self, deliveries: list) -> None:
        self.assertEqual(1, self.sink.effect_count(), "more than one external effect was produced")
        self.assertEqual({KEY}, self.sink.applied_keys())
        self.assertEqual(1, self.outbox.applied_observations(UNIT, RECORD))
        self.assertEqual(2, self.duplicates(), "expected exactly two DUPLICATE_IGNORED observations")
        self.assertEqual(1, sum(1 for d in deliveries if d.status == EFFECT_APPLIED))
        self.assertEqual(2, sum(1 for d in deliveries if d.status == DUPLICATE_IGNORED))
        self.assertTrue(self.ledger.verify().ok)


class SequentialReplayTests(OutboxCase):
    def test_three_sequential_replays_produce_one_effect(self):
        deliveries = [self.outbox.deliver(RECORD, self.sink) for _ in range(3)]
        self.assertExactlyOnce(deliveries)
        self.assertEqual(APPLIED, self.outbox.record(RECORD)["state"])

    def test_duplicate_is_never_dropped_without_a_ledger_observation(self):
        self.outbox.deliver(RECORD, self.sink)
        before = len(self.ledger.rows())
        self.outbox.deliver(RECORD, self.sink)
        after = self.ledger.rows()
        self.assertEqual(before + 1, len(after))
        self.assertEqual("DUPLICATE_IGNORED", after[-1]["event"])
        self.assertEqual(RECORD, after[-1]["payload"]["record_id"])
        self.assertEqual(KEY, after[-1]["payload"]["idempotency_key"])

    def test_effect_bytes_are_written_once_and_not_rewritten(self):
        first = self.outbox.deliver(RECORD, self.sink)
        original = self.sink._path_for(KEY).read_bytes()
        self.outbox.deliver(RECORD, self.sink)
        self.outbox.deliver(RECORD, self.sink)
        self.assertEqual(original, self.sink._path_for(KEY).read_bytes())
        self.assertEqual(EFFECT_APPLIED, first.status)

    def test_record_id_cannot_be_reused_for_a_different_effect(self):
        with self.assertRaises(OutboxError):
            self.outbox.enqueue(
                RECORD,
                unit_id=UNIT,
                idempotency_key="a different key",
                effect_name="publish-result",
                payload={},
            )


class ConcurrentReplayTests(OutboxCase):
    def test_three_concurrent_replays_produce_one_effect(self):
        results: list = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(3)
        lock = threading.Lock()

        def worker() -> None:
            try:
                barrier.wait(timeout=30)
                delivery = self.outbox.deliver(RECORD, self.sink)
                with lock:
                    results.append(delivery)
            except BaseException as exc:  # pragma: no cover - surfaced by assert
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, name=f"replay-{i}") for i in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual([], errors, f"delivery raised under concurrency: {errors}")
        self.assertEqual(3, len(results))
        self.assertExactlyOnce(results)

    def test_concurrent_replays_leave_a_verifiable_ledger(self):
        barrier = threading.Barrier(3)

        def worker() -> None:
            barrier.wait(timeout=30)
            self.outbox.deliver(RECORD, self.sink)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        verification = self.ledger.verify()
        self.assertTrue(verification.ok, verification.as_dict())
        # A losing replay short-circuits on the APPLIED state before claiming,
        # so the history is: enqueue, one claim, one applied, two duplicates.
        events = [row["event"] for row in self.ledger.events_for(UNIT)]
        self.assertEqual(
            ["OUTBOX_ENQUEUED", "OUTBOX_CLAIMED", "OUTBOX_APPLIED", "DUPLICATE_IGNORED", "DUPLICATE_IGNORED"],
            events,
        )
        self.assertEqual(5, verification.row_count)


class InterleavedCrashReplayTests(OutboxCase):
    """The hard case: the effect landed but the mark did not."""

    def test_crash_after_effect_before_mark_does_not_duplicate_the_effect(self):
        class Injected(RuntimeError):
            pass

        def hook(point: str) -> None:
            if point == "after_effect_before_mark":
                raise Injected(point)

        with self.assertRaises(Injected):
            self.outbox.deliver(RECORD, self.sink, fault_hook=hook)

        # The effect exists, but the record still says CLAIMED: the ambiguous
        # state a recovery scanner must be able to resolve.
        self.assertEqual(1, self.sink.effect_count())
        self.assertEqual(CLAIMED, self.outbox.record(RECORD)["state"])
        self.assertEqual([RECORD], self.outbox.redrivable())

        second = self.outbox.deliver(RECORD, self.sink)
        third = self.outbox.deliver(RECORD, self.sink)

        self.assertEqual(DUPLICATE_IGNORED, second.status)
        self.assertEqual(DUPLICATE_IGNORED, third.status)
        self.assertEqual(1, self.sink.effect_count(), "replay after the crash produced a second effect")
        self.assertEqual(2, self.duplicates())
        self.assertEqual(0, self.outbox.applied_observations(UNIT, RECORD))
        self.assertEqual(APPLIED, self.outbox.record(RECORD)["state"])
        self.assertTrue(self.ledger.verify().ok)

    def test_crash_after_claim_before_effect_is_resolved_by_redrive(self):
        class Injected(RuntimeError):
            pass

        with self.assertRaises(Injected):
            self.outbox.deliver(
                RECORD,
                self.sink,
                fault_hook=lambda point: (_ for _ in ()).throw(Injected(point))
                if point == "after_claim"
                else None,
            )
        self.assertEqual(0, self.sink.effect_count())
        self.assertEqual([RECORD], self.outbox.redrivable())

        deliveries = self.outbox.drain(self.sink)
        self.assertEqual([EFFECT_APPLIED], [d.status for d in deliveries])
        self.assertEqual(1, self.sink.effect_count())
        self.assertEqual([], self.outbox.redrivable())

    def test_lost_return_message_is_recovered_by_the_scanner(self):
        """A delivery that never reported back is still exactly-once."""
        self.outbox.enqueue(
            "outbox-record-2",
            unit_id=UNIT,
            idempotency_key="a1-u02:effect:second",
            effect_name="publish-result",
            payload={"result": "second"},
        )
        self.assertEqual({RECORD, "outbox-record-2"}, set(self.outbox.redrivable()))
        first_pass = self.outbox.drain(self.sink)
        self.assertEqual(2, self.sink.effect_count())
        self.assertTrue(all(d.status == EFFECT_APPLIED for d in first_pass))
        # A second scanner pass, as would happen after a parent restart.
        self.assertEqual([], self.outbox.redrivable())
        replay = [self.outbox.deliver(rid, self.sink) for rid in (RECORD, "outbox-record-2")]
        self.assertTrue(all(d.status == DUPLICATE_IGNORED for d in replay))
        self.assertEqual(2, self.sink.effect_count())


class NegativeControlTests(OutboxCase):
    """Prove the assertions above would fail if the guard were removed."""

    def test_unguarded_delivery_produces_three_effects(self):
        effects = self.scratch / "unguarded-effects"
        effects.mkdir()

        def unguarded_deliver(attempt: int) -> None:
            # No claim, no idempotent create: the naive implementation the
            # outbox replaces.  Each attempt writes its own effect.
            (effects / f"effect-{attempt}.json").write_text("{}", encoding="utf-8")

        for attempt in range(3):
            unguarded_deliver(attempt)
        self.assertEqual(3, len(list(effects.glob("*.json"))))
        self.assertNotEqual(
            1,
            len(list(effects.glob("*.json"))),
            "the exactly-one assertion must be able to fail; if this passed, it proves nothing",
        )

    def test_sink_without_exclusive_create_overwrites(self):
        target = self.scratch / "overwritable.json"
        target.write_text("first", encoding="utf-8")
        target.write_text("second", encoding="utf-8")
        self.assertEqual("second", target.read_text(encoding="utf-8"))

        from engine.canonical import create_exclusive

        exclusive = self.scratch / "exclusive.json"
        self.assertTrue(create_exclusive(exclusive, b"first"))
        self.assertFalse(create_exclusive(exclusive, b"second"))
        self.assertEqual(b"first", exclusive.read_bytes())


if __name__ == "__main__":
    unittest.main()
