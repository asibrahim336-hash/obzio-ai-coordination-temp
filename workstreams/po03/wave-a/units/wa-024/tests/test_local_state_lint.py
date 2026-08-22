"""Focused tests for the PO03-WA-024 hidden-local-state static control."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, commit_all, corrupt_tail, git, init_repo, load, write

LINT = load("local_state_lint")

HISTORY_DEPENDENT_WORKFLOW = """\
name: needs history
on: [push]
jobs:
  provenance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Verify ancestry
        run: |
          git merge-base --is-ancestor $BASE HEAD
"""

FULL_FETCH_WORKFLOW = """\
name: needs history but asks for it
on: [push]
jobs:
  provenance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Verify ancestry
        run: |
          git merge-base --is-ancestor $BASE HEAD
"""

BARE_PYTHON_WORKFLOW = """\
name: bare interpreter
on: [push]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - run: python tools/missing_tool.py
"""

SETUP_PYTHON_WORKFLOW = """\
name: set up interpreter first
on: [push]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python tools/present_tool.py
"""


class FixtureRepo:
    """A throwaway git repository carrying one instance of each defect class."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="wa024-lint-fixture-")
        self.root = Path(self._tmp.name) / "repo"
        init_repo(self.root)
        write(self.root, "tools/present_tool.py", "print('present')\n")
        write(self.root, "seed.txt", "seed\n")
        self.first_commit = commit_all(self.root, "seed")

        write(self.root, ".github/workflows/history.yml", HISTORY_DEPENDENT_WORKFLOW)
        write(self.root, ".github/workflows/full-fetch.yml", FULL_FETCH_WORKFLOW)
        write(self.root, ".github/workflows/bare-python.yml", BARE_PYTHON_WORKFLOW)
        write(self.root, ".github/workflows/setup-python.yml", SETUP_PYTHON_WORKFLOW)
        self.prefix_only = corrupt_tail(self.first_commit)
        self.unknown = "b" * 40
        write(
            self.root,
            "workstreams/po03/control/inputs/good.json",
            json.dumps({"base": self.first_commit}, indent=2) + "\n",
        )
        write(
            self.root,
            "workstreams/po03/control/inputs/prefix-only.json",
            json.dumps({"base": self.prefix_only}, indent=2) + "\n",
        )
        write(
            self.root,
            "workstreams/po03/control/inputs/unknown.json",
            json.dumps({"base": self.unknown}, indent=2) + "\n",
        )
        self.external = "c" * 40
        write(
            self.root,
            "workstreams/po03/control/inputs/external.json",
            json.dumps({"upstream": self.external}, indent=2) + "\n",
        )
        write(
            self.root,
            "workstreams/po03/tools/host_path_tool.py",
            # The fixture carries one unsuppressed host path and one suppressed
            # one, so both branches of the marker are exercised.
            "FLAGGED = '/workspace/flagged'\n"  # local-state-lint: allow R4_HOST_ABSOLUTE_PATH
            "ALLOWED = '/workspace/allowed'  # local-state-lint: allow R4_HOST_ABSOLUTE_PATH\n",
        )
        self.head = commit_all(self.root, "defect fixtures")

    def close(self) -> None:
        self._tmp.cleanup()

    def lint(self, **kwargs: object) -> dict:
        return LINT.lint(
            self.root,
            scan_globs=("workstreams/po03/", ".github/workflows/"),
            **kwargs,
        )


def by_rule(report: dict, rule: str) -> list[dict]:
    return [row for row in report["findings"] if row["rule"] == rule]


class YamlSubsetTests(unittest.TestCase):
    def test_parses_repository_workflows(self):
        for name in ("po03-contracts.yml", "operator-taxonomy-currentness.yml"):
            with self.subTest(workflow=name):
                doc = LINT.parse_yaml_subset(
                    (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
                )
                self.assertIn("jobs", doc)
                job = next(iter(doc["jobs"].values()))
                self.assertEqual("ubuntu-latest", job["runs-on"])
                self.assertTrue(any("actions/checkout" in str(s.get("uses", "")) for s in job["steps"]))

    def test_reads_fetch_depth_as_integer_zero(self):
        doc = LINT.parse_yaml_subset(FULL_FETCH_WORKFLOW)
        checkout = doc["jobs"]["provenance"]["steps"][0]
        self.assertEqual(0, checkout["with"]["fetch-depth"])

    def test_block_scalar_preserves_newlines(self):
        doc = LINT.parse_yaml_subset("jobs:\n  a:\n    steps:\n      - run: |\n          one\n          two\n")
        self.assertEqual("one\ntwo", doc["jobs"]["a"]["steps"][0]["run"])

    def test_folded_scalar_joins_lines(self):
        doc = LINT.parse_yaml_subset("jobs:\n  a:\n    steps:\n      - run: >\n          one\n          two\n")
        self.assertEqual("one two", doc["jobs"]["a"]["steps"][0]["run"])

    def test_comments_outside_quotes_are_stripped(self):
        doc = LINT.parse_yaml_subset('name: keep # drop\nvalue: "a # b"\n')
        self.assertEqual("keep", doc["name"])
        self.assertEqual("a # b", doc["value"])

    def test_anchors_are_refused_rather_than_mis_parsed(self):
        with self.assertRaises(ValueError):
            LINT.parse_yaml_subset("defaults: &base\n  runs-on: ubuntu-latest\njobs:\n  a: *base\n")


class ObjectIdentifierRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = FixtureRepo()
        cls.report = cls.fixture.lint()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def test_prefix_only_correct_identifier_is_detected(self):
        rows = [
            row
            for row in by_rule(self.report, "R1_UNRESOLVABLE_OBJECT_ID")
            if row["path"].endswith("prefix-only.json")
        ]
        self.assertEqual(1, len(rows), self.report["findings"])
        self.assertEqual("PREFIX_ONLY_CORRECT", rows[0]["subclass"])
        self.assertEqual(self.fixture.prefix_only, rows[0]["recorded_object_id"])
        self.assertEqual(self.fixture.first_commit, rows[0]["prefix_resolves_to"])
        self.assertEqual("error", rows[0]["severity"])

    def test_wholly_unknown_identifier_is_a_warning_not_an_error(self):
        rows = [
            row
            for row in by_rule(self.report, "R1_UNRESOLVABLE_OBJECT_ID")
            if row["path"].endswith("unknown.json")
        ]
        self.assertEqual(1, len(rows))
        self.assertEqual("UNKNOWN_OBJECT", rows[0]["subclass"])
        self.assertEqual("warning", rows[0]["severity"])
        self.assertIsNone(rows[0]["prefix_resolves_to"])

    def test_declared_external_identifier_is_informational(self):
        report = self.fixture.lint(
            external_object_ids={self.fixture.external: "github.com/example/upstream (pinned dependency)"}
        )
        rows = [
            row
            for row in by_rule(report, "R1_UNRESOLVABLE_OBJECT_ID")
            if row["path"].endswith("external.json")
        ]
        self.assertEqual(1, len(rows))
        self.assertEqual("EXTERNAL_DECLARED", rows[0]["subclass"])
        self.assertEqual("info", rows[0]["severity"])

    def test_declaring_a_prefix_correct_identifier_external_does_not_downgrade_it(self):
        """The dangerous class cannot be silenced by an allowlist entry."""
        report = self.fixture.lint(
            external_object_ids={self.fixture.prefix_only: "github.com/example/upstream (claimed external)"}
        )
        row = next(
            row
            for row in by_rule(report, "R1_UNRESOLVABLE_OBJECT_ID")
            if row["path"].endswith("prefix-only.json")
        )
        self.assertEqual("PREFIX_ONLY_CORRECT", row["subclass"])
        self.assertEqual("error", row["severity"])

    def test_external_declaration_file_requires_a_reason(self):
        with tempfile.TemporaryDirectory(prefix="wa024-external-") as tmp:
            path = Path(tmp) / "external.json"
            path.write_text(
                json.dumps({"external_object_ids": [{"object_id": "d" * 40, "repository": "x"}]}),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                LINT.load_external_object_ids(path)

    def test_external_declaration_file_rejects_a_malformed_identifier(self):
        with tempfile.TemporaryDirectory(prefix="wa024-external-bad-") as tmp:
            path = Path(tmp) / "external.json"
            path.write_text(
                json.dumps({"external_object_ids": [{"object_id": "deadbeef", "why": "short"}]}),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                LINT.load_external_object_ids(path)

    def test_committed_external_declaration_file_is_valid(self):
        declared = LINT.load_external_object_ids(
            REPO_ROOT / "workstreams/po03/wave-a/units/wa-024/harness/external-object-ids.json"
        )
        self.assertGreaterEqual(len(declared), 4)
        for reason in declared.values():
            self.assertIn("(", reason)

    def test_resolvable_identifier_is_not_flagged(self):
        self.assertEqual(
            [],
            [row for row in by_rule(self.report, "R1_UNRESOLVABLE_OBJECT_ID") if row["path"].endswith("good.json")],
        )

    def test_shallow_repository_reports_not_supported_instead_of_guessing(self):
        with tempfile.TemporaryDirectory(prefix="wa024-shallow-") as tmp:
            shallow = Path(tmp) / "shallow"
            git(
                [
                    "clone",
                    "--quiet",
                    "--depth",
                    "1",
                    self.fixture.root.resolve().as_uri(),
                    str(shallow),
                ],
                Path(tmp),
            )
            report = LINT.lint(shallow, scan_globs=("workstreams/po03/", ".github/workflows/"))
        rows = by_rule(report, "R1_UNRESOLVABLE_OBJECT_ID")
        self.assertEqual(1, len(rows))
        self.assertEqual("NOT_SUPPORTED_SHALLOW_REPOSITORY", rows[0]["subclass"])
        self.assertEqual("info", rows[0]["severity"])
        self.assertTrue(report["repository_shallow"])


class WorkflowRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = FixtureRepo()
        cls.report = cls.fixture.lint()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def test_history_dependent_command_without_full_fetch_is_flagged(self):
        rows = by_rule(self.report, "R2_HISTORY_DEPENDENT_WITHOUT_FULL_FETCH")
        paths = {row["path"] for row in rows}
        self.assertIn(".github/workflows/history.yml", paths)
        self.assertNotIn(".github/workflows/full-fetch.yml", paths)
        row = next(row for row in rows if row["path"].endswith("history.yml"))
        self.assertEqual("provenance", row["job"])
        self.assertIn("merge-base", row["commands"])

    def test_bare_interpreter_without_setup_is_a_warning(self):
        rows = by_rule(self.report, "R3_BARE_INTERPRETER_WITHOUT_SETUP")
        bare = next(row for row in rows if row["path"].endswith("bare-python.yml"))
        self.assertEqual("warning", bare["severity"])
        self.assertFalse(bare["setup_present"])
        guarded = next(row for row in rows if row["path"].endswith("setup-python.yml"))
        self.assertEqual("info", guarded["severity"])
        self.assertTrue(guarded["setup_present"])

    def test_untracked_referenced_path_is_flagged(self):
        rows = by_rule(self.report, "R5_UNTRACKED_REFERENCED_PATH")
        references = {row["reference"] for row in rows}
        self.assertIn("tools/missing_tool.py", references)
        self.assertNotIn("tools/present_tool.py", references)

    def test_host_absolute_path_is_flagged_once_and_suppression_is_honoured(self):
        rows = [row for row in by_rule(self.report, "R4_HOST_ABSOLUTE_PATH") if row["path"].endswith("host_path_tool.py")]
        self.assertEqual(1, len(rows), rows)
        self.assertEqual(1, rows[0]["line"])
        self.assertEqual("warning", rows[0]["severity"])

    def test_findings_are_ordered_deterministically(self):
        again = self.fixture.lint()
        self.assertEqual(
            json.dumps(self.report["findings"], sort_keys=True),
            json.dumps(again["findings"], sort_keys=True),
        )

    def test_exit_code_reflects_severity_threshold(self):
        args = ["--repo", str(self.fixture.root), "--json", str(self.fixture.root / "out.json")]
        self.assertEqual(1, LINT.main([*args, "--fail-on", "error"]))
        self.assertEqual(0, LINT.main([*args, "--fail-on", "never"]))


class LiveRepositoryInvariantTests(unittest.TestCase):
    """Repair-stable invariants over the real repository.

    These assert that the control is *correct* on live data, not that a
    particular defect is still present, so they keep passing after the defect is
    repaired.
    """

    @classmethod
    def setUpClass(cls):
        cls.report = LINT.lint(REPO_ROOT)

    def _resolves(self, object_id: str) -> bool:
        return (
            subprocess.run(
                ["git", "cat-file", "-e", f"{object_id}^{{object}}"],
                cwd=str(REPO_ROOT),
                capture_output=True,
            ).returncode
            == 0
        )

    def test_every_reported_identifier_is_genuinely_unresolvable(self):
        rows = [
            row
            for row in by_rule(self.report, "R1_UNRESOLVABLE_OBJECT_ID")
            if row.get("subclass") != "NOT_SUPPORTED_SHALLOW_REPOSITORY"
        ]
        for row in rows:
            with self.subTest(path=row["path"], oid=row["recorded_object_id"]):
                self.assertFalse(self._resolves(row["recorded_object_id"]))

    def test_no_unresolvable_identifier_escapes_the_control(self):
        """Independent brute-force scan must agree with the control."""
        if self.report["repository_shallow"]:
            self.skipTest("NOT_SUPPORTED: identifier integrity is unverifiable in a shallow clone")
        tracked = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD", "workstreams/po03", ".github/workflows"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        expected: set[tuple[str, str]] = set()
        for path in tracked:
            blob = subprocess.run(
                ["git", "show", f"HEAD:{path}"], cwd=str(REPO_ROOT), capture_output=True, text=True
            )
            if blob.returncode != 0:
                continue
            for oid in set(LINT.HEX40.findall(blob.stdout)):
                if not self._resolves(oid):
                    expected.add((path, oid))
        reported = {
            (row["path"], row["recorded_object_id"])
            for row in by_rule(self.report, "R1_UNRESOLVABLE_OBJECT_ID")
            if row.get("subclass") != "NOT_SUPPORTED_SHALLOW_REPOSITORY"
        }
        self.assertEqual(expected, reported)

    def test_every_repository_workflow_parses(self):
        self.assertEqual([], self.report["workflow_parse_errors"])
        self.assertGreaterEqual(self.report["workflow_count"], 2)

    def test_this_unit_hardcodes_no_host_absolute_path(self):
        """The unit must satisfy the control it introduces."""
        own = [
            row
            for row in by_rule(self.report, "R4_HOST_ABSOLUTE_PATH")
            if "wave-a/units/wa-024/" in row["path"]
        ]
        self.assertEqual([], own)


if __name__ == "__main__":
    unittest.main()
