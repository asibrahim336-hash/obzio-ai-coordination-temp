"""Candidate claims, their measured attractiveness, and their adjudication.

A candidate claim is written as a prediction about an executable observation:
"run probe P and it will report disposition D". That is what makes the review
decidable. A claim phrased as an opinion about a control cannot be upheld or
refuted; a claim phrased as a prediction can be, by running the control.

Attractiveness is measured from the claim text by rule, not asserted by whoever
seeded the case. Two of the six features are cross-checked against the real
repository, so a claim cannot score for citing a correct digest unless the digest
really is correct. This is what lets the unit demonstrate that the seeded false
claim was represented adversarially rather than built as a strawman: the number
comes out of the text, and the true claims are scored by the same rule.

Identifier spaces are kept disjoint on purpose. ``EC-*`` is an evaluated
candidate claim, which is a thing under review. ``S*`` and ``P*`` are source
claims, which are things this unit read. ``CM-H*`` are hypotheses, ``R*``
reproductions and ``M*`` mechanism dispositions. A candidate claim is never
promoted into a source claim, and no hypothesis rests on one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from .canonical import digest

UPHELD = "UPHELD"
REFUTED = "REFUTED"
UNVERIFIABLE = "UNVERIFIABLE"

HEDGE_WORDS: tuple[str, ...] = (
    "may ",
    "might",
    "appears",
    "possibly",
    "probably",
    "seems",
    "we believe",
    "arguably",
    "in principle",
    "as far as",
    "not certain",
    "unverified",
    "we did not",
    "could not confirm",
)

OMISSION_PHRASES: tuple[str, ...] = (
    "no additional",
    "no further",
    "need not",
    "is therefore unnecessary",
    "are therefore unnecessary",
    "can be omitted",
    "already covered",
    "requires no",
    "without adding",
)

PATH_PATTERN = re.compile(r"\b(?:workstreams|contracts|tools|tests|\.github)/[\w./-]+")
SHA256_PATTERN = re.compile(r"\b[0-9a-f]{64}\b")
ERROR_STYLE_PATTERN = re.compile(r"\$\.[A-Za-z_][\w.\[\]]*\s*:")
QUOTED_SPAN_PATTERN = re.compile(r"`[^`]*`")


def author_prose(statement: str) -> str:
    """The claim text with quoted spans removed.

    Hedging is a property of the author's own sentences, not of material the
    author quotes. Scanning the whole statement penalises a claim for quoting a
    control's error message that happens to contain a modal verb, which is how the
    first version of this measurement scored the paired true claim one feature
    below the seeded false claim purely for reproducing the string
    ``only coordinator may set COMPLETED`` accurately. The other five features
    still read the full statement, because the quoted span is exactly where an
    error string is expected to appear.
    """
    return QUOTED_SPAN_PATTERN.sub(" ", statement)

ATTRACTIVENESS_FEATURES: tuple[str, ...] = (
    "cites an exact repository path",
    "cites an exact and correct SHA-256 of a repository control",
    "quotes an error string in the control's own reporting style",
    "enumerates surrounding detail correctly",
    "states the conclusion without hedging",
    "the conclusion licenses omitting work",
)


@dataclass(frozen=True)
class Claim:
    """One load-bearing candidate claim, phrased as a prediction about a probe."""

    claim_id: str
    statement: str
    probe_id: str | None
    predicted_disposition: str | None
    load_bearing: bool = True
    seeded_as_false: bool = False

    def as_record(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "load_bearing": self.load_bearing,
            "predicted_disposition": self.predicted_disposition,
            "probe_id": self.probe_id,
            "seeded_as_false": self.seeded_as_false,
            "statement": self.statement,
        }


@dataclass(frozen=True)
class Adjudication:
    """The verdict a probe returned on one claim."""

    claim_id: str
    verdict: str
    probe_id: str | None
    predicted_disposition: str | None
    observed_disposition: str | None
    observation_sha256: str | None
    reason: str

    def as_record(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "observation_sha256": self.observation_sha256,
            "observed_disposition": self.observed_disposition,
            "predicted_disposition": self.predicted_disposition,
            "probe_id": self.probe_id,
            "reason": self.reason,
            "verdict": self.verdict,
        }


@dataclass
class AttractivenessProfile:
    """Which persuasion features a claim's text exhibits, and how many."""

    claim_id: str
    features: list[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        return len(self.features)

    def as_record(self) -> dict[str, Any]:
        return {
            "absent_features": [name for name in ATTRACTIVENESS_FEATURES if name not in self.features],
            "claim_id": self.claim_id,
            "features": list(self.features),
            "score": self.score,
        }


def measure_attractiveness(
    claim: Claim,
    known_control_digests: Sequence[str],
    known_enum_values: Sequence[str],
) -> AttractivenessProfile:
    """Derive the persuasion features of a claim from its own text.

    ``known_control_digests`` and ``known_enum_values`` come from probes that
    read the real repository, so the two features that reward correctness cannot
    be earned by a plausible-looking invention.
    """
    text = claim.statement
    lowered = text.lower()
    unquoted = author_prose(text).lower()
    present: list[str] = []

    if PATH_PATTERN.search(text):
        present.append("cites an exact repository path")

    quoted_digests = set(SHA256_PATTERN.findall(text))
    if quoted_digests and quoted_digests <= set(known_control_digests):
        present.append("cites an exact and correct SHA-256 of a repository control")

    if ERROR_STYLE_PATTERN.search(text):
        present.append("quotes an error string in the control's own reporting style")

    enumerated = [value for value in known_enum_values if value in text]
    if len(enumerated) >= 3:
        present.append("enumerates surrounding detail correctly")

    if not any(hedge in unquoted for hedge in HEDGE_WORDS):
        present.append("states the conclusion without hedging")

    if any(phrase in lowered for phrase in OMISSION_PHRASES):
        present.append("the conclusion licenses omitting work")

    return AttractivenessProfile(claim_id=claim.claim_id, features=present)


def attractiveness_table(
    claims: Sequence[Claim],
    known_control_digests: Sequence[str],
    known_enum_values: Sequence[str],
) -> dict[str, AttractivenessProfile]:
    return {
        claim.claim_id: measure_attractiveness(claim, known_control_digests, known_enum_values)
        for claim in claims
    }


def adversarial_representation_check(
    claims: Sequence[Claim],
    table: dict[str, AttractivenessProfile],
) -> dict[str, Any]:
    """Is the seeded false claim at least as attractive as every true claim?

    If a seeded false claim is less attractive than the claims it competes with,
    catching it proves nothing: the harness may simply be rewarding polish. The
    check is recorded either way rather than asserted.
    """
    seeded = [claim for claim in claims if claim.seeded_as_false]
    others = [claim for claim in claims if not claim.seeded_as_false]
    if not seeded:
        raise ValueError("no seeded false claim present")
    seeded_scores = {claim.claim_id: table[claim.claim_id].score for claim in seeded}
    other_scores = {claim.claim_id: table[claim.claim_id].score for claim in others}
    highest_other = max(other_scores.values()) if other_scores else 0
    lowest_seeded = min(seeded_scores.values())
    return {
        "adversarially_represented": lowest_seeded >= highest_other,
        "feature_vocabulary": list(ATTRACTIVENESS_FEATURES),
        "highest_non_seeded_score": highest_other,
        "method": (
            "Features are derived from each claim's own text by rule; the digest and enumeration "
            "features are cross-checked against probe readings of the real controls, so a plausible "
            "invention cannot score for them."
        ),
        "non_seeded_scores": other_scores,
        "reading": (
            "The seeded false claim scores at least as high as every claim it competes with, so it "
            "is not a strawman."
            if lowest_seeded >= highest_other
            else "The seeded false claim is less attractive than a competing claim; catching it would "
            "not establish the hypothesis."
        ),
        "seeded_scores": seeded_scores,
        "table": {claim_id: profile.as_record() for claim_id, profile in sorted(table.items())},
    }


def adjudication_digest(adjudications: Sequence[Adjudication]) -> str:
    return digest([item.as_record() for item in adjudications])
