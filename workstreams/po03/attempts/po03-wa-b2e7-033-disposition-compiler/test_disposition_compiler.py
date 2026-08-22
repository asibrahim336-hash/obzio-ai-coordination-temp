#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from disposition_compiler import DispositionError, compile_dispositions


class DispositionCompilerTests(unittest.TestCase):
    def test_compiles_all_decisions_and_preserves_lineage(self):
        routes = [
            {"route_id": "new", "decision": "SUPERSEDE", "predecessor_route_id": "old"},
            {"route_id": "old", "decision": "RETAIN"},
        ]
        result = compile_dispositions(routes)
        self.assertEqual([item["route_id"] for item in result], ["new", "old"])

    def test_rejects_orphaned_predecessor(self):
        with self.assertRaisesRegex(DispositionError, "does not resolve"):
            compile_dispositions(
                [{"route_id": "new", "decision": "SUPERSEDE", "predecessor_route_id": "gone"}]
            )

    def test_rejects_missing_predecessor_for_supersession(self):
        with self.assertRaisesRegex(DispositionError, "requires"):
            compile_dispositions([{"route_id": "new", "decision": "SUPERSEDE"}])

    def test_rejects_unknown_decision(self):
        with self.assertRaisesRegex(DispositionError, "decision must be one"):
            compile_dispositions([{"route_id": "r", "decision": "ARCHIVE"}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
