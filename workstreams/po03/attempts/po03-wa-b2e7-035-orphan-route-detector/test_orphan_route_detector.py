#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from orphan_route_detector import detect


class OrphanRouteDetectorTests(unittest.TestCase):
    def test_reaches_instruction_through_current_pointer(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            (root / "state").mkdir()
            (root / "instructions" / "functions").mkdir(parents=True)
            (root / "state" / "current.json").write_text(
                '{"function_instruction": "instructions/functions/current.md"}\n',
                encoding="utf-8",
            )
            (root / "instructions/functions/current.md").write_text(
                "current instruction\n", encoding="utf-8"
            )
            (root / "instructions/functions/old.md").write_text(
                "retained evidence\n", encoding="utf-8"
            )
            report = detect(root, ["state/current.json"])
        self.assertEqual(
            report["reachable"], ["instructions/functions/current.md", "state/current.json"]
        )
        self.assertEqual(report["orphans"], ["instructions/functions/old.md"])

    def test_reports_missing_reference(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            (root / "state").mkdir()
            (root / "state/current.json").write_text(
                '{"next": "state/missing.json"}\n', encoding="utf-8"
            )
            report = detect(root, ["state/current.json"])
        self.assertEqual(report["missing_references"], [{"from": "state/current.json", "path": "state/missing.json"}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
