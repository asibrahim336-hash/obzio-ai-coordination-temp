import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[3]
CORRECTION = (
    ROOT
    / "workstreams"
    / "po03"
    / "review"
    / "luna"
    / "rejection-assessment-correction.json"
)


class RejectionCorrectionTests(unittest.TestCase):
    def test_unavailable_rows_are_separated_from_quality_findings(self):
        document = json.loads(CORRECTION.read_text(encoding="utf-8"))
        availability = document["availability_reclassification"]
        self.assertEqual(27, availability["availability_artifact"])
        self.assertEqual(3, availability["quality_relevant_units"])
        self.assertEqual(2, availability["quality_defect_classes"])
        self.assertEqual([], document["decision_changed"])

    def test_bytecode_attribution_has_git_history_reproducer(self):
        document = json.loads(CORRECTION.read_text(encoding="utf-8"))
        attribution = document["attribution_correction"]
        self.assertEqual("real", attribution["bytecode_escape"])
        self.assertEqual("coordinator commits 04827c3 and 6f5e386 via broad git add -A", attribution["true_origin"])
        self.assertIn("git log --diff-filter=A", attribution["reproducer"])


if __name__ == "__main__":
    unittest.main()
