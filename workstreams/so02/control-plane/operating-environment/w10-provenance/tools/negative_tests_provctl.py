#!/usr/bin/env python3
"""Negative tests for provctl.

A checker that only ever passes is a shape-checker, and this estate has already
paid for one of those: a fabricated read-back naming an all-zero commit exited 0
against the producer's own verifier (L3 AC-05). Every test below injects a
failure the classifier must refuse, so the PASS on the real register means
something.

    python3 negative_tests_provctl.py            # from the repository root

Standard library only. No network.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import provctl  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(LANE, "..", "..", "..", "..", ".."))
CORPUS = os.path.join(LANE, "FOUNDER-CORPUS-20260823-v001.json")
REGISTER = os.path.join(LANE, "PROVENANCE-REGISTER-20260823-v001.json")
SOURCE = os.path.join(
    LANE, "..", "FOUNDER-STANDING-INSTRUCTION-20260822.md"
)

# A real founder sentence, and a faithful paraphrase of the same sentence. The
# paraphrase is true, is what he meant, and is not what he said.
REAL_QUOTE = "Model and runtime choice is mine and remains substitutable."
PARAPHRASE = "The founder retains the choice of model and runtime, and it stays substitutable."

# From the ChatGPT advisory proposal, which sits under a `## Verbatim` heading
# in the same file as the founder's own words. This is the trap.
ADVISORY_QUOTE = (
    "ChatGPT should not assume that its current thread contains the complete "
    "estate or impose its own structure."
)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class ProvctlNegativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load(CORPUS)
        cls.register = load(REGISTER)

    def check(self, register):
        return provctl.check_register(self.corpus, register, REPO)

    def one(self, cid="TEST-01", **over):
        base = {
            "constraint_id": cid,
            "provenance_class": "FOUNDER_AUTHORED",
            "recommended_disposition": "RETAIN_FOUNDER_AUTHORED",
            "statement": "A test constraint.",
            "founder_quotations": [{"quote": REAL_QUOTE, "corpus_id": "FC-03"}],
            "evidence_label": "DOCUMENTED",
        }
        base.update(over)
        return {"constraints": [base]}

    # -- the real artifacts pass ------------------------------------------

    def test_the_real_register_passes(self):
        self.assertEqual(self.check(self.register), [])

    def test_the_real_register_has_every_constraint_classified(self):
        for c in self.register["constraints"]:
            self.assertIn(c.get("provenance_class"), provctl.CLASSES,
                          f"{c.get('constraint_id')} is unclassified")

    # -- the quotation test actually tests something ----------------------

    def test_a_faithful_paraphrase_is_refused(self):
        """The single most important test in this file."""
        f = self.check(self.one(founder_quotations=[{"quote": PARAPHRASE}]))
        self.assertTrue(any("QUOTATION_NOT_IN_CORPUS" in x for x in f), f)

    def test_a_real_quotation_is_accepted(self):
        self.assertEqual(self.check(self.one()), [])

    def test_typography_does_not_break_a_real_quotation(self):
        """An em dash retyped as a hyphen is transcription, not paraphrase."""
        q = ("Model and runtime choice is mine and remains substitutable. "
             "Nothing in this instruction binds Obzio to Claude, Cursor or any provider.")
        self.assertEqual(self.check(self.one(founder_quotations=[{"quote": q}])), [])

    def test_a_quotation_from_the_advisory_proposal_is_refused(self):
        """The ChatGPT proposal is verbatim, is in the founder record, and is
        not founder text. Admitting it would reproduce the original defect."""
        f = self.check(self.one(founder_quotations=[{"quote": ADVISORY_QUOTE}]))
        self.assertTrue(any("QUOTATION_NOT_IN_CORPUS" in x for x in f), f)

    def test_founder_authored_without_any_quotation_is_refused(self):
        f = self.check(self.one(founder_quotations=[]))
        self.assertTrue(any("FOUNDER_AUTHORED_WITHOUT_QUOTATION" in x for x in f), f)

    def test_a_miscited_segment_is_refused(self):
        f = self.check(self.one(founder_quotations=[
            {"quote": REAL_QUOTE,
             "segment_heading": "Verbatim — founder clarification on the ChatGPT account"}
        ]))
        self.assertTrue(any("QUOTATION_SEGMENT_MISMATCH" in x for x in f), f)

    # -- "an unclassified constraint is not in force" ---------------------

    def test_an_unclassified_constraint_is_refused(self):
        f = self.check(self.one(provenance_class=None))
        self.assertTrue(any("UNCLASSIFIED" in x for x in f), f)

    def test_an_invented_fourth_class_is_refused(self):
        f = self.check(self.one(provenance_class="FOUNDER_BOUND"))
        self.assertTrue(any("UNKNOWN_CLASS" in x for x in f), f)

    # -- earned needs a receipt that exists -------------------------------

    def test_earned_without_a_named_defect_is_refused(self):
        f = self.check(self.one(
            provenance_class="EARNED", recommended_disposition="RETAIN_EARNED",
            founder_quotations=None, defect_evidence_paths=["AGENTS.md"]))
        self.assertTrue(any("EARNED_WITHOUT_NAMED_DEFECT" in x for x in f), f)

    def test_earned_with_a_receipt_that_does_not_exist_is_refused(self):
        f = self.check(self.one(
            provenance_class="EARNED", recommended_disposition="RETAIN_EARNED",
            founder_quotations=None, defect_caught="something broke",
            defect_evidence_paths=["receipts/does/not/exist.json"]))
        self.assertTrue(any("DEFECT_RECEIPT_MISSING" in x for x in f), f)

    def test_earned_with_no_receipt_at_all_is_refused(self):
        f = self.check(self.one(
            provenance_class="EARNED", recommended_disposition="RETAIN_EARNED",
            founder_quotations=None, defect_caught="something broke"))
        self.assertTrue(any("EARNED_WITHOUT_RECEIPT" in x for x in f), f)

    # -- assistant-authored is void unless ratified -----------------------

    def test_assistant_authored_carrying_a_founder_quotation_is_refused(self):
        f = self.check(self.one(
            provenance_class="ASSISTANT_AUTHORED",
            recommended_disposition="PURGE",
            what_it_constrains="x", removal_unlocks="y"))
        self.assertTrue(
            any("ASSISTANT_AUTHORED_WITH_FOUNDER_QUOTATION" in x for x in f), f)

    def test_assistant_authored_without_an_unlock_is_refused(self):
        f = self.check(self.one(
            provenance_class="ASSISTANT_AUTHORED",
            recommended_disposition="PURGE",
            founder_quotations=None, what_it_constrains="x"))
        self.assertTrue(
            any("ASSISTANT_AUTHORED_WITHOUT_UNLOCK" in x for x in f), f)

    def test_assistant_authored_may_not_be_retained_silently(self):
        f = self.check(self.one(
            provenance_class="ASSISTANT_AUTHORED",
            recommended_disposition="RETAIN_EARNED",
            founder_quotations=None, what_it_constrains="x", removal_unlocks="y"))
        self.assertTrue(any("void unless ratified" in x for x in f), f)

    def test_seek_ratification_without_a_binary_question_is_refused(self):
        f = self.check(self.one(
            provenance_class="ASSISTANT_AUTHORED",
            recommended_disposition="SEEK_RATIFICATION",
            founder_quotations=None, what_it_constrains="x", removal_unlocks="y"))
        self.assertTrue(
            any("SEEK_RATIFICATION_WITHOUT_BINARY_QUESTION" in x for x in f), f)

    # -- a void quote has to be as real as an authoring quote -------------

    def test_an_invented_void_quotation_is_refused(self):
        f = self.check(self.one(
            provenance_class="ASSISTANT_AUTHORED",
            recommended_disposition="PURGE",
            founder_quotations=None, what_it_constrains="x", removal_unlocks="y",
            founder_void_quote="I hereby void this constraint."))
        self.assertTrue(any("FOUNDER_VOID_QUOTE_NOT_IN_CORPUS" in x for x in f), f)

    def test_an_invented_ratification_quotation_is_refused(self):
        f = self.check(self.one(
            provenance_class="EARNED", recommended_disposition="RETAIN_EARNED",
            founder_quotations=None, defect_caught="d",
            defect_evidence_paths=["AGENTS.md"],
            founder_ratification_quote="I ratify this control."))
        self.assertTrue(
            any("FOUNDER_RATIFICATION_QUOTE_NOT_IN_CORPUS" in x for x in f), f)

    # -- bookkeeping ------------------------------------------------------

    def test_a_duplicate_constraint_id_is_refused(self):
        r = self.one()
        r["constraints"].append(copy.deepcopy(r["constraints"][0]))
        self.assertTrue(any("DUPLICATE_CONSTRAINT_ID" in x for x in self.check(r)), r)

    def test_a_miscounted_register_is_refused(self):
        r = copy.deepcopy(self.register)
        r["counts"]["FOUNDER_AUTHORED"] += 1
        self.assertTrue(any("COUNTS_MISMATCH" in x for x in self.check(r)))

    def test_a_wrong_total_is_refused(self):
        r = copy.deepcopy(self.register)
        r["total_classified"] = 76
        self.assertTrue(any("TOTAL_MISMATCH" in x for x in self.check(r)))

    def test_an_unlabelled_claim_is_refused(self):
        f = self.check(self.one(evidence_label="PROBABLY_TRUE"))
        self.assertTrue(any("BAD_EVIDENCE_LABEL" in x for x in f), f)

    # -- the corpus cannot drift out from under a verdict -----------------

    def test_an_edited_founder_record_invalidates_the_corpus(self):
        with open(SOURCE, "rb") as fh:
            src = fh.read()
        with tempfile.TemporaryDirectory() as d:
            tampered = os.path.join(d, "tampered.md")
            with open(tampered, "wb") as fh:
                fh.write(src.replace(b"remains substitutable", b"remains fixed"))
            rc = provctl.main(["verify-corpus", tampered, CORPUS])
        self.assertEqual(rc, 1, "a changed founder record must invalidate the corpus")

    def test_the_corpus_rebuilds_byte_identical(self):
        self.assertEqual(provctl.main(["verify-corpus", SOURCE, CORPUS]), 0)

    def test_the_advisory_proposal_is_excluded_from_the_corpus(self):
        headings = [s["heading"] for s in self.corpus["segments"]
                    if not s["is_founder_corpus"]]
        self.assertEqual(len(headings), 1)
        self.assertIn("advisory", headings[0].lower())

    def test_three_founder_segments_and_no_more(self):
        founder = [s for s in self.corpus["segments"] if s["is_founder_corpus"]]
        self.assertEqual(len(founder), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
