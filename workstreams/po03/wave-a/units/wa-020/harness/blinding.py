"""Withholding producer identity from the scorer.

The scorer never receives a candidate object. It receives bytes. That is the
whole design: if the only thing crossing the boundary is a rendered payload, then
"identity was withheld" is a property of those bytes and can be checked by
scanning them, rather than a property of which attributes some caller remembered
not to read.

Four things are enforced here.

* **Redaction.** Every token derivable from the identity envelope is removed from
  the rendered payload, including the sub-tokens a reader would actually
  recognise. A runner id is not one string; it contains a unit number, an attempt
  number and a run identifier, and any one of them identifies the producer to
  someone who has read the other results.

* **A pool-wide redaction vocabulary.** Redacting each submission against its own
  identity tokens leaks the identity even when it removes every one of them, because
  the *damage* differs: a submission whose producer is called ``composer-2.5`` loses
  the word ``composer`` from its prose and a submission from another configuration
  does not. The surviving text then differs by identity. Redaction therefore runs
  against the union of the tokens of every identity in the pool, so the damage is
  identical whoever wrote the submission. ``PerIdentityVocabularyBlinder`` keeps the
  naive version as a permanent control.

* **Leak scanning.** The scanner runs over the rendered bytes the scorer will read,
  after redaction, and reports any surviving token. Scanning the object graph
  instead would miss exactly the case that matters, where a field was rendered
  into prose by some other code path.

* **Pseudonym assignment.** Labels are assigned by the digest of the blinded
  content, not by submission order. Submission order is an identity channel: if
  candidates arrive in standing order, then ``CANDIDATE-A`` means "the one from the
  strongest configuration" and the blind leaks a rank with every string redacted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .canonical import canonical_bytes, digest, digest_bytes

REDACTION = "[REDACTED-IDENTITY]"

# Model family words, held as a constant vocabulary rather than derived per
# identity. These are identity even when no slug appears verbatim: the commission
# assigns a standing to each family, so the family name alone carries the
# prestige signal the blind exists to remove. Because the list is constant, every
# submission loses the same words and the redaction leaves no per-identity trace.
MODEL_FAMILY_TOKENS: tuple[str, ...] = (
    "claude",
    "opus",
    "sonnet",
    "gpt",
    "gemini",
    "composer",
    "thinking-high",
    "max-fast",
)

_SPLIT_PATTERN = re.compile(r"[/:@_.\s-]+")
_HEX40_PATTERN = re.compile(r"[0-9a-f]{40}")


class IdentityLeak(Exception):
    """A blinded payload still contains a producer-identifying token."""


def _informative(part: str) -> bool:
    """Is this sub-token specific enough to be worth redacting?

    A sub-token is kept when it carries a digit or is long enough to be an
    identifier rather than an English word. Without this filter the vocabulary
    swallows words like ``best`` and ``runner`` out of ordinary prose, which
    destroys the content under review for no gain in blinding.
    """
    if len(part) < 3:
        return False
    return bool(re.search(r"\d", part)) or len(part) >= 8


@dataclass(frozen=True)
class IdentityEnvelope:
    """Everything about a candidate that the scorer must not see.

    ``standing_tier`` is not an opinion about any producer. It is the standing the
    commission itself assigns to a configuration in its strongest-model policy,
    read from ``workstreams/po03/COMMISSION.md`` and recorded as a source claim.
    It is carried here because a prestige-sensitive reviewer needs something to be
    sensitive to, and inventing a ranking would have made the experiment a
    statement about a ranking this unit made up.
    """

    envelope_id: str
    producer_id: str
    runner_id: str
    attempt_id: str
    model_slug: str
    reasoning: str
    branch: str
    result_commit_id: str
    standing_tier: int
    standing_role: str
    standing_source: str
    observed_in: str

    def tokens(self) -> tuple[str, ...]:
        """Every string a reader could use to identify this producer."""
        seeds = [
            self.envelope_id,
            self.producer_id,
            self.runner_id,
            self.attempt_id,
            self.model_slug,
            self.branch,
            self.result_commit_id,
        ]
        found: list[str] = []
        for seed in seeds:
            if not seed:
                continue
            found.append(seed)
            found.extend(part for part in _SPLIT_PATTERN.split(seed) if _informative(part))
            if _HEX40_PATTERN.fullmatch(seed):
                # A seven-character prefix identifies a commit as well as forty do.
                found.extend(seed[:size] for size in range(7, 41))
        found.extend(MODEL_FAMILY_TOKENS)
        unique = {token.lower(): token for token in found if len(token) >= 3}
        # Longest first, so redacting a sub-token never leaves the parent behind.
        return tuple(sorted(unique.values(), key=lambda token: (-len(token), token.lower())))

    def as_record(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "branch": self.branch,
            "envelope_id": self.envelope_id,
            "model_slug": self.model_slug,
            "observed_in": self.observed_in,
            "producer_id": self.producer_id,
            "reasoning": self.reasoning,
            "result_commit_id": self.result_commit_id,
            "runner_id": self.runner_id,
            "standing_role": self.standing_role,
            "standing_source": self.standing_source,
            "standing_tier": self.standing_tier,
        }


def pool_vocabulary(envelopes: Iterable[IdentityEnvelope]) -> tuple[str, ...]:
    """The identity-independent redaction vocabulary for a submission pool."""
    unique: dict[str, str] = {}
    for envelope in envelopes:
        for token in envelope.tokens():
            unique.setdefault(token.lower(), token)
    return tuple(sorted(unique.values(), key=lambda token: (-len(token), token.lower())))


def redact(text: str, tokens: Sequence[str]) -> str:
    """Remove every vocabulary token from a string, longest token first."""
    redacted = text
    for token in tokens:
        if not token:
            continue
        redacted = re.sub(re.escape(token), REDACTION, redacted, flags=re.IGNORECASE)
    return redacted


def _redact_structure(value: Any, tokens: Sequence[str]) -> Any:
    if isinstance(value, str):
        return redact(value, tokens)
    if isinstance(value, dict):
        return {key: _redact_structure(item, tokens) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_structure(item, tokens) for item in value]
    return value


def find_leaks(payload: bytes, envelope: IdentityEnvelope) -> list[dict[str, Any]]:
    """Report every identity token surviving in the exact bytes handed to the scorer."""
    haystack = payload.decode("utf-8", errors="replace").lower()
    leaks: list[dict[str, Any]] = []
    for token in envelope.tokens():
        needle = token.lower()
        if needle in haystack:
            leaks.append(
                {
                    "envelope_id": envelope.envelope_id,
                    "occurrences": haystack.count(needle),
                    "token": token,
                }
            )
    return leaks


@dataclass(frozen=True)
class BlindedCandidate:
    """What the scorer sees: a pseudonym and a rendered payload, nothing else."""

    pseudonym: str
    payload: dict[str, Any]
    content_sha256: str
    admitted_at_tick: int

    def rendered(self) -> bytes:
        return canonical_bytes(self.payload)


class Blinder:
    """The blinding function under test."""

    name = "Blinder"

    def strip(self, submission, vocabulary: Sequence[str]) -> dict[str, Any]:
        """Render a submission down to reviewable content, with identity removed."""
        return _redact_structure(submission.reviewable_content(), vocabulary)

    def label(self, index: int, content_sha256: str) -> str:
        """Assign a pseudonym from content, never from arrival order."""
        del index
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        value = int(content_sha256[:8], 16)
        return f"CANDIDATE-{alphabet[value % len(alphabet)]}{content_sha256[:6]}"

    def vocabulary_for(self, submission, pool: Sequence[str]) -> Sequence[str]:
        return pool

    def blind(self, submission, admitted_at_tick: int, index: int, pool: Sequence[str]) -> BlindedCandidate:
        stripped = self.strip(submission, self.vocabulary_for(submission, pool))
        content_sha256 = digest(stripped)
        return BlindedCandidate(
            pseudonym=self.label(index, content_sha256),
            payload=stripped,
            content_sha256=content_sha256,
            admitted_at_tick=admitted_at_tick,
        )


class LeakyBlinder(Blinder):
    """Adversarial control: drops the identity fields and nothing else.

    This is the plausible defect, not a strawman. It removes the identity envelope
    from the payload exactly as a careful implementation would, and still leaks,
    because the producer's own prose refers to its branch and its earlier attempt.
    The scanner must catch what the redactor never looked at.
    """

    name = "LeakyBlinder"

    def strip(self, submission, vocabulary: Sequence[str]) -> dict[str, Any]:
        del vocabulary
        return submission.reviewable_content()


class PerIdentityVocabularyBlinder(Blinder):
    """Adversarial control: correct redaction against the wrong vocabulary.

    Redacts every token of the submission's own identity, so a byte scan of any
    single payload reports no leak. The channel is comparative: because the
    vocabulary differs by identity, so does the collateral damage, and the same
    content rendered under two identities produces two different payloads. This
    is the defect the metamorphic test in this unit found; the mutant is retained
    so the defect cannot come back unnoticed.
    """

    name = "PerIdentityVocabularyBlinder"

    def vocabulary_for(self, submission, pool: Sequence[str]) -> Sequence[str]:
        del pool
        return submission.identity.tokens()


class ArrivalOrderBlinder(Blinder):
    """Adversarial control: correct redaction, but pseudonyms follow arrival order.

    Every identity string is gone, so a byte scan of one payload reports no leak.
    The channel is in the label set rather than in any payload: with submissions
    arriving in standing order, the label ranks the producers.
    """

    name = "ArrivalOrderBlinder"

    def label(self, index: int, content_sha256: str) -> str:
        del content_sha256
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        return f"CANDIDATE-{alphabet[index % len(alphabet)]}"


def label_standing_correlation(labels: Sequence[str], tiers: Sequence[int]) -> float:
    """Rank correlation between assigned labels and withheld standing tiers.

    A blind that assigns labels from content scores near zero on a submission set
    arriving in standing order. A blind that assigns labels from arrival order
    scores 1.0 on the same set: the identity is gone from the bytes and still
    recoverable from the label.
    """
    if len(labels) != len(tiers):
        raise ValueError("labels and tiers must be the same length")
    if len(labels) < 2:
        return 0.0
    order = sorted(range(len(labels)), key=lambda index: labels[index])
    concordant = 0
    discordant = 0
    for left in range(len(order)):
        for right in range(left + 1, len(order)):
            first, second = order[left], order[right]
            if tiers[first] == tiers[second]:
                continue
            if tiers[first] > tiers[second]:
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    if total == 0:
        return 0.0
    return (concordant - discordant) / total


def assert_no_leak(blinded: BlindedCandidate, envelope: IdentityEnvelope) -> None:
    leaks = find_leaks(blinded.rendered(), envelope)
    if leaks:
        raise IdentityLeak(
            f"{blinded.pseudonym} still carries {len(leaks)} identity token(s): "
            + ", ".join(leak["token"] for leak in leaks)
        )


def rendered_digests(renderings: dict[str, bytes]) -> dict[str, str]:
    """Digest each rendering, for metamorphic comparison across identities."""
    return {key: digest_bytes(payload) for key, payload in sorted(renderings.items())}
