"""Executable probes for currentctl.

Most of these are old-behaviour probes: each recurring failure recorded in the
founder review is injected here, and the test passes only when the mechanism
rejects it. A happy path that passes proves nothing about a failure that used to
get through, so the happy paths are deliberately few.

Run:  python3 -I workstreams/so02/control-plane/operating-environment/l4-currentness-recovery/tests/test_currentctl.py
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _load_lane_d_fix(name: str):
    """SCP-SI-01 lane D's proposed mechanism, loaded from its own namespace.

    Not merged into `currentctl.py` by this lane (out of write scope); see
    `scp-si-01/lane-d/patches/currentctl.py.patch` for the proposed
    integration this test demonstrates is both necessary and sufficient.
    """
    lane_d = (
        Path(__file__).resolve().parents[2]
        / "scp-si-01" / "lane-d" / "fixes" / f"{name}.py"
    )
    spec = importlib.util.spec_from_file_location(f"lane_d_{name}", lane_d)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[f"lane_d_{name}"] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def _new_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "tester")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


def _git_available() -> bool:
    try:
        return subprocess.run(["git", "--version"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False

LANE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[6]
MODULE_PATH = LANE_ROOT / "tools/currentctl.py"
SPEC = importlib.util.spec_from_file_location("currentctl", MODULE_PATH)
currentctl = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(currentctl)

LADDER_CONTRACT = json.loads((LANE_ROOT / "ledger/admission-ladder.json").read_text(encoding="utf-8"))


def ladder() -> "currentctl.AdmissionLadder":
    return currentctl.AdmissionLadder(copy.deepcopy(LADDER_CONTRACT))


def codes(findings) -> set[str]:
    return {finding.code for finding in findings}


class FakeGit(currentctl.GitEvidence):
    """A git surface driven by a fixture rather than an object store.

    The fixture describes branch heads, the commit DAG, per-ref trees and the
    blobs each ref holds at a path, which is everything the compiler reads.
    """

    def __init__(self, refs: dict, dag: dict, trees: dict | None = None,
                 blobs: dict | None = None, added_paths: dict | None = None) -> None:
        self.refs = refs
        self.dag = dag
        self.trees = trees or {}
        self.blobs = blobs or {}
        self.added_paths = added_paths or {}
        super().__init__(Path("/nonexistent"), runner=self._fixture)

    def _fixture(self, args) -> str:
        args = list(args)
        if args[0] == "for-each-ref":
            return "".join(
                f"origin/{name}\t{spec['head']}\t{spec.get('unix', 1)}\t{spec.get('iso', '2026-08-22 00:00:00 +0000')}\t{spec.get('subject', '')}\n"
                for name, spec in self.refs.items()
            )
        if args[0] == "rev-list" and "--parents" in args:
            return "".join(f"{commit} {' '.join(parents)}\n".strip() + "\n"
                           for commit, parents in self.dag.items())
        if args[0] == "rev-list" and "--count" in args:
            return "0\n"
        if args[0] == "rev-parse":
            target = args[1]
            if ":" in target:
                ref, path = target.split(":", 1)
                return (self.blobs.get(ref.replace("origin/", ""), {}).get(path, "") or "") + "\n"
            return (self.refs.get(target.replace("origin/", ""), {}).get("head", "") or "") + "\n"
        if args[0] == "ls-tree":
            ref = args[-1].replace("origin/", "")
            return "".join(f"{path}\n" for path in self.trees.get(ref, []))
        if args[0] == "log":
            pattern = args[-1]
            return "".join(f"{sha}\n" for sha in self.added_paths.get(pattern, []))
        return ""


# ---------------------------------------------------------------------------
# Failure 1 - several competing claims of what is current
# ---------------------------------------------------------------------------


class CompetingCurrentnessTests(unittest.TestCase):
    SCOPE = [{"scope_id": "pointer.x", "paths": ["state/P.json"], "supersedes": {}}]

    def compile(self, blobs, supersedes=None):
        scope = copy.deepcopy(self.SCOPE)
        if supersedes:
            scope[0]["supersedes"] = supersedes
        git = FakeGit(refs={}, dag={}, blobs=blobs)
        return currentctl.compile_currentness(git, scope, list(blobs))["pointer.x"]

    def test_two_branches_disagreeing_is_unresolvable(self) -> None:
        """Old behaviour: pick the newest or the nearest file and call it current."""
        scope = self.compile({"main": {"state/P.json": "a" * 40},
                              "repair": {"state/P.json": "b" * 40}})
        self.assertEqual("UNRESOLVABLE_COMPETING_CLAIMS", scope["state"])
        self.assertIsNone(scope["resolved_blob"])

    def test_agreeing_branches_resolve(self) -> None:
        scope = self.compile({"main": {"state/P.json": "a" * 40},
                              "other": {"state/P.json": "a" * 40}})
        self.assertEqual("RESOLVED", scope["state"])
        self.assertEqual("a" * 40, scope["resolved_blob"])

    def test_declared_supersession_breaks_the_tie(self) -> None:
        """Disagreement is allowed once someone records which side lost."""
        scope = self.compile(
            {"main": {"state/P.json": "a" * 40}, "repair": {"state/P.json": "b" * 40}},
            supersedes={"b" * 40: "superseded by the accepted currentness lineage"},
        )
        self.assertEqual("RESOLVED_BY_DECLARED_SUPERSESSION", scope["state"])
        self.assertEqual("a" * 40, scope["resolved_blob"])

    def test_three_way_disagreement_is_still_one_finding_not_a_vote(self) -> None:
        """Old behaviour: majority of branches wins. Seven-to-one is still unresolved."""
        blobs = {f"b{n}": {"state/P.json": "a" * 40} for n in range(7)}
        blobs["repair"] = {"state/P.json": "b" * 40}
        blobs["repair2"] = {"state/P.json": "c" * 40}
        scope = self.compile(blobs)
        self.assertEqual("UNRESOLVABLE_COMPETING_CLAIMS", scope["state"])
        self.assertEqual(3, scope["variant_count"])


# ---------------------------------------------------------------------------
# Failure 2 - v007, a missing v008 and v009/v010 not forming one lineage
# ---------------------------------------------------------------------------


class LineageTests(unittest.TestCase):
    def test_version_referenced_but_never_committed_is_a_phantom(self) -> None:
        """Old behaviour: a version named in six documents is treated as existing."""
        git = FakeGit(refs={}, dag={}, added_paths={"*ROUTE*v008*": []})
        findings = currentctl.detect_phantom_versions(
            git, Path("/nonexistent"),
            [{"token": "ROUTE_v008", "path_glob": "*ROUTE*v008*",
              "referenced_by": ["a.md", "b.md", "c.md"]}],
        )
        self.assertEqual({"LINEAGE_PHANTOM_VERSION"}, codes(findings))
        self.assertIn("no commit on any ref ever added", findings[0].detail)

    def test_renamed_family_is_a_discontinuity_not_a_phantom(self) -> None:
        """The version exists; the chain does not. Those are different defects."""
        git = FakeGit(refs={}, dag={}, added_paths={"*OLD*v009*": []})
        findings = currentctl.detect_phantom_versions(
            git, Path("/nonexistent"),
            [{"token": "OLD_v009", "path_glob": "*OLD*v009*", "continues_as": "dispatch/NEW_v009.md"}],
        )
        self.assertEqual({"LINEAGE_FAMILY_DISCONTINUITY"}, codes(findings))
        self.assertEqual("dispatch/NEW_v009.md", findings[0].evidence["continues_as"])

    def test_version_that_was_committed_is_not_a_phantom(self) -> None:
        git = FakeGit(refs={}, dag={}, added_paths={"*ROUTE*v008*": ["f" * 40]})
        findings = currentctl.detect_phantom_versions(
            git, Path("/nonexistent"),
            [{"token": "ROUTE_v008", "path_glob": "*ROUTE*v008*", "referenced_by": ["a.md"]}],
        )
        self.assertEqual([], findings)

    def test_internal_gap_in_a_family_is_reported(self) -> None:
        git = FakeGit(refs={}, dag={}, trees={"HEAD": [
            "dispatch/ROUTE_v005.md", "dispatch/ROUTE_v006.md", "dispatch/ROUTE_v009.md"]})
        lineage = currentctl.compile_version_lineage(git, "HEAD")
        family = lineage["dispatch/ROUTE_vNNN.md"]
        self.assertEqual([5, 6, 9], family["observed_versions"])
        self.assertEqual([7, 8], family["internal_gaps"])

    def test_supersession_chain_is_derived_not_declared(self) -> None:
        git = FakeGit(refs={}, dag={}, trees={"HEAD": [
            "dispatch/ROUTE_v005.md", "dispatch/ROUTE_v006.md"]})
        chain = currentctl.compile_version_lineage(git, "HEAD")["dispatch/ROUTE_vNNN.md"]["chain"]
        self.assertIsNone(chain[0]["supersedes"])
        self.assertEqual("dispatch/ROUTE_v005.md", chain[1]["supersedes"])


# ---------------------------------------------------------------------------
# Failure 3 - PRs, ZIPs, agents, prompts, file counts and acknowledgements
#             treated as completed capability
# ---------------------------------------------------------------------------


class NonAdmissibleEvidenceTests(unittest.TestCase):
    """One probe per artefact the estate has previously counted as capability."""

    def assert_ceilinged(self, evidence_class: str, claimed: str = "ACCEPTED") -> None:
        admitted, findings = ladder().evaluate(
            "WS-PROBE", claimed, [{"evidence_class": evidence_class, "detail": "probe"}])
        self.assertEqual("PROPOSED", admitted,
                         f"{evidence_class} advanced a subject to {admitted}")
        self.assertIn("ADMISSION_OVERCLAIM", codes(findings))
        self.assertIn("NON_ADMISSIBLE_EVIDENCE_OFFERED", codes(findings))

    def test_open_pull_request_cannot_complete_capability(self) -> None:
        self.assert_ceilinged("PULL_REQUEST_EXISTS")

    def test_branch_existing_cannot_complete_capability(self) -> None:
        self.assert_ceilinged("BRANCH_EXISTS")

    def test_zip_archive_cannot_complete_capability(self) -> None:
        self.assert_ceilinged("ZIP_ARCHIVE")

    def test_file_count_cannot_complete_capability(self) -> None:
        self.assert_ceilinged("FILE_COUNT")

    def test_agent_existing_cannot_complete_capability(self) -> None:
        self.assert_ceilinged("AGENT_EXISTS")

    def test_prompt_sent_cannot_complete_capability(self) -> None:
        self.assert_ceilinged("PROMPT_SENT")

    def test_acknowledgement_cannot_complete_capability(self) -> None:
        self.assert_ceilinged("ACKNOWLEDGEMENT")

    def test_provider_completed_cannot_complete_capability(self) -> None:
        self.assert_ceilinged("PROVIDER_COMPLETED")

    def test_receipt_count_cannot_complete_capability(self) -> None:
        self.assert_ceilinged("RECEIPT_COUNT")

    def test_documented_mechanism_is_not_an_operating_mechanism(self) -> None:
        self.assert_ceilinged("DOCUMENT_DESCRIBES_MECHANISM")

    def test_documented_lesson_that_changes_no_gate_cannot_advance_state(self) -> None:
        """Failure 12: lessons documented without changing the actual mechanism."""
        self.assert_ceilinged("LESSON_DOCUMENTED")

    def test_a_pile_of_non_admissible_evidence_is_still_proposed(self) -> None:
        """Old behaviour: enough weak evidence adds up to strong evidence."""
        entries = [{"evidence_class": name} for name in
                   ("PULL_REQUEST_EXISTS", "BRANCH_EXISTS", "ZIP_ARCHIVE", "FILE_COUNT",
                    "AGENT_EXISTS", "PROMPT_SENT", "ACKNOWLEDGEMENT", "PROVIDER_COMPLETED",
                    "RECEIPT_COUNT", "LESSON_DOCUMENTED")]
        admitted, _ = ladder().evaluate("WS-PILE", "ACCEPTED", entries)
        self.assertEqual("PROPOSED", admitted)

    def test_an_alias_locator_does_not_satisfy_a_locator_requirement(self) -> None:
        """An admissible class whose locator addresses nothing counts for nothing."""
        admitted, findings = ladder().evaluate("WS-ALIAS", "OBSERVED", [
            {"evidence_class": "COMMISSION_DOCUMENT", "artifact_path": "c.md"},
            {"evidence_class": "LAUNCH_RECEIPT_WITH_LOCATOR", "locator": "current_project_conversation"},
            {"evidence_class": "OBSERVED_OUTPUT_WITH_LOCATOR", "locator": "current_project_conversation"},
        ])
        self.assertEqual("PROPOSED", admitted)
        self.assertIn("EVIDENCE_DISQUALIFIED", codes(findings))

    def test_an_externally_disqualified_class_stops_counting(self) -> None:
        admitted, findings = ladder().evaluate("WS-STALE", "DURABLE", [
            {"evidence_class": "COMMISSION_DOCUMENT", "artifact_path": "c.md"},
            {"evidence_class": "LAUNCH_RECEIPT_WITH_LOCATOR", "locator": "https://x/1"},
            {"evidence_class": "OBSERVED_OUTPUT_WITH_LOCATOR", "locator": "https://x/1"},
            {"evidence_class": "COMMITTED_ARTIFACT_HASH", "artifact_path": "a", "sha256": "0" * 64},
            {"evidence_class": "REMOTE_READBACK_HASH", "artifact_path": "a", "sha256": "0" * 64},
        ], disqualified={"REMOTE_READBACK_HASH"})
        self.assertEqual("OBSERVED", admitted)
        self.assertIn("EVIDENCE_DISQUALIFIED", codes(findings))

    def test_unknown_evidence_class_is_not_silently_trusted(self) -> None:
        _, findings = ladder().evaluate(
            "WS-PROBE", "PROPOSED", [{"evidence_class": "SOMETHING_NEW"}])
        self.assertIn("EVIDENCE_CLASS_UNKNOWN", codes(findings))


# ---------------------------------------------------------------------------
# Failure 4 - proposed, launched, observed, completed and accepted conflated
# ---------------------------------------------------------------------------


class AdmissionLadderTests(unittest.TestCase):
    COMMISSION = {"evidence_class": "COMMISSION_DOCUMENT", "artifact_path": "c.md"}
    LAUNCH = {"evidence_class": "LAUNCH_RECEIPT_WITH_LOCATOR", "locator": "https://example/agents/x"}
    OUTPUT = {"evidence_class": "OBSERVED_OUTPUT_WITH_LOCATOR", "locator": "https://example/agents/x"}
    ARTIFACT = {"evidence_class": "COMMITTED_ARTIFACT_HASH", "artifact_path": "a.md", "sha256": "0" * 64}
    READBACK = {"evidence_class": "REMOTE_READBACK_HASH", "artifact_path": "a.md", "sha256": "0" * 64}
    COMMAND = {"evidence_class": "REPRODUCIBLE_COMMAND", "argv": ["true"]}
    REVIEW = {"evidence_class": "INDEPENDENT_EVALUATION", "evaluator_identity": "L3",
              "producer_identity": "L4"}
    FOUNDER = {"evidence_class": "FOUNDER_BOUND_ACCEPTANCE", "decision": "APPROVED"}

    def test_launch_receipt_alone_does_not_reach_observed(self) -> None:
        admitted, findings = ladder().evaluate("WS", "OBSERVED", [self.COMMISSION, self.LAUNCH])
        self.assertEqual("LAUNCHED", admitted)
        self.assertIn("ADMISSION_OVERCLAIM", codes(findings))

    def test_observed_output_does_not_reach_durable(self) -> None:
        admitted, _ = ladder().evaluate("WS", "DURABLE",
                                        [self.COMMISSION, self.LAUNCH, self.OUTPUT])
        self.assertEqual("OBSERVED", admitted)

    def test_durable_does_not_reach_independently_validated(self) -> None:
        admitted, _ = ladder().evaluate("WS", "INDEPENDENTLY_VALIDATED", [
            self.COMMISSION, self.LAUNCH, self.OUTPUT, self.ARTIFACT, self.READBACK])
        self.assertEqual("DURABLE", admitted)

    def test_independent_validation_does_not_reach_accepted(self) -> None:
        """Acceptance is a founder-bound act, not the last step of a good review."""
        admitted, _ = ladder().evaluate("WS", "ACCEPTED", [
            self.COMMISSION, self.LAUNCH, self.OUTPUT, self.ARTIFACT, self.READBACK,
            self.COMMAND, self.REVIEW])
        self.assertEqual("INDEPENDENTLY_VALIDATED", admitted)

    def test_full_evidence_reaches_accepted(self) -> None:
        admitted, findings = ladder().evaluate("WS", "ACCEPTED", [
            self.COMMISSION, self.LAUNCH, self.OUTPUT, self.ARTIFACT, self.READBACK,
            self.COMMAND, self.REVIEW, self.FOUNDER])
        self.assertEqual("ACCEPTED", admitted)
        self.assertEqual(set(), codes(findings))

    def test_states_cannot_be_skipped(self) -> None:
        """Old behaviour: artifact in the repo, therefore durable, without a launch."""
        admitted, findings = ladder().evaluate("WS", "DURABLE", [
            self.COMMISSION, self.ARTIFACT, self.READBACK])
        self.assertEqual("PROPOSED", admitted)
        self.assertIn("ADMISSION_OVERCLAIM", codes(findings))

    def test_launch_without_a_commission_is_held_and_named(self) -> None:
        """An agent dispatched with no commission behind it cannot be LAUNCHED."""
        admitted, findings = ladder().evaluate("WS", "LAUNCHED", [self.LAUNCH])
        self.assertEqual("PROPOSED", admitted)
        self.assertIn("LADDER_FOUNDATION_MISSING", codes(findings))

    def test_later_evidence_does_not_backfill_an_earlier_rung(self) -> None:
        admitted, findings = ladder().evaluate("WS", "ACCEPTED", [
            self.ARTIFACT, self.READBACK, self.COMMAND, self.REVIEW, self.FOUNDER])
        self.assertEqual("PROPOSED", admitted)
        self.assertIn("LADDER_FOUNDATION_MISSING", codes(findings))

    def test_claiming_a_lower_state_than_supported_is_never_upgraded(self) -> None:
        admitted, findings = ladder().evaluate("WS", "PROPOSED",
                                               [self.COMMISSION, self.LAUNCH, self.OUTPUT])
        self.assertEqual("PROPOSED", admitted)
        self.assertEqual(set(), codes(findings))


# ---------------------------------------------------------------------------
# Failure 5 - a producer accepting its own work; founder as the recovery layer
# ---------------------------------------------------------------------------


class IndependenceTests(unittest.TestCase):
    def test_producer_cannot_be_its_own_evaluator(self) -> None:
        findings = currentctl.check_reproducibility(
            Path("/nonexistent"), "WS",
            [{"evidence_class": "INDEPENDENT_EVALUATION",
              "evaluator_identity": "L4", "producer_identity": "L4"}],
            LADDER_CONTRACT)
        self.assertIn("SELF_ACCEPTANCE", codes(findings))

    def test_evaluation_without_a_named_evaluator_is_unbacked(self) -> None:
        findings = currentctl.check_reproducibility(
            Path("/nonexistent"), "WS",
            [{"evidence_class": "INDEPENDENT_EVALUATION"}], LADDER_CONTRACT)
        self.assertIn("UNBACKED_EVIDENCE_CLAIM", codes(findings))

    def test_distinct_evaluator_is_accepted(self) -> None:
        findings = currentctl.check_reproducibility(
            Path("/nonexistent"), "WS",
            [{"evidence_class": "INDEPENDENT_EVALUATION",
              "evaluator_identity": "L3", "producer_identity": "L4"}],
            LADDER_CONTRACT)
        self.assertEqual([], findings)


# ---------------------------------------------------------------------------
# Failure 6 - an evidence claim with no reproducible artifact behind it
# ---------------------------------------------------------------------------


class ReproducibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def check(self, entries):
        return currentctl.check_reproducibility(self.root, "WS", entries, LADDER_CONTRACT)

    def test_artifact_hash_naming_a_missing_file_is_rejected(self) -> None:
        findings = self.check([{"evidence_class": "COMMITTED_ARTIFACT_HASH",
                                "artifact_path": "gone.md", "sha256": "0" * 64}])
        self.assertIn("UNBACKED_EVIDENCE_CLAIM", codes(findings))

    def test_artifact_hash_that_does_not_match_the_bytes_is_rejected(self) -> None:
        (self.root / "a.md").write_text("real content", encoding="utf-8")
        findings = self.check([{"evidence_class": "COMMITTED_ARTIFACT_HASH",
                                "artifact_path": "a.md", "sha256": "0" * 64}])
        self.assertIn("EVIDENCE_HASH_MISMATCH", codes(findings))

    def test_artifact_hash_that_matches_is_accepted(self) -> None:
        (self.root / "a.md").write_text("real content", encoding="utf-8")
        digest = currentctl.sha256_bytes(b"real content")
        findings = self.check([{"evidence_class": "COMMITTED_ARTIFACT_HASH",
                                "artifact_path": "a.md", "sha256": digest}])
        self.assertEqual([], findings)

    def test_malformed_hash_is_rejected_before_it_is_trusted(self) -> None:
        (self.root / "a.md").write_text("x", encoding="utf-8")
        findings = self.check([{"evidence_class": "COMMITTED_ARTIFACT_HASH",
                                "artifact_path": "a.md", "sha256": "not-a-hash"}])
        self.assertIn("UNBACKED_EVIDENCE_CLAIM", codes(findings))

    def test_command_without_argv_is_not_reproducible(self) -> None:
        findings = self.check([{"evidence_class": "REPRODUCIBLE_COMMAND"}])
        self.assertIn("UNBACKED_EVIDENCE_CLAIM", codes(findings))

    def test_launch_receipt_without_a_locator_is_unaddressable(self) -> None:
        findings = self.check([{"evidence_class": "LAUNCH_RECEIPT_WITH_LOCATOR"}])
        self.assertIn("UNBACKED_EVIDENCE_CLAIM", codes(findings))

    def test_display_alias_is_not_a_locator(self) -> None:
        """Failure 10: local platform surfaces standing in for durable identity."""
        findings = self.check([{"evidence_class": "OBSERVED_OUTPUT_WITH_LOCATOR",
                                "locator": "current_project_conversation"}])
        self.assertIn("ALIAS_USED_AS_LOCATOR", codes(findings))

    def test_reproduce_reruns_the_command_and_reports_the_real_exit_code(self) -> None:
        ledger = {"workstreams": [{"workstream_id": "WS", "evidence": [
            {"evidence_class": "REPRODUCIBLE_COMMAND",
             "argv": [sys.executable, "-c", "raise SystemExit(3)"], "expected_exit_code": 0}]}]}
        findings = currentctl.reproduce_commands(self.root, ledger)
        self.assertIn("REPRODUCTION_FAILED", codes(findings))
        self.assertEqual(3, findings[0].evidence["actual_exit_code"])

    def test_reproduce_passes_when_the_command_really_passes(self) -> None:
        ledger = {"workstreams": [{"workstream_id": "WS", "evidence": [
            {"evidence_class": "REPRODUCIBLE_COMMAND",
             "argv": [sys.executable, "-c", "pass"], "expected_exit_code": 0}]}]}
        self.assertEqual([], currentctl.reproduce_commands(self.root, ledger))


class StaleReadbackTests(unittest.TestCase):
    def test_readback_pinned_to_a_moved_ref_is_stale(self) -> None:
        class MovedGit(FakeGit):
            def _fixture(self, args):
                args = list(args)
                if args[0] == "rev-parse":
                    return "b" * 40 + "\n"
                if args[0] == "rev-list" and "--count" in args:
                    return "53\n"
                return super()._fixture(args)

        findings = currentctl.check_reproducibility(
            Path("/nonexistent"), "WS",
            [{"evidence_class": "REMOTE_READBACK_HASH", "artifact_path": "x",
              "sha256": "0" * 64, "readback_ref": "po03/x", "readback_commit": "a" * 40}],
            LADDER_CONTRACT, MovedGit(refs={}, dag={}))
        self.assertIn("STALE_REMOTE_READBACK", codes(findings))
        self.assertIn("53 commits behind", findings[0].detail)

    def test_readback_matching_the_ref_head_is_current(self) -> None:
        class SteadyGit(FakeGit):
            def _fixture(self, args):
                if list(args)[0] == "rev-parse":
                    return "a" * 40 + "\n"
                return super()._fixture(args)

        findings = currentctl.check_reproducibility(
            Path("/nonexistent"), "WS",
            [{"evidence_class": "REMOTE_READBACK_HASH", "artifact_path": "x",
              "sha256": "0" * 64, "readback_ref": "po03/x", "readback_commit": "a" * 40}],
            LADDER_CONTRACT, SteadyGit(refs={}, dag={}))
        self.assertNotIn("STALE_REMOTE_READBACK", codes(findings))


# ---------------------------------------------------------------------------
# Defect 4 / DEF-SCP-01 - EVIDENCE_HASH_MISMATCH conflates supersession with
#                         tampering
# ---------------------------------------------------------------------------


@unittest.skipUnless(_git_available(), "git is required to reproduce this against real history")
class DefSCP01SupersessionVsTamperingTests(unittest.TestCase):
    """SCP-SI-01 lane D, DEF-SCP-01.

    Published by the coordinator on the integration branch at commit
    f0fb3f51 as `scp-si-01/DEFECT-SCP-01-SUPERSESSION-READS-AS-TAMPERING.json`
    with `routing.owning_lane: "D"`. `check_reproducibility`'s
    `COMMITTED_ARTIFACT_HASH` branch (`currentctl.py`, the `EVIDENCE_HASH_MISMATCH`
    finding below `elif entry_class in artifact_classes:`) compares a recorded
    sha256 against the CURRENT working-tree bytes of `artifact_path`. It has
    no field recording which commit the hash was taken at, so it cannot tell
    "this was hashed correctly and the file has since legitimately changed"
    (supersession, routine) apart from "this hash was never right" (tampering,
    an integrity incident). Both conditions read as the identical finding
    code with identical severity.

    This is exercised against a real disposable git repository, never a
    fixture, because the defect is specifically about commit-scoped history
    that `FakeGit` (used elsewhere in this file) does not carry.
    """

    def test_case_2_and_case_3_are_indistinguishable_in_the_unmodified_checker(self) -> None:
        """Pre-fix failure, DIRECTLY_REPRODUCED against the shipped checker."""
        with tempfile.TemporaryDirectory() as d:
            repo = _new_repo(Path(d))

            # Case 2 - SUPERSESSION: correctly hashed at v1, legitimately
            # changed to v2 afterward (the routine, expected case).
            (repo / "evidence.json").write_text('{"v":1}\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "v1")
            v1_sha256 = currentctl.sha256_bytes((repo / "evidence.json").read_bytes())
            (repo / "evidence.json").write_text('{"v":2}\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "v2 legitimately supersedes v1")

            superseded_findings = currentctl.check_reproducibility(
                repo, "WS-SUPERSEDED",
                [{"evidence_class": "COMMITTED_ARTIFACT_HASH",
                  "artifact_path": "evidence.json", "sha256": v1_sha256}],
                LADDER_CONTRACT)

            # Case 3 - TAMPERING: the recorded hash was never correct, even
            # at the moment it was supposedly taken (an integrity incident).
            (repo / "tampered.json").write_text('{"v":"real"}\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "tampered.json, hash never matched its own content")
            wrong_sha256 = currentctl.sha256_bytes(b"this was never the content")

            tampered_findings = currentctl.check_reproducibility(
                repo, "WS-TAMPERED",
                [{"evidence_class": "COMMITTED_ARTIFACT_HASH",
                  "artifact_path": "tampered.json", "sha256": wrong_sha256}],
                LADDER_CONTRACT)

        self.assertEqual({"EVIDENCE_HASH_MISMATCH"}, codes(superseded_findings),
                         "documents the defect for evidence entries that predate the "
                         "artifact_commit anchor (see patches/currentctl.py.patch); "
                         "test_the_lane_d_mechanism_correctly_splits_all_four_cases below is "
                         "the passing rerun for entries that adopt the anchor")
        self.assertEqual({"EVIDENCE_HASH_MISMATCH"}, codes(tampered_findings))
        # The defect: routine drift and an integrity incident produce the
        # exact same code, at the exact same severity, with no field on
        # either finding that lets a reader tell them apart.
        self.assertEqual(superseded_findings[0].code, tampered_findings[0].code)
        self.assertEqual(superseded_findings[0].severity, tampered_findings[0].severity)

    def test_the_lane_d_mechanism_correctly_splits_all_four_cases(self) -> None:
        """Passing rerun: `currentctl_supersession_split.check_artifact_hash_with_supersession`."""
        fix = _load_lane_d_fix("currentctl_supersession_split")
        with tempfile.TemporaryDirectory() as d:
            repo = _new_repo(Path(d))
            (repo / "evidence.json").write_text('{"v":1}\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "v1")
            v1_commit = _git(repo, "rev-parse", "HEAD")
            v1_sha256 = currentctl.sha256_bytes((repo / "evidence.json").read_bytes())

            (repo / "evidence.json").write_text('{"v":2}\n', encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "v2 legitimately supersedes v1")
            v2_commit = _git(repo, "rev-parse", "HEAD")
            v2_sha256 = currentctl.sha256_bytes((repo / "evidence.json").read_bytes())

            # Case 1 - CLEAN: hashed at its own commit, which is also the tip.
            clean = fix.check_artifact_hash_with_supersession(
                {"artifact_path": "evidence.json", "sha256": v2_sha256, "artifact_commit": v2_commit},
                repo, branch_ref="HEAD")

            # Case 2 - SUPERSESSION: correct at v1, legitimately moved on by the tip.
            superseded = fix.check_artifact_hash_with_supersession(
                {"artifact_path": "evidence.json", "sha256": v1_sha256, "artifact_commit": v1_commit},
                repo, branch_ref="HEAD")

            # Case 3 - TAMPERING: wrong even at its own recorded commit.
            tampered = fix.check_artifact_hash_with_supersession(
                {"artifact_path": "evidence.json", "sha256": "0" * 64, "artifact_commit": v1_commit},
                repo, branch_ref="HEAD")

            # Case 4 - no artifact_commit at all: cannot be resolved either way.
            unanchored = fix.check_artifact_hash_with_supersession(
                {"artifact_path": "evidence.json", "sha256": v1_sha256},
                repo, branch_ref="HEAD")

        self.assertIsNone(clean)
        self.assertEqual("EVIDENCE_SUPERSEDED", superseded["code"])
        self.assertEqual("INFO", superseded["severity"])
        self.assertEqual("EVIDENCE_HASH_MISMATCH", tampered["code"])
        self.assertEqual("ERROR", tampered["severity"])
        self.assertEqual("EVIDENCE_ANCHOR_MISSING", unanchored["code"])
        self.assertEqual("ERROR", unanchored["severity"])
        # The two ERROR-severity codes must differ in text from each other
        # and from the INFO code: this is the split the defect lacked.
        self.assertNotEqual(tampered["code"], unanchored["code"])
        self.assertNotEqual(tampered["code"], superseded["code"])

    def test_the_fix_does_not_regress_the_real_estate_reproducibility_checks(self) -> None:
        """The split mechanism must still catch a plain missing-file claim."""
        fix = _load_lane_d_fix("currentctl_supersession_split")
        with tempfile.TemporaryDirectory() as d:
            repo = _new_repo(Path(d))
            (repo / "a.md").write_text("x", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "a")
            commit = _git(repo, "rev-parse", "HEAD")
            finding = fix.check_artifact_hash_with_supersession(
                {"artifact_path": "gone.md", "sha256": "0" * 64, "artifact_commit": commit},
                repo, branch_ref="HEAD")
        self.assertEqual("EVIDENCE_HASH_MISMATCH", finding["code"])
        self.assertEqual("ERROR", finding["severity"])


# ---------------------------------------------------------------------------
# Failure 7 - several agents receiving overlapping whole-operation commissions
# ---------------------------------------------------------------------------


class CommissionDifferentiationTests(unittest.TestCase):
    WHOLE = "operate the durable coordination kernel for the whole operation"
    NARROW = "produce one branch classification table"

    def commission(self, cid, path, namespace, scope_text, binds=(), supersedes=()):
        return {"commission_id": cid, "path": path, "namespace": list(namespace),
                "scope_text": scope_text, "binds": list(binds),
                "supersedes": list(supersedes), "active": True}

    def test_two_whole_operation_commissions_over_one_namespace_are_rejected(self) -> None:
        findings = currentctl.check_commission_differentiation([
            self.commission("COM-A", "a.md", ["state/**"], self.WHOLE, ["CUR-01"]),
            self.commission("COM-B", "b.md", ["state/**"], self.WHOLE, ["CUR-01"]),
        ], LADDER_CONTRACT)
        self.assertIn("UNDIFFERENTIATED_COMMISSION_OVERLAP", codes(findings))
        self.assertIn("both bind the same runtime actor", findings[0].detail)

    def test_a_declared_supersession_edge_permits_the_overlap(self) -> None:
        findings = currentctl.check_commission_differentiation([
            self.commission("COM-A", "a.md", ["state/**"], self.WHOLE, ["CUR-01"], ["COM-B"]),
            self.commission("COM-B", "b.md", ["state/**"], self.WHOLE, ["CUR-01"]),
        ], LADDER_CONTRACT)
        self.assertEqual(set(), codes(findings))

    def test_disjoint_namespaces_permit_two_whole_operation_commissions(self) -> None:
        findings = currentctl.check_commission_differentiation([
            self.commission("COM-A", "a.md", ["workstreams/a/**"], self.WHOLE),
            self.commission("COM-B", "b.md", ["workstreams/b/**"], self.WHOLE),
        ], LADDER_CONTRACT)
        self.assertEqual(set(), codes(findings))

    def test_differentiated_scope_permits_the_overlap(self) -> None:
        """Overlap is allowed; undifferentiated whole-operation overlap is not."""
        findings = currentctl.check_commission_differentiation([
            self.commission("COM-A", "a.md", ["state/**"], self.WHOLE),
            self.commission("COM-B", "b.md", ["state/**"], self.NARROW),
        ], LADDER_CONTRACT)
        self.assertEqual(set(), codes(findings))

    def test_one_identifier_naming_two_documents_is_not_addressable(self) -> None:
        findings = currentctl.check_commission_differentiation([
            self.commission("COM-A", "a.md", ["x/**"], self.NARROW),
            self.commission("COM-A", "b.json", ["y/**"], self.NARROW),
        ], LADDER_CONTRACT)
        self.assertIn("COMMISSION_ID_COLLISION", codes(findings))

    def test_retired_commission_does_not_collide(self) -> None:
        findings = currentctl.check_commission_differentiation([
            self.commission("COM-A", "a.md", ["state/**"], self.WHOLE),
            dict(self.commission("COM-B", "b.md", ["state/**"], self.WHOLE), active=False),
        ], LADDER_CONTRACT)
        self.assertEqual(set(), codes(findings))

    def test_active_commission_absent_from_the_register_cannot_resolve(self) -> None:
        findings = currentctl.check_commission_resolution(
            [self.commission("COM-A", "a.md", ["x/**"], self.NARROW)], {"COM-OTHER"})
        self.assertIn("COMMISSION_UNRESOLVED_IN_REGISTER", codes(findings))

    def test_registered_commission_resolves(self) -> None:
        findings = currentctl.check_commission_resolution(
            [self.commission("COM-A", "a.md", ["x/**"], self.NARROW)], {"COM-A"})
        self.assertEqual([], findings)


# ---------------------------------------------------------------------------
# Failure 8 - refs, PR stacks and coordination tokens counted as delivered scale
# ---------------------------------------------------------------------------


class RefGraphTests(unittest.TestCase):
    def build(self):
        # main <- feature; merged is an ancestor of main; orphan has its own root.
        refs = {
            "main": {"head": "m2"},
            "feature": {"head": "f2"},
            "merged": {"head": "m1"},
            "orphan": {"head": "o1"},
            "lease": {"head": "l1"},
        }
        dag = {"f2": ["f1"], "f1": ["m2"], "m2": ["m1"], "m1": [], "o1": [], "l1": []}
        trees = {"main": ["a.md"], "feature": ["a.md", "b.md"], "merged": ["a.md"],
                 "orphan": ["x.md"], "lease": ["claim.json"]}
        return FakeGit(refs=refs, dag=dag, trees=trees)

    def test_classification_is_derived_from_the_dag(self) -> None:
        graph = currentctl.compile_ref_graph(self.build(), live_branches=["main", "feature"])
        nodes = graph["nodes"]
        self.assertEqual("MERGED", nodes["merged"]["classification"])
        self.assertEqual("ACTIVE", nodes["feature"]["classification"])
        self.assertEqual("ORPHANED", nodes["orphan"]["classification"])

    def test_an_addressed_branch_is_active_even_when_contained(self) -> None:
        """A base branch a pull request still targets is live, not superseded."""
        git = self.build()
        git.refs["base"] = {"head": "f1"}
        git.trees["base"] = ["a.md"]
        graph = currentctl.compile_ref_graph(git, live_branches=["main", "base"])
        node = graph["nodes"]["base"]
        self.assertEqual("ACTIVE", node["classification"])
        self.assertIn("feature", node["contained_by"])

    def test_an_unaddressed_contained_branch_is_superseded(self) -> None:
        git = self.build()
        git.refs["stale"] = {"head": "f1"}
        git.trees["stale"] = ["a.md"]
        graph = currentctl.compile_ref_graph(git, live_branches=["main"])
        self.assertEqual("SUPERSEDED", graph["nodes"]["stale"]["classification"])

    def test_an_unaddressed_tip_is_abandoned_not_active(self) -> None:
        """Old behaviour: a recent branch is treated as live work."""
        git = self.build()
        git.refs["stray"] = {"head": "s1", "unix": 9999999999}
        git.dag["s1"] = ["m2"]
        git.trees["stray"] = ["a.md", "z.md"]
        graph = currentctl.compile_ref_graph(git, live_branches=["main", "feature"])
        self.assertEqual("ABANDONED", graph["nodes"]["stray"]["classification"])

    def test_a_lease_token_is_not_work(self) -> None:
        graph = currentctl.compile_ref_graph(self.build(), live_branches=["main"])
        self.assertEqual("LEASE_TOKEN", graph["nodes"]["lease"]["ref_role"])
        findings = currentctl.check_integration_reality(graph, [], ladder())
        self.assertIn("COORDINATION_TOKENS_COUNTED_AS_SCALE", codes(findings))

    def test_orphan_population_is_reported(self) -> None:
        graph = currentctl.compile_ref_graph(self.build(), live_branches=["main"])
        findings = currentctl.check_integration_reality(graph, [], ladder())
        self.assertIn("ORPHANED_REF_POPULATION", codes(findings))

    def test_a_stack_of_open_prs_is_one_unlanded_chain(self) -> None:
        """Failure 9: the founder becomes the merge layer for a stack nothing can land."""
        graph = currentctl.compile_ref_graph(self.build(), live_branches=["main"])
        prs = [
            {"number": 1, "state": "OPEN", "headRefName": "feature", "baseRefName": "merged"},
            {"number": 2, "state": "OPEN", "headRefName": "merged", "baseRefName": "main"},
        ]
        findings = currentctl.check_integration_reality(graph, prs, ladder())
        self.assertIn("STACKED_UNLANDED_PR_CHAIN", codes(findings))

    def test_independent_prs_are_not_a_stack(self) -> None:
        graph = currentctl.compile_ref_graph(self.build(), live_branches=["main"])
        prs = [
            {"number": 1, "state": "OPEN", "headRefName": "feature", "baseRefName": "main"},
            {"number": 2, "state": "OPEN", "headRefName": "orphan", "baseRefName": "main"},
        ]
        findings = currentctl.check_integration_reality(graph, prs, ladder())
        self.assertNotIn("STACKED_UNLANDED_PR_CHAIN", codes(findings))


# ---------------------------------------------------------------------------
# Integration - the mechanism must find the real estate, not just fixtures
# ---------------------------------------------------------------------------


class RealRepositoryTests(unittest.TestCase):
    """These run against the checkout. They assert shape, not exact counts, so
    they keep working while the estate moves under them."""

    @classmethod
    def setUpClass(cls) -> None:
        if not (REPO_ROOT / ".git").exists():
            raise unittest.SkipTest("not a git checkout")
        cls.projection = currentctl.Compiler(REPO_ROOT, LANE_ROOT / "ledger").compile()

    def test_the_repository_fails_closed_today(self) -> None:
        self.assertTrue(self.projection["fail_closed"])

    def test_the_v008_phantom_is_found_in_the_real_history(self) -> None:
        phantoms = [f for f in self.projection["findings"]
                    if f["code"] == "LINEAGE_PHANTOM_VERSION" and "v008" in f["subject"]]
        self.assertEqual(1, len(phantoms))
        self.assertEqual([], phantoms[0]["evidence"]["commits_adding_path"])

    def test_real_pointer_scopes_are_in_competition(self) -> None:
        competing = [f["subject"] for f in self.projection["findings"]
                     if f["code"] == "COMPETING_CURRENTNESS_CLAIM"]
        self.assertIn("urn:obzio:l4:scope:pointer.operator-system", competing)

    def test_no_workstream_is_admitted_above_its_evidence(self) -> None:
        rank = self.projection["workstreams"]
        for workstream in rank.values():
            claimed = currentctl.AdmissionLadder(LADDER_CONTRACT).rank(workstream["claimed_state"])
            admitted = currentctl.AdmissionLadder(LADDER_CONTRACT).rank(workstream["admitted_state"])
            self.assertLessEqual(admitted, claimed, workstream["workstream_id"])

    def test_nothing_in_the_real_estate_reaches_accepted(self) -> None:
        self.assertEqual(0, self.projection["admission_counts"]["admitted"].get("ACCEPTED", 0))

    def test_projection_hash_is_a_pure_function_of_repository_state(self) -> None:
        again = currentctl.Compiler(REPO_ROOT, LANE_ROOT / "ledger").compile()
        self.assertEqual(self.projection["projection_sha256"], again["projection_sha256"])

    def test_resolve_refuses_a_contested_scope_from_the_cli(self) -> None:
        result = subprocess.run(
            [sys.executable, "-I", str(MODULE_PATH), "resolve", "--scope", "pointer.instruction-stack"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
        self.assertEqual(1, result.returncode)
        self.assertIn("REFUSED", result.stdout)

    def test_validate_exits_nonzero_from_the_cli(self) -> None:
        result = subprocess.run(
            [sys.executable, "-I", str(MODULE_PATH), "validate"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
        self.assertEqual(1, result.returncode)


if __name__ == "__main__":
    unittest.main(verbosity=2)
