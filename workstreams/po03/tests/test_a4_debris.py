import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workstreams.po03.packverify.debris import classify_path


class DebrisFixtureTests(unittest.TestCase):
    def test_planted_transport_and_temporary_paths_are_classified(self):
        transport = classify_path("_transport/part00.bin")
        temporary = classify_path(".tmp-upload/probe.bin")
        self.assertEqual(transport["class"], "transport_debris_candidate")
        self.assertEqual(temporary["class"], "transport_debris_candidate")
        self.assertIn("DO_NOT_DELETE", transport["proposed_disposition"])

    def test_live_source_path_is_not_classified(self):
        self.assertIsNone(classify_path("packs/demo/engine.py"))


if __name__ == "__main__":
    unittest.main()
