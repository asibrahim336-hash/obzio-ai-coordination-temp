"""Unit tests for the a5-u04 needle-recall proxy comparison."""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from lib.context_admission_u04 import (  # noqa: E402
    build_corpus,
    hashed_capsule,
    measure_recall,
    whole_tree_dump,
)


class TestContextAdmission(unittest.TestCase):
    def test_both_arms_execute_and_return_admitted_sets(self) -> None:
        rng = random.Random(1)
        files, tasks = build_corpus(rng, num_files=3, chunks_per_file=5, chunk_size=50)
        dump = whole_tree_dump(files, budget_chars=10_000)
        capsule = hashed_capsule(files, budget_chars=10_000, query_keywords=tasks[0].query_keywords)
        self.assertIsInstance(dump, set)
        self.assertIsInstance(capsule, set)
        self.assertGreater(len(dump), 0)
        self.assertGreater(len(capsule), 0)

    def test_small_corpus_within_budget_both_recall_fully(self) -> None:
        rng = random.Random(2)
        files, tasks = build_corpus(rng, num_files=2, chunks_per_file=3, chunk_size=50)
        result = measure_recall(files, tasks, budget_chars=100_000)
        self.assertEqual(result["whole_tree_dump_recall"], 1.0)
        self.assertEqual(result["hashed_capsule_recall"], 1.0)

    def test_large_corpus_past_budget_capsule_recall_dominates_dump_recall(self) -> None:
        rng = random.Random(3)
        files, tasks = build_corpus(rng, num_files=60, chunks_per_file=8, chunk_size=200)
        # Budget large enough for roughly 10% of the corpus.
        total_chars = sum(len(c) for f in files for c in f)
        budget = int(total_chars * 0.1)
        result = measure_recall(files, tasks, budget_chars=budget)
        self.assertLess(result["whole_tree_dump_recall"], 0.3)
        self.assertGreater(result["hashed_capsule_recall"], 0.9)
        self.assertGreater(result["hashed_capsule_recall"], result["whole_tree_dump_recall"])

    def test_capsule_selection_is_deterministic(self) -> None:
        rng = random.Random(4)
        files, tasks = build_corpus(rng, num_files=10, chunks_per_file=6, chunk_size=100)
        a = hashed_capsule(files, budget_chars=500, query_keywords=tasks[0].query_keywords)
        b = hashed_capsule(files, budget_chars=500, query_keywords=tasks[0].query_keywords)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
