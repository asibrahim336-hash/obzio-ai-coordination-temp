"""Tests for the wave-a-003 pointer-driven currentness compiler.

The suite is dependency-free and hermetic: every synthetic estate is a fresh
Git repository, and the live-repository assertions read only immutable commits.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = UNIT_ROOT.parents[4]
COMPILER_PATH = UNIT_ROOT / "tools" / "currentness_compiler.py"
RUNNER_PATH = UNIT_ROOT / "tools" / "run_cases.py"
CASES_PATH = UNIT_ROOT / "fixtures" / "synthetic" / "cases.json"
LIVE_SPEC_PATH = "workstreams/po03/attempts/wave-a/wave-a-003-currentness-compiler/fixtures/spec/currentness.spec.json"


def _load(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


COMPILER = _load("currentness_compiler", COMPILER_PATH)
RUNNER = _load("run_cases", RUNNER_PATH)
COUNTERFACTUAL = _load("counterfactual", UNIT_ROOT / "tools" / "counterfactual.py")
READBACK = _load("readback", UNIT_ROOT / "tools" / "readback.py")
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))


class SyntheticCaseMatrixTests(unittest.TestCase):
    """Each frozen synthetic case must reproduce its recorded expectation."""

    def test_every_case_matches_its_frozen_expectation(self):
        for case in CASES["cases"]:
            with self.subTest(case=case["case_id"]):
                with tempfile.TemporaryDirectory(prefix="po03-wa003-") as directory:
                    root = Path(directory)
                    commit = RUNNER.materialize_case(root, case, CASES["base_spec"])
                    report = COMPILER.compile_currentness(
                        repository=str(root),
                        revision=commit,
                        spec_path=RUNNER.SYNTHETIC_SPEC_PATH,
                    )
                    self.assertEqual(RUNNER.check_case(report, case["expect"]), [])

    def test_case_matrix_covers_the_documented_gate_rules(self):
        identifiers = {case["case_id"] for case in CASES["cases"]}
        self.assertEqual(len(identifiers), len(CASES["cases"]))
        for required in (
            "superseded-pointer-exclusion",
            "superseded-reached-by-active-role",
            "standing-substring-is-not-supersession",
            "lineage-role-names-superseded-target",
            "declared-absence-is-preserved-evidence",
            "active-role-naming-absent-object",
            "routing-pointer-cycle",
            "ambiguous-single-valued-role",
        ):
            self.assertIn(required, identifiers)

    def test_runner_reports_all_cases_passing(self):
        summary = RUNNER.run_cases()
        self.assertEqual(summary["failed"], 0, summary)
        self.assertEqual(summary["passed"], len(CASES["cases"]))


class CompilerUnitTests(unittest.TestCase):
    def _repository(self, case_id: str):
        case = next(item for item in CASES["cases"] if item["case_id"] == case_id)
        directory = tempfile.TemporaryDirectory(prefix="po03-wa003-unit-")
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        commit = RUNNER.materialize_case(root, case, CASES["base_spec"])
        return root, commit

    def test_superseded_pointer_never_enters_the_current_set(self):
        root, commit = self._repository("superseded-pointer-exclusion")
        report = COMPILER.compile_currentness(
            repository=str(root), revision=commit, spec_path=RUNNER.SYNTHETIC_SPEC_PATH
        )
        self.assertEqual(report["gate"], "PASS")
        self.assertIn("old.json", report["retained_superseded_set"])
        self.assertNotIn("old.json", report["current_source_set"])
        node = next(item for item in report["nodes"] if item["path"] == "old.json")
        self.assertEqual(node["classification"], "RETAINED_SUPERSEDED_EVIDENCE")
        self.assertIn("pointer_key:superseded_pointer", node["supersession_signals"])

    def test_superseded_subtree_is_not_expanded_into_launch_surfaces(self):
        root, commit = self._repository("superseded-pointer-exclusion")
        (root / "old.json").write_text(
            json.dumps({"selected_pointer": {"path": "hidden.json", "standing": "CURRENT_ACTIVE"}}),
            encoding="utf-8",
        )
        (root / "hidden.json").write_text(json.dumps({"note": "should stay unreachable"}), encoding="utf-8")
        subprocess.run(("git", "-C", str(root), "add", "-A"), check=True, capture_output=True)
        subprocess.run(
            ("git", "-C", str(root), "commit", "-q", "-m", "extend superseded subtree"),
            check=True,
            capture_output=True,
        )
        head = subprocess.run(
            ("git", "-C", str(root), "rev-parse", "HEAD"), check=True, capture_output=True, text=True
        ).stdout.strip()
        report = COMPILER.compile_currentness(
            repository=str(root), revision=head, spec_path=RUNNER.SYNTHETIC_SPEC_PATH
        )
        self.assertEqual(report["gate"], "PASS")
        self.assertNotIn("hidden.json", report["current_source_set"])
        self.assertEqual([node["path"] for node in report["nodes"] if node["path"] == "hidden.json"], [])

    def test_result_is_pinned_to_the_commit_not_the_worktree(self):
        root, commit = self._repository("superseded-pointer-exclusion")
        first = COMPILER.compile_currentness(
            repository=str(root), revision=commit, spec_path=RUNNER.SYNTHETIC_SPEC_PATH
        )
        (root / "pointer.json").write_text(
            json.dumps({"selected_pointer": {"path": "old.json", "standing": "CURRENT_ACTIVE"}}),
            encoding="utf-8",
        )
        (root / "current.json").unlink()
        second = COMPILER.compile_currentness(
            repository=str(root), revision=commit, spec_path=RUNNER.SYNTHETIC_SPEC_PATH
        )
        self.assertEqual(first["determinism_digest"], second["determinism_digest"])

    def test_compilation_is_deterministic_across_repeated_runs(self):
        root, commit = self._repository("lineage-role-names-superseded-target")
        digests = {
            COMPILER.compile_currentness(
                repository=str(root), revision=commit, spec_path=RUNNER.SYNTHETIC_SPEC_PATH
            )["determinism_digest"]
            for _ in range(3)
        }
        self.assertEqual(len(digests), 1)

    def test_spec_must_be_a_supported_version(self):
        root, commit = self._repository("superseded-pointer-exclusion")
        (root / RUNNER.SYNTHETIC_SPEC_PATH).write_text(json.dumps({"spec_version": "OTHER"}), encoding="utf-8")
        subprocess.run(("git", "-C", str(root), "add", "-A"), check=True, capture_output=True)
        subprocess.run(
            ("git", "-C", str(root), "commit", "-q", "-m", "break spec"), check=True, capture_output=True
        )
        head = subprocess.run(
            ("git", "-C", str(root), "rev-parse", "HEAD"), check=True, capture_output=True, text=True
        ).stdout.strip()
        with self.assertRaises(COMPILER.CompilerError):
            COMPILER.compile_currentness(
                repository=str(root), revision=head, spec_path=RUNNER.SYNTHETIC_SPEC_PATH
            )
        # The earlier commit still compiles, so a later defect cannot rewrite history.
        self.assertEqual(
            COMPILER.compile_currentness(
                repository=str(root), revision=commit, spec_path=RUNNER.SYNTHETIC_SPEC_PATH
            )["gate"],
            "PASS",
        )

    def test_absent_spec_is_reported_as_a_compiler_error(self):
        root, commit = self._repository("superseded-pointer-exclusion")
        with self.assertRaises(COMPILER.CompilerError):
            COMPILER.compile_currentness(
                repository=str(root), revision=commit, spec_path="spec/does-not-exist.json"
            )

    def test_cli_exit_codes_separate_pass_fail_and_usage(self):
        passing_root, passing_commit = self._repository("superseded-pointer-exclusion")
        failing_root, failing_commit = self._repository("routing-pointer-cycle")
        self.assertEqual(
            COMPILER.main(
                [
                    "--repository",
                    str(passing_root),
                    "--commit",
                    passing_commit,
                    "--spec",
                    RUNNER.SYNTHETIC_SPEC_PATH,
                    "--quiet",
                ]
            ),
            COMPILER.EXIT_PASS,
        )
        self.assertEqual(
            COMPILER.main(
                [
                    "--repository",
                    str(failing_root),
                    "--commit",
                    failing_commit,
                    "--spec",
                    RUNNER.SYNTHETIC_SPEC_PATH,
                    "--quiet",
                ]
            ),
            COMPILER.EXIT_GATE_FAIL,
        )
        self.assertEqual(
            COMPILER.main(
                [
                    "--repository",
                    str(passing_root),
                    "--commit",
                    passing_commit,
                    "--spec",
                    "spec/does-not-exist.json",
                    "--quiet",
                ]
            ),
            COMPILER.EXIT_USAGE,
        )


class HelperUnitTests(unittest.TestCase):
    def test_entrypoint_section_is_scoped_to_its_heading(self):
        text = (
            "# Title\n\n## Read in this order\n\n1. `a.json`\n\n"
            "## Other section\n\n- `b.json`\n"
        )
        self.assertEqual(COMPILER.entrypoint_references(text, "Read in this order"), ["a.json"])

    def test_role_skips_generic_locator_keys(self):
        self.assertEqual(COMPILER._role_of(("selected_pointer", "path")), "selected_pointer")
        self.assertEqual(COMPILER._role_of(("historical_defects", "[0]", "expected_path")), "expected_path")
        self.assertEqual(COMPILER._role_of(("path",)), "path")

    def test_only_extension_bearing_paths_count_as_broken_references(self):
        self.assertTrue(COMPILER.looks_like_repository_file("dispatch/MISSING_v008.md"))
        self.assertFalse(COMPILER.looks_like_repository_file("PROVIDER_COMPLETED_UNCOMMITTED"))
        self.assertFalse(COMPILER.looks_like_repository_file("state/operator-system"))

    def test_disposition_rows_split_resolved_and_unresolved_objects(self):
        text = (
            "| Object/class | Disposition | Treatment |\n"
            "|---|---|---|\n"
            "| `state/OLD.json` | SUPERSEDED / RETAIN EVIDENCE | keep |\n"
            "| v009 payload family | SUPERSEDED / UNSENT | keep |\n"
        )
        rows = COMPILER.disposition_rows(text)
        self.assertEqual([row["paths"] for row in rows], [["state/OLD.json"], []])


class ReadbackVerifierTests(unittest.TestCase):
    """The read-back verifier must accept honest bytes and reject tampering."""

    def _unit_repository(self):
        directory = tempfile.TemporaryDirectory(prefix="po03-wa003-readback-")
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for command in (
            ("init", "-q"),
            ("config", "user.email", "po03-wave-a-003@obzio.invalid"),
            ("config", "user.name", "PO-03 wave-a-003 readback test"),
            ("config", "commit.gpgsign", "false"),
        ):
            subprocess.run(("git", "-C", str(root), *command), check=True, capture_output=True)
        (root / "seed.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(("git", "-C", str(root), "add", "-A"), check=True, capture_output=True)
        subprocess.run(
            ("git", "-C", str(root), "commit", "-q", "-m", "base"), check=True, capture_output=True
        )
        base = subprocess.run(
            ("git", "-C", str(root), "rev-parse", "HEAD"), check=True, capture_output=True, text=True
        ).stdout.strip()
        unit = root / READBACK.UNIT_ROOT
        unit.mkdir(parents=True)
        payload = b"artifact bytes\n"
        (unit / "artifact.txt").write_bytes(payload)
        return root, base, unit, payload

    def _commit(self, root: Path, message: str) -> str:
        subprocess.run(("git", "-C", str(root), "add", "-A"), check=True, capture_output=True)
        subprocess.run(
            ("git", "-C", str(root), "commit", "-q", "-m", message), check=True, capture_output=True
        )
        return subprocess.run(
            ("git", "-C", str(root), "rev-parse", "HEAD"), check=True, capture_output=True, text=True
        ).stdout.strip()

    def _manifest(self, payload: bytes, **overrides):
        manifest = {
            "manifest_version": "PO03-ATTEMPT-MANIFEST-v1",
            "task_id": READBACK.TASK_ID,
            "unit_root": READBACK.UNIT_ROOT,
            "self_excluded": "manifest.json",
            "artifact_count": 1,
            "total_bytes": len(payload),
            "sources": [
                {
                    "path": "artifact.txt",
                    "sha256": __import__("hashlib").sha256(payload).hexdigest(),
                    "bytes": len(payload),
                    "git_blob_sha": READBACK.git_blob_sha(payload),
                }
            ],
            "decision_changed": [],
        }
        manifest.update(overrides)
        return manifest

    def test_honest_manifest_and_range_pass(self):
        root, base, unit, payload = self._unit_repository()
        (unit / "manifest.json").write_text(json.dumps(self._manifest(payload)), encoding="utf-8")
        commit = self._commit(root, "result")
        report = READBACK.verify(repository=str(root), commit=commit, base=base)
        self.assertEqual(report["outcome"], "PASS", report["failures"])
        self.assertEqual(report["verified_artifact_count"], 1)
        self.assertEqual(report["changed_paths_outside_owned_subtree"], [])

    def test_tampered_hash_is_rejected(self):
        root, base, unit, payload = self._unit_repository()
        manifest = self._manifest(payload)
        manifest["sources"][0]["sha256"] = "0" * 64
        (unit / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        commit = self._commit(root, "tampered")
        report = READBACK.verify(repository=str(root), commit=commit, base=base)
        self.assertEqual(report["outcome"], "FAIL")
        self.assertTrue(any("sha256 mismatch" in failure for failure in report["failures"]))

    def test_change_outside_the_owned_subtree_is_rejected(self):
        root, base, unit, payload = self._unit_repository()
        (unit / "manifest.json").write_text(json.dumps(self._manifest(payload)), encoding="utf-8")
        (root / "outside.txt").write_text("foreign change\n", encoding="utf-8")
        commit = self._commit(root, "result with foreign path")
        report = READBACK.verify(repository=str(root), commit=commit, base=base)
        self.assertEqual(report["outcome"], "FAIL")
        self.assertIn("outside.txt", report["changed_paths_outside_owned_subtree"])

    def test_undeclared_owned_path_is_rejected(self):
        root, base, unit, payload = self._unit_repository()
        (unit / "manifest.json").write_text(json.dumps(self._manifest(payload)), encoding="utf-8")
        (unit / "undeclared.txt").write_text("not in the manifest\n", encoding="utf-8")
        commit = self._commit(root, "result with undeclared artifact")
        report = READBACK.verify(repository=str(root), commit=commit, base=base)
        self.assertEqual(report["outcome"], "FAIL")
        self.assertTrue(any("undeclared" in failure for failure in report["failures"]))


class LiveRepositoryTests(unittest.TestCase):
    """Compile the real instruction estate from the current immutable commit."""

    @classmethod
    def setUpClass(cls):
        cls.head = subprocess.run(
            ("git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        cls.report = COMPILER.compile_currentness(
            repository=str(REPOSITORY_ROOT), revision=cls.head, spec_path=LIVE_SPEC_PATH
        )

    def test_live_estate_compiles_without_gate_violations(self):
        self.assertEqual(self.report["gate"], "PASS", self.report["violations"])

    def test_live_current_set_contains_the_active_pointer_chain(self):
        for path in (
            "operations/README.md",
            "state/ACTIVE_CONTROL_POINTER_CURRENT.json",
            "state/ACTIVE_CONTROL_POINTER_20260819_02.json",
            "state/operator-system/ACTIVE_INSTRUCTION_STACK.json",
            "instructions/functions/strategic-operations-orchestration/CURRENT.md",
        ):
            self.assertIn(path, self.report["current_source_set"])

    def test_live_superseded_pointer_is_excluded_from_the_current_set(self):
        self.assertIn("state/ACTIVE_CONTROL_POINTER_20260819_01.json", self.report["retained_superseded_set"])
        self.assertNotIn("state/ACTIVE_CONTROL_POINTER_20260819_01.json", self.report["current_source_set"])

    def test_live_v010_payload_survives_a_supersession_mentioning_standing(self):
        payload = "dispatch/CLAUDE_CHROME_FULL_SCALE_CHATGPT_ACCOUNT_OPERATION_SUCCESSOR_20260819_v010.md"
        self.assertIn(payload, self.report["current_source_set"])
        self.assertEqual(
            [item["target"] for item in self.report["substring_near_misses"]],
            [payload],
        )

    def test_live_missing_v008_object_stays_declared_absence_evidence(self):
        self.assertEqual(self.report["missing_references"], [])
        absent = {item["target"] for item in self.report["declared_absent_objects"]}
        self.assertIn("dispatch/CLAUDE_EXTENSION_LAUNCH_ROUTE_20260818_v008.md", absent)

    def test_every_hardening_rule_changes_the_live_verdict(self):
        spec = json.loads((REPOSITORY_ROOT / LIVE_SPEC_PATH).read_text(encoding="utf-8"))
        summary = COUNTERFACTUAL.evaluate(self.report, spec["single_valued_roles"])
        self.assertEqual(summary["rules_defended_by_measurement"], summary["rules_evaluated"])
        for variant in summary["variants"]:
            with self.subTest(variant=variant["variant"]):
                self.assertTrue(variant["changes_verdict"], variant)

    def test_naive_substring_rule_would_drop_the_current_payload(self):
        spec = json.loads((REPOSITORY_ROOT / LIVE_SPEC_PATH).read_text(encoding="utf-8"))
        variant = COUNTERFACTUAL.naive_substring_supersession(self.report)
        self.assertIn(
            "dispatch/CLAUDE_CHROME_FULL_SCALE_CHATGPT_ACCOUNT_OPERATION_SUCCESSOR_20260819_v010.md",
            variant["false_exclusions"],
        )
        self.assertEqual(
            COUNTERFACTUAL.naive_leaf_key_roles(self.report, spec["single_valued_roles"])[
                "single_valued_roles_detected_naively"
            ],
            [],
        )


if __name__ == "__main__":
    unittest.main()
