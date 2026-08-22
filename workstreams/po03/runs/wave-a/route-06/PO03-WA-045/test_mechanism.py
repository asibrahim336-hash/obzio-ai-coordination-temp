import unittest
from mechanism import MAX_LENGTH, baseline_step, first_breach, guarded_step


class TransitionPropertyTests(unittest.TestCase):
    def test_generator_finds_baseline_false_completion(self):
        breach, _ = first_breach(baseline_step, MAX_LENGTH)
        self.assertEqual(["provider_complete"], breach)

    def test_guarded_machine_passes_frozen_bound(self):
        breach, checked = first_breach(guarded_step, MAX_LENGTH)
        self.assertIsNone(breach)
        self.assertEqual(3906, checked)

    def test_bound_is_frozen(self):
        self.assertEqual(5, MAX_LENGTH)


if __name__ == "__main__":
    unittest.main()
