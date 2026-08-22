import unittest

from generation_comparator import NOT_SUPPORTED, compare


class GenerationComparatorTests(unittest.TestCase):
    def test_critical_regression_refuses_lift(self):
        report = compare({"correct": 1.0}, {"correct": 0.99, "speed": 1.0}, {"correct"})
        self.assertEqual(report["lift"], "REFUSED")

    def test_unknown_critical_refuses_lift(self):
        report = compare({"correct": 1.0}, {"correct": NOT_SUPPORTED}, {"correct"})
        self.assertEqual(report["lift"], "REFUSED")

    def test_optional_score_cannot_override(self):
        report = compare(
            {"correct": 1.0, "optional": 0.0},
            {"correct": 0.5, "optional": 1.0},
            {"correct"},
        )
        self.assertEqual(report["lift"], "REFUSED")
        self.assertFalse(report["optional_improvement_can_override_critical"])

    def test_no_regression_is_eligible(self):
        report = compare({"a": 1.0}, {"a": 1.0}, {"a"})
        self.assertEqual(report["lift"], "ELIGIBLE")


if __name__ == "__main__":
    unittest.main()
