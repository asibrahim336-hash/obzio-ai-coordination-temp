"""PO03-WA-052 — function, appointment, runtime and provider stay orthogonal.

Frozen hypothesis: ontology checks separate function, appointment, runtime, and
provider identity.

The repository-wide operator rules state the separation directly: actors are
identified by durable institutional function and appointment, while provider,
model, browser, extension, device, account and tool details are recorded only as
runtime bindings or execution evidence. A runtime never grants authority and a
rename never removes standing permission.

This component turns those rules into an executable resolver over four
orthogonal axes. It refuses records that route from the wrong axis, that source
authority from a runtime, or that let a rename cancel an existing appointment.

Standard library only. Distinct from PO03-WA-050, which resolves *one* identity
through aliasing; this component checks the *shape* of an actor record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Axis(str, Enum):
    FUNCTION = "function"
    APPOINTMENT = "appointment"
    RUNTIME = "runtime"
    PROVIDER = "provider"


AUTHORITY_BEARING_AXES = frozenset({Axis.FUNCTION, Axis.APPOINTMENT})
EVIDENCE_ONLY_AXES = frozenset({Axis.RUNTIME, Axis.PROVIDER})

FUNCTION_PATTERN = re.compile(r"^obzio\.function\.[a-z0-9][a-z0-9-]*$")
APPOINTMENT_PATTERN = re.compile(r"^obzio\.appointment\.[a-z0-9][a-z0-9.-]*\.\d{8}\.\d{3}$")

# Vocabulary that names a runtime surface, never a durable institutional actor.
RUNTIME_VOCABULARY = frozenset(
    {
        "cursor",
        "cursor cloud",
        "cursor cloud agent",
        "chrome",
        "browser",
        "chrome extension",
        "claude extension",
        "claude chrome extension",
        "claude browser operator",
        "desktop",
        "vm",
        "worktree",
        "terminal",
    }
)

# Vocabulary that names a provider, model or account, never a function.
PROVIDER_VOCABULARY = frozenset(
    {
        "anthropic",
        "openai",
        "google",
        "claude-opus-5",
        "claude-opus-5-thinking-high",
        "gpt-5.6-sol",
        "gpt-5.6-sol-xhigh",
        "gpt-5.6-sol-max-fast",
        "gemini-3.1-pro",
        "composer-2.5",
        "auto",
    }
)

# Colloquial or historical labels, permitted only inside declared alias fields.
LEGACY_ALIASES = frozenset(
    {
        "operator d",
        "claude extension",
        "claude browser operator",
        "principal ai operator",
        "chatgpt account operations and commissioning director",
    }
)


class OntologyViolation(ValueError):
    """Raised when an actor record collapses two ontology axes."""


class AuthoritySourceError(PermissionError):
    """Raised when authority is claimed from a runtime or provider binding."""


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip().casefold())


def axis_of(value: str) -> Axis | None:
    """Best-effort axis inference used to detect a value placed on the wrong axis."""
    raw = str(value).strip()
    if FUNCTION_PATTERN.match(raw):
        return Axis.FUNCTION
    if APPOINTMENT_PATTERN.match(raw):
        return Axis.APPOINTMENT
    norm = _norm(raw)
    if norm in RUNTIME_VOCABULARY:
        return Axis.RUNTIME
    if norm in PROVIDER_VOCABULARY:
        return Axis.PROVIDER
    return None


@dataclass(frozen=True)
class ActorRecord:
    """Four orthogonal axes plus explicitly quarantined alias/provenance fields."""

    function: str
    appointment: str
    runtime_binding: str = ""
    provider_model: str = ""
    aliases: tuple = ()
    provenance: tuple = ()
    authority_envelope: str = ""
    supersedes_appointment: str = ""


@dataclass
class Resolution:
    axes: dict
    aliases: tuple
    provenance: tuple
    authority_envelope: str
    violations: list = field(default_factory=list)

    @property
    def separated(self) -> bool:
        return not self.violations


def resolve(record: ActorRecord, strict: bool = True) -> Resolution:
    """Resolve an actor record into four axes, refusing any cross-axis leak."""
    violations = []

    if not FUNCTION_PATTERN.match(record.function.strip()):
        violations.append(f"function {record.function!r} is not a durable function identifier")
    if not APPOINTMENT_PATTERN.match(record.appointment.strip()):
        violations.append(
            f"appointment {record.appointment!r} is not a durable appointment identifier"
        )

    for axis, value in (
        (Axis.FUNCTION, record.function),
        (Axis.APPOINTMENT, record.appointment),
    ):
        inferred = axis_of(value)
        if inferred is not None and inferred is not axis:
            violations.append(
                f"{axis.value} field carries a {inferred.value} value {value!r}"
            )
        if _norm(value) in LEGACY_ALIASES:
            violations.append(
                f"{axis.value} field carries the legacy alias {value!r}; aliases belong in "
                f"the alias or provenance field"
            )

    if record.runtime_binding:
        inferred = axis_of(record.runtime_binding)
        if inferred in AUTHORITY_BEARING_AXES:
            violations.append(
                f"runtime_binding carries a {inferred.value} value {record.runtime_binding!r}"
            )
    if record.provider_model:
        inferred = axis_of(record.provider_model)
        if inferred in AUTHORITY_BEARING_AXES:
            violations.append(
                f"provider_model carries a {inferred.value} value {record.provider_model!r}"
            )
        if inferred is Axis.RUNTIME:
            violations.append(
                f"provider_model carries a runtime value {record.provider_model!r}"
            )

    resolution = Resolution(
        axes={
            Axis.FUNCTION.value: record.function.strip(),
            Axis.APPOINTMENT.value: record.appointment.strip(),
            Axis.RUNTIME.value: record.runtime_binding.strip(),
            Axis.PROVIDER.value: record.provider_model.strip(),
        },
        aliases=tuple(record.aliases),
        provenance=tuple(record.provenance),
        authority_envelope=record.authority_envelope,
        violations=violations,
    )
    if strict and violations:
        raise OntologyViolation("; ".join(violations))
    return resolution


def authority_source(record: ActorRecord, claimed_from: Axis) -> str:
    """Authority may be read only from an authority-bearing axis."""
    if claimed_from in EVIDENCE_ONLY_AXES:
        raise AuthoritySourceError(
            f"{claimed_from.value} is execution evidence and never grants authority; "
            f"use {sorted(a.value for a in AUTHORITY_BEARING_AXES)}"
        )
    resolve(record)
    if not record.authority_envelope:
        raise AuthoritySourceError("record carries no authority envelope")
    return record.authority_envelope


def rebind_runtime(record: ActorRecord, new_runtime: str, new_provider: str = "") -> ActorRecord:
    """Change the runtime/provider binding. Authority and appointment must survive."""
    updated = ActorRecord(
        function=record.function,
        appointment=record.appointment,
        runtime_binding=new_runtime,
        provider_model=new_provider or record.provider_model,
        aliases=record.aliases,
        provenance=record.provenance + (f"previous-runtime:{record.runtime_binding}",),
        authority_envelope=record.authority_envelope,
        supersedes_appointment=record.supersedes_appointment,
    )
    resolve(updated)
    return updated


def rename_function(record: ActorRecord, new_function: str) -> ActorRecord:
    """A rename is additive: the prior name becomes provenance, authority persists."""
    updated = ActorRecord(
        function=new_function,
        appointment=record.appointment,
        runtime_binding=record.runtime_binding,
        provider_model=record.provider_model,
        aliases=record.aliases,
        provenance=record.provenance + (f"previous-function:{record.function}",),
        authority_envelope=record.authority_envelope,
        supersedes_appointment=record.supersedes_appointment,
    )
    resolve(updated)
    return updated
