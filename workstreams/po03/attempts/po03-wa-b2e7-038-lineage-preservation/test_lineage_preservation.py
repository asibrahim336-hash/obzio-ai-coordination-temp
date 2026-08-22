#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lineage_preservation import validate_lineage


class LineagePreservationTests(unittest.TestCase):
    def test_resolvable_supersession_is_valid(self):
        records = [
            {"route_id": "old", "decision": "RETAIN"},
            {"route_id": "new", "decision": "SUPERSEDE", "predecessor_route_id": "old"},
        ]
        self.assertEqual(validate_lineage(records), [])

    def test_missing_predecessor_is_detected(self):
        records = [{"route_id": "new", "decision": "SUPERSEDE", "predecessor_route_id": "missing"}]
        self.assertTrue(any("unresolved predecessor" in error for error in validate_lineage(records)))

    def test_predecessor_cycle_is_detected(self):
        records = [
            {"route_id": "a", "decision": "SUPERSEDE", "predecessor_route_id": "b"},
            {"route_id": "b", "decision": "SUPERSEDE", "predecessor_route_id": "a"},
        ]
        self.assertTrue(any("cycle" in error for error in validate_lineage(records)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
