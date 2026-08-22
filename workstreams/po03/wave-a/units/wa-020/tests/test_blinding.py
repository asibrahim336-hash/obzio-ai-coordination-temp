"""Blinding: redaction, the pool vocabulary, leak scanning and label channels."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from harness.bias_experiment import identity_permutations
from harness.blinding import (
    MODEL_FAMILY_TOKENS,
    REDACTION,
    ArrivalOrderBlinder,
    Blinder,
    IdentityEnvelope,
    IdentityLeak,
    LeakyBlinder,
    PerIdentityVocabularyBlinder,
    assert_no_leak,
    find_leaks,
    label_standing_correlation,
    pool_vocabulary,
    redact,
)
from harness.candidates import build_pool, identity_pool, observed_prior_producer
from harness.canonical import digest_bytes
from harness.probes import repository_root

ROOT = repository_root()
PRIOR = observed_prior_producer(ROOT)
IDENTITIES = identity_pool(ROOT)
POOL = build_pool(IDENTITIES, PRIOR)
VOCABULARY = pool_vocabulary(IDENTITIES)


class TokenTests(unittest.TestCase):
    def test_composite_identifiers_yield_their_informative_sub_tokens(self) -> None:
        envelope = IDENTITIES[0]
        tokens = {token.lower() for token in envelope.tokens()}
        self.assertIn(envelope.runner_id.lower(), tokens)
        self.assertTrue(
            any("016" in token or "020" in token for token in tokens),
            "a unit number inside a composite identifier must be redactable on its own",
        )

    def test_ordinary_english_words_are_not_swept_into_the_vocabulary(self) -> None:
        """Over-redaction destroys the content under review for no gain in blinding."""
        tokens = {token.lower() for token in IDENTITIES[0].tokens()}
        for word in ("best", "runner", "worker", "cursor", "result", "producer"):
            self.assertNotIn(word, tokens)

    def test_a_commit_identifier_yields_its_abbreviated_prefixes(self) -> None:
        envelope = IdentityEnvelope(
            envelope_id="IDENT-X",
            producer_id="p",
            runner_id="r",
            attempt_id="a",
            model_slug="m",
            reasoning="high",
            branch="b",
            result_commit_id="a" * 40,
            standing_tier=1,
            standing_role="role",
            standing_source="source",
            observed_in="test",
        )
        tokens = set(envelope.tokens())
        self.assertIn("a" * 7, tokens)
        self.assertIn("a" * 40, tokens)

    def test_model_family_words_are_a_constant_vocabulary(self) -> None:
        """Constant, so redacting them leaves no per-identity trace."""
        for envelope in IDENTITIES:
            tokens = {token.lower() for token in envelope.tokens()}
            for family in MODEL_FAMILY_TOKENS:
                self.assertIn(family.lower(), tokens)

    def test_tokens_are_ordered_longest_first(self) -> None:
        lengths = [len(token) for token in IDENTITIES[0].tokens()]
        self.assertEqual(lengths, sorted(lengths, reverse=True))


class RedactionTests(unittest.TestCase):
    def test_redaction_is_case_insensitive(self) -> None:
        self.assertNotIn("opus", redact("Claude OPUS 5", VOCABULARY).lower())

    def test_redacting_a_sub_token_does_not_leave_the_parent_behind(self) -> None:
        envelope = IDENTITIES[0]
        text = f"produced by {envelope.runner_id} on {envelope.branch}"
        self.assertEqual(find_leaks(redact(text, envelope.tokens()).encode("utf-8"), envelope), [])

    def test_redaction_marks_where_content_was_removed(self) -> None:
        self.assertIn(REDACTION, redact("model claude-opus-5", VOCABULARY))


class PoolVocabularyTests(unittest.TestCase):
    """The mechanism M1 installs, and the defect it replaced."""

    def _renderings(self, blinder, submission_id: str) -> dict[str, str]:
        digests: dict[str, str] = {}
        for permutation in identity_permutations(POOL, IDENTITIES):
            permuted = POOL.with_identities(permutation["assignment"])
            blinded = blinder.blind(
                permuted.by_id(submission_id), 1, 0, pool_vocabulary(permuted.identities)
            )
            digests[permutation["permutation_id"]] = digest_bytes(blinded.rendered())
        return digests

    def test_pool_vocabulary_renders_identically_under_every_identity(self) -> None:
        digests = self._renderings(Blinder(), "SUB-1")
        self.assertEqual(
            len(set(digests.values())),
            1,
            "the same content under different identities must reach the scorer as the same bytes",
        )

    def test_per_identity_vocabulary_leaves_an_identity_channel(self) -> None:
        digests = self._renderings(PerIdentityVocabularyBlinder(), "SUB-1")
        self.assertGreater(
            len(set(digests.values())),
            1,
            "the retained defect must still be detectable, or the control is not controlling anything",
        )

    def test_the_channel_is_invisible_to_a_single_payload_leak_scan(self) -> None:
        """This is why the metamorphic comparison exists and a leak scan is not enough."""
        permutation = identity_permutations(POOL, IDENTITIES)[0]
        permuted = POOL.with_identities(permutation["assignment"])
        submission = permuted.by_id("SUB-1")
        blinded = PerIdentityVocabularyBlinder().blind(
            submission, 1, 0, pool_vocabulary(permuted.identities)
        )
        self.assertEqual(find_leaks(blinded.rendered(), submission.identity), [])

    def test_the_channel_needs_a_prior_art_citation_to_exist(self) -> None:
        """A submission citing nobody's prior work renders identically either way."""
        digests = self._renderings(PerIdentityVocabularyBlinder(), "SUB-3")
        self.assertEqual(len(set(digests.values())), 1)
        self.assertEqual(POOL.by_id("SUB-3").prior_art, "")
        self.assertNotEqual(POOL.by_id("SUB-1").prior_art, "")

    def test_the_pool_vocabulary_covers_every_identity_in_the_pool(self) -> None:
        combined = {token.lower() for token in VOCABULARY}
        for envelope in IDENTITIES:
            self.assertTrue({token.lower() for token in envelope.tokens()} <= combined)


class LeakScannerTests(unittest.TestCase):
    def test_the_correct_blinder_leaves_no_token(self) -> None:
        for submission in POOL.submissions:
            blinded = Blinder().blind(submission, 1, 0, VOCABULARY)
            self.assertEqual(
                find_leaks(blinded.rendered(), submission.identity),
                [],
                f"{submission.submission_id} leaked",
            )

    def test_a_field_level_redactor_still_leaks_through_prose(self) -> None:
        submission = POOL.by_id("SUB-2")
        blinded = LeakyBlinder().blind(submission, 1, 1, VOCABULARY)
        self.assertNotEqual(find_leaks(blinded.rendered(), submission.identity), [])

    def test_assert_no_leak_raises_on_the_leaky_blinder(self) -> None:
        submission = POOL.by_id("SUB-2")
        with self.assertRaises(IdentityLeak):
            assert_no_leak(LeakyBlinder().blind(submission, 1, 1, VOCABULARY), submission.identity)

    def test_assert_no_leak_is_silent_on_the_correct_blinder(self) -> None:
        submission = POOL.by_id("SUB-2")
        assert_no_leak(Blinder().blind(submission, 1, 1, VOCABULARY), submission.identity)

    def test_the_scanner_reads_rendered_bytes_not_the_object_graph(self) -> None:
        """The prose is where the leak lives, so scanning fields would miss it."""
        submission = POOL.by_id("SUB-2")
        content = submission.reviewable_content()
        self.assertNotIn("identity", content)
        self.assertIn(submission.identity.attempt_id, content["self_reference"])


class LabelChannelTests(unittest.TestCase):
    def _tiers(self) -> list[int]:
        return [submission.identity.standing_tier for submission in POOL.submissions]

    def test_the_pool_arrives_in_descending_standing_order(self) -> None:
        tiers = self._tiers()
        self.assertEqual(tiers, sorted(tiers, reverse=True))

    def test_arrival_order_labels_rank_the_withheld_standing(self) -> None:
        labels = [
            ArrivalOrderBlinder().blind(submission, 1, index, VOCABULARY).pseudonym
            for index, submission in enumerate(POOL.submissions)
        ]
        self.assertEqual(label_standing_correlation(labels, self._tiers()), 1.0)

    def test_content_derived_labels_do_not_rank_the_withheld_standing(self) -> None:
        labels = [
            Blinder().blind(submission, 1, index, VOCABULARY).pseudonym
            for index, submission in enumerate(POOL.submissions)
        ]
        self.assertLess(abs(label_standing_correlation(labels, self._tiers())), 0.5)

    def test_a_content_derived_label_is_stable_under_identity_permutation(self) -> None:
        labels = set()
        for permutation in identity_permutations(POOL, IDENTITIES):
            permuted = POOL.with_identities(permutation["assignment"])
            labels.add(
                Blinder()
                .blind(permuted.by_id("SUB-3"), 1, 2, pool_vocabulary(permuted.identities))
                .pseudonym
            )
        self.assertEqual(len(labels), 1)

    def test_correlation_ignores_tied_tiers(self) -> None:
        self.assertEqual(label_standing_correlation(["A", "B"], [2, 2]), 0.0)

    def test_correlation_requires_matching_lengths(self) -> None:
        with self.assertRaises(ValueError):
            label_standing_correlation(["A"], [1, 2])

    def test_correlation_of_a_single_label_is_zero(self) -> None:
        self.assertEqual(label_standing_correlation(["A"], [4]), 0.0)


if __name__ == "__main__":
    unittest.main()
