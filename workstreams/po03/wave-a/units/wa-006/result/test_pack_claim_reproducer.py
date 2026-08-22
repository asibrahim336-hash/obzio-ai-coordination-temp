#!/usr/bin/env python3
"""Focused tests for the PO03-WA-006 read-only pack-claim reproducer.

Run with ``python3 -m unittest`` from this directory, or via ``python3
test_pack_claim_reproducer.py``.  Only the standard library is used so a clean
clone can run the suite without installing anything.

The suite has three jobs:

1. prove the reproducer is genuinely read-only and cannot mutate a branch;
2. prove it detects the injected defects in the sanitized fixture and does not
   invent defects in the fixture's clean control pack;
3. recur the frozen findings against the immutable PO-01 commits when those
   objects are present in the local object store, and skip explicitly when they
   are not, rather than silently passing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
FROZEN_REPORT = HERE / "frozen-discrepancy-report.json"

# Self-locating import so the suite runs identically under `python3 file.py`,
# `python3 -m unittest`, and CI's isolated `python3 -I -m unittest discover`,
# which drops the script directory from sys.path.
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import build_sanitized_fixture  # noqa: E402
import pack_claim_reproducer as reproducer  # noqa: E402


def _local_repo_root() -> Path:
    """The repository that owns this file, used only for immutable reads."""
    completed = subprocess.run(
        ["git", "-C", str(HERE), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise unittest.SkipTest("this file is not inside a git repository")
    return Path(completed.stdout.strip())


def _commit_present(repo: Path, commit: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


class ReadOnlyGuardTests(unittest.TestCase):
    """The guard is the load-bearing safety property, so it is tested directly."""

    def setUp(self) -> None:
        self.repo = _local_repo_root()
        self.git = reproducer.ReadOnlyGit(self.repo)

    def test_write_subcommands_are_refused(self) -> None:
        for argv in (
            ["checkout", "main"],
            ["switch", "-c", "anything"],
            ["fetch", "origin"],
            ["push", "origin", "HEAD"],
            ["branch", "-f", "main", "HEAD"],
            ["update-ref", "refs/heads/main", "HEAD"],
            ["commit", "-m", "x"],
            ["reset", "--hard"],
            ["clean", "-fd"],
            ["worktree", "add", "/tmp/nope"],
        ):
            with self.subTest(argv=argv):
                with self.assertRaises(reproducer.ReadOnlyViolation):
                    self.git.text(argv)

    def test_hash_object_write_flag_is_refused(self) -> None:
        with self.assertRaises(reproducer.ReadOnlyViolation):
            self.git.text(["cat-file", "-w", "blob", "HEAD"])

    def test_empty_argument_vector_is_refused(self) -> None:
        with self.assertRaises(reproducer.ReadOnlyViolation):
            self.git.text([])

    def test_allowlisted_read_succeeds(self) -> None:
        self.assertEqual(len(self.git.resolve_commit("HEAD")), 40)


class SanitizedFixtureTests(unittest.TestCase):
    """The fixture declares its defects up front; the reproducer must match."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="wa006-fixture-"))
        cls.spec = build_sanitized_fixture.load_spec()
        cls.facts = build_sanitized_fixture.build(cls.tmp, cls.spec)
        cls.report = reproducer.reproduce(cls.tmp, cls.facts["commit"], cls.facts["pack_root"])

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_injected_defects_are_detected_exactly(self) -> None:
        self.assertEqual(
            self.report["totals"]["discrepancy_kind_counts"],
            self.spec["expected_discrepancy_kind_counts"],
        )
        self.assertEqual(
            self.report["totals"]["discrepancy_count"], self.spec["expected_discrepancy_total"]
        )

    def test_clean_control_pack_reports_no_discrepancy(self) -> None:
        clean = f"{self.facts['pack_root']}/{self.spec['expected_clean_pack']}/MANIFEST.json"
        matching = [r for r in self.report["per_pack_manifests"] if r["manifest_path"] == clean]
        self.assertEqual(len(matching), 1, "clean control pack was not checked")
        self.assertEqual(matching[0]["discrepancies"], [])
        self.assertEqual(matching[0]["checked_claim_count"], matching[0]["verified_claim_count"])

    def test_relocated_content_is_distinguished_from_absent_content(self) -> None:
        by_kind: dict[str, list[dict]] = {}
        for discrepancy in self.report["discrepancies"]:
            by_kind.setdefault(discrepancy["kind"], []).append(discrepancy)

        relocated = by_kind["MISSING_AT_CLAIMED_PATH_CONTENT_RELOCATED"]
        self.assertEqual(len(relocated), 1)
        self.assertEqual(relocated[0]["subject"], "_spine.py")
        self.assertTrue(relocated[0]["observed"]["content_identical"])
        self.assertEqual(
            relocated[0]["observed"]["present_at"], [self.spec["shared_spine"]["published_at"]]
        )

        absent = by_kind["MISSING_AT_CLAIMED_PATH_CONTENT_ABSENT"]
        self.assertEqual(len(absent), 1)
        self.assertEqual(absent[0]["subject"], "lost.py")
        self.assertIsNone(absent[0]["observed"])

    def test_both_manifest_dialects_are_normalised(self) -> None:
        checked = {r["manifest_path"] for r in self.report["per_pack_manifests"]}
        root = self.facts["pack_root"]
        self.assertIn(f"{root}/alpha-clean/MANIFEST.json", checked)  # object dialect
        self.assertIn(f"{root}/beta-relocated/MANIFEST.json", checked)  # array dialect
        self.assertEqual(self.report["totals"]["file_claims_checked"], 18)

    def test_scan_does_not_move_any_ref_or_head(self) -> None:
        witness = self.report["non_mutation_witness"]
        self.assertTrue(witness["refs_unchanged"])
        self.assertTrue(witness["head_unchanged"])
        self.assertFalse(witness["checkout_performed"])
        self.assertFalse(witness["producer_narrative_read"])
        self.assertGreater(witness["read_only_git_calls"], 0)

    def test_expect_clean_flag_fails_on_a_defective_corpus(self) -> None:
        exit_code = reproducer.main(
            [
                "--repo",
                str(self.tmp),
                "--revision",
                self.facts["commit"],
                "--pack-root",
                self.facts["pack_root"],
                "--out",
                str(self.tmp / "report.json"),
                "--expect-clean",
            ]
        )
        self.assertEqual(exit_code, 1)

    def test_report_is_deterministic_across_runs(self) -> None:
        again = reproducer.reproduce(self.tmp, self.facts["commit"], self.facts["pack_root"])
        self.assertEqual(
            json.dumps(again["discrepancies"], sort_keys=True),
            json.dumps(self.report["discrepancies"], sort_keys=True),
        )

    def test_branch_name_and_immutable_commit_agree(self) -> None:
        """A moving branch must not change what a pinned commit reports."""
        by_name = reproducer.reproduce(self.tmp, "fixture", self.facts["pack_root"])
        self.assertEqual(by_name["target"]["resolved_commit"], self.facts["commit"])
        self.assertEqual(by_name["totals"], self.report["totals"])

    def test_absent_pack_root_is_refused_rather_than_passed(self) -> None:
        with self.assertRaises(reproducer.ClaimReadError):
            reproducer.reproduce(self.tmp, self.facts["commit"], "no-such-root")


class NonPortabilityDetectionTests(unittest.TestCase):
    def test_build_host_absolute_paths_are_collected_with_pointers(self) -> None:
        found = reproducer.collect_absolute_path_claims(
            {
                "root": "/tmp/packs",
                "nested": {"ok": "packs/a.py", "bad": "/home/builder/packs"},
                "list": ["packs/b.py", "/Users/someone/x"],
            }
        )
        self.assertEqual(
            [(entry["json_pointer"], entry["value"]) for entry in found],
            [
                ("$.list[1]", "/Users/someone/x"),
                ("$.nested.bad", "/home/builder/packs"),
                ("$.root", "/tmp/packs"),
            ],
        )

    def test_repository_relative_paths_are_not_flagged(self) -> None:
        self.assertEqual(
            reproducer.collect_absolute_path_claims({"a": "packs/x.py", "b": "./y", "c": "z"}), []
        )


class DialectNormalisationTests(unittest.TestCase):
    def test_claim_without_digest_is_rejected(self) -> None:
        with self.assertRaises(reproducer.ClaimReadError):
            reproducer.normalise_file_claims({"files": {"a.py": {"bytes": 3}}})

    def test_claim_with_uppercase_digest_is_rejected(self) -> None:
        with self.assertRaises(reproducer.ClaimReadError):
            reproducer.normalise_file_claims({"files": {"a.py": {"bytes": 3, "sha256": "A" * 64}}})

    def test_array_entry_without_path_is_rejected(self) -> None:
        with self.assertRaises(reproducer.ClaimReadError):
            reproducer.normalise_file_claims({"files": [{"sha256": "a" * 64, "bytes": 1}]})

    def test_missing_files_key_is_rejected(self) -> None:
        with self.assertRaises(reproducer.ClaimReadError):
            reproducer.normalise_file_claims({"file_count": 0})


class FrozenFindingRecurrenceTests(unittest.TestCase):
    """Recurrence test: the frozen PO-01 findings must reproduce byte-for-byte.

    These commits belong to PO-01 pack branches.  They are read through git
    object reads only.  If the objects are not in the local store the test
    skips with an explicit reason instead of reporting a pass it did not earn.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if not FROZEN_REPORT.exists():
            raise unittest.SkipTest(f"frozen report not present: {FROZEN_REPORT.name}")
        cls.frozen = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))
        cls.repo = _local_repo_root()

    def test_every_frozen_target_recurs(self) -> None:
        checked = 0
        for target in self.frozen["targets"]:
            commit = target["commit"]
            with self.subTest(commit=commit, pack_root=target["pack_root"]):
                if not _commit_present(self.repo, commit):
                    self.skipTest(f"immutable commit {commit} absent from local object store")
                if target["expected_outcome"] == "REFUSED_NO_PACK_ROOT":
                    with self.assertRaises(reproducer.ClaimReadError):
                        reproducer.reproduce(self.repo, commit, target["pack_root"])
                    checked += 1
                    continue
                report = reproducer.reproduce(self.repo, commit, target["pack_root"])
                self.assertEqual(report["target"]["resolved_commit"], commit)
                self.assertEqual(
                    report["totals"]["file_claims_checked"], target["file_claims_checked"]
                )
                self.assertEqual(
                    report["totals"]["file_claims_verified"], target["file_claims_verified"]
                )
                self.assertEqual(
                    report["totals"]["discrepancy_kind_counts"],
                    target["discrepancy_kind_counts"],
                )
                self.assertTrue(report["non_mutation_witness"]["refs_unchanged"])
                self.assertTrue(report["non_mutation_witness"]["head_unchanged"])
                checked += 1
        if checked == 0:
            self.skipTest("no frozen target was resolvable in this object store")

    def test_frozen_relocation_resolves_by_content_on_the_sibling_commit(self) -> None:
        """The spine claim that fails on one commit is satisfied on another.

        This is the finding that makes the discrepancy actionable: the bytes
        were never lost, only republished at one shared path.
        """
        resolution = self.frozen["cross_commit_resolution"]
        for commit in (resolution["failing_commit"], resolution["satisfying_commit"]):
            if not _commit_present(self.repo, commit):
                self.skipTest(f"immutable commit {commit} absent from local object store")
        git = reproducer.ReadOnlyGit(self.repo)
        digest = resolution["claimed_sha256"]

        failing = git.blob(resolution["failing_commit"], resolution["claimed_path_on_failing_commit"])
        self.assertIsNone(failing, "claimed path unexpectedly present on the failing commit")

        shared = git.blob(resolution["failing_commit"], resolution["actual_path_on_failing_commit"])
        self.assertIsNotNone(shared)
        self.assertEqual(reproducer.sha256_hex(shared), digest)
        self.assertEqual(len(shared), resolution["claimed_bytes"])

        for path in resolution["satisfied_paths_on_satisfying_commit"]:
            payload = git.blob(resolution["satisfying_commit"], path)
            self.assertIsNotNone(payload, f"expected {path} on the satisfying commit")
            self.assertEqual(reproducer.sha256_hex(payload), digest)
            self.assertEqual(len(payload), resolution["claimed_bytes"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
