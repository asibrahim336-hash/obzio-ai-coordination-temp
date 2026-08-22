import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "repository_disposition.py"
SPEC = importlib.util.spec_from_file_location("repository_disposition", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

REPO_ROOT = Path(__file__).resolve().parents[3]
GIT = shutil.which("git")


def scan_digest(root):
    digests = {}
    for directory in MODULE.SCAN_DIRECTORIES:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                digests[path.relative_to(root).as_posix()] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    return digests


class RealRepositoryAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = MODULE.analyse(REPO_ROOT)

    def test_report_is_json_serialisable(self):
        self.assertIsInstance(json.dumps(self.report), str)

    def test_required_keys_are_present(self):
        for key in (
            "evidence_id",
            "scanned_directories",
            "pointer_sources",
            "reachable_paths",
            "totals",
            "current_files",
            "superseded_files",
            "unclassified_files",
            "marker_definitions",
            "limitations",
        ):
            self.assertIn(key, self.report)

    def test_classified_counts_sum_to_total(self):
        totals = self.report["totals"]
        self.assertEqual(
            totals["scanned_files"],
            totals["current"] + totals["superseded"] + totals["unclassified"],
        )

    def test_counts_match_list_lengths(self):
        totals = self.report["totals"]
        self.assertEqual(totals["current"], len(self.report["current_files"]))
        self.assertEqual(totals["superseded"], len(self.report["superseded_files"]))
        self.assertEqual(totals["unclassified"], len(self.report["unclassified_files"]))
        self.assertEqual(totals["reachable_declared"], len(self.report["reachable_paths"]))

    def test_classification_is_a_partition(self):
        current = set(self.report["current_files"])
        superseded = {row["path"] for row in self.report["superseded_files"]}
        unclassified = set(self.report["unclassified_files"])
        self.assertEqual(set(), current & superseded)
        self.assertEqual(set(), current & unclassified)
        self.assertEqual(set(), superseded & unclassified)
        self.assertEqual(
            len(current) + len(superseded) + len(unclassified),
            self.report["totals"]["scanned_files"],
        )

    def test_something_was_actually_scanned(self):
        self.assertGreater(self.report["totals"]["scanned_files"], 0)
        self.assertGreater(self.report["totals"]["reachable_declared"], 0)

    def test_every_scanned_path_is_inside_a_scanned_directory(self):
        paths = (
            list(self.report["current_files"])
            + [row["path"] for row in self.report["superseded_files"]]
            + list(self.report["unclassified_files"])
        )
        for path in paths:
            self.assertIn(path.split("/")[0], self.report["scanned_directories"], path)

    def test_current_files_are_pointer_reachable(self):
        reachable = set(self.report["reachable_paths"])
        for path in self.report["current_files"]:
            self.assertIn(path, reachable)

    def test_instruction_stack_entries_are_reachable(self):
        reachable = set(self.report["reachable_paths"])
        for path in (
            "state/ACTIVE_CONTROL_POINTER_CURRENT.json",
            "state/operator-system/ACTIVE_INSTRUCTION_STACK.json",
            "dispatch/SC_CIEG_V010_FULL_SCALE_CHATGPT_LAUNCH_MANIFEST_20260819_v001.json",
        ):
            self.assertIn(path, reachable, path)

    def test_reachable_paths_exist_on_disk(self):
        self.assertEqual([], self.report["reachable_paths_missing_from_disk"])

    def test_superseded_entries_carry_a_recognised_marker(self):
        known = set(MODULE.QUALIFIED_MARKERS) | set(MODULE.BARE_MARKERS)
        self.assertTrue(self.report["superseded_files"])
        for row in self.report["superseded_files"]:
            self.assertIn(row["marker"], known)

    def test_taxonomy_high_risk_files_are_not_unclassified(self):
        unclassified = set(self.report["unclassified_files"])
        for path in (
            "commissions/OPERATOR_D_CONTINUATION_DIRECTIVE_20260818.md",
            "dispatch/OPERATOR_D_REFERENCE_UPDATE_20260818.md",
            "state/DESK_OPERATOR_D_RECOVERY_AND_CONTINUATION_20260818.md",
            "templates/NEXT_OPERATOR_PREFLIGHT_20260818.md",
            "handover/PRINCIPAL_AI_OPERATOR_HANDOVER_20260819.md",
        ):
            self.assertNotIn(path, unclassified, path)

    def test_alias_cross_check_is_consistent_with_the_taxonomy_gate(self):
        cross = self.report["alias_cross_check"]
        self.assertEqual("CONSISTENT", cross["state"], cross)
        self.assertEqual([], cross["required_aliases_missing_from_register"])
        self.assertIn("Operator D", cross["required_aliases"])
        self.assertGreaterEqual(cross["classified_alias_count"], cross["required_alias_count"])

    def test_pointer_sources_are_hashed(self):
        for row in self.report["pointer_sources"]:
            self.assertIn("sha256", row)
            if row["sha256"] != "NOT_APPLICABLE":
                self.assertEqual(64, len(row["sha256"]))


class ReadOnlyGuaranteeTests(unittest.TestCase):
    def test_analysis_does_not_modify_scanned_directories(self):
        before = scan_digest(REPO_ROOT)
        MODULE.analyse(REPO_ROOT)
        after = scan_digest(REPO_ROOT)
        self.assertEqual(before, after)

    @unittest.skipUnless(GIT, "git is required for the worktree cleanliness check")
    def test_scanned_directories_stay_clean_in_git(self):
        MODULE.analyse(REPO_ROOT)
        result = subprocess.run(
            [GIT, "-C", str(REPO_ROOT), "status", "--porcelain", "--", *MODULE.SCAN_DIRECTORIES],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual("", result.stdout.strip())

    def test_output_outside_the_po03_allowlist_is_refused(self):
        for candidate in (
            REPO_ROOT / "state" / "leak.json",
            REPO_ROOT / "AGENTS.md",
            REPO_ROOT / "receipts" / "po03" / "leak.json",
        ):
            with self.assertRaises(MODULE.DispositionError):
                MODULE._validate_output_path(REPO_ROOT, candidate)

    def test_output_inside_the_po03_allowlist_is_accepted(self):
        relative = MODULE._validate_output_path(
            REPO_ROOT, REPO_ROOT / MODULE.DEFAULT_OUTPUT
        )
        self.assertEqual(MODULE.DEFAULT_OUTPUT, relative)

    def test_output_escaping_the_root_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(MODULE.DispositionError):
                MODULE._validate_output_path(REPO_ROOT, Path(tmp) / "leak.json")


class ParserTests(unittest.TestCase):
    def test_readme_order_parses_backticked_numbered_paths(self):
        paths = MODULE.parse_readme_order(REPO_ROOT)
        self.assertIn("state/ACTIVE_CONTROL_POINTER_CURRENT.json", paths)
        self.assertIn("templates/NEXT_OPERATOR_PREFLIGHT_CURRENT.md", paths)
        for path in paths:
            self.assertNotIn("`", path)

    def test_instruction_stack_arrays_are_both_read(self):
        resolve, evidence = MODULE.parse_instruction_stack(REPO_ROOT)
        self.assertIn("state/ACTIVE_CONTROL_POINTER_CURRENT.json", resolve)
        self.assertIn("state/ACTIVE_CONTROL_POINTER_20260819_02.json", evidence)

    def test_missing_pointer_source_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(MODULE.DispositionError):
                MODULE.parse_readme_order(Path(tmp))
            with self.assertRaises(MODULE.DispositionError):
                MODULE.parse_instruction_stack(Path(tmp))

    def test_marker_detection_is_case_insensitive_and_head_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()
            (root / "state" / "a.md").write_text("this file is Superseded\n", encoding="utf-8")
            (root / "state" / "b.md").write_text("x" * 5000 + "SUPERSEDED\n", encoding="utf-8")
            (root / "state" / "c.md").write_text("ordinary content\n", encoding="utf-8")
            self.assertEqual("SUPERSEDED", MODULE.find_marker(root, "state/a.md"))
            self.assertIsNone(MODULE.find_marker(root, "state/b.md"))
            self.assertIsNone(MODULE.find_marker(root, "state/c.md"))

    def test_qualified_marker_wins_over_bare_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()
            (root / "state" / "a.md").write_text(
                "SUPERSEDED FOR ACTIVE ROUTING\n", encoding="utf-8"
            )
            self.assertEqual(
                "SUPERSEDED FOR ACTIVE ROUTING", MODULE.find_marker(root, "state/a.md")
            )


class SyntheticTreeTests(unittest.TestCase):
    def build(self, root):
        (root / "operations").mkdir()
        (root / "operations" / "README.md").write_text(
            "# Current operator route\n\n"
            "## Read in this order\n\n"
            "1. `state/pointer.json` — pointer.\n"
            "2. `state/operator-system/ACTIVE_INSTRUCTION_STACK.json` — stack.\n\n"
            "## Active identity\n\n"
            "3. `state/not-in-order.json` — outside the section.\n",
            encoding="utf-8",
        )
        stack_dir = root / "state" / "operator-system"
        stack_dir.mkdir(parents=True)
        (stack_dir / "ACTIVE_INSTRUCTION_STACK.json").write_text(
            json.dumps(
                {
                    "resolve_in_order": ["state/pointer.json"],
                    "immutable_execution_evidence": ["dispatch/evidence.md"],
                }
            ),
            encoding="utf-8",
        )
        (root / "state" / "pointer.json").write_text("{}\n", encoding="utf-8")
        (root / "state" / "old.md").write_text("QUARANTINED OPERATOR REPORT\n", encoding="utf-8")
        (root / "state" / "plain.md").write_text("nothing notable\n", encoding="utf-8")
        (root / "dispatch").mkdir()
        (root / "dispatch" / "evidence.md").write_text("launch manifest\n", encoding="utf-8")

    def test_synthetic_tree_classifies_as_expected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build(root)
            report = MODULE.analyse(root)
            self.assertEqual(
                [
                    "dispatch/evidence.md",
                    "state/operator-system/ACTIVE_INSTRUCTION_STACK.json",
                    "state/pointer.json",
                ],
                report["current_files"],
            )
            self.assertEqual(
                [{"path": "state/old.md", "marker": "QUARANTINED OPERATOR REPORT"}],
                report["superseded_files"],
            )
            self.assertIn("state/plain.md", report["unclassified_files"])
            totals = report["totals"]
            self.assertEqual(
                totals["scanned_files"],
                totals["current"] + totals["superseded"] + totals["unclassified"],
            )

    def test_section_scoping_excludes_later_numbered_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build(root)
            paths = MODULE.parse_readme_order(root)
            self.assertIn("state/pointer.json", paths)
            self.assertNotIn("state/not-in-order.json", paths)

    def test_pointer_reachable_file_with_marker_is_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build(root)
            (root / "state" / "pointer.json").write_text(
                '{"note": "SUPERSEDED rule text"}\n', encoding="utf-8"
            )
            report = MODULE.analyse(root)
            self.assertIn("state/pointer.json", report["current_files"])
            self.assertEqual(
                [{"path": "state/pointer.json", "marker": "SUPERSEDED"}],
                report["current_but_marked_superseded"],
            )

    def test_alias_cross_check_is_not_applicable_without_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build(root)
            cross = MODULE.alias_cross_check(root)
            self.assertEqual("NOT_APPLICABLE", cross["state"])

    def test_alias_cross_check_reports_missing_required_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build(root)
            (root / "scripts").mkdir()
            (root / "scripts" / "check_operator_taxonomy.py").write_text(
                'required_aliases = {"Alpha", "Beta"}\n', encoding="utf-8"
            )
            (root / "state" / "operator-system" / "OPERATOR_ALIAS_REGISTER.jsonl").write_text(
                '{"alias":"Alpha"}\n{"alias":"Gamma"}\n', encoding="utf-8"
            )
            cross = MODULE.alias_cross_check(root)
            self.assertEqual("INCONSISTENT", cross["state"])
            self.assertEqual(["Beta"], cross["required_aliases_missing_from_register"])
            self.assertEqual(["Gamma"], cross["classified_aliases_beyond_required"])

    def test_missing_reachable_path_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build(root)
            (root / "dispatch" / "evidence.md").unlink()
            report = MODULE.analyse(root)
            self.assertEqual(
                ["dispatch/evidence.md"], report["reachable_paths_missing_from_disk"]
            )


if __name__ == "__main__":
    unittest.main()
