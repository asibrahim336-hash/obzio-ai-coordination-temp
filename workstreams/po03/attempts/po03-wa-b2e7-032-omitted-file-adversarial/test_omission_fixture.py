#!/usr/bin/env python3
"""Tests for the adversarial omission fixture and the residual coverage check.

The fixture's own claim is that omission is refused, so the thing most worth
testing is whether the fixture could tell if it were not.  Three properties are
therefore asserted about the fixture itself: its controls pass, so "everything
was refused" is not merely a verifier that refuses everything; its attacks really
omit a file, so a scenario cannot be a no-op dressed as an attack; and a verifier
that stops rejecting makes the fixture diverge rather than stay green.

The residual check is tested against cases where it must fire and cases where it
must stay silent, including the two omissions the existing verifiers cannot see,
and against this repository's own manifested slots.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = UNIT_ROOT.parents[3]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = load(UNIT_ROOT / "omission_fixture.py", "po03_omission_fixture")
residual = load(UNIT_ROOT / "residual_coverage.py", "po03_residual_coverage")


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments), cwd=repo, check=True, capture_output=True, text=True
    ).stdout


class FixtureBehaviourTests(unittest.TestCase):
    """The fixture must be able to tell that it is measuring something."""

    @classmethod
    def setUpClass(cls):
        cls.holder = Path(tempfile.mkdtemp(prefix="po03-032-fixture-"))
        cls.scenarios = (
            fixture.emitter_scenarios(cls.holder / "emitter")
            + fixture.auditor_scenarios(cls.holder / "auditor")
            + fixture.manifest_tool_scenarios(cls.holder / "tool")
        )

    @classmethod
    def tearDownClass(cls):
        subprocess.run(("rm", "-rf", str(cls.holder)), check=False)

    def test_every_scenario_behaved_as_declared(self):
        diverged = [s.name for s in self.scenarios if not s.as_declared]
        self.assertEqual(diverged, [], f"scenarios diverged from their declared exit: {diverged}")

    def test_controls_exist_and_pass(self):
        controls = [s for s in self.scenarios if s.name.startswith("control-")]
        self.assertGreaterEqual(len(controls), 2, "without controls, rejection is unmeasured")
        for control in controls:
            self.assertEqual(control.expected_exit, 0)
            self.assertEqual(control.actual_exit, 0, f"{control.name} refused a valid manifest")

    def test_the_attacks_outnumber_the_controls(self):
        rejecting = [s for s in self.scenarios if s.expected_exit != 0]
        self.assertGreater(len(rejecting), len(
            [s for s in self.scenarios if s.expected_exit == 0]
        ))

    def test_more_than_one_verifier_is_attacked(self):
        targets = {s.target for s in self.scenarios}
        self.assertGreaterEqual(len(targets), 3, f"only these targets were attacked: {targets}")

    def test_the_self_consistent_omission_is_among_the_attacks(self):
        # The whole point of the unit: an omission whose manifest agrees with
        # itself, catchable only by enumerating the repository.
        names = {s.name for s in self.scenarios}
        self.assertIn("entry-omitted-manifest-fully-self-consistent", names)
        self.assertIn("line-omitted-trailer-adjusted-to-match", names)

    def test_known_gaps_are_labelled_rather_than_reported_as_refusals(self):
        gaps = [s for s in self.scenarios if s.gap]
        self.assertTrue(gaps, "the fixture found no generation-time gap to report")
        for gap in gaps:
            self.assertEqual(
                gap.expected_exit, 0,
                f"{gap.name} is recorded as a gap, so it must declare that it was not refused",
            )

    def test_a_scenario_whose_verifier_stops_rejecting_is_flagged(self):
        # Directly exercises the comparison the fixture's verdict rests on.
        honest = fixture.Scenario("probe", "t", 1, 1, "m", "o")
        vacuous = fixture.Scenario("probe", "t", 1, 0, "m", "o")
        self.assertTrue(honest.as_declared)
        self.assertFalse(vacuous.as_declared)


class AttackRealityTests(unittest.TestCase):
    """An attack that omits nothing would prove nothing."""

    @classmethod
    def setUpClass(cls):
        cls.holder = Path(tempfile.mkdtemp(prefix="po03-032-reality-"))
        cls.scratch = fixture.Scratch(cls.holder / "repo")
        if cls.scratch.emit().returncode != 0:
            raise unittest.SkipTest("could not emit a baseline manifest")
        cls.manifest = json.loads((cls.scratch.slot / "manifest.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        subprocess.run(("rm", "-rf", str(cls.holder)), check=False)

    def test_the_baseline_manifest_really_covers_every_committed_file(self):
        present = [
            path for path in self.scratch.committed_slot_files()
            if Path(path).name not in ("manifest.json", "result.json")
        ]
        covered = {entry["logical_name"] for entry in self.manifest["artifacts"]}
        self.assertEqual({Path(p).name for p in present}, covered)
        self.assertEqual(self.manifest["artifact_count"], len(present))

    def test_dropping_an_entry_really_removes_coverage_of_a_real_file(self):
        mutated = copy.deepcopy(self.manifest)
        dropped = mutated["artifacts"].pop(0)
        covered = {entry["logical_name"] for entry in mutated["artifacts"]}
        self.assertNotIn(dropped["logical_name"], covered)
        # The dropped file must still exist in the commit, or the "omission" is
        # just a manifest describing a file that was never there.
        body = subprocess.run(
            ("git", "cat-file", "blob",
             f"{self.scratch.artifact_commit}:{self.scratch.slot.name}/{dropped['logical_name']}"),
            cwd=self.scratch.root, capture_output=True,
        )
        listing = self.scratch.committed_slot_files()
        self.assertTrue(
            any(path.endswith(dropped["logical_name"]) for path in listing),
            "the omitted entry named a file the commit does not hold",
        )
        self.assertGreater(dropped["bytes"], 0)
        del body

    def test_the_self_consistent_mutation_leaves_no_internal_contradiction(self):
        mutated = copy.deepcopy(self.manifest)
        dropped = mutated["artifacts"].pop(0)
        mutated["artifact_count"] -= 1
        mutated["total_bytes"] -= dropped["bytes"]
        # This is what makes the attack hard: every internal cross-check agrees.
        self.assertEqual(mutated["artifact_count"], len(mutated["artifacts"]))
        self.assertEqual(
            mutated["total_bytes"], sum(entry["bytes"] for entry in mutated["artifacts"])
        )


class ResidualCoverageTests(unittest.TestCase):
    """The residual check must fire on uncovered bytes and stay silent otherwise."""

    def setUp(self):
        self.holder = Path(tempfile.mkdtemp(prefix="po03-032-residual-"))
        self.addCleanup(lambda: subprocess.run(("rm", "-rf", str(self.holder)), check=False))
        self.scratch = fixture.Scratch(self.holder / "repo")
        if self.scratch.emit().returncode != 0:
            self.skipTest("could not emit a baseline manifest")
        self.scratch.git("add", "-A")
        self.scratch.git("commit", "--quiet", "-m", "result")

    def audit(self) -> tuple[dict, list[str]]:
        head = self.scratch.git("rev-parse", "HEAD").strip()
        return residual.audit_slot(self.scratch.root, head, fixture.SLOT)

    def test_a_fully_manifested_slot_is_clean(self):
        summary, findings = self.audit()
        self.assertEqual(findings, [])
        self.assertEqual(summary["residual_files"], 0)
        self.assertEqual(summary["residual_bytes"], 0)
        self.assertEqual(summary["manifests_seen"], 1)

    def test_a_file_committed_after_the_manifest_is_residual(self):
        (self.scratch.slot / "late.txt").write_text("uncovered bytes\n", encoding="utf-8")
        self.scratch.git("add", "-A")
        self.scratch.git("commit", "--quiet", "-m", "late")
        summary, findings = self.audit()
        self.assertEqual(summary["residual_files"], 1)
        self.assertEqual(summary["residual_bytes"], len("uncovered bytes\n"))
        self.assertTrue(any("RESIDUAL_FILE" in f and "late.txt" in f for f in findings), findings)

    def test_a_payload_named_like_a_generated_document_is_residual(self):
        # The emitter excludes these basenames at any depth; the residual check
        # excludes them only at the slot root, which is what closes the gap.
        nested = self.scratch.slot / "nested"
        nested.mkdir()
        (nested / "manifest.json").write_text('{"smuggled": true}\n', encoding="utf-8")
        self.scratch.git("add", "-A")
        self.scratch.git("commit", "--quiet", "-m", "smuggled")
        summary, findings = self.audit()
        self.assertEqual(summary["residual_files"], 1, findings)
        self.assertTrue(
            any("nested/manifest.json" in f for f in findings),
            f"the smuggled payload was not reported: {findings}",
        )

    def test_the_generated_documents_at_the_slot_root_are_not_residual(self):
        # Excluding them is a declared exclusion, matching the emitter's contract.
        _, findings = self.audit()
        self.assertFalse(any("manifest.json" in f or "result.json" in f for f in findings))

    def test_a_manifested_file_moved_afterwards_is_matched_by_hash(self):
        # Renaming a covered file changes its path but not its bytes; reporting it
        # as residual would be a false positive that trains people to ignore this.
        source = self.scratch.slot / "component.py"
        body = source.read_bytes()
        source.rename(self.scratch.slot / "renamed_component.py")
        self.scratch.git("add", "-A")
        self.scratch.git("commit", "--quiet", "-m", "moved")
        _, findings = self.audit()
        digest = hashlib.sha256(body).hexdigest()
        self.assertFalse(
            any(digest in finding for finding in findings),
            f"a relocated but manifested file was reported residual: {findings}",
        )

    def test_a_slot_with_bytes_and_no_manifest_is_reported(self):
        bare = fixture.Scratch(self.holder / "bare")
        head = bare.git("rev-parse", "HEAD").strip()
        summary, findings = residual.audit_slot(bare.root, head, fixture.SLOT)
        self.assertEqual(summary["manifests_seen"], 0)
        self.assertTrue(any(f.startswith("NO_MANIFEST") for f in findings), findings)

    def test_a_superseded_manifest_still_counts_as_coverage(self):
        # A slot may be re-emitted.  A file covered only by the older manifest is
        # accounted for, not residual.
        (self.scratch.slot / "second.txt").write_text("second wave payload\n", encoding="utf-8")
        self.scratch.git("add", "-A")
        self.scratch.git("commit", "--quiet", "-m", "second artifact")
        self.scratch.artifact_commit = self.scratch.git("rev-parse", "HEAD").strip()
        self.assertEqual(self.scratch.emit().returncode, 0)
        self.scratch.git("add", "-A")
        self.scratch.git("commit", "--quiet", "-m", "second result")
        summary, findings = self.audit()
        self.assertEqual(summary["manifests_seen"], 2, findings)
        self.assertEqual(findings, [])


class ResidualCommandLineTests(unittest.TestCase):
    """The residual check is CI-callable and signals through its exit code."""

    def run_tool(self, *extra: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            (sys.executable, "-I", str(UNIT_ROOT / "residual_coverage.py"), *extra),
            cwd=cwd or REPO_ROOT, capture_output=True, text=True,
        )

    def test_every_manifested_slot_in_this_repository_is_accounted_for(self):
        manifested = [
            slot for slot in (REPO_ROOT / "workstreams" / "po03" / "attempts").iterdir()
            if (slot / "manifest.json").is_file()
        ]
        self.assertTrue(manifested, "no manifested slot to audit")
        for slot in sorted(manifested):
            completed = self.run_tool(
                "--repo-root", ".", "--commit", "HEAD", "--task-id", slot.name
            )
            self.assertEqual(
                completed.returncode, 0,
                f"{slot.name} holds bytes no manifest covers: {completed.stderr}",
            )

    def test_an_unknown_commit_exits_two(self):
        completed = self.run_tool("--repo-root", ".", "--commit", "not-a-commit")
        self.assertEqual(completed.returncode, 2)
        self.assertIn("PO03_RESIDUAL_ERROR", completed.stderr)

    def test_an_unknown_slot_exits_two_rather_than_reporting_a_clean_pass(self):
        # A tool that passes on a target it never found would let a mistyped task
        # id in a CI loop turn the gate green having audited nothing.
        completed = self.run_tool("--repo-root", ".", "--slot", "workstreams/po03/attempts/absent")
        self.assertEqual(completed.returncode, 2, completed.stdout)
        self.assertIn("nothing was audited", completed.stderr)

    def test_an_unknown_task_id_exits_two(self):
        completed = self.run_tool("--repo-root", ".", "--task-id", "po03-wa-b2e7-999-absent")
        self.assertEqual(completed.returncode, 2, completed.stdout)

    def test_json_mode_emits_one_parseable_document_on_stdout(self):
        completed = self.run_tool(
            "--repo-root", ".", "--commit", "HEAD",
            "--task-id", "po03-wa-b2e7-025-manifest-generator-verifier", "--json",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(len(report["slots"]), 1)
        self.assertEqual(report["findings"], [])


class FixtureCommandLineTests(unittest.TestCase):
    """The fixture is CI-callable and reports its own verdict."""

    def test_the_fixture_passes_and_reports_its_scenario_counts(self):
        completed = subprocess.run(
            (sys.executable, "-I", str(UNIT_ROOT / "omission_fixture.py")),
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("PO03_OMISSION_PASS", completed.stdout)
        self.assertIn("KNOWN_GAP", completed.stderr)

    def test_json_mode_emits_one_parseable_document_on_stdout(self):
        completed = subprocess.run(
            (sys.executable, "-I", str(UNIT_ROOT / "omission_fixture.py"), "--json"),
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        scenarios = json.loads(completed.stdout)
        self.assertTrue(all(entry["as_declared"] for entry in scenarios))
        self.assertTrue(any(entry["known_gap"] for entry in scenarios))


if __name__ == "__main__":
    unittest.main(verbosity=2)
