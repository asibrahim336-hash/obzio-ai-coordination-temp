import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[3]
DISPOSITIONS = ROOT / "workstreams" / "po03" / "review" / "luna" / "a12-dispositions.json"


class A12ReviewBoundaryTests(unittest.TestCase):
    def test_all_a12_units_are_explicitly_not_yet(self):
        document = json.loads(DISPOSITIONS.read_text(encoding="utf-8"))
        self.assertEqual("5a642fc", document["criteria_commit"])
        rows = document["dispositions"]
        self.assertEqual(["a12-u01", "a12-u02", "a12-u03", "a12-u04"], [row["unit_id"] for row in rows])
        self.assertTrue(all(row["disposition"] == "NOT_YET" for row in rows))
        self.assertTrue(all(row["rationale"] for row in rows))
        self.assertEqual("NOT_YET", document["mutation_review"]["status"])


if __name__ == "__main__":
    unittest.main()
