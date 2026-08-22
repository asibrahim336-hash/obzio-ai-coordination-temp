#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from legacy_alias_census import census


class LegacyAliasCensusTests(unittest.TestCase):
    def test_records_alias_file_line_and_enclosing_field_without_replacement(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            fixture = Path(directory) / "evidence.json"
            original = '{"recorded_by": "Operator D"}\n'
            fixture.write_text(original, encoding="utf-8")
            report = census([fixture])
            self.assertEqual(fixture.read_text(encoding="utf-8"), original)
        self.assertEqual(report["occurrence_count"], 1)
        occurrence = report["occurrences"][0]
        self.assertEqual(occurrence["alias"], "Operator D")
        self.assertEqual(occurrence["line"], 1)
        self.assertEqual(occurrence["enclosing_field"], "recorded_by")
        self.assertFalse(report["replacement_performed"])

    def test_records_close_variant_under_heading(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            fixture = Path(directory) / "notes.md"
            fixture.write_text("## Runtime history\nClaude Chrome extension was used.\n", encoding="utf-8")
            report = census([fixture])
        self.assertEqual(report["occurrence_count"], 1)
        self.assertEqual(report["occurrences"][0]["enclosing_field"], "Runtime history")


if __name__ == "__main__":
    unittest.main(verbosity=2)
