import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[3]
DISPOSITIONS = ROOT / "workstreams" / "po03" / "review" / "luna" / "dispositions.json"


class DispositionTests(unittest.TestCase):
    def test_every_reviewed_unit_has_non_ceremonial_disposition(self):
        document = json.loads(DISPOSITIONS.read_text(encoding="utf-8"))
        rows = document["dispositions"]
        self.assertEqual(30, len(rows))
        self.assertEqual(30, len({row["unit_id"] for row in rows}))
        self.assertTrue(all(row["disposition"] in {"ACCEPTED", "REJECTED"} for row in rows))
        self.assertTrue(all(row["basis"] for row in rows))
        self.assertEqual(0, document["summary"]["accepted"])
        self.assertEqual(30, document["summary"]["rejected"])

    def test_rejection_is_tied_to_frozen_criteria_or_exact_boundary(self):
        document = json.loads(DISPOSITIONS.read_text(encoding="utf-8"))
        for row in document["dispositions"]:
            self.assertTrue(
                any(
                    marker in row["basis"]
                    for marker in ("C1", "C2", "C3", "C4", "C5", "C6", "NOT_YET")
                ),
                row["unit_id"],
            )

    def test_observed_a7_locator_defect_is_recorded(self):
        document = json.loads(DISPOSITIONS.read_text(encoding="utf-8"))
        row = next(item for item in document["dispositions"] if item["unit_id"] == "a7-u01")
        self.assertEqual("REJECTED", row["disposition"])
        self.assertIn("result_commit_id", row["basis"])


if __name__ == "__main__":
    unittest.main()
