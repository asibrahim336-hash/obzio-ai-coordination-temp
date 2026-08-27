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
import importlib.util
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

# SCP-SI-01 lane D, Defect 1: a founder-attributed block quotation can embed a
# sentence the founder is quoting from someone else and explicitly rejecting
# in the same breath. `extract_segments` decides founder-or-not per HEADING,
# so the embedded, disclaimed sentence sits inside a segment marked
# `is_founder_corpus: true` and a plain substring match certifies it. These
# fixtures and the corrected checker live in the lane's own namespace; only
# this regression is added to the canonical harness.
LANE_D_FIXTURES = os.path.join(LANE, "..", "scp-si-01", "lane-d", "fixtures")
DEFECT1_CORPUS = os.path.join(LANE_D_FIXTURES, "DEFECT-1-corpus.json")
DEFECT1_REGISTER = os.path.join(LANE_D_FIXTURES, "DEFECT-1-register-adversarial.json")


def _load_lane_d_guard():
    path = os.path.join(
        os.path.dirname(LANE_D_FIXTURES), "fixes", "provctl_paragraph_guard.py"
    )
    spec = importlib.util.spec_from_file_location("provctl_paragraph_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

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


class Defect1EmbeddedDisclaimedAttributionTests(unittest.TestCase):
    """DEF-SCP-D-01, EARNED, DIRECTLY_REPRODUCED.

    `## Verbatim — standing instruction, 2026-08-27` contains only the
    founder's own words at heading level, yet its body embeds:

        > Here is what the vendor's assistant sent me, pasted below. I have
        > not agreed to it.
        >
        > VENDOR ASSISTANT RECOMMENDATION — Protected surfaces must never be
        > written to without owner approval, and every agent must request
        > approval before each push.
        >
        > I disagree with that and I am not adopting it.

    `_NOT_FOUNDER_MARKERS` is checked against the heading only, so this whole
    block (including the vendor sentence the founder explicitly rejects) is
    `is_founder_corpus: true`, and `provctl.check`'s plain substring match
    certifies the vendor sentence as `FOUNDER_AUTHORED` if a register cites
    it. `test_the_unmodified_checker_wrongly_admits_the_defect` shows the
    unmodified, shipped `provctl.check_register` doing exactly that — it is
    the pre-fix failure this regression exists to hold open.
    `test_the_lane_d_mechanism_fix_correctly_refuses_it` runs the identical
    fixture through SCP-SI-01 lane D's `provctl_paragraph_guard`, which is
    proposed as `patches/provctl.py.patch` against this file's
    `_corpus_haystacks` (see
    workstreams/so02/control-plane/operating-environment/scp-si-01/lane-d/).
    """

    @classmethod
    def setUpClass(cls):
        cls.corpus = load(DEFECT1_CORPUS)
        cls.register = load(DEFECT1_REGISTER)
        cls.guard = _load_lane_d_guard()

    def test_the_unmodified_checker_wrongly_admits_the_defect(self):
        """Pre-fix failure, DIRECTLY_REPRODUCED against the shipped checker.

        This asserts the CURRENT defect, not the desired behaviour: it stays
        green only for as long as `provctl.check_register` remains
        unpatched. If `patches/provctl.py.patch` is applied to this file,
        this assertion flips and must be deleted in the same change that
        applies the patch — it is the tripwire, not the target state.
        """
        failures = provctl.check_register(self.corpus, self.register, REPO)
        self.assertEqual(
            failures, [],
            "if this fails, provctl.py has been patched for DEF-SCP-D-01 and "
            "this tripwire test (not the mechanism) should now be deleted",
        )

    def test_the_lane_d_mechanism_fix_correctly_refuses_it(self):
        """Passing rerun: the corrected haystack construction refuses the quote."""
        failures = self.guard.check_register_guarded(self.corpus, self.register, REPO)
        self.assertTrue(
            any("QUOTATION_NOT_IN_CORPUS" in f for f in failures), failures,
        )

    def test_the_fix_does_not_regress_the_real_86_constraint_register(self):
        """The paragraph guard must not disturb a register with no embedded quotes."""
        real_corpus, real_register = load(CORPUS), load(REGISTER)
        unguarded = provctl.check_register(real_corpus, real_register, REPO)
        guarded = self.guard.check_register_guarded(real_corpus, real_register, REPO)
        self.assertEqual(unguarded, [])
        self.assertEqual(guarded, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
