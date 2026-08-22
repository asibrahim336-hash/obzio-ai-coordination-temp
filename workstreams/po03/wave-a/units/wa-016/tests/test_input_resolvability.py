"""Recurrence test for M2: a frozen input must be able to locate its own base.

Resume-from-immutable-input is only real if the pointers inside that input
resolve in the repository the recovering worker actually has.  A commit-shaped
string is not a reachable commit, and nothing in the seeded controls checks the
difference.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from harness import input_resolvability
from harness.input_resolvability import (
    COMMIT_POINTER_KEYS,
    WAVE_A_INPUT_DIR,
    check_input,
    check_wave_a,
    gate,
    git_available,
    object_type,
)
from harness.seeded import PINNED_DIGEST_KEYS, repository_root

UNIT_ROOT = Path(__file__).resolve().parents[1]
DISPOSITIONS = {"RESOLVES", "UNRESOLVABLE", "MISSING", "DRIFTED", "NOT_SUPPORTED"}


class ReportShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = repository_root()
        cls.report = check_wave_a(cls.repo)

    def test_every_frozen_wave_a_input_is_inspected(self):
        on_disk = sorted((self.repo / WAVE_A_INPUT_DIR).glob("*.json"))
        self.assertEqual(len(on_disk), self.report["input_count"])
        self.assertEqual(64, self.report["input_count"])

    def test_every_pointer_carries_a_declared_disposition(self):
        for row in self.report["rows"]:
            for finding in row["findings"]:
                self.assertIn(finding["disposition"], DISPOSITIONS)

    def test_every_pointer_the_module_knows_about_is_checked(self):
        expected = set(COMMIT_POINTER_KEYS) | set(PINNED_DIGEST_KEYS.values())
        for row in self.report["rows"]:
            self.assertEqual(expected, {f["pointer"] for f in row["findings"]})

    def test_the_counts_agree_with_the_rows(self):
        failing = [r for r in self.report["rows"] if not r["resumable_from_immutable_input"]]
        self.assertEqual(len(failing), self.report["non_resumable_count"])
        self.assertEqual(
            self.report["input_count"],
            self.report["resumable_count"] + self.report["non_resumable_count"],
        )

    def test_this_units_own_input_is_among_them(self):
        rows = {r["task_id"]: r for r in self.report["rows"]}
        self.assertIn("PO03-WA-016", rows)
        self.assertEqual(
            "workstreams/po03/control/inputs/wave-a/wa-016.json", rows["PO03-WA-016"]["input_path"]
        )


class DefectTests(unittest.TestCase):
    """The observed defect, recorded as an assertion so a fix is visible.

    Every Wave A input pins ``minimum_protocol_ancestor`` to a full-length SHA
    that does not exist, while its own seven-character prefix resolves to a
    different commit.  When the generator is fixed these assertions invert, which
    is the point: the recurrence test then reports the change instead of passing
    quietly.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = repository_root()
        if not git_available(cls.repo):
            raise unittest.SkipTest("git unavailable: pointer resolution is NOT_SUPPORTED here")
        cls.report = check_wave_a(cls.repo)

    def test_the_only_unresolvable_pointer_is_the_protocol_ancestor(self):
        self.assertEqual(
            {"minimum_protocol_ancestor"},
            set(self.report["pointer_failure_counts"]),
            "a pointer other than minimum_protocol_ancestor now fails; the defect has changed shape",
        )

    def test_the_defect_is_systemic_across_the_whole_wave(self):
        self.assertEqual(self.report["input_count"], self.report["non_resumable_count"])
        self.assertEqual(
            self.report["input_count"],
            self.report["pointer_failure_counts"]["minimum_protocol_ancestor"],
        )

    def test_the_pinned_ancestor_does_not_resolve_but_its_prefix_does(self):
        row = next(r for r in self.report["rows"] if r["task_id"] == "PO03-WA-016")
        finding = next(f for f in row["findings"] if f["pointer"] == "minimum_protocol_ancestor")
        self.assertEqual("UNRESOLVABLE", finding["disposition"])
        self.assertEqual("commit", finding["abbreviated_resolves_to"])
        resolved = object_type(self.repo, finding["abbreviated_prefix"])
        self.assertEqual("commit", resolved)
        self.assertNotEqual(finding["value"][:7], finding["value"])

    def test_the_commission_commit_pointer_does_resolve(self):
        for row in self.report["rows"]:
            finding = next(f for f in row["findings"] if f["pointer"] == "commission_commit")
            self.assertEqual("RESOLVES", finding["disposition"], row["task_id"])

    def test_the_gate_refuses_dispatch_while_the_defect_stands(self):
        passed, report = gate(self.repo)
        self.assertFalse(passed)
        self.assertGreater(report["non_resumable_count"], 0)


class GatePositiveTests(unittest.TestCase):
    """The gate must be able to pass, or it is not a gate but a constant."""

    def setUp(self) -> None:
        self.repo = repository_root()
        if not git_available(self.repo):
            self.skipTest("git unavailable")
        # check_input reports paths relative to the repository, so the fixture has
        # to live inside it; it goes in this unit's own subtree and is removed.
        self.scratch = Path(tempfile.mkdtemp(prefix=".scratch-gate-", dir=UNIT_ROOT))
        self.addCleanup(shutil.rmtree, self.scratch, True)

    def test_a_repaired_input_resolves_completely(self):
        source = self.repo / WAVE_A_INPUT_DIR / "wa-016.json"
        document = json.loads(source.read_text(encoding="utf-8"))
        resolved = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.strip()
        document["source_base"]["minimum_protocol_ancestor"] = resolved

        repaired = self.scratch / "wa-016-repaired.json"
        repaired.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        row = check_input(repaired, self.repo, have_git=True)
        self.assertTrue(row["resumable_from_immutable_input"], row["findings"])
        self.assertEqual(0, row["unresolvable_count"])
        self.assertEqual({"RESOLVES"}, {f["disposition"] for f in row["findings"]})


class NotSupportedTests(unittest.TestCase):
    def test_pointer_resolution_without_git_is_not_supported_rather_than_guessed(self):
        row = check_input(
            repository_root() / WAVE_A_INPUT_DIR / "wa-016.json",
            repository_root(),
            have_git=False,
        )
        pointer_findings = [f for f in row["findings"] if f["pointer"] in COMMIT_POINTER_KEYS]
        self.assertEqual({"NOT_SUPPORTED"}, {f["disposition"] for f in pointer_findings})
        self.assertEqual({"git unavailable"}, {f["reason"] for f in pointer_findings})

    def test_an_absent_object_reports_no_type_rather_than_raising(self):
        self.assertIsNone(object_type(repository_root(), "f" * 40))

    def test_a_directory_that_is_not_a_repository_reports_git_unavailable(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertFalse(git_available(Path(plain)))

    def test_the_module_reads_and_never_writes_the_inputs_it_inspects(self):
        source = (Path(input_resolvability.__file__)).read_text(encoding="utf-8")
        for forbidden in ("write_text", "write_bytes", "unlink", "open("):
            self.assertNotIn(forbidden, source, forbidden)


if __name__ == "__main__":
    unittest.main()
