#!/usr/bin/env python3
"""Tests for the authorship sidecar. Stdlib `unittest` only, no pytest.

Run:

    python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/test_authorship_sidecar.py

Every accuracy claim this lane makes rests on a case below, on a fixture in
`../fixtures/`, or on a real estate artifact read at its pinned hash. None of it
rests on assertion.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import authorship_sidecar as A  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "fixtures")
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         *([os.pardir] * 7)))
ESTATE = os.path.join(REPO_ROOT, "workstreams", "so02", "control-plane",
                      "operating-environment")


def fixture(name: str) -> str:
    return os.path.join(FIXTURES, name)


def classes_of(path: str) -> list[str]:
    view = A.adapter_markdown_record(path, item_id="T")
    sidecar = A.build_sidecar([view], sidecar_id="t", built_against_commit="test")
    return [s["authorship_class"] for s in sidecar["items"][0]["segments"]]


def segs_of(path: str):
    view = A.adapter_markdown_record(path, item_id="T")
    sidecar = A.build_sidecar([view], sidecar_id="t", built_against_commit="test")
    return sidecar, sidecar["items"][0]["segments"]


def seg_with(segments, needle: str):
    for s in segments:
        if needle.lower() in s["decision_basis"].lower():
            return s
    return None


def text_of(path: str, seg) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()[seg["char_start"]:seg["char_end"]]


# --------------------------------------------------------------------------


class TestSegmentation(unittest.TestCase):
    def test_offsets_recompute_to_the_source_exactly(self):
        for name in os.listdir(FIXTURES):
            if not name.endswith(".md"):
                continue
            path = fixture(name)
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
            _, segments = segs_of(path)
            self.assertTrue(segments, name)
            for s in segments:
                span = raw[s["char_start"]:s["char_end"]]
                self.assertEqual(A.sha256_text(span), s["text_sha256"], f"{name} {s['segment_id']}")

    def test_segments_are_ordered_and_non_overlapping(self):
        _, segments = segs_of(fixture("mixed-message-founder-and-pasted.md"))
        last = -1
        for s in segments:
            self.assertGreaterEqual(s["char_start"], last)
            self.assertLess(s["char_start"], s["char_end"])
            last = s["char_end"]

    def test_one_message_yields_many_segments(self):
        # Message granularity is the defect. A single item must segment below it.
        _, segments = segs_of(fixture("mixed-message-founder-and-pasted.md"))
        self.assertGreater(len(segments), 8, "one item collapsed to too few segments")

    def test_blockquote_depth_change_is_a_boundary(self):
        segments = A.segment_text("> outer one\n> > inner two\n> outer three\n")
        self.assertEqual([s.quote_depth for s in segments], [1, 2, 1])

    def test_fenced_block_is_atomic(self):
        segments = A.segment_text("para\n\n```\nI am Ahmed Sadek\n\nstill in fence\n```\n\ntail\n")
        kinds = [s.kind for s in segments]
        self.assertIn("fence", kinds)
        fence = [s for s in segments if s.kind == "fence"][0]
        self.assertIn("still in fence", fence.text)


class TestPositionIsInert(unittest.TestCase):
    """The reproduced defect: position was mistaken for founder authorship."""

    def test_verbatim_heading_and_blockquote_do_not_confer_founder_class(self):
        got = classes_of(fixture("position-without-evidence.md"))
        self.assertNotIn(A.FOUNDER_DIRECT, got)
        self.assertNotIn(A.FOUNDER_ADOPTED, got)
        self.assertIn(A.UNRESOLVED_USER_ROLE, got)

    def test_the_protected_surface_sentence_is_not_founder_authored(self):
        # The exact constraint the estate mis-certified as FOUNDER_BOUND.
        sidecar, segments = segs_of(fixture("position-without-evidence.md"))
        with open(fixture("position-without-evidence.md"), encoding="utf-8") as fh:
            raw = fh.read()
        result = A.verdict_for_quote(
            sidecar, {fixture("position-without-evidence.md"): raw},
            "Protected surfaces are untouchable")
        self.assertEqual(result["verdict"], A.REFUSED_UNRESOLVED)

    def test_user_role_alone_never_upgrades_a_segment(self):
        item = A.IndexItem("I1", "user", "Please rotate the deployment key this week.")
        rec = A.build_item_record(item)
        self.assertEqual(rec["segments"][0]["authorship_class"], A.UNRESOLVED_USER_ROLE)
        self.assertEqual(rec["segments"][0]["confidence"], A.NO_EVIDENCE)

    def test_same_sentence_classifies_the_same_wrapped_or_bare(self):
        bare = A.build_item_record(A.IndexItem(
            "b", "user", "I am Ahmed Sadek, founder of Obzio, speaking directly."))
        wrapped = A.build_item_record(A.IndexItem(
            "w", "assistant",
            "## Notes\n\n> > I am Ahmed Sadek, founder of Obzio, speaking directly."))
        self.assertEqual(bare["segments"][0]["authorship_class"], A.FOUNDER_DIRECT)
        self.assertEqual(wrapped["segments"][-1]["authorship_class"], A.FOUNDER_DIRECT)


class TestMixedMessageSegmentation(unittest.TestCase):
    def test_founder_words_and_pasted_material_separate_within_one_message(self):
        path = fixture("mixed-message-founder-and-pasted.md")
        sidecar, segments = segs_of(path)
        self.assertTrue(sidecar["items"][0]["is_mixed_authorship"])
        got = {s["authorship_class"] for s in segments}
        self.assertIn(A.FOUNDER_DIRECT, got)
        self.assertIn(A.NONFOUNDER_PASTED, got)
        self.assertIn(A.FOUNDER_REPRESENTED, got)

    def test_the_pasted_vendor_sentence_is_refused(self):
        path = fixture("mixed-message-founder-and-pasted.md")
        sidecar, _ = segs_of(path)
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        result = A.verdict_for_quote(sidecar, {path: raw},
                                    "Protected surfaces must never be written to "
                                    "without owner approval")
        self.assertEqual(result["verdict"], A.REFUSED_PASTED)

    def test_the_founder_sentence_in_the_same_message_is_admitted(self):
        path = fixture("mixed-message-founder-and-pasted.md")
        sidecar, _ = segs_of(path)
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        result = A.verdict_for_quote(
            sidecar, {path: raw},
            "No surface is off-limits because of a name on a list")
        self.assertEqual(result["verdict"], A.ADMITTED_FOUNDER)

    def test_pasted_scope_propagates_to_the_unmarked_paragraph_after_it(self):
        # "Agents should additionally pause all work..." carries no marker of its
        # own. It is part of the paste and must not become founder material.
        path = fixture("mixed-message-founder-and-pasted.md")
        sidecar, _ = segs_of(path)
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        result = A.verdict_for_quote(sidecar, {path: raw},
                                    "pause all work until a human confirms each step")
        self.assertEqual(result["verdict"], A.REFUSED_PASTED)

    def test_founder_resumption_after_a_paste_is_admitted(self):
        path = fixture("mixed-message-founder-and-pasted.md")
        sidecar, _ = segs_of(path)
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        result = A.verdict_for_quote(
            sidecar, {path: raw},
            "a write is gated by a reason and a rollback, nothing else")
        self.assertEqual(result["verdict"], A.ADMITTED_FOUNDER)

    def test_mere_mention_of_a_third_party_is_not_attribution(self):
        rec = A.build_item_record(A.IndexItem(
            "m", "user",
            "I am Ahmed Sadek. ChatGPT mistakenly limited Obzio's plan to you "
            "acting primarily as a planner."))
        self.assertEqual(rec["segments"][0]["authorship_class"], A.FOUNDER_DIRECT)


class TestAdoption(unittest.TestCase):
    def test_pasted_material_adopted_in_a_later_segment_is_not_retroactively_founder(self):
        # Adoption is scoped and forward-looking. The already-classified pasted
        # segment stays pasted; conflating the two directions is how a paste
        # becomes authority.
        path = fixture("adopted-and-disavowed.md")
        _, segments = segs_of(path)
        got = [s["authorship_class"] for s in segments]
        self.assertIn(A.NONFOUNDER_PASTED, got)

    def test_adoption_in_the_same_segment_as_attribution_yields_founder_adopted(self):
        rec = A.build_item_record(A.IndexItem(
            "a", "user",
            "This is ChatGPT's recommendation, and I take the following as my own: "
            "every lane must attach an admission verdict before pushing."))
        self.assertEqual(rec["segments"][0]["authorship_class"], A.FOUNDER_ADOPTED)

    def test_disavowal_defeats_adoption_in_the_same_segment(self):
        rec = A.build_item_record(A.IndexItem(
            "d", "user",
            "This is ChatGPT's proposal, and I take it as my own - no, on "
            "reflection I have not agreed to it and I am not adopting it."))
        self.assertEqual(rec["segments"][0]["authorship_class"], A.NONFOUNDER_PASTED)

    def test_first_person_refusal_is_his_utterance(self):
        rec = A.build_item_record(A.IndexItem(
            "fp", "user",
            "Here is what the vendor sent, pasted below.\n"
            "\n"
            "VENDOR RECOMMENDATION - approval is required before every push.\n"
            "\n"
            "I have not agreed to it and I am not adopting it.\n"))
        got = [s["authorship_class"] for s in rec["segments"]]
        self.assertEqual(got[-1], A.FOUNDER_DIRECT)
        self.assertEqual(got[1], A.NONFOUNDER_PASTED)

    def test_third_person_advisory_label_confers_nothing(self):
        # An agent recording a section as advisory writes these words too, so the
        # label closes a pasted scope without becoming founder speech.
        rec = A.build_item_record(A.IndexItem(
            "tp", "document",
            "Here is what the vendor sent, pasted below.\n"
            "\n"
            "VENDOR RECOMMENDATION - approval is required before every push.\n"
            "\n"
            "Recorded as advisory only.\n"))
        got = [s["authorship_class"] for s in rec["segments"]]
        self.assertNotIn(A.FOUNDER_DIRECT, got)

    def test_founder_adopted_is_admitted_by_the_default_query(self):
        rec = A.build_item_record(A.IndexItem(
            "a", "user",
            "This is ChatGPT's recommendation, and I adopt it as my own."))
        self.assertEqual(rec["segments"][0]["authorship_class"], A.FOUNDER_ADOPTED)
        self.assertTrue(rec["segments"][0]["included_in_default_authority_query"])


class TestRepresentation(unittest.TestCase):
    def test_third_person_reference_to_the_founder_is_representation(self):
        got = classes_of(fixture("agent-representation.md"))
        self.assertIn(A.FOUNDER_REPRESENTED, got)
        self.assertIn(A.FOUNDER_DIRECT, got)

    def test_representation_outranks_first_person_drafting(self):
        # An agent drafting in his voice writes both. Representation wins.
        rec = A.build_item_record(A.IndexItem(
            "r", "assistant",
            "The founder asked that this control be kept, and my instruction is "
            "that it stays."))
        self.assertEqual(rec["segments"][0]["authorship_class"], A.FOUNDER_REPRESENTED)

    def test_a_recorder_speaker_label_is_representation_not_speech(self):
        rec = A.build_item_record(A.IndexItem(
            "s", "document", "**Speaker:** Ahmed Sadek, founder of Obzio"))
        self.assertEqual(rec["segments"][0]["authorship_class"], A.FOUNDER_REPRESENTED)

    def test_representation_is_refused_by_the_default_query(self):
        rec = A.build_item_record(A.IndexItem(
            "s", "document", "**Speaker:** Ahmed Sadek, founder of Obzio"))
        # FOUNDER_REPRESENTED is not in DEFAULT_EXCLUDED, so it is returned by an
        # authority query, but a *quotation* verdict refuses it: an agent's
        # rendering of his authority is not his utterance.
        self.assertNotIn(A.FOUNDER_REPRESENTED, A.DEFAULT_EXCLUDED)
        self.assertEqual(A._VERDICT_FOR_CLASS[A.FOUNDER_REPRESENTED],
                         A.REFUSED_REPRESENTED)


class TestDefaultExclusion(unittest.TestCase):
    def setUp(self):
        self.path = fixture("mixed-message-founder-and-pasted.md")
        self.sidecar, _ = segs_of(self.path)

    def test_default_query_excludes_pasted_and_unresolved(self):
        result = A.authority_segments(self.sidecar)
        got = {s["authorship_class"] for s in result["segments"]}
        self.assertNotIn(A.NONFOUNDER_PASTED, got)
        self.assertNotIn(A.UNRESOLVED_USER_ROLE, got)
        self.assertEqual(result["explicitly_opted_in"], [])
        self.assertFalse(result["opt_in_is_explicit"])

    def test_opting_in_is_explicit_and_recorded(self):
        result = A.authority_segments(self.sidecar, include=[A.NONFOUNDER_PASTED])
        got = {s["authorship_class"] for s in result["segments"]}
        self.assertIn(A.NONFOUNDER_PASTED, got)
        self.assertNotIn(A.UNRESOLVED_USER_ROLE, got)
        self.assertEqual(result["explicitly_opted_in"], [A.NONFOUNDER_PASTED])
        self.assertTrue(result["opt_in_is_explicit"])

    def test_unknown_class_is_refused_not_ignored(self):
        with self.assertRaises(ValueError):
            A.authority_segments(self.sidecar, include=["FOUNDER_PROBABLY"])

    def test_require_local_evidence_drops_inherited_segments(self):
        rec = A.build_item_record(A.IndexItem(
            "inh", "user",
            "I am Ahmed Sadek, founder of Obzio, speaking directly.\n"
            "\n"
            "The pipeline migration proceeds this cycle.\n"))
        sidecar = {"schema": A.SIDECAR_SCHEMA,
                   "items": [dict(rec, source_artifact_path="mem",
                                  source_artifact_sha256="unused")]}
        self.assertEqual(rec["segments"][1]["confidence"], A.SCOPE_INHERITED)
        loose = A.authority_segments(sidecar)
        strict = A.authority_segments(sidecar, require_local_evidence=True)
        self.assertEqual(loose["segment_count"], 2)
        self.assertEqual(strict["segment_count"], 1)
        self.assertTrue(all(s["confidence"] == A.LOCAL_EVIDENCE
                            for s in strict["segments"]))

    def test_every_class_has_a_default_query_flag_that_agrees_with_the_policy(self):
        for rec in self.sidecar["items"]:
            for seg in rec["segments"]:
                self.assertEqual(
                    seg["included_in_default_authority_query"],
                    seg["authorship_class"] not in A.DEFAULT_EXCLUDED,
                    seg["segment_id"])


class TestSubstringIsALocatorNotAVerdict(unittest.TestCase):
    def setUp(self):
        self.path = fixture("mixed-message-founder-and-pasted.md")
        self.sidecar, _ = segs_of(self.path)
        with open(self.path, encoding="utf-8") as fh:
            self.raw = fh.read()

    def test_a_hit_carries_the_landing_segment_class(self):
        landings = A.locate_quote(self.sidecar, {self.path: self.raw},
                                  "Protected surfaces must never be written to")
        self.assertTrue(landings)
        self.assertTrue(all(l["authorship_class"] == A.NONFOUNDER_PASTED
                            for l in landings))

    def test_absent_quote_is_refused_not_silently_true(self):
        result = A.verdict_for_quote(self.sidecar, {self.path: self.raw},
                                     "a sentence nobody in this estate ever wrote")
        self.assertEqual(result["verdict"], A.REFUSED_NOT_PRESENT)

    def test_ambiguous_landing_fails_closed(self):
        item = A.IndexItem(
            "amb", "user",
            "I am Ahmed Sadek and I rule that the gate expires with its reason.\n"
            "\n"
            "Here is what the vendor sent, pasted below.\n"
            "\n"
            "the gate expires with its reason\n")
        rec = A.build_item_record(item)
        sidecar = {
            "schema": A.SIDECAR_SCHEMA,
            "items": [dict(rec, source_artifact_path="mem",
                           source_artifact_sha256=A.sha256_text(item.text))],
        }
        result = A.verdict_for_quote(sidecar, {"mem": item.text},
                                     "the gate expires with its reason")
        self.assertTrue(result["ambiguous"])
        self.assertEqual(result["verdict"], A.REFUSED_PASTED)

    def test_opting_the_pasted_class_in_admits_the_ambiguous_quote(self):
        item = A.IndexItem(
            "amb", "user",
            "I am Ahmed Sadek and I rule that the gate expires with its reason.\n"
            "\n"
            "Here is what the vendor sent, pasted below.\n"
            "\n"
            "the gate expires with its reason\n")
        rec = A.build_item_record(item)
        sidecar = {"schema": A.SIDECAR_SCHEMA,
                   "items": [dict(rec, source_artifact_path="mem",
                                  source_artifact_sha256=A.sha256_text(item.text))]}
        result = A.verdict_for_quote(sidecar, {"mem": item.text},
                                     "the gate expires with its reason",
                                     include=[A.NONFOUNDER_PASTED])
        self.assertEqual(result["verdict"], A.ADMITTED_FOUNDER)
        self.assertEqual(result["explicitly_opted_in"], [A.NONFOUNDER_PASTED])

    def test_changed_source_refuses_rather_than_answering(self):
        result = A.verdict_for_quote(self.sidecar, {self.path: self.raw + "\ntampered\n"},
                                     "No surface is off-limits")
        self.assertEqual(result["verdict"], A.REFUSED_SOURCE_CHANGED)


class TestNonDestructive(unittest.TestCase):
    def test_legacy_fields_are_preserved_byte_for_byte(self):
        legacy = {"speaker_class": "FOUNDER_DIRECT", "is_founder_corpus": True,
                  "heading": "Verbatim", "sha256": "deadbeef", "bytes": 12}
        item = A.IndexItem("L1", "user", "Some text here.", legacy=legacy)
        rec = A.build_item_record(item)
        self.assertEqual(rec["legacy"]["fields"], legacy)
        self.assertEqual(rec["legacy"]["legacy_sha256"],
                         A.sha256_text(A.canonical_json(legacy)))

    def test_building_a_sidecar_does_not_touch_the_source_file(self):
        path = fixture("mixed-message-founder-and-pasted.md")
        with open(path, "rb") as fh:
            before = fh.read()
        segs_of(path)
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), before)

    def test_sidecar_stores_spans_not_content(self):
        _, segments = segs_of(fixture("mixed-message-founder-and-pasted.md"))
        for s in segments:
            self.assertNotIn("text", s)
            self.assertIn("char_start", s)
            self.assertIn("text_sha256", s)

    def test_declared_flags_state_non_destructiveness(self):
        sidecar, _ = segs_of(fixture("mixed-message-founder-and-pasted.md"))
        self.assertFalse(sidecar["non_destructive"]["writes_to_index"])
        self.assertFalse(sidecar["non_destructive"]["copies_index_content"])


class TestVerificationAndReadBack(unittest.TestCase):
    def test_verify_passes_on_an_untouched_sidecar(self):
        path = fixture("mixed-message-founder-and-pasted.md")
        sidecar, _ = segs_of(path)
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        self.assertEqual(A.verify_sidecar(sidecar, {path: raw}), [])

    def test_verify_catches_a_changed_source(self):
        path = fixture("mixed-message-founder-and-pasted.md")
        sidecar, _ = segs_of(path)
        failures = A.verify_sidecar(sidecar, {path: "different content entirely"})
        self.assertTrue(any(f.startswith("SOURCE_CHANGED") for f in failures))

    def test_verify_catches_a_tampered_tally(self):
        path = fixture("mixed-message-founder-and-pasted.md")
        sidecar, _ = segs_of(path)
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        sidecar["class_tally"][A.FOUNDER_DIRECT] += 5
        failures = A.verify_sidecar(sidecar, {path: raw})
        self.assertTrue(any("CLASS_TALLY_MISMATCH" in f for f in failures))

    def test_hash_valid_but_unparsable_artifact_is_a_named_defect(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "truncated.json")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write('{"schema": "authorship-sidecar/1.0", "items": [')
            parsed, problems = A.read_back_and_parse(bad)
            self.assertIsNone(parsed)
            self.assertTrue(any("HASH_VALID_BUT_UNPARSABLE" in p for p in problems))

    def test_round_trip_through_json_preserves_every_verdict(self):
        path = fixture("mixed-message-founder-and-pasted.md")
        sidecar, _ = segs_of(path)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "sidecar.json")
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(sidecar, fh, indent=2, ensure_ascii=False)
            reread, problems = A.read_back_and_parse(out)
            self.assertEqual(problems, [])
            self.assertEqual(reread["class_tally"], sidecar["class_tally"])
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(A.verify_sidecar(reread, {path: fh.read()}), [])

    def test_bundle_sha256_matches_the_estate_construction(self):
        entries = [{"path": "b", "size_bytes": 2, "sha256": "y"},
                   {"path": "a", "size_bytes": 1, "sha256": "x"}]
        expected = A.sha256_text(json.dumps(entries, sort_keys=True,
                                            separators=(",", ":")))
        self.assertEqual(A.bundle_sha256(entries), expected)


class TestAgainstTheRealEstateArtifacts(unittest.TestCase):
    """Runs against the real artifacts, skipping cleanly if they are absent."""

    CORPUS = os.path.join(ESTATE, "w10-provenance", "FOUNDER-CORPUS-20260823-v001.json")
    RECORD = os.path.join(ESTATE, "FOUNDER-STANDING-INSTRUCTION-20260822.md")
    REGISTER = os.path.join(ESTATE, "w10-provenance",
                            "PROVENANCE-REGISTER-20260823-v001.json")

    def test_real_founder_record_is_mixed_authorship(self):
        if not os.path.exists(self.RECORD):
            self.skipTest(f"NOT_FOUND {self.RECORD}")
        view = A.adapter_markdown_record(self.RECORD, item_id="FSI-20260822")
        sidecar = A.build_sidecar([view], sidecar_id="real",
                                  built_against_commit="test")
        rec = sidecar["items"][0]
        self.assertTrue(rec["is_mixed_authorship"])
        self.assertGreater(rec["segment_count"], 30)
        self.assertIn(A.NONFOUNDER_PASTED, rec["classes_present"])
        self.assertIn(A.FOUNDER_DIRECT, rec["classes_present"])
        self.assertIn(A.FOUNDER_REPRESENTED, rec["classes_present"])

    def test_the_real_pasted_chatgpt_proposal_is_refused(self):
        if not os.path.exists(self.RECORD):
            self.skipTest(f"NOT_FOUND {self.RECORD}")
        view = A.adapter_markdown_record(self.RECORD, item_id="FSI-20260822")
        sidecar = A.build_sidecar([view], sidecar_id="real",
                                  built_against_commit="test")
        with open(self.RECORD, encoding="utf-8") as fh:
            raw = fh.read()
        result = A.verdict_for_quote(
            sidecar, {self.RECORD: raw},
            "ChatGPT could be used as a connected, founder-facing capability")
        self.assertEqual(result["verdict"], A.REFUSED_PASTED)

    def test_a_real_founder_sentence_is_admitted(self):
        if not os.path.exists(self.RECORD):
            self.skipTest(f"NOT_FOUND {self.RECORD}")
        view = A.adapter_markdown_record(self.RECORD, item_id="FSI-20260822")
        sidecar = A.build_sidecar([view], sidecar_id="real",
                                  built_against_commit="test")
        with open(self.RECORD, encoding="utf-8") as fh:
            raw = fh.read()
        result = A.verdict_for_quote(
            sidecar, {self.RECORD: raw},
            "No surface is off-limits because of a name on a list")
        self.assertEqual(result["verdict"], A.ADMITTED_FOUNDER)

    def test_corpus_adapter_preserves_every_legacy_field(self):
        if not os.path.exists(self.CORPUS):
            self.skipTest(f"NOT_FOUND {self.CORPUS}")
        with open(self.CORPUS, encoding="utf-8") as fh:
            corpus = json.load(fh)
        view = A.adapter_founder_corpus(self.CORPUS)
        self.assertEqual(len(view.items), len(corpus["segments"]))
        for original, item in zip(corpus["segments"], view.items):
            for key, value in original.items():
                if key == "text":
                    self.assertEqual(item.text, value)
                else:
                    self.assertEqual(item.legacy[key], value, key)

    def test_corpus_items_segment_below_their_legacy_granularity(self):
        if not os.path.exists(self.CORPUS):
            self.skipTest(f"NOT_FOUND {self.CORPUS}")
        view = A.adapter_founder_corpus(self.CORPUS)
        sidecar = A.build_sidecar([view], sidecar_id="real-corpus",
                                  built_against_commit="test")
        self.assertGreater(sidecar["segment_count"], len(view.items),
                           "the sidecar must be finer-grained than the legacy corpus")

    def test_register_quotations_load_as_probes_not_verdicts(self):
        if not os.path.exists(self.REGISTER):
            self.skipTest(f"NOT_FOUND {self.REGISTER}")
        probes = A.load_provenance_quotations(self.REGISTER)
        self.assertTrue(probes)
        for p in probes:
            self.assertIn("quote", p)
            self.assertIn("register_provenance_class", p)


class TestInvariants(unittest.TestCase):
    def test_the_five_classes_are_exactly_the_commissioned_set(self):
        self.assertEqual(set(A.CLASSES), {
            "FOUNDER_DIRECT", "FOUNDER_ADOPTED", "FOUNDER_REPRESENTED",
            "NONFOUNDER_PASTED", "UNRESOLVED_USER_ROLE"})

    def test_default_exclusion_set_is_exactly_the_two_required(self):
        self.assertEqual(A.DEFAULT_EXCLUDED,
                         frozenset({"NONFOUNDER_PASTED", "UNRESOLVED_USER_ROLE"}))

    def test_every_signal_declares_its_rule_provenance(self):
        for sig in A.SIGNALS:
            self.assertIn(sig.provenance,
                          {"FOUNDER_AUTHORED", "EARNED", "ASSISTANT_AUTHORED"},
                          sig.name)
            self.assertTrue(sig.basis.strip(), sig.name)

    def test_the_role_field_cannot_change_any_verdict(self):
        # A signal is only ever handed one segment's stripped text. This asserts
        # the consequence: the same body under every role classifies identically.
        body = ("Here is what the vendor sent, pasted below.\n\nVENDOR "
                "RECOMMENDATION - approval is required before every push.\n")
        seen = set()
        for role in ("user", "assistant", "system", "document", "tool"):
            rec = A.build_item_record(A.IndexItem("r", role, body))
            seen.add(tuple(s["authorship_class"] for s in rec["segments"]))
        self.assertEqual(len(seen), 1, f"role changed the verdict: {seen}")

    def test_heading_text_cannot_change_any_verdict(self):
        body = "The deployment pipeline should be migrated to the new runner.\n"
        seen = set()
        for heading in ("## Verbatim - direct founder instruction",
                        "## Verbatim - founder authority",
                        "## Assistant scratch notes",
                        "## Vendor correspondence"):
            rec = A.build_item_record(A.IndexItem("h", "user", f"{heading}\n\n{body}"))
            seen.add(rec["segments"][-1]["authorship_class"])
        self.assertEqual(seen, {A.UNRESOLVED_USER_ROLE},
                         f"heading changed the verdict: {seen}")

    def test_resumption_without_founder_evidence_stays_unresolved(self):
        # The safe direction. Closing a pasted scope does not manufacture
        # authority for whatever follows.
        rec = A.build_item_record(A.IndexItem(
            "res", "user",
            "Here is what the vendor sent, pasted below.\n"
            "\n"
            "VENDOR RECOMMENDATION - approval is required before every push.\n"
            "\n"
            "That was their text.\n"
            "\n"
            "The runner should be upgraded first.\n"))
        got = [s["authorship_class"] for s in rec["segments"]]
        self.assertEqual(got[-1], A.UNRESOLVED_USER_ROLE)
        self.assertNotIn(A.FOUNDER_DIRECT, got)

    def test_weak_signals_alone_never_produce_a_founder_class(self):
        rec = A.build_item_record(A.IndexItem(
            "w", "user", "I want the pipeline migrated and my instruction stands."))
        self.assertEqual(rec["segments"][0]["authorship_class"],
                         A.UNRESOLVED_USER_ROLE)

    def test_every_segment_records_a_decision_basis(self):
        for name in os.listdir(FIXTURES):
            if not name.endswith(".md"):
                continue
            _, segments = segs_of(fixture(name))
            for s in segments:
                self.assertTrue(s["decision_basis"].strip(), s["segment_id"])

    def test_determinism(self):
        path = fixture("mixed-message-founder-and-pasted.md")
        a, _ = segs_of(path)
        b, _ = segs_of(path)
        self.assertEqual(A.canonical_json(a), A.canonical_json(b))


if __name__ == "__main__":
    unittest.main(verbosity=2)
