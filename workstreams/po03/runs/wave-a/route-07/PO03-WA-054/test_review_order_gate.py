"""Falsification tests for the PO03-WA-054 blind review-order gate.

The hypothesis fails if a producer conclusion can be opened before the rubric is
frozen, if the rubric can be amended after producer contact, or if the ledger can
be rewritten to hide either event.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from review_order_gate import (  # noqa: E402
    LedgerEntry,
    LedgerTampering,
    Phase,
    ReviewOrderGate,
    ReviewOrderViolation,
    SourceClass,
    classify_source,
)

CRITERIA = "workstreams/po03/evidence/criteria-freeze.json"
TASK_INPUT = "workstreams/po03/control/tasks/PO03-WA-001/input.json"
TARGET_CODE = "workstreams/po03/runs/wave-a/route-01/PO03-WA-001/custody_fsm.py"
FINDING = "workstreams/po03/runs/wave-a/route-01/PO03-WA-001/FINDING.md"
PRODUCER_RESULT = "workstreams/po03/runs/wave-a/route-01/PO03-WA-001/result.json"


class ClassificationTests(unittest.TestCase):
    def test_frozen_criteria_are_criteria(self):
        for path in (
            CRITERIA,
            "workstreams/po03/evidence/source-lock.json",
            TASK_INPUT,
            "workstreams/po03/control/tasks/PO03-WA-001/acceptance.json",
            "workstreams/po03/contracts/transactional-result.schema.json",
            "workstreams/po03/control/completions/route-01.json",
        ):
            with self.subTest(path=path):
                self.assertIs(SourceClass.CRITERIA, classify_source(path))

    def test_narratives_and_dispositions_are_producer_conclusions(self):
        for path in (
            FINDING,
            PRODUCER_RESULT,
            "workstreams/po03/runs/wave-a/route-05/PO03-WA-033/README.md",
            "workstreams/po03/runs/wave-a/route-06/PO03-WA-041/observed-result.json",
            "workstreams/po03/runs/wave-a/route-05/PO03-WA-033/evidence/run-log.txt",
            "workstreams/po03/control/results/PO03-WA-001.json",
            "workstreams/po03/control/results/route-01-ingestion.json",
        ):
            with self.subTest(path=path):
                self.assertIs(SourceClass.PRODUCER_CONCLUSION, classify_source(path))

    def test_immutable_code_and_manifests_are_target_artifacts(self):
        for path in (
            TARGET_CODE,
            "workstreams/po03/runs/wave-a/route-01/PO03-WA-001/manifest.json",
            "workstreams/po03/runs/wave-a/route-06/PO03-WA-041/artifact-manifest.json",
        ):
            with self.subTest(path=path):
                self.assertIs(SourceClass.TARGET_ARTIFACT, classify_source(path))


class OrderingTests(unittest.TestCase):
    def setUp(self):
        self.gate = ReviewOrderGate()

    def test_a_correct_review_passes_the_audit(self):
        self.gate.open_source(CRITERIA)
        self.gate.open_source(TASK_INPUT)
        self.gate.freeze_rubric("a" * 64)
        self.gate.open_source(TARGET_CODE)
        self.gate.freeze_outcomes("b" * 64)
        self.gate.open_source(FINDING)
        audit = self.gate.audit()
        self.assertTrue(audit["blind_order_held"], audit)
        self.assertEqual([], audit["producer_reads_before_freeze"])

    def test_reading_a_finding_before_freeze_is_refused(self):
        self.gate.open_source(CRITERIA)
        with self.assertRaises(ReviewOrderViolation):
            self.gate.open_source(FINDING)
        self.assertFalse(self.gate.audit()["blind_order_held"])

    def test_reading_target_code_before_freeze_is_refused(self):
        with self.assertRaises(ReviewOrderViolation):
            self.gate.open_source(TARGET_CODE)

    def test_a_denied_open_is_still_recorded_in_the_ledger(self):
        try:
            self.gate.open_source(FINDING)
        except ReviewOrderViolation:
            pass
        self.assertEqual(1, len(self.gate.entries))
        self.assertEqual("OPEN_DENIED", self.gate.entries[0].event)
        self.assertTrue(self.gate.verify_chain())

    def test_the_rubric_cannot_be_frozen_twice(self):
        self.gate.freeze_rubric("a" * 64)
        with self.assertRaises(ReviewOrderViolation):
            self.gate.freeze_rubric("c" * 64)

    def test_an_empty_rubric_digest_is_refused(self):
        with self.assertRaises(ValueError):
            self.gate.freeze_rubric("")

    def test_outcomes_cannot_be_frozen_before_the_rubric(self):
        with self.assertRaises(ReviewOrderViolation):
            self.gate.freeze_outcomes("b" * 64)


class AmendmentTests(unittest.TestCase):
    def setUp(self):
        self.gate = ReviewOrderGate()
        self.gate.open_source(CRITERIA)
        self.gate.freeze_rubric("a" * 64)

    def test_an_amendment_before_producer_contact_is_allowed_and_logged(self):
        entry = self.gate.amend_rubric("d" * 64, "manifest filename was over-constrained")
        self.assertEqual("RUBRIC_AMEND", entry.event)
        self.assertEqual("d" * 64, self.gate.rubric_digest)
        self.assertTrue(self.gate.audit()["blind_order_held"])

    def test_an_amendment_after_producer_contact_is_refused(self):
        self.gate.freeze_outcomes("b" * 64)
        self.gate.phase = Phase.RUBRIC_FROZEN  # re-open only to isolate the amendment path
        self.gate.open_source(FINDING)
        with self.assertRaises(ReviewOrderViolation):
            self.gate.amend_rubric("e" * 64, "producer says the manifest is fine")

    def test_an_amendment_requires_a_justification(self):
        with self.assertRaises(ValueError):
            self.gate.amend_rubric("d" * 64, "   ")

    def test_amending_an_unfrozen_rubric_is_refused(self):
        fresh = ReviewOrderGate()
        with self.assertRaises(ReviewOrderViolation):
            fresh.amend_rubric("d" * 64, "why")


class TamperTests(unittest.TestCase):
    def setUp(self):
        self.gate = ReviewOrderGate()
        self.gate.open_source(CRITERIA)
        self.gate.freeze_rubric("a" * 64)
        self.gate.open_source(TARGET_CODE)

    def test_a_clean_ledger_verifies(self):
        self.assertTrue(self.gate.verify_chain())

    def test_rewriting_an_entry_is_detected(self):
        original = self.gate.entries[0]
        self.gate.entries[0] = LedgerEntry(
            original.seq, original.event, CRITERIA, SourceClass.CRITERIA.value, original.phase, "x"
        )
        with self.assertRaises(LedgerTampering):
            self.gate.verify_chain()

    def test_deleting_an_entry_is_detected(self):
        del self.gate.entries[1]
        with self.assertRaises(LedgerTampering):
            self.gate.verify_chain()

    def test_reordering_entries_is_detected(self):
        self.gate.entries[0], self.gate.entries[1] = self.gate.entries[1], self.gate.entries[0]
        with self.assertRaises(LedgerTampering):
            self.gate.verify_chain()

    def test_replacing_the_genesis_marker_is_detected(self):
        self.gate.chain[0] = "forged"
        with self.assertRaises(LedgerTampering):
            self.gate.verify_chain()

    def test_hiding_an_early_producer_read_by_truncation_is_detected(self):
        gate = ReviewOrderGate()
        try:
            gate.open_source(FINDING)
        except ReviewOrderViolation:
            pass
        gate.entries.clear()
        with self.assertRaises(LedgerTampering):
            gate.verify_chain()


if __name__ == "__main__":
    unittest.main()
