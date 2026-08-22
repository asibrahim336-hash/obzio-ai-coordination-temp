"""Unit a3-u02: the hermeticity prober detects what it claims to detect.

Two assertions carry the unit.  Every rule fires on a planted defect with an
exact expected count, so a rule that stops matching fails the suite rather than
reporting a clean tree.  And the real PO-03 tree reports zero findings, so the
gate is currently satisfied rather than merely present.

The prober is loaded by file path rather than imported as a package, because
``workstreams/po03`` is not a Python package and a clean clone has nothing on
``sys.path`` that would make it one.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_DIR = REPO_ROOT / "workstreams" / "po03" / "runtime"
PROBER_PATH = RUNTIME_DIR / "hermeticity.py"
RULES_PATH = RUNTIME_DIR / "hermeticity-rules.json"
FIXTURE_DIR = RUNTIME_DIR / "fixtures" / "non_portable"
SCOPE_DIR = RUNTIME_DIR / "fixtures" / "scope"
EXPECTATIONS_PATH = RUNTIME_DIR / "fixtures" / "expected-findings.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hermeticity = load_module(PROBER_PATH, "po03_hermeticity")


def counts_by_file(findings) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {}
    for finding in findings:
        grouped.setdefault(finding.path, {})
        grouped[finding.path][finding.rule] = grouped[finding.path].get(finding.rule, 0) + 1
    return grouped


class PlantedDefectsAreDetected(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = hermeticity.load_rules(RULES_PATH)
        self.expectations = json.loads(EXPECTATIONS_PATH.read_text(encoding="utf-8"))
        self.fixtures = sorted(FIXTURE_DIR.glob("*.py"))
        self.findings = hermeticity.scan_paths(self.fixtures, self.rules, REPO_ROOT)

    def test_fixture_findings_match_the_expected_counts_exactly(self) -> None:
        self.assertEqual(counts_by_file(self.findings), self.expectations["expected_findings"])
        self.assertEqual(len(self.findings), self.expectations["total_expected_findings"])

    def test_every_rule_has_a_planted_defect_that_fires(self) -> None:
        fired = {finding.rule for finding in self.findings}
        declared = set(self.rules["rules"])
        uncovered = declared - fired - set(self.expectations["rules_without_a_committed_fixture"])
        self.assertEqual(uncovered, set(), f"rules with no planted defect: {sorted(uncovered)}")

    def test_parse_error_is_reported_rather_than_crashing(self) -> None:
        findings = hermeticity.scan_source("synthetic.py", "def broken(:\n", self.rules)
        self.assertEqual([finding.rule for finding in findings], ["PARSE_ERROR"])

    def test_every_fixture_file_is_covered_by_the_expectations(self) -> None:
        relative = {str(path.relative_to(REPO_ROOT)) for path in self.fixtures}
        self.assertEqual(relative, set(self.expectations["expected_findings"]))


class RealTreeIsHermetic(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = hermeticity.load_rules(RULES_PATH)

    def test_real_tree_reports_zero_findings(self) -> None:
        scan_root = REPO_ROOT / self.rules["scan_root"]
        targets = hermeticity.discover(scan_root, self.rules, REPO_ROOT)
        self.assertGreater(len(targets), 0, "the prober scanned nothing")
        findings = hermeticity.scan_paths(targets, self.rules, REPO_ROOT)
        detail = "\n".join(f"{f.rule} {f.path}:{f.line} {f.detail}" for f in findings)
        self.assertEqual(findings, [], f"non-portable patterns in the PO-03 tree:\n{detail}")

    def test_the_prober_scans_itself(self) -> None:
        """A prober exempt from its own gate proves nothing about the tree."""
        scan_root = REPO_ROOT / self.rules["scan_root"]
        targets = hermeticity.discover(scan_root, self.rules, REPO_ROOT)
        self.assertIn(PROBER_PATH.resolve(), {path.resolve() for path in targets})

    def test_fixtures_are_excluded_from_discovery_but_not_from_explicit_scans(self) -> None:
        scan_root = REPO_ROOT / self.rules["scan_root"]
        discovered = {path.resolve() for path in hermeticity.discover(scan_root, self.rules, REPO_ROOT)}
        planted = (FIXTURE_DIR / "temp_state.py").resolve()
        self.assertNotIn(planted, discovered, "planted fixtures must not pollute the real-tree scan")
        explicit = hermeticity.scan_paths([planted], self.rules, REPO_ROOT)
        self.assertTrue(explicit, "an explicitly named fixture must still be scanned")


class ScopeOfDetection(unittest.TestCase):
    """The exemptions must be narrow enough to keep the gate meaningful.

    These cases live as real files under the excluded fixtures tree rather than
    as string literals in this module.  A test that embedded the patterns it
    asserts on would itself be flagged by the real-tree scan -- which is exactly
    what happened the first time this suite ran.
    """

    def setUp(self) -> None:
        self.rules = hermeticity.load_rules(RULES_PATH)

    def rules_fired(self, fixture: str) -> set[str]:
        path = SCOPE_DIR / fixture
        return {finding.rule for finding in hermeticity.scan_paths([path], self.rules, REPO_ROOT)}

    def test_docstring_prose_is_not_flagged(self) -> None:
        self.assertEqual(self.rules_fired("docstring_prose.py"), set())

    def test_the_same_text_as_an_operational_literal_is_flagged(self) -> None:
        self.assertEqual(
            self.rules_fired("operational_literal.py"),
            {"ABS_PATH_LITERAL", "TEMP_PATH_LITERAL"},
        )

    def test_a_non_docstring_string_expression_is_still_flagged(self) -> None:
        self.assertIn("TEMP_PATH_LITERAL", self.rules_fired("late_string_expression.py"))

    def test_relative_paths_are_not_flagged(self) -> None:
        self.assertEqual(self.rules_fired("relative_path.py"), set())

    def test_import_alias_form_is_detected(self) -> None:
        self.assertIn("NETWORK_IMPORT", self.rules_fired("network_alias_import.py"))

    def test_scope_fixtures_are_excluded_from_the_real_tree_scan(self) -> None:
        scan_root = REPO_ROOT / self.rules["scan_root"]
        discovered = {path.resolve() for path in hermeticity.discover(scan_root, self.rules, REPO_ROOT)}
        for fixture in sorted(SCOPE_DIR.glob("*.py")):
            self.assertNotIn(fixture.resolve(), discovered)


class CommandLineBehaviour(unittest.TestCase):
    """CI runs the prober as a command, so the command is what gets tested."""

    def run_prober(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", "-B", str(PROBER_PATH), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

    def test_clean_tree_exits_zero(self) -> None:
        result = self.run_prober()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS 0 hermeticity findings", result.stdout)

    def test_planted_fixtures_exit_nonzero(self) -> None:
        fixtures = [str(path) for path in sorted(FIXTURE_DIR.glob("*.py"))]
        result = self.run_prober(*fixtures)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("FAIL 19 hermeticity finding(s)", result.stdout)

    def test_json_report_shape(self) -> None:
        result = self.run_prober("--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "po03-hermeticity-report-v1")
        self.assertEqual(report["finding_count"], 0)
        self.assertGreater(report["scanned_file_count"], 0)
        self.assertIn("TEMP_PATH_LITERAL", report["rules_available"])

    def test_rules_schema_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            bad = Path(scratch) / "rules.json"
            bad.write_text(json.dumps({"schema": "wrong", "rules": {}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                hermeticity.load_rules(bad)


if __name__ == "__main__":
    unittest.main()
