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
ROLE_DIR = RUNTIME_DIR / "fixtures" / "literal_roles"
EXPECTATIONS_PATH = RUNTIME_DIR / "fixtures" / "expected-findings.json"
ROUTER_PATH = RUNTIME_DIR / "route_findings.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hermeticity = load_module(PROBER_PATH, "po03_hermeticity")
router = load_module(ROUTER_PATH, "po03_route_findings")


def counts_by_file(findings) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {}
    for finding in findings:
        grouped.setdefault(finding.path, {})
        grouped[finding.path][finding.rule] = grouped[finding.path].get(finding.rule, 0) + 1
    return grouped


def reportable(findings) -> list:
    return [finding for finding in findings if finding.reportable]


def advisory(findings) -> list:
    return [
        finding
        for finding in findings
        if finding.exempt_role is None and finding.severity == "advisory"
    ]


class PlantedDefectsAreDetected(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = hermeticity.load_rules(RULES_PATH)
        self.expectations = json.loads(EXPECTATIONS_PATH.read_text(encoding="utf-8"))
        self.fixtures = sorted(FIXTURE_DIR.glob("*.py"))
        self.findings = hermeticity.scan_paths(self.fixtures, self.rules, REPO_ROOT)

    def test_fixture_findings_match_the_expected_counts_exactly(self) -> None:
        self.assertEqual(
            counts_by_file(reportable(self.findings)), self.expectations["expected_findings"]
        )
        self.assertEqual(
            len(reportable(self.findings)), self.expectations["total_expected_findings"]
        )

    def test_no_planted_defect_is_exempted_by_a_role(self) -> None:
        """The precision work must not have quietly forgiven the recall set.

        This is the assertion that makes the whole role classifier auditable:
        the six fixtures the commission requires must fire with no role
        touching them, or precision was bought with recall.
        """
        exempted = [
            f"{finding.rule} {finding.path}:{finding.line} via {finding.exempt_role}"
            for finding in self.findings
            if finding.exempt_role is not None
        ]
        self.assertEqual(exempted, [], f"a role exempted a planted defect: {exempted}")

    def test_the_accepted_form_is_downgraded_rather_than_reported(self) -> None:
        """The judgement behind the sys.path verdict, proved rather than asserted."""
        expected = self.expectations["expected_advisory"]
        self.assertEqual(counts_by_file(advisory(self.findings)), expected)
        self.assertEqual(len(advisory(self.findings)), self.expectations["total_expected_advisory"])
        anchored = FIXTURE_DIR / "anchored_import_path.py"
        unanchored = FIXTURE_DIR / "import_path_mutation.py"
        self.assertEqual(reportable(hermeticity.scan_paths([anchored], self.rules, REPO_ROOT)), [])
        self.assertEqual(
            {finding.rule for finding in hermeticity.scan_paths([unanchored], self.rules, REPO_ROOT)},
            {"SYS_PATH_MUTATION"},
            "the unanchored form must keep firing, or the downgrade is a hole",
        )

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
        covered = set(self.expectations["expected_findings"]) | set(
            self.expectations["expected_advisory"]
        )
        self.assertEqual(relative, covered)


class LiteralRolesImprovePrecisionWithoutLosingRecall(unittest.TestCase):
    """Both halves of the precision claim, because one half alone proves nothing.

    Making a gate quieter is easy and worthless on its own. The pair of
    fixtures here is the evidence: one holds path-shaped strings that no program
    uses as a path and must report nothing, the other holds real defects inside
    an asserting test method in a ``test_*.py`` file and must report all of them.
    """

    def setUp(self) -> None:
        self.rules = hermeticity.load_rules(RULES_PATH)
        self.expectations = json.loads(EXPECTATIONS_PATH.read_text(encoding="utf-8"))[
            "precision_fixtures"
        ]

    def scan(self, name: str):
        return hermeticity.scan_paths([ROLE_DIR / name], self.rules, REPO_ROOT)

    def test_strings_under_test_are_not_reported(self) -> None:
        name = "test_strings_under_test.py"
        expected = self.expectations[f"workstreams/po03/runtime/fixtures/literal_roles/{name}"]
        findings = self.scan(name)
        leaked = [f"{f.rule} {f.path}:{f.line} {f.detail}" for f in reportable(findings)]
        self.assertEqual(len(leaked), expected["expected_reportable"], leaked)

    def test_every_role_is_exercised_by_that_fixture(self) -> None:
        """A role that classifies nothing is untested code deciding what to hide."""
        name = "test_strings_under_test.py"
        expected = self.expectations[f"workstreams/po03/runtime/fixtures/literal_roles/{name}"]
        roles = {
            finding.exempt_role
            for finding in self.scan(name)
            if finding.exempt_role is not None
        }
        self.assertEqual(sorted(roles), expected["expected_exempt_roles"])
        self.assertEqual(sorted(roles), sorted(self.rules["literal_roles"]["roles"]))

    def test_real_defects_in_a_test_module_still_fire(self) -> None:
        name = "test_real_defects_in_a_test.py"
        expected = self.expectations[f"workstreams/po03/runtime/fixtures/literal_roles/{name}"]
        findings = self.scan(name)
        forgiven = [
            f"{f.rule} {f.path}:{f.line} via {f.exempt_role}"
            for f in findings
            if f.exempt_role is not None
        ]
        self.assertEqual(len(forgiven), expected["expected_exempt"], forgiven)
        self.assertGreaterEqual(
            len(reportable(findings)), expected["expected_reportable_minimum"]
        )

    def test_a_sink_outranks_every_positional_role(self) -> None:
        """The ordering that stops an assertion from laundering a real path.

        ``os.path.exists("/srv/x")`` inside an assertion is still a path the
        program acts on, so the sink check has to beat ASSERTION_OPERAND. This
        is the ordering rule stated as a test, because getting it wrong is
        invisible: the finding simply disappears.
        """
        source = (
            "import os\n"
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_x(self):\n"
            "        self.assertTrue(os.path.exists('/srv/obzio/x'))\n"
        )
        findings = hermeticity.scan_source("test_probe.py", source, self.rules)
        self.assertEqual([finding.rule for finding in reportable(findings)], ["ABS_PATH_LITERAL"])

    def test_no_literal_is_forgiven_by_its_value(self) -> None:
        """The same string is data in one position and a defect in another.

        If precision had been bought with a forgiven-value list this would be
        impossible to satisfy, which is why it is worth asserting: it shows the
        classifier reads position rather than spelling.
        """
        data = "def check(v):\n    return v.startswith('/tmp/po03')\n"
        used = "def check():\n    return open('/tmp/po03', encoding='utf-8').read()\n"
        self.assertEqual(reportable(hermeticity.scan_source("m.py", data, self.rules)), [])
        self.assertEqual(
            [f.rule for f in reportable(hermeticity.scan_source("m.py", used, self.rules))],
            ["ABS_PATH_LITERAL", "TEMP_PATH_LITERAL"],
        )


class RealTreeIsHermetic(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = hermeticity.load_rules(RULES_PATH)

    def whole_tree_findings(self):
        scan_root = REPO_ROOT / self.rules["scan_root"]
        targets = hermeticity.discover(scan_root, self.rules, REPO_ROOT)
        self.assertGreater(len(targets), 0, "the prober scanned nothing")
        return reportable(hermeticity.scan_paths(targets, self.rules, REPO_ROOT))

    @unittest.expectedFailure
    def test_real_tree_reports_zero_findings(self) -> None:
        """SCOPE: whole-tree, kept red on purpose.

        The commission's clean-runtime requirement is about the whole PO-03
        suite, so narrowing this to my own files would be answering an easier
        question than the one asked. It fails on the fourteen genuine findings
        routed in ``runtime/finding-triage.json`` -- thirteen in
        ``metrics/probe_telemetry.py`` owned by a7, one in
        ``packverify/boundary_run.py`` owned by a4. Neither is mine to fix.

        Marked expected rather than skipped so that it retires itself: when the
        routed findings land, unittest reports an unexpected success and forces
        this marker off. A truthful red that cannot be forgotten.
        """
        findings = self.whole_tree_findings()
        detail = "\n".join(f"{f.rule} {f.path}:{f.line} {f.detail}" for f in findings)
        self.assertEqual(findings, [], f"non-portable patterns in the PO-03 tree:\n{detail}")

    def test_my_own_paths_report_zero_findings(self) -> None:
        """SCOPE: narrowed to owned paths, and green.

        The companion to the red above. It is what I can actually be held to,
        and keeping it separate means the whole-tree failure never becomes an
        excuse for a regression of my own.
        """
        owned = sorted(
            path
            for path in (REPO_ROOT / "workstreams" / "po03" / "runtime").rglob("*.py")
            if "fixtures" not in path.relative_to(REPO_ROOT).parts
        ) + sorted((REPO_ROOT / "workstreams" / "po03" / "tests").glob("test_a3_*.py"))
        self.assertGreater(len(owned), 0)
        findings = reportable(hermeticity.scan_paths(owned, self.rules, REPO_ROOT))
        detail = "\n".join(f"{f.rule} {f.path}:{f.line} {f.detail}" for f in findings)
        self.assertEqual(findings, [], f"non-portable patterns in my own files:\n{detail}")

    def test_every_whole_tree_finding_is_triaged_and_routed(self) -> None:
        """The obligation that replaces the one the red test can no longer meet.

        A failing gate is only useful if someone can act on it, so what is
        asserted here is not that the tree is clean but that every finding in it
        has a verdict and an owner. An untriaged finding is the real failure.
        """
        routed = router.route(REPO_ROOT)
        untriaged = [
            f"{record['finding_class']} {record['file']}:{record['line']}"
            for record in routed["findings"]
            if record["triage"] == "UNTRIAGED"
        ]
        self.assertEqual(untriaged, [], f"findings with no verdict: {untriaged}")
        unowned = [
            record["file"] for record in routed["findings"] if record["owner"] == "UNOWNED"
        ]
        self.assertEqual(unowned, [], f"findings no owner claims: {sorted(set(unowned))}")
        for record in routed["findings"]:
            if record["triage"] == "GENUINE":
                self.assertNotEqual(record["minimal_fix"], "NOT_YET", record)

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

    def test_a_relative_directory_argument_still_excludes_the_fixtures(self) -> None:
        """Found by pointing the harness at my own directory instead of the tree.

        ``discover`` compares candidates against absolute excluded directories,
        so a relative argument matched none of them and pulled every planted
        fixture into an ordinary scan -- forty findings from a clean directory.
        Nothing detected it earlier because every previous caller passed either
        no argument or an absolute one.
        """
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(PROBER_PATH), "workstreams/po03/runtime"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("fixtures/", result.stdout)

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

    def test_a_clean_input_exits_zero(self) -> None:
        """SCOPE: narrowed to owned paths.

        This once ran the prober bare and asserted exit 0, which made a claim
        about the whole tree inside a test whose subject is the command's
        contract. The contract is that a clean input exits 0 and says so; the
        tree's cleanliness is asserted, and currently expected to fail, in
        RealTreeIsHermetic where it belongs.
        """
        owned = [str(path) for path in sorted(RUNTIME_DIR.glob("*.py"))]
        result = self.run_prober(*owned)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS 0 hermeticity findings", result.stdout)

    def test_planted_fixtures_exit_nonzero(self) -> None:
        fixtures = [
            str(path)
            for path in sorted(FIXTURE_DIR.glob("*.py"))
            if path.name != "anchored_import_path.py"
        ]
        result = self.run_prober(*fixtures)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("FAIL 19 hermeticity finding(s)", result.stdout)

    def test_the_accepted_form_exits_zero_but_is_still_shown(self) -> None:
        """An advisory must not fail the gate, and must not be silent either."""
        anchored = str(FIXTURE_DIR / "anchored_import_path.py")
        quiet = self.run_prober(anchored)
        self.assertEqual(quiet.returncode, 0, quiet.stdout + quiet.stderr)
        self.assertIn("3 advisory", quiet.stdout)
        loud = self.run_prober("--show-exempt", anchored)
        self.assertIn("advisory: SYS_PATH_ANCHORED", loud.stdout)

    def test_json_report_shape(self) -> None:
        """SCOPE: narrowed to owned paths, for the same reason as above."""
        owned = [str(path) for path in sorted(RUNTIME_DIR.glob("*.py"))]
        result = self.run_prober("--json", *owned)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "po03-hermeticity-report-v1")
        self.assertEqual(report["finding_count"], 0)
        self.assertGreater(report["scanned_file_count"], 0)
        self.assertIn("TEMP_PATH_LITERAL", report["rules_available"])
        self.assertIn("SYS_PATH_ANCHORED", report["rules_available"])

    def test_the_report_keeps_every_suppression_visible(self) -> None:
        """A suppression that cannot be read cannot be disputed."""
        fixture = str(ROLE_DIR / "test_strings_under_test.py")
        result = self.run_prober("--json", fixture)
        report = json.loads(result.stdout)
        self.assertEqual(report["finding_count"], 0)
        self.assertGreater(report["exempt_count"], 0)
        self.assertEqual(sum(report["exempt_by_role"].values()), report["exempt_count"])
        for record in report["exempt"]:
            self.assertIn("exempt_role", record)
            self.assertIn(record["exempt_role"], report["exempt_by_role"])

    def test_rules_schema_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            bad = Path(scratch) / "rules.json"
            bad.write_text(json.dumps({"schema": "wrong", "rules": {}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                hermeticity.load_rules(bad)


if __name__ == "__main__":
    unittest.main()
