"""Unit tests for the a5-u10 mutable-status-file model."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from lib.dst_scheduler_u07 import exhaustive_interleavings, run_schedule  # noqa: E402
from lib.mutable_status_store_u10 import (  # noqa: E402
    MutableStatusStore,
    apply_event_sequentially,
    attempt_tamper_detection,
    mutable_update_actor,
    replay_history_sequentially,
)


class TestMutableStatusStore(unittest.TestCase):
    def test_write_then_read_round_trips(self) -> None:
        store = MutableStatusStore()
        store.write("u1", {"a": 1})
        self.assertEqual(store.read("u1"), {"a": 1})

    def test_read_of_unknown_unit_is_empty(self) -> None:
        store = MutableStatusStore()
        self.assertEqual(store.read("nope"), {})

    def test_write_replaces_the_whole_file(self) -> None:
        store = MutableStatusStore()
        store.write("u1", {"a": 1, "b": 2})
        store.write("u1", {"c": 3})
        self.assertEqual(store.read("u1"), {"c": 3})  # a, b are gone: no merge at the store level


class TestSequentialReplay(unittest.TestCase):
    def test_only_latest_event_per_unit_survives(self) -> None:
        rows = [
            {"unit_id": "u1", "event": "CREATED", "seq": 1, "obzio_state": "CREATED", "fence_token": None},
            {"unit_id": "u1", "event": "LEASED", "seq": 2, "obzio_state": "LEASED", "fence_token": 1},
        ]
        store = replay_history_sequentially(rows)
        status = store.read("u1")
        self.assertEqual(status["last_event"], "LEASED")
        self.assertEqual(status["last_seq_seen"], 2)
        # No trace that a CREATED event ever happened survives in the file.
        self.assertNotIn("CREATED", str(status.values()))

    def test_number_of_stored_files_equals_distinct_units_not_total_events(self) -> None:
        rows = [
            {"unit_id": "u1", "event": "CREATED", "seq": 1, "obzio_state": "CREATED", "fence_token": None},
            {"unit_id": "u1", "event": "LEASED", "seq": 2, "obzio_state": "LEASED", "fence_token": 1},
            {"unit_id": "u2", "event": "CREATED", "seq": 3, "obzio_state": "CREATED", "fence_token": None},
        ]
        store = replay_history_sequentially(rows)
        self.assertEqual(len(store.files), 2)  # u1, u2 -- 3 raw events collapsed into 2 snapshots

    def test_sequential_single_writer_replay_never_needs_interleaving(self) -> None:
        rows = [{"unit_id": "solo", "event": "CREATED", "seq": 1, "obzio_state": "CREATED", "fence_token": None}]
        apply_event_sequentially(store := MutableStatusStore(), rows[0])
        self.assertEqual(store.read("solo")["last_event"], "CREATED")


class TestTamperDetection(unittest.TestCase):
    def test_tampering_is_never_detected_by_construction(self) -> None:
        store = MutableStatusStore()
        store.write("u1", {"obzio_state": "RESULT_COMMITTED"})
        detected = attempt_tamper_detection(store, "u1", {"obzio_state": "COMPLETED", "forged": True})
        self.assertFalse(detected)
        self.assertEqual(store.read("u1")["obzio_state"], "COMPLETED")  # the forgery is now just "the file"


class TestConcurrentUpdateLosesData(unittest.TestCase):
    def _run_two_actor_interleaving(self, schedule: tuple[int, ...]) -> tuple[dict, dict]:
        store = MutableStatusStore()
        out_a: dict = {}
        out_b: dict = {}
        actors = [
            lambda: mutable_update_actor(store, "shared-unit", {"a_field": "A-data"}, out_a),
            lambda: mutable_update_actor(store, "shared-unit", {"b_field": "B-data"}, out_b),
        ]
        run_schedule(actors, schedule)
        return store.read("shared-unit"), {"a": out_a, "b": out_b}

    def test_interleaved_reads_before_either_write_loses_one_actors_field(self) -> None:
        final, _ = self._run_two_actor_interleaving((0, 1, 0, 1))
        has_both = "a_field" in final and "b_field" in final
        self.assertFalse(has_both, f"expected a lost update, got both fields present: {final}")

    def test_fully_serial_scheduling_preserves_both_fields(self) -> None:
        final, _ = self._run_two_actor_interleaving((0, 0, 1, 1))
        self.assertIn("a_field", final)
        self.assertIn("b_field", final)

    def test_across_the_full_six_interleaving_space_at_least_one_loses_data(self) -> None:
        lost_count = 0
        for schedule in exhaustive_interleavings([2, 2]):
            final, _ = self._run_two_actor_interleaving(schedule)
            if not ("a_field" in final and "b_field" in final):
                lost_count += 1
        self.assertGreater(lost_count, 0)
        self.assertLessEqual(lost_count, 6)


if __name__ == "__main__":
    unittest.main()
