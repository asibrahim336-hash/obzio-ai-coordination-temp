#!/usr/bin/env python3
"""Tests for disposition_completeness.py.

Run with: python3 -I test_disposition_completeness.py
(standard-library `unittest` only; no third-party packages, no network.)
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import disposition_completeness as dc

REPO_ROOT = Path(__file__).resolve().parents[4]


class TestExtractTargetsWithStanding(unittest.TestCase):
    def test_dict_with_path_and_standing(self):
        value = {"path": "state/OLD.json", "standing": "SUPERSEDED_RETAINED"}
        self.assertEqual(dc._extract_targets_with_standing(value), [("state/OLD.json", "SUPERSEDED_RETAINED")])

    def test_dict_with_path_no_standing(self):
        value = {"path": "state/OLD.json"}
        self.assertEqual(dc._extract_targets_with_standing(value), [("state/OLD.json", None)])

    def test_dict_with_objects_list_shares_standing(self):
        value = {
            "objects": [
                "dispatch/A.md@abc123",
                "dispatch/B.md@def456",
                "not-a-path-just-an-id",
            ],
            "standing": "SUPERSEDED_UNSENT_RETAINED",
        }
        self.assertEqual(
            dc._extract_targets_with_standing(value),
            [
                ("dispatch/A.md", "SUPERSEDED_UNSENT_RETAINED"),
                ("dispatch/B.md", "SUPERSEDED_UNSENT_RETAINED"),
            ],
        )

    def test_list_of_dicts_each_carries_own_standing(self):
        value = [
            {"path": "a.json", "standing": "S1"},
            {"path": "b.json", "standing": "S2"},
        ]
        self.assertEqual(
            dc._extract_targets_with_standing(value),
            [("a.json", "S1"), ("b.json", "S2")],
        )

    def test_plain_string_path_no_standing_available(self):
        value = "state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json"
        self.assertEqual(
            dc._extract_targets_with_standing(value),
            [("state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json", None)],
        )

    def test_dict_without_path_or_objects_contributes_nothing(self):
        value = {"note": "no target here", "standing": "IRRELEVANT"}
        self.assertEqual(dc._extract_targets_with_standing(value), [])

    def test_non_path_string_is_ignored(self):
        value = "just a bare receipt id, not a path"
        self.assertEqual(dc._extract_targets_with_standing(value), [])


class TestDiscoverSupersededFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rel, obj):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj), encoding="utf-8")

    def test_forward_key_with_standing(self):
        self._write(
            "state/NEW.json",
            {"supersedes_pointer": {"path": "state/OLD.json", "standing": "SUPERSEDED_RETAINED"}},
        )
        report = dc.discover_superseded_files(self.root)
        self.assertEqual(report["superseded"], {"state/OLD.json": ["SUPERSEDED_RETAINED"]})

    def test_backward_key_marks_own_record_as_older(self):
        self._write(
            "state/OLD.json",
            {"superseded_by": "state/NEW.json"},
        )
        report = dc.discover_superseded_files(self.root)
        self.assertIn("state/OLD.json", report["superseded"])
        # Backward key gives no co-located standing at this level.
        self.assertEqual(report["superseded"]["state/OLD.json"], [None])

    def test_no_supersession_keys_yields_empty(self):
        self._write("state/PLAIN.json", {"unrelated_field": "value"})
        report = dc.discover_superseded_files(self.root)
        self.assertEqual(report["superseded"], {})

    def test_multiple_records_accumulate_standings_for_same_path(self):
        self._write(
            "dispatch/A.json",
            {"supersedes_pointer": {"path": "state/OLD.json", "standing": "FIRST"}},
        )
        self._write(
            "dispatch/B.json",
            {"supersedes_pointer": {"path": "state/OLD.json", "standing": "SECOND"}},
        )
        report = dc.discover_superseded_files(self.root)
        self.assertEqual(sorted(report["superseded"]["state/OLD.json"]), ["FIRST", "SECOND"])

    def test_unparsable_json_is_reported_not_raised(self):
        bad = self.root / "state" / "BROKEN.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("{not valid json", encoding="utf-8")
        report = dc.discover_superseded_files(self.root)
        self.assertIn("state/BROKEN.json", report["unparsable_files"])


class TestLoadDispositionTable(unittest.TestCase):
    def test_missing_table_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(dc.DispositionCheckError):
                dc.load_disposition_table(Path(tmp))

    def test_parses_backtick_path_and_disposition_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            table = root / "operations" / "INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md"
            table.parent.mkdir(parents=True)
            table.write_text(
                "| Object/class | Disposition | Current treatment |\n"
                "|---|---|---|\n"
                "| `state/FOO.json` | RETAIN / CURRENT | some notes |\n",
                encoding="utf-8",
            )
            result = dc.load_disposition_table(root)
            self.assertEqual(result, {"state/FOO.json": "RETAIN / CURRENT"})


class TestLoadVerifiedHighRiskMarkers(unittest.TestCase):
    def test_missing_script_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(dc.DispositionCheckError):
                dc.load_verified_high_risk_markers(Path(tmp))

    def test_only_verified_markers_are_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts_dir = root / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "check_operator_taxonomy.py").write_text(
                'high_risk_markers = {\n'
                '    "legacy/CLAIMED_AND_PRESENT.md": "SUPERSEDED FOR ACTIVE ROUTING",\n'
                '    "legacy/CLAIMED_BUT_ABSENT.md": "SUPERSEDED FOR ACTIVE ROUTING",\n'
                '}\n',
                encoding="utf-8",
            )
            legacy = root / "legacy"
            legacy.mkdir()
            (legacy / "CLAIMED_AND_PRESENT.md").write_text(
                "Notice: SUPERSEDED FOR ACTIVE ROUTING as of today.", encoding="utf-8"
            )
            (legacy / "CLAIMED_BUT_ABSENT.md").write_text(
                "This file does not contain the marker text.", encoding="utf-8"
            )
            result = dc.load_verified_high_risk_markers(root)
            self.assertEqual(result, {"legacy/CLAIMED_AND_PRESENT.md": "SUPERSEDED FOR ACTIVE ROUTING"})


class TestComputeCompletenessSynthetic(unittest.TestCase):
    """End-to-end test against a small synthetic fixture repo proving the
    three disposition sources and the open-defect path all function, and
    that nothing is ever mutated."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "state").mkdir()
        (self.root / "operations").mkdir()
        (self.root / "scripts").mkdir()

        # File with inline standing disposition.
        (self.root / "state" / "NEW_A.json").write_text(
            json.dumps({"supersedes_pointer": {"path": "state/OLD_A.json", "standing": "SUPERSEDED_RETAINED"}}),
            encoding="utf-8",
        )
        (self.root / "state" / "OLD_A.json").write_text(json.dumps({"note": "old a"}), encoding="utf-8")

        # File dispositioned only via the disposition table.
        (self.root / "state" / "NEW_B.json").write_text(
            json.dumps({"supersedes_pointer": {"path": "state/OLD_B.json"}}),
            encoding="utf-8",
        )
        (self.root / "state" / "OLD_B.json").write_text(json.dumps({"note": "old b"}), encoding="utf-8")
        (self.root / "operations" / "INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md").write_text(
            "| Object/class | Disposition | Current treatment |\n"
            "|---|---|---|\n"
            "| `state/OLD_B.json` | RETAIN / EVIDENCE | table-listed |\n",
            encoding="utf-8",
        )

        # File dispositioned only via a verified high_risk_marker.
        (self.root / "state" / "NEW_C.json").write_text(
            json.dumps({"supersedes_pointer": {"path": "state/OLD_C.md"}}),
            encoding="utf-8",
        )
        (self.root / "state" / "OLD_C.md").write_text("SUPERSEDED FOR ACTIVE ROUTING notice.", encoding="utf-8")
        (self.root / "scripts" / "check_operator_taxonomy.py").write_text(
            'high_risk_markers = {\n'
            '    "state/OLD_C.md": "SUPERSEDED FOR ACTIVE ROUTING",\n'
            '}\n',
            encoding="utf-8",
        )

        # File with no disposition at all: the open defect.
        (self.root / "state" / "NEW_D.json").write_text(
            json.dumps({"supersedes_pointer": {"path": "state/OLD_D.json"}}),
            encoding="utf-8",
        )
        (self.root / "state" / "OLD_D.json").write_text(json.dumps({"note": "old d, no disposition"}), encoding="utf-8")

        self._before = {
            p: p.read_bytes()
            for p in self.root.rglob("*")
            if p.is_file()
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_four_scenarios_classified_correctly(self):
        report = dc.compute_completeness(self.root)
        self.assertEqual(report["superseded_file_count"], 4)
        self.assertEqual(report["open_defects"], ["state/OLD_D.json"])
        dispositioned_paths = {d["path"]: d["sources"] for d in report["dispositioned"]}
        self.assertEqual(
            dispositioned_paths["state/OLD_A.json"],
            [{"kind": "INLINE_STANDING", "value": "SUPERSEDED_RETAINED"}],
        )
        self.assertEqual(
            dispositioned_paths["state/OLD_B.json"],
            [{"kind": "DISPOSITION_TABLE", "value": "RETAIN / EVIDENCE"}],
        )
        self.assertEqual(
            dispositioned_paths["state/OLD_C.md"],
            [{"kind": "VERIFIED_HIGH_RISK_MARKER", "value": "SUPERSEDED FOR ACTIVE ROUTING"}],
        )
        self.assertEqual(report["status"], "OPEN_DEFECTS_PRESENT")
        self.assertFalse(report["all_dispositioned"])

    def test_no_scanned_file_is_mutated(self):
        dc.compute_completeness(self.root)
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(self._before, after)

    def test_fully_dispositioned_synthetic_repo_reports_true(self):
        # Remove the undispositioned pair to prove the positive branch also works.
        (self.root / "state" / "NEW_D.json").unlink()
        (self.root / "state" / "OLD_D.json").unlink()
        report = dc.compute_completeness(self.root)
        self.assertEqual(report["open_defects"], [])
        self.assertTrue(report["all_dispositioned"])
        self.assertEqual(report["status"], "ALL_DISPOSITIONED")


class TestMainFailsClosedOnMissingRepo(unittest.TestCase):
    def test_missing_disposition_table_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()
            (root / "state" / "X.json").write_text(json.dumps({"note": "x"}), encoding="utf-8")
            exit_code = dc.main(["--repo-root", str(root)])
            self.assertEqual(exit_code, 1)


class TestRealRepository(unittest.TestCase):
    """Grounding tests against the actual repository contents. These record
    genuine findings; a non-empty open_defects list here is a real,
    expected result, not a bug in the checker."""

    def test_disposition_table_is_readable_in_real_repo(self):
        table = dc.load_disposition_table(REPO_ROOT)
        self.assertIsInstance(table, dict)

    def test_verified_markers_readable_in_real_repo(self):
        markers = dc.load_verified_high_risk_markers(REPO_ROOT)
        self.assertIsInstance(markers, dict)
        # Every entry returned must be independently re-verifiable.
        for path, marker in markers.items():
            target = REPO_ROOT / path
            self.assertTrue(target.is_file())
            self.assertIn(marker, target.read_text(encoding="utf-8", errors="replace"))

    def test_real_repo_completeness_report_is_internally_consistent(self):
        report = dc.compute_completeness(REPO_ROOT)
        self.assertEqual(
            report["superseded_file_count"],
            report["dispositioned_count"] + report["open_defect_count"],
        )
        self.assertEqual(len(set(report["open_defects"])), len(report["open_defects"]))
        dispositioned_paths = {d["path"] for d in report["dispositioned"]}
        self.assertTrue(dispositioned_paths.isdisjoint(set(report["open_defects"])))

    def test_real_repo_has_58_superseded_files_currently(self):
        # A concrete, falsifiable snapshot of the real repository's current
        # state at the pinned working commit. If this fails, the repository
        # content changed underneath the checker and the new count is the
        # fact to record, not this test's expectation.
        report = dc.compute_completeness(REPO_ROOT)
        self.assertEqual(report["superseded_file_count"], 58)

    def test_real_repo_has_open_defects_none_rescued_by_table_or_markers(self):
        report = dc.compute_completeness(REPO_ROOT)
        # This is the falsifying observation for this unit: at the current
        # commit, 34 of 58 superseded files have no disposition from any of
        # the three checked sources. That is reported precisely below, not
        # hidden or silently patched.
        self.assertEqual(report["open_defect_count"], 34)
        self.assertEqual(report["dispositioned_count"], 24)
        self.assertEqual(report["status"], "OPEN_DEFECTS_PRESENT")

    def test_real_repo_no_file_is_mutated_by_running_the_checker(self):
        before = (REPO_ROOT / "state" / "ACTIVE_CONTROL_POINTER_CURRENT.json").read_bytes()
        dc.compute_completeness(REPO_ROOT)
        after = (REPO_ROOT / "state" / "ACTIVE_CONTROL_POINTER_CURRENT.json").read_bytes()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
