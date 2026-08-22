import json
import tempfile
import unittest
from pathlib import Path
from mechanism import CapsuleStore, exercise, reproduce_mutable_ambiguity


class CapsuleTests(unittest.TestCase):
    def test_mutable_callback_is_ambiguous(self):
        self.assertTrue(reproduce_mutable_ambiguity()["ambiguous"])

    def test_content_address_recovers_original_and_is_idempotent(self):
        result = exercise()
        self.assertEqual(1, result["callback_recovered_sequence"])
        self.assertTrue(result["same_content_is_idempotent"])
        self.assertTrue(result["different_content_has_different_address"])

    def test_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CapsuleStore(tmp)
            digest = store.put({"fixture": "sanitized"})
            (Path(tmp) / f"{digest}.json").write_text(json.dumps({"fixture": "tampered"}))
            with self.assertRaises(ValueError):
                store.get(digest)


if __name__ == "__main__":
    unittest.main()
