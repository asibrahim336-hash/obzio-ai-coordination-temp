"""Focused tests for the PO03-WA-024 clean-runner differential harness.

Each hidden-local-state class the unit claims to detect is injected into a
throwaway git repository and the harness must classify it, so the harness is
tested against known ground truth rather than against the repository it happens
to be run in.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from _support import REPO_ROOT, commit_all, init_repo, load, write

PROBE = load("clean_runner_probe")

ENV_MARKER = "WA024_WARM_ONLY_MARKER"


class ProbeFixture:
    """A repository with one injected instance of each dependence class."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="wa024-probe-fixture-")
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "repo"
        init_repo(self.root)
        write(self.root, "committed.txt", "committed\n")
        self.first_commit = commit_all(self.root, "first")
        write(self.root, "second.txt", "second\n")
        self.head = commit_all(self.root, "second")

        # Local state that exists only in the warm working tree.
        write(self.root, "untracked-local.txt", "warm only\n")
        self.ambient_tmp_marker = self.tmp / "ambient-marker.txt"
        self.ambient_tmp_marker.write_text("ambient\n", encoding="utf-8")

    def close(self) -> None:
        self._tmp.cleanup()

    def probes(self) -> list[dict]:
        return [
            {
                "probe_id": "control-always-passes",
                "argv": ["PYTHON", "-c", "print('ok')"],
                "expected_classification": "AGREE",
            },
            {
                "probe_id": "control-reads-committed-file",
                "argv": ["PYTHON", "-c", "print(open('committed.txt').read())"],
                "expected_classification": "AGREE",
            },
            {
                "probe_id": "needs-untracked-local-file",
                "argv": ["PYTHON", "-c", "print(open('untracked-local.txt').read())"],
                "expected_classification": "WARM_ONLY_PASS",
            },
            {
                "probe_id": "needs-git-history",
                "argv": ["git", "merge-base", "--is-ancestor", self.first_commit, "HEAD"],
                "expected_classification": "DEPTH_SENSITIVE",
            },
            {
                "probe_id": "needs-inherited-env-var",
                "argv": ["PYTHON", "-c", f"import os,sys; sys.exit(0 if os.environ.get({ENV_MARKER!r}) else 1)"],
                "expected_classification": "WARM_ONLY_PASS",
            },
            {
                "probe_id": "needs-ambient-tmpdir-file",
                "argv": [
                    "PYTHON",
                    "-c",
                    "import os,sys,tempfile; "
                    "sys.exit(0 if os.path.exists(os.path.join(tempfile.gettempdir(),'ambient-marker.txt')) else 1)",
                ],
                "expected_classification": "WARM_ONLY_PASS",
            },
            {
                "probe_id": "mutates-the-worktree",
                "argv": ["PYTHON", "-c", "open('generated.txt','w').write('x')"],
                "expected_classification": "AGREE",
                "expect_worktree_mutation": True,
            },
        ]

    def run(self, **kwargs: object) -> dict:
        return PROBE.probe_repository(self.root, self.probes(), commit=self.head, **kwargs)


class TreeMaterialisationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = ProbeFixture()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def test_full_clone_carries_history_and_no_untracked_state(self):
        with tempfile.TemporaryDirectory(prefix="wa024-full-") as tmp:
            info = PROBE.materialise_clean(
                self.fixture.root, self.fixture.head, "HEAD", Path(tmp) / "tree", None
            )
        self.assertFalse(info["shallow"])
        self.assertEqual(2, info["commits_present"])
        self.assertEqual(self.fixture.head, info["head"])

    def test_depth_one_clone_matches_default_actions_checkout(self):
        with tempfile.TemporaryDirectory(prefix="wa024-shallow-") as tmp:
            tree = Path(tmp) / "tree"
            info = PROBE.materialise_clean(self.fixture.root, self.fixture.head, "HEAD", tree, 1)
            self.assertTrue(info["shallow"])
            self.assertEqual(1, info["commits_present"])
            self.assertFalse((tree / "untracked-local.txt").exists())

    def test_specific_commit_is_fetchable_by_object_id(self):
        with tempfile.TemporaryDirectory(prefix="wa024-by-id-") as tmp:
            info = PROBE.materialise_clean(
                self.fixture.root, self.fixture.first_commit, "HEAD", Path(tmp) / "tree", 1
            )
        self.assertEqual("commit", info["fetch_strategy"])
        self.assertEqual(self.fixture.first_commit, info["head"])

    def test_unfetchable_commit_falls_back_to_the_ref_and_is_then_refused(self):
        """The ref fallback must never let a mismatched tree be probed silently."""
        absent = "0" * 39 + "1"
        with tempfile.TemporaryDirectory(prefix="wa024-mismatch-") as tmp:
            with self.assertRaises(PROBE.ProbeError) as caught:
                PROBE.materialise_clean(self.fixture.root, absent, "HEAD", Path(tmp) / "tree", 1)
        self.assertIn("does not match requested commit", str(caught.exception))


class ScrubbedEnvironmentTests(unittest.TestCase):
    def test_inherited_variables_are_dropped_and_runner_variables_set(self):
        os.environ["WA024_LEAK_CHECK"] = "leaked"
        os.environ["PYTHONPATH"] = "/should/not/survive"
        try:
            env = PROBE.scrubbed_env(Path("/tree"), Path("/home"), Path("/tmpdir"))
        finally:
            os.environ.pop("WA024_LEAK_CHECK", None)
            os.environ.pop("PYTHONPATH", None)
        self.assertNotIn("WA024_LEAK_CHECK", env)
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("PYTHONDONTWRITEBYTECODE", env)
        self.assertEqual("/home", env["HOME"])
        self.assertEqual("/tmpdir", env["TMPDIR"])
        self.assertEqual("/tree", env["GITHUB_WORKSPACE"])
        self.assertEqual("true", env["GITHUB_ACTIONS"])
        self.assertIn("PATH", env)


class ClassificationUnitTests(unittest.TestCase):
    @staticmethod
    def _results(warm: str, full: str, shallow: str, mutated: bool = False) -> dict:
        return {
            "warm": {"outcome": warm, "worktree_mutated": mutated},
            "clean_full": {"outcome": full, "worktree_mutated": mutated},
            "clean_shallow": {"outcome": shallow, "worktree_mutated": mutated},
        }

    def test_uniform_outcomes_agree(self):
        self.assertEqual(PROBE.CLASS_AGREE, PROBE.classify(self._results("PASS", "PASS", "PASS"))[0])
        self.assertEqual(PROBE.CLASS_AGREE, PROBE.classify(self._results("FAIL", "FAIL", "FAIL"))[0])

    def test_warm_only_pass_names_hidden_local_state(self):
        classification, findings = PROBE.classify(self._results("PASS", "FAIL", "FAIL"))
        self.assertEqual(PROBE.CLASS_WARM_ONLY_PASS, classification)
        self.assertIn("HIDDEN_LOCAL_STATE_DEPENDENCE", findings)

    def test_depth_sensitive_names_shallow_history(self):
        classification, findings = PROBE.classify(self._results("PASS", "PASS", "FAIL"))
        self.assertEqual(PROBE.CLASS_DEPTH_SENSITIVE, classification)
        self.assertIn("SHALLOW_HISTORY_DEPENDENCE", findings)

    def test_clean_only_pass_is_distinguished(self):
        self.assertEqual(
            PROBE.CLASS_CLEAN_ONLY_PASS, PROBE.classify(self._results("FAIL", "PASS", "PASS"))[0]
        )

    def test_mutation_is_reported_per_mode(self):
        _, findings = PROBE.classify(self._results("PASS", "PASS", "PASS", mutated=True))
        self.assertEqual(
            [
                "WORKTREE_MUTATED_BY_WORKLOAD:clean_full",
                "WORKTREE_MUTATED_BY_WORKLOAD:clean_shallow",
                "WORKTREE_MUTATED_BY_WORKLOAD:warm",
            ],
            findings,
        )


class DifferentialDetectionTests(unittest.TestCase):
    """End-to-end: every injected dependence class must be classified correctly."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = ProbeFixture()
        os.environ[ENV_MARKER] = "present-in-warm-environment"
        # tempfile.gettempdir() honours TMPDIR, so the ambient marker is visible
        # to the warm run and invisible to the scrubbed clean runs.
        cls._saved_tmpdir = os.environ.get("TMPDIR")
        os.environ["TMPDIR"] = str(cls.fixture.tmp)
        try:
            cls.report = cls.fixture.run()
        finally:
            os.environ.pop(ENV_MARKER, None)
            if cls._saved_tmpdir is None:
                os.environ.pop("TMPDIR", None)
            else:
                os.environ["TMPDIR"] = cls._saved_tmpdir

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def row(self, probe_id: str) -> dict:
        return next(row for row in self.report["probes"] if row["probe_id"] == probe_id)

    def test_every_declared_expectation_is_met(self):
        unmet = [
            (row["probe_id"], row["expected_classification"], row["classification"])
            for row in self.report["probes"]
            if row["expectation_met"] is False
        ]
        self.assertEqual([], unmet)

    def test_untracked_file_dependence_is_exposed_only_by_the_clean_runs(self):
        row = self.row("needs-untracked-local-file")
        self.assertEqual("PASS", row["observed_outcomes"]["warm"])
        self.assertEqual("FAIL", row["observed_outcomes"]["clean_full"])
        self.assertEqual("FAIL", row["observed_outcomes"]["clean_shallow"])
        self.assertIn("HIDDEN_LOCAL_STATE_DEPENDENCE", row["findings"])

    def test_history_dependence_is_exposed_only_by_the_shallow_run(self):
        row = self.row("needs-git-history")
        self.assertEqual("PASS", row["observed_outcomes"]["clean_full"])
        self.assertEqual("FAIL", row["observed_outcomes"]["clean_shallow"])
        self.assertIn("SHALLOW_HISTORY_DEPENDENCE", row["findings"])

    def test_inherited_environment_dependence_is_exposed(self):
        row = self.row("needs-inherited-env-var")
        self.assertEqual(PROBE.CLASS_WARM_ONLY_PASS, row["classification"])

    def test_ambient_tmpdir_dependence_is_exposed(self):
        row = self.row("needs-ambient-tmpdir-file")
        self.assertEqual(PROBE.CLASS_WARM_ONLY_PASS, row["classification"])

    def test_controls_do_not_produce_false_positives(self):
        for probe_id in ("control-always-passes", "control-reads-committed-file"):
            with self.subTest(probe=probe_id):
                row = self.row(probe_id)
                self.assertEqual(PROBE.CLASS_AGREE, row["classification"])
                self.assertEqual([], row["findings"])

    def test_worktree_mutation_is_detected_and_matched_against_expectation(self):
        row = self.row("mutates-the-worktree")
        self.assertTrue(row["mutation_expectation_met"])
        self.assertIn("mutates-the-worktree", self.report["summary"]["worktree_mutating_probes"])

    def test_report_leaks_no_host_filesystem_path(self):
        payload = json.dumps(self.report)
        self.assertNotIn(str(self.fixture.tmp), payload)
        self.assertNotIn(str(self.fixture.root), payload)

    def test_redaction_replaces_sandbox_and_repository_roots(self):
        node = {"a": "/sandbox/x/tree", "b": ["/repo/file", 3, None]}
        redacted = PROBE.redact_tree(node, {"/sandbox": "<SANDBOX>", "/repo": "<REPO>"})
        self.assertEqual({"a": "<SANDBOX>/x/tree", "b": ["<REPO>/file", 3, None]}, redacted)

    def test_binding_and_advisory_failures_are_accounted_separately(self):
        summary = self.report["summary"]
        self.assertEqual([], summary["binding_expectation_failures"])
        self.assertEqual([], summary["advisory_expectation_failures"])


class DeclaredProbeSetTests(unittest.TestCase):
    """The committed probe set must stay loadable and internally consistent."""

    def setUp(self):
        self.path = REPO_ROOT / "workstreams/po03/wave-a/units/wa-024/harness/probes.json"
        self.probes = PROBE.load_probes(self.path)

    def test_probe_ids_are_unique_and_ordered(self):
        ids = [probe["probe_id"] for probe in self.probes]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, sorted(ids))

    def test_every_probe_declares_a_hypothesis_and_a_workload(self):
        for probe in self.probes:
            with self.subTest(probe=probe["probe_id"]):
                self.assertTrue(probe["hypothesis_ids"])
                self.assertTrue(probe["workload"].strip())
                self.assertIn("role", probe)

    def test_declared_hypotheses_exist_in_the_frozen_register(self):
        register = json.loads(
            (
                REPO_ROOT / "workstreams/po03/wave-a/units/wa-024/hypotheses/hypotheses.json"
            ).read_text(encoding="utf-8")
        )
        known = {row["hypothesis_id"] for row in register["hypotheses"]}
        for probe in self.probes:
            for hypothesis_id in probe["hypothesis_ids"]:
                with self.subTest(probe=probe["probe_id"], hypothesis=hypothesis_id):
                    self.assertIn(hypothesis_id, known)

    def test_every_hypothesis_names_declared_probes_and_every_probe_is_claimed(self):
        register = json.loads(
            (
                REPO_ROOT / "workstreams/po03/wave-a/units/wa-024/hypotheses/hypotheses.json"
            ).read_text(encoding="utf-8")
        )
        declared = {probe["probe_id"] for probe in self.probes}
        claimed: set[str] = set()
        for row in register["hypotheses"]:
            for probe_id in row["measured_by"]:
                with self.subTest(hypothesis=row["hypothesis_id"], probe=probe_id):
                    self.assertIn(probe_id, declared)
                claimed.add(probe_id)
        self.assertEqual(set(), declared - claimed)

    def test_hypothesis_count_matches_its_own_tally(self):
        register = json.loads(
            (
                REPO_ROOT / "workstreams/po03/wave-a/units/wa-024/hypotheses/hypotheses.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(register["counted_current_method_hypotheses"], len(register["hypotheses"]))
        self.assertGreaterEqual(len(register["hypotheses"]), register["minimum_required_by_input"])
        for row in register["hypotheses"]:
            with self.subTest(hypothesis=row["hypothesis_id"]):
                self.assertTrue(row["refutation_condition"].strip())
                self.assertTrue(row["derived_from_source_claims"])

    def test_declared_hypotheses_cite_recorded_source_claims(self):
        unit = REPO_ROOT / "workstreams/po03/wave-a/units/wa-024"
        claims = json.loads((unit / "sources/source-claims.json").read_text(encoding="utf-8"))
        known = {row["claim_id"] for row in claims["external_claims"]} | {
            row["claim_id"] for row in claims["repository_claims"]
        }
        register = json.loads((unit / "hypotheses/hypotheses.json").read_text(encoding="utf-8"))
        for row in register["hypotheses"]:
            for claim_id in row["derived_from_source_claims"]:
                with self.subTest(hypothesis=row["hypothesis_id"], claim=claim_id):
                    self.assertIn(claim_id, known)

    def test_every_source_capsule_referenced_by_a_claim_exists(self):
        unit = REPO_ROOT / "workstreams/po03/wave-a/units/wa-024"
        claims = json.loads((unit / "sources/source-claims.json").read_text(encoding="utf-8"))
        for row in claims["external_claims"]:
            capsule = unit / row["capsule"]
            with self.subTest(claim=row["claim_id"]):
                self.assertTrue(capsule.is_file(), capsule)
                text = capsule.read_text(encoding="utf-8")
                self.assertIn(row["immutable_commit"], text)
                self.assertIn(row["url"], text)
                if "retrieved_sha256" in row:
                    self.assertIn(row["retrieved_sha256"], text)

    def test_duplicate_probe_ids_are_refused(self):
        with tempfile.TemporaryDirectory(prefix="wa024-dupe-") as tmp:
            path = Path(tmp) / "probes.json"
            path.write_text(
                json.dumps({"probes": [{"probe_id": "x", "argv": ["true"]}, {"probe_id": "x", "argv": ["true"]}]}),
                encoding="utf-8",
            )
            with self.assertRaises(PROBE.ProbeError):
                PROBE.load_probes(path)


if __name__ == "__main__":
    unittest.main()
