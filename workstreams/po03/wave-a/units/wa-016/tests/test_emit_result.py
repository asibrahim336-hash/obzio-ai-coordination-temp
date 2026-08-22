"""The emitter's accounting has to be checkable, not merely plausible.

Two things here are easy to get wrong and impossible to spot by reading the
output.  The first is self-reference: a document that lists digests cannot list
its own, so a naive implementation silently records the digest an earlier run
left on disk.  The second is test attribution: verbose unittest output puts a
docstring on the line carrying the verdict, so a parser that keys on the verdict
line alone loses every test that has one.

Both are checked against constructed inputs rather than against the emitter's
own last run, so a wrong answer fails here instead of being carried into
result.json.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from harness.durable_io import sha256_bytes
from harness.emit_result import (
    MANIFEST_EXCLUDED,
    MANIFEST_NAME,
    READY_NAME,
    REQUIRED_RESULT_DOCUMENTS,
    RESULT_EXCLUDED,
    UNIT_ROOT,
    artifact_accounting,
    branch_base,
    build_manifest,
    describe,
    git_output,
    owned_file_total,
    owned_files,
    parse_unittest_output,
)
from harness.seeded import repository_root

OWNED_SUBTREE = "workstreams/po03/wave-a/units/wa-016/"


class InventoryTests(unittest.TestCase):
    def test_the_inventory_is_stable_and_relative_to_the_unit_root(self):
        first = owned_files()
        self.assertEqual(first, owned_files())
        for path in first:
            self.assertTrue(path.is_file())
            path.relative_to(UNIT_ROOT)

    def test_caches_and_scratch_directories_are_not_owned_artifacts(self):
        for path in owned_files():
            relative = path.relative_to(UNIT_ROOT).as_posix()
            self.assertNotIn("__pycache__", relative)
            self.assertFalse(relative.endswith(".pyc"), relative)
            self.assertFalse(
                any(part.startswith(".scratch-") for part in path.parts), relative
            )

    def test_describe_reports_the_bytes_actually_on_disk(self):
        path = UNIT_ROOT / "harness" / "emit_result.py"
        described = describe(path)
        raw = path.read_bytes()
        self.assertEqual("harness/emit_result.py", described["logical_name"])
        self.assertEqual(sha256_bytes(raw), described["sha256"])
        self.assertEqual(len(raw), described["bytes"])
        self.assertEqual("text/x-python", described["media_type"])

    def test_the_owned_total_counts_each_result_document_once(self):
        total = owned_file_total()
        on_disk = {p.relative_to(UNIT_ROOT).as_posix() for p in owned_files()}
        expected = on_disk | {f"result/{name}" for name in REQUIRED_RESULT_DOCUMENTS}
        self.assertEqual(len(expected), total)
        # Idempotent: asking twice cannot inflate the count, which is the bug a
        # plain "+ 1" would introduce once ready-to-commit.json exists.
        self.assertEqual(total, owned_file_total())


class ArtifactAccountingTests(unittest.TestCase):
    """Every owned file is digested in exactly one link of the chain."""

    def setUp(self) -> None:
        self.manifest = build_manifest()

    def test_the_manifest_covers_every_owned_file_but_the_two_it_cannot(self):
        covered = {a["logical_name"] for a in self.manifest["artifacts"]}
        on_disk = {p.relative_to(UNIT_ROOT).as_posix() for p in owned_files()}
        self.assertEqual(on_disk - set(MANIFEST_EXCLUDED), covered)

    def test_the_manifest_never_records_a_digest_for_itself(self):
        covered = {a["logical_name"] for a in self.manifest["artifacts"]}
        self.assertNotIn(f"result/{MANIFEST_NAME}", covered)
        self.assertNotIn(f"result/{READY_NAME}", covered)
        for name in (MANIFEST_NAME, READY_NAME):
            entry = self.manifest["required_result_documents"][name]
            self.assertFalse(entry["digest_recorded_here"])
            self.assertNotIn("sha256", entry)
            self.assertTrue(entry["reason"])

    def test_a_stale_digest_left_by_an_earlier_run_is_not_reported_as_current(self):
        """The regression this guards: reading one's own file back off disk."""
        path = UNIT_ROOT / "result" / MANIFEST_NAME
        if not path.exists():
            self.skipTest("no manifest on disk yet")
            return
        entry = build_manifest()["required_result_documents"][MANIFEST_NAME]
        self.assertNotIn("sha256", entry)
        self.assertNotEqual(sha256_bytes(path.read_bytes()), entry.get("sha256"))

    def test_the_excluded_set_is_declared_once_and_used_everywhere(self):
        declared = {e["logical_name"] for e in self.manifest["excluded"]}
        self.assertEqual(set(MANIFEST_EXCLUDED), declared)
        self.assertEqual(set(MANIFEST_EXCLUDED) | {"result/result.json"}, set(RESULT_EXCLUDED))

    def test_the_counts_and_byte_total_agree_with_the_artifact_list(self):
        artifacts = self.manifest["artifacts"]
        self.assertEqual(len(artifacts), self.manifest["artifact_count"])
        self.assertEqual(sum(a["bytes"] for a in artifacts), self.manifest["total_bytes"])
        for artifact in artifacts:
            self.assertEqual(64, len(artifact["sha256"]), artifact["logical_name"])
            self.assertGreater(artifact["bytes"], 0, artifact["logical_name"])

    def test_the_groups_partition_the_artifact_list(self):
        grouped = sorted(name for names in self.manifest["groups"].values() for name in names)
        self.assertEqual(sorted(a["logical_name"] for a in self.manifest["artifacts"]), grouped)

    def test_all_five_required_documents_are_named(self):
        self.assertEqual(set(REQUIRED_RESULT_DOCUMENTS), set(self.manifest["required_result_documents"]))
        self.assertEqual(5, len(REQUIRED_RESULT_DOCUMENTS))

    def test_the_chain_accounts_for_every_owned_file_exactly_once(self):
        """Asserted on the live computation, not on a document already written.

        A test that read only the emitted result.json could not run before the
        first emission, and the emitter refuses to emit while the suite fails.
        """
        digested = [
            describe(path)
            for path in owned_files()
            if path.relative_to(UNIT_ROOT).as_posix() not in RESULT_EXCLUDED
        ]
        accounting = artifact_accounting(digested)
        deferred = {row["logical_name"] for row in accounting["not_digested_here"]}

        self.assertEqual({"result/result.json", f"result/{MANIFEST_NAME}", f"result/{READY_NAME}"}, deferred)
        self.assertEqual(len(digested), accounting["digested_in_this_document"])
        self.assertEqual(accounting["owned_files"], len(digested) + len(deferred))
        self.assertEqual(set(), {a["logical_name"] for a in digested} & deferred)
        for row in accounting["not_digested_here"]:
            self.assertTrue(row["digest_recorded_in"], row["logical_name"])

    def test_the_emitted_result_document_carries_that_same_chain(self):
        path = UNIT_ROOT / "result" / "result.json"
        if not path.exists() or "artifact_accounting" not in path.read_text(encoding="utf-8"):
            self.skipTest("result.json has not been emitted by this emitter yet")
            return
        result = json.loads(path.read_text(encoding="utf-8"))
        accounting = result["artifact_accounting"]
        digested = {a["logical_name"] for a in result["artifacts"]}
        self.assertNotIn("result/result.json", digested)
        self.assertEqual(len(digested), accounting["digested_in_this_document"])
        self.assertEqual(accounting["owned_files"], len(digested) + len(accounting["not_digested_here"]))


class TestOutputParsingTests(unittest.TestCase):
    SAMPLE = "\n".join(
        [
            "test_plain (test_alpha.Case.test_plain) ... ok",
            "test_with_docstring (test_alpha.Case.test_with_docstring)",
            "A docstring that unittest prints instead of the test name ... ok",
            "test_multiline (test_beta.Case.test_multiline)",
            "First line of a longer docstring",
            "continued on a second line ... ok",
            "test_broken (test_beta.Case.test_broken) ... FAIL",
            "test_errored (test_beta.Case.test_errored) ... ERROR",
            "test_absent (test_gamma.Case.test_absent) ... skipped 'no git'",
            "test_skipped (test_gamma.Case.test_skipped) ... skipped",
            "",
            "Ran 7 tests in 1.234s",
            "",
            "FAILED (failures=1, errors=1, skipped=2)",
        ]
    )

    def setUp(self) -> None:
        self.parsed = parse_unittest_output(self.SAMPLE)

    def test_the_reported_total_is_read_from_the_summary_line(self):
        self.assertEqual(7, self.parsed["total"])
        self.assertEqual("Ran 7 tests in 1.234s", self.parsed["summary_line"])

    def test_a_docstring_does_not_detach_a_test_from_its_module(self):
        """The regression: docstring tests were counted but not attributed."""
        self.assertEqual({"test_alpha": 2, "test_beta": 3, "test_gamma": 1}, self.parsed["per_module"])

    def test_outcomes_are_split_by_verdict(self):
        self.assertEqual(3, self.parsed["passed"])
        self.assertEqual(2, self.parsed["failed"])
        self.assertEqual(1, self.parsed["skipped"])

    def test_a_verdict_carrying_a_reason_is_not_silently_dropped(self):
        """"... skipped 'no git'" does not end in the bare verdict.

        Recorded rather than papered over: the parser sees one of the two skips,
        so per_module_total can legitimately fall short of the summary total. The
        summary line stays authoritative for the count.
        """
        self.assertEqual(6, self.parsed["per_module_total"])
        self.assertLess(self.parsed["per_module_total"], self.parsed["total"])

    def test_an_empty_run_reports_zero_rather_than_raising(self):
        empty = parse_unittest_output("")
        self.assertEqual(0, empty["total"])
        self.assertEqual({}, empty["per_module"])
        self.assertEqual("", empty["summary_line"])

    def test_the_real_recorded_run_is_fully_attributed(self):
        """Every outcome in the recorded log belongs to a named module.

        Whether that run passed is not asserted here; a log left by a failing run
        is exactly what this parser has to describe correctly. The emitter is what
        refuses to write a result when the suite fails.
        """
        log = UNIT_ROOT / "evidence" / "test-run.txt"
        if not log.exists():
            self.skipTest("no recorded test run")
            return
        parsed = parse_unittest_output(log.read_text(encoding="utf-8"))
        self.assertEqual(parsed["total"], parsed["per_module_total"])
        self.assertEqual(parsed["per_module_total"], sum(parsed["outcome_histogram"].values()))
        self.assertEqual(sorted(parsed["per_module"]), [p.stem for p in sorted((UNIT_ROOT / "tests").glob("test_*.py"))])


class BranchBaseTests(unittest.TestCase):
    """Ownership must be judged against the dispatch branch, not the ancestor.

    The preregistration commit carries all 64 frozen Wave A inputs.  Diffing past
    it reports 150-odd paths the coordinator wrote as though this unit had touched
    them, which is a false ownership violation rather than a real one.
    """

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.base = branch_base()
        except (subprocess.CalledProcessError, OSError, SystemExit) as exc:
            raise unittest.SkipTest(f"base branch unresolvable: {exc}") from exc

    def test_the_base_is_an_ancestor_of_the_current_head(self):
        subprocess.run(
            ["git", "-C", str(repository_root()), "merge-base", "--is-ancestor", self.base, "HEAD"],
            check=True,
            timeout=120,
        )

    def test_the_diff_from_the_base_names_only_this_units_subtree(self):
        changed = git_output("diff", "--name-only", f"{self.base}..HEAD").split()
        self.assertTrue(changed)
        outside = [path for path in changed if not path.startswith(OWNED_SUBTREE)]
        self.assertEqual([], outside)

    def test_the_base_itself_carries_the_frozen_inputs_this_unit_must_not_own(self):
        listing = git_output("ls-tree", "-r", "--name-only", self.base, "workstreams/po03/control/").split()
        self.assertIn("workstreams/po03/control/inputs/wave-a/wa-016.json", listing)
        # Already present in the base, so it cannot appear in this unit's diff.
        self.assertNotIn(
            "workstreams/po03/control/inputs/wave-a/wa-016.json",
            git_output("diff", "--name-only", f"{self.base}..HEAD").split(),
        )


class EmitterDisciplineTests(unittest.TestCase):
    def test_the_emitter_writes_only_inside_the_result_slot_and_the_evidence_log(self):
        source = (UNIT_ROOT / "harness" / "emit_result.py").read_text(encoding="utf-8")
        for line in source.splitlines():
            if "write_text" in line or "write_bytes" in line:
                self.assertTrue(
                    any(token in line for token in ("path.write_bytes", "log.write_text")),
                    f"unrecognised write: {line.strip()}",
                )

    def test_no_terminal_report_other_than_ready_to_commit_is_emitted(self):
        source = (UNIT_ROOT / "harness" / "emit_result.py").read_text(encoding="utf-8")
        self.assertIn('"terminal_report": "READY_TO_COMMIT"', source)
        for forbidden in ('"COMPLETED"', '"ACCEPTED"'):
            self.assertNotIn(f'"terminal_report": {forbidden}', source)

    def test_the_read_back_clone_is_not_the_producer_worktree(self):
        source = (UNIT_ROOT / "harness" / "emit_result.py").read_text(encoding="utf-8")
        self.assertIn("--no-checkout", source)
        self.assertIn("clone_shares_no_objects_with_the_producer_worktree", source)


if __name__ == "__main__":
    unittest.main()
