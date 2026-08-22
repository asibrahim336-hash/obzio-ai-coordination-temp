import unittest

from overhead_meter import NOT_SUPPORTED, measure, summarize


class OverheadMeterTests(unittest.TestCase):
    def test_observed_delta_is_measured(self):
        result = {
            "task_id": "T",
            "result_transaction": {
                "committed_at": "2026-08-22T00:00:00Z",
                "parent_ingested_at": "2026-08-22T00:00:03.5Z",
            },
        }
        report = measure([result])
        self.assertEqual(report["units"][0]["coordination_overhead_seconds"], 3.5)

    def test_unavailable_is_not_zero(self):
        summary = summarize([NOT_SUPPORTED, None])
        self.assertEqual(summary["value"], NOT_SUPPORTED)
        self.assertEqual(summary["known_count"], 0)
        self.assertEqual(summary["unknown_count"], 2)

    def test_mixed_support_keeps_coverage(self):
        summary = summarize([0, NOT_SUPPORTED, 4])
        self.assertEqual(summary["value"], 2)
        self.assertEqual(summary["coverage"], 2 / 3)


if __name__ == "__main__":
    unittest.main()
