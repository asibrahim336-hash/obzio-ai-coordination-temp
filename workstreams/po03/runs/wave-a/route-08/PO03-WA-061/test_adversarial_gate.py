import unittest

from adversarial_gate import gate


class AdversarialGateTests(unittest.TestCase):
    def test_public_pass_cannot_mask_hidden_failure(self):
        verdict = gate(True, [{"case_id": "novel", "status": "FAIL"}])
        self.assertEqual(verdict["verdict"], "RECOMMEND_REJECT")

    def test_missing_held_case_requires_retest(self):
        self.assertEqual(gate(True, [])["verdict"], "RETEST")

    def test_both_suites_must_pass(self):
        verdict = gate(True, [{"case_id": "novel", "status": "PASS"}])
        self.assertEqual(verdict["verdict"], "RECOMMEND_ACCEPT")


if __name__ == "__main__":
    unittest.main()
