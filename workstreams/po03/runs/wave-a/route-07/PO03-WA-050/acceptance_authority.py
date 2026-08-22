"""PO03-WA-050 — self-acceptance stays blocked when identities are aliased.

Frozen hypothesis: a producer cannot self-accept through identity aliasing.

A naive reviewer check compares two identity strings. That check is defeated by
trivial aliasing: case folding, Unicode confusables, zero-width joiners, an
e-mail form of the same handle, or a runtime label standing in for the durable
institutional actor. The repository-wide operator rules make the last case
explicit — `Operator D`, `Claude extension`, `Claude browser operator` and
`principal AI operator` are historical or colloquial aliases and are prohibited
for active routing outside alias, runtime or provenance fields.

This component resolves any identity claim to a durable principal before the
distinctness test, and additionally requires a different frontier model family
for consequential acceptance. It is a pure standard-library component.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Confusable code points that render like ASCII letters.
_HOMOGLYPHS = {
    "\u0430": "a",  # CYRILLIC SMALL LETTER A
    "\u0435": "e",  # CYRILLIC SMALL LETTER IE
    "\u043e": "o",  # CYRILLIC SMALL LETTER O
    "\u0440": "p",  # CYRILLIC SMALL LETTER ER
    "\u0441": "c",  # CYRILLIC SMALL LETTER ES
    "\u0445": "x",  # CYRILLIC SMALL LETTER HA
    "\u0455": "s",  # CYRILLIC SMALL LETTER DZE
    "\u0456": "i",  # CYRILLIC SMALL LETTER BYELORUSSIAN-UKRAINIAN I
    "\u03bf": "o",  # GREEK SMALL LETTER OMICRON
    "\u0501": "d",  # CYRILLIC SMALL LETTER KOMI DE
    "\uff41": "a",  # FULLWIDTH LATIN SMALL LETTER A
}

_INVISIBLE = "".join(
    ch
    for ch in (
        "\u200b",  # zero width space
        "\u200c",  # zero width non-joiner
        "\u200d",  # zero width joiner
        "\u2060",  # word joiner
        "\ufeff",  # zero width no-break space
        "\u00ad",  # soft hyphen
    )
)

# Runtime/colloquial labels that never identify a durable principal.
PROHIBITED_ROUTING_ALIASES = frozenset(
    {
        "operator d",
        "claude extension",
        "claude chrome extension",
        "claude browser operator",
        "principal ai operator",
    }
)

ALIAS_ONLY_FIELDS = frozenset({"alias", "aliases", "runtime", "runtime_binding", "provenance"})


class IdentityRoutingError(ValueError):
    """Raised when a runtime or colloquial alias is used as a routing identity."""


class SelfAcceptanceBlocked(PermissionError):
    """Raised when the reviewer resolves to the same principal as the producer."""


class ChallengerFamilyRequired(PermissionError):
    """Raised when consequential acceptance lacks a second frontier family."""


def normalize_identity(raw: str) -> str:
    """Collapse an identity claim to a comparison-safe canonical form."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("identity must be a non-empty string")
    text = unicodedata.normalize("NFKC", raw)
    text = text.translate({ord(ch): None for ch in _INVISIBLE})
    text = "".join(_HOMOGLYPHS.get(ch, ch) for ch in text)
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.split("@", 1)[0] if "@" in text else text
    text = re.sub(r"[\s._\-+]+", "-", text.strip())
    text = re.sub(r"-+", "-", text).strip("-")
    return text


@dataclass(frozen=True)
class Principal:
    """A durable institutional actor, separate from whatever runtime executes it."""

    function: str
    appointment: str
    display_name: str = ""
    aliases: tuple = ()
    runtime_binding: str = ""
    provider_run_id: str = ""
    model_family: str = ""

    @property
    def durable_key(self) -> str:
        return f"{normalize_identity(self.function)}::{normalize_identity(self.appointment)}"

    def claims(self) -> set:
        out = {normalize_identity(self.appointment), normalize_identity(self.function)}
        if self.display_name:
            out.add(normalize_identity(self.display_name))
        for alias in self.aliases:
            out.add(normalize_identity(alias))
        return out


@dataclass
class IdentityRegistry:
    """Resolves an identity claim, from any field, to one durable principal."""

    principals: list = field(default_factory=list)

    def register(self, principal: Principal) -> None:
        self.principals.append(principal)

    def resolve(self, claim: str, field_name: str = "reviewer_id") -> Principal:
        key = normalize_identity(claim)
        if key in PROHIBITED_ROUTING_ALIASES or claim.strip().casefold() in PROHIBITED_ROUTING_ALIASES:
            if field_name not in ALIAS_ONLY_FIELDS:
                raise IdentityRoutingError(
                    f"{claim!r} is a runtime or colloquial alias and is prohibited for routing "
                    f"in field {field_name!r}; permitted only in {sorted(ALIAS_ONLY_FIELDS)}"
                )
        for principal in self.principals:
            if key in principal.claims():
                return principal
        raise IdentityRoutingError(f"identity claim {claim!r} resolves to no registered principal")


def authorize_acceptance(
    registry: IdentityRegistry,
    producer_claim: str,
    reviewer_claim: str,
    consequential: bool = True,
    reviewer_field: str = "reviewer_id",
) -> dict:
    """Return the authorisation record, or refuse.

    Refuses when the reviewer resolves to the producer's durable principal, and
    when a consequential decision is not challenged by a different frontier
    model family.
    """
    producer = registry.resolve(producer_claim, field_name="producer_id")
    reviewer = registry.resolve(reviewer_claim, field_name=reviewer_field)

    if producer.durable_key == reviewer.durable_key:
        raise SelfAcceptanceBlocked(
            f"reviewer claim {reviewer_claim!r} resolves to the producing principal "
            f"{producer.durable_key!r}; self-acceptance is prohibited"
        )
    if normalize_identity(producer_claim) == normalize_identity(reviewer_claim):
        raise SelfAcceptanceBlocked("reviewer and producer claims normalise to one identity")

    if consequential:
        if not producer.model_family or not reviewer.model_family:
            raise ChallengerFamilyRequired("model family must be recorded on both sides")
        if normalize_identity(producer.model_family) == normalize_identity(reviewer.model_family):
            raise ChallengerFamilyRequired(
                f"consequential acceptance requires a second frontier family; both sides are "
                f"{producer.model_family!r}"
            )

    return {
        "authorized": True,
        "producer_principal": producer.durable_key,
        "reviewer_principal": reviewer.durable_key,
        "producer_model_family": producer.model_family,
        "reviewer_model_family": reviewer.model_family,
        "consequential": consequential,
        "terminal_state_permitted": False,
        "permitted_reviewer_outputs": ["RECOMMEND_ACCEPT", "RECOMMEND_REJECT", "RETEST"],
    }
