import unittest
from mechanism import CASES, MUTANTS, VALID, mutation_run


class MutationStrengthTests(unittest.TestCase):
    def test_weak_happy_path_suite_lets_every_mutant_survive(self):
        result = mutation_run([VALID])
        self.assertEqual(0.0, result["score"])
        self.assertEqual(sorted(MUTANTS), result["survived"])

    def test_strengthened_suite_kills_every_false_completion_mutant(self):
        result = mutation_run(CASES)
        self.assertEqual(1.0, result["score"])
        self.assertEqual([], result["survived"])
        self.assertEqual(sorted(MUTANTS), result["killed"])

    def test_each_adversarial_case_is_required(self):
        for index in range(1, len(CASES)):
            reduced = [case for i, case in enumerate(CASES) if i != index]
            self.assertLess(mutation_run(reduced)["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
