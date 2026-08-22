import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("semantic_novelty_gate.py")
SPEC = importlib.util.spec_from_file_location("wa031_novelty", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class SemanticNoveltyGateTests(unittest.TestCase):
    def test_distinct_generated_scenario_passes(self):
        cases = [
            {
                "case_id": "new-route-cardinality",
                "stimulus": "Present zero portable execution routes.",
                "oracle": "Qualification fails with exact route count evidence.",
            }
        ]
        existing = {
            "test_hash.py": "def test_hash_mismatch():\n"
            "    assert verify_same_size_corruption() == 'FAIL'\n"
        }
        self.assertEqual("PASS", MODULE.qualify_cases(cases, existing)["disposition"])

    def test_hidden_paraphrase_of_existing_test_is_rejected(self):
        cases = [
            {
                "case_id": "generated-1",
                "stimulus": "Remove a claimed artifact.",
                "oracle": "The missing file is rejected.",
            }
        ]
        existing = {
            "test_existing.py": (
                "def test_delete_claimed_file_fails():\n"
                "    assert delete_claimed_file() == 'fail: missing file'\n"
            )
        }
        report = MODULE.qualify_cases(cases, existing, threshold=0.5)
        self.assertEqual("FAIL", report["disposition"])
        self.assertEqual(
            "SEMANTIC_DUPLICATE_OF_EXISTING_TEST", report["defects"][0]["code"]
        )

    def test_reworded_generated_pair_is_not_counted_twice(self):
        cases = [
            {
                "case_id": "first",
                "stimulus": "Delete a claimed file.",
                "oracle": "Missing file must fail.",
            },
            {
                "case_id": "second",
                "stimulus": "Remove the claimed artifact.",
                "oracle": "An absent artifact is rejected.",
            },
        ]
        report = MODULE.qualify_cases(cases, {}, threshold=0.6)
        self.assertEqual("SEMANTIC_DUPLICATE_GENERATED_SCENARIO", report["defects"][0]["code"])

    def test_empty_scenario_never_passes(self):
        report = MODULE.qualify_cases([{"case_id": "empty"}], {})
        self.assertEqual("FAIL", report["disposition"])


if __name__ == "__main__":
    unittest.main()
