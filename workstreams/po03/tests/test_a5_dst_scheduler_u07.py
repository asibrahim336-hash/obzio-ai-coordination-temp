"""Unit tests for the a5-u07 deterministic-simulation-testing scheduler."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from lib.dst_scheduler_u07 import (  # noqa: E402
    exhaustive_interleavings,
    multinomial_space_size,
    run_schedule,
    seeded_random_interleavings,
    sequential_orderings,
)


class TestSpaceSize(unittest.TestCase):
    def test_two_actors_two_steps_each_is_six(self) -> None:
        self.assertEqual(multinomial_space_size([2, 2]), 6)

    def test_three_actors_two_steps_each_is_ninety(self) -> None:
        self.assertEqual(multinomial_space_size([2, 2, 2]), 90)

    def test_single_actor_has_exactly_one_interleaving(self) -> None:
        self.assertEqual(multinomial_space_size([3]), 1)

    def test_matches_exhaustive_enumeration_count(self) -> None:
        for counts in ([2, 2], [2, 2, 2], [1, 2, 3], [2, 3]):
            with self.subTest(counts=counts):
                self.assertEqual(len(exhaustive_interleavings(counts)), multinomial_space_size(counts))


class TestExhaustiveInterleavings(unittest.TestCase):
    def test_every_schedule_preserves_each_actors_internal_order(self) -> None:
        for schedule in exhaustive_interleavings([2, 2, 2]):
            for actor in range(3):
                positions = [i for i, a in enumerate(schedule) if a == actor]
                self.assertEqual(positions, sorted(positions))

    def test_every_schedule_uses_each_actor_exactly_its_step_count(self) -> None:
        counts = [2, 3]
        for schedule in exhaustive_interleavings(counts):
            self.assertEqual(schedule.count(0), counts[0])
            self.assertEqual(schedule.count(1), counts[1])

    def test_no_duplicate_schedules(self) -> None:
        schedules = exhaustive_interleavings([2, 2])
        self.assertEqual(len(schedules), len(set(schedules)))

    def test_includes_the_fully_serial_and_the_fully_alternating_schedule(self) -> None:
        schedules = set(exhaustive_interleavings([2, 2]))
        self.assertIn((0, 0, 1, 1), schedules)
        self.assertIn((1, 1, 0, 0), schedules)
        self.assertIn((0, 1, 0, 1), schedules)
        self.assertIn((0, 1, 1, 0), schedules)


class TestSequentialOrderings(unittest.TestCase):
    def test_two_actors_have_exactly_two_serial_orderings(self) -> None:
        orderings = sequential_orderings([2, 2])
        self.assertEqual(len(orderings), 2)
        self.assertIn((0, 0, 1, 1), orderings)
        self.assertIn((1, 1, 0, 0), orderings)

    def test_four_actors_have_exactly_twenty_four_serial_orderings(self) -> None:
        self.assertEqual(len(sequential_orderings([2, 2, 2, 2])), 24)

    def test_serial_orderings_are_a_strict_subset_of_the_full_space(self) -> None:
        full = set(exhaustive_interleavings([2, 2, 2]))
        serial = set(sequential_orderings([2, 2, 2]))
        self.assertTrue(serial.issubset(full))
        self.assertLess(len(serial), len(full))

    def test_serial_orderings_never_interleave_two_actors_partial_steps(self) -> None:
        for schedule in sequential_orderings([2, 3, 2]):
            # A schedule is "fully serial" iff it is a concatenation of
            # contiguous same-actor runs, i.e. it changes actor at most
            # (num_actors - 1) times.
            changes = sum(1 for i in range(1, len(schedule)) if schedule[i] != schedule[i - 1])
            self.assertLessEqual(changes, 2)  # 3 actors -> at most 2 switches


class TestSeededRandomInterleavings(unittest.TestCase):
    def test_same_seed_and_count_reproduce_identically(self) -> None:
        a = seeded_random_interleavings([2, 2, 2, 2, 2], seed=42, count=50)
        b = seeded_random_interleavings([2, 2, 2, 2, 2], seed=42, count=50)
        self.assertEqual(a, b)

    def test_different_seeds_usually_diverge(self) -> None:
        a = seeded_random_interleavings([2, 2, 2, 2, 2], seed=1, count=50)
        b = seeded_random_interleavings([2, 2, 2, 2, 2], seed=2, count=50)
        self.assertNotEqual(a, b)

    def test_every_sample_is_a_valid_order_preserving_interleaving(self) -> None:
        counts = [2, 3, 1]
        samples = seeded_random_interleavings(counts, seed=7, count=40)
        valid = set(exhaustive_interleavings(counts))
        for schedule in samples:
            self.assertIn(schedule, valid)

    def test_sampling_explores_more_than_one_distinct_schedule(self) -> None:
        samples = seeded_random_interleavings([2, 2, 2, 2], seed=99, count=100)
        self.assertGreater(len(set(samples)), 1)


class TestRunSchedule(unittest.TestCase):
    def test_drives_generators_in_schedule_order_and_tags_by_actor(self) -> None:
        log: list[str] = []

        def make_actor(label: str):
            def factory():
                log.append(f"{label}-start")
                yield f"{label}-step1"
                log.append(f"{label}-mid")
                yield f"{label}-step2"

            return factory

        actors = [make_actor("A"), make_actor("B")]
        trace = run_schedule(actors, (0, 1, 0, 1))
        self.assertEqual(
            trace,
            [(0, "A-step1"), (1, "B-step1"), (0, "A-step2"), (1, "B-step2")],
        )

    def test_fresh_generators_are_created_per_run(self) -> None:
        def factory():
            yield "only-step"

        run_schedule([factory], (0,))
        # A second run must not raise StopIteration from a stale generator.
        trace = run_schedule([factory], (0,))
        self.assertEqual(trace, [(0, "only-step")])


if __name__ == "__main__":
    unittest.main()
