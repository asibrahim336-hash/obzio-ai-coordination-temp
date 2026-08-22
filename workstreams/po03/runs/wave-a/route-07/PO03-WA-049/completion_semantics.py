"""PO03-WA-049 — provider, Obzio and acceptance completion are three separate axes.

Frozen hypothesis: frozen evaluators distinguish provider, Obzio, and acceptance
completion.

The failure this component blocks is the conflation that produced the lost PO-02
Code-2 packaging return: a provider reported `COMPLETED`, that observation was
read as Obzio completion, and the absence of a durable result commit was never
surfaced. The commission fixes the semantics explicitly — provider `COMPLETED`
is merely an observation, and without a verified durable result commit the Obzio
state is `PROVIDER_COMPLETED_UNCOMMITTED`, never `COMPLETED`.

This module models the three axes as independent lattices and refuses any read
that collapses one into another. It is a pure standard-library component.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Axis(str, Enum):
    PROVIDER = "provider"
    OBZIO = "obzio"
    ACCEPTANCE = "acceptance"


PROVIDER_STATES = (
    "QUEUED",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "UNKNOWN",
)

OBZIO_STATES = (
    "CREATED",
    "LEASED",
    "RUNNING",
    "CHECKPOINTED",
    "RESULT_STAGING",
    "RESULT_STAGED",
    "RESULT_VERIFIED",
    "RESULT_COMMITTED",
    "PARENT_INGESTED",
    "COMPLETED",
    "PROVIDER_COMPLETED_UNCOMMITTED",
    "RECOVERY_REQUIRED",
    "RETRY_SCHEDULED",
    "FAILED_TERMINAL",
    "CANCELLED",
)

ACCEPTANCE_STATES = ("NOT_TESTED", "PENDING", "ACCEPTED", "REJECTED")

# Obzio states that assert a durable, independently readable result commit.
DURABLE_OBZIO_STATES = frozenset(
    {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"}
)

# Only the coordinator may set COMPLETED; a subordinate may report no further
# than READY_TO_COMMIT.
SUBORDINATE_CEILING = "READY_TO_COMMIT"
COORDINATOR_ONLY_OBZIO_STATES = frozenset({"COMPLETED"})


class AxisConfusion(ValueError):
    """Raised when one completion axis is read as if it were another."""


class CustodyViolation(ValueError):
    """Raised when a triple asserts a state its evidence cannot support."""


@dataclass(frozen=True)
class CompletionTriple:
    provider_state: str
    obzio_state: str
    acceptance_state: str
    durable_result_commit_id: str | None = None
    parent_ingested_at: str | None = None
    completion_actor: str | None = None
    reviewer_id: str | None = None
    producer_id: str | None = None

    def __post_init__(self) -> None:
        if self.provider_state not in PROVIDER_STATES:
            raise ValueError(f"unknown provider state {self.provider_state!r}")
        if self.obzio_state not in OBZIO_STATES:
            raise ValueError(f"unknown obzio state {self.obzio_state!r}")
        if self.acceptance_state not in ACCEPTANCE_STATES:
            raise ValueError(f"unknown acceptance state {self.acceptance_state!r}")


@dataclass(frozen=True)
class Classification:
    effective_obzio_state: str
    reclassified: bool
    reason: str
    axis_values: dict


def is_complete(triple: CompletionTriple, axis: Axis) -> bool:
    """Ask exactly one axis whether it is complete. Never blend axes."""
    if not isinstance(axis, Axis):
        raise AxisConfusion(f"axis must be an Axis member, got {axis!r}")
    if axis is Axis.PROVIDER:
        return triple.provider_state == "COMPLETED"
    if axis is Axis.OBZIO:
        return triple.obzio_state == "COMPLETED"
    return triple.acceptance_state == "ACCEPTED"


def provider_completion_implies_obzio_completion(triple: CompletionTriple) -> bool:
    """The conflation the commission forbids. Always refuses to answer."""
    raise AxisConfusion(
        "provider completion is an observation and never implies Obzio completion; "
        "ask is_complete(triple, Axis.OBZIO) and supply durable commit evidence"
    )


def classify(triple: CompletionTriple) -> Classification:
    """Return the Obzio state the evidence actually supports."""
    axis_values = {
        Axis.PROVIDER.value: triple.provider_state,
        Axis.OBZIO.value: triple.obzio_state,
        Axis.ACCEPTANCE.value: triple.acceptance_state,
    }
    has_commit = bool(triple.durable_result_commit_id)

    if triple.obzio_state in DURABLE_OBZIO_STATES and not has_commit:
        if triple.provider_state == "COMPLETED":
            return Classification(
                "PROVIDER_COMPLETED_UNCOMMITTED",
                True,
                "provider reported COMPLETED with no durable result commit",
                axis_values,
            )
        return Classification(
            "RECOVERY_REQUIRED",
            True,
            f"{triple.obzio_state} asserted without a durable result commit",
            axis_values,
        )

    if triple.obzio_state == "COMPLETED":
        if triple.completion_actor != "coordinator":
            raise CustodyViolation(
                f"only the coordinator may set COMPLETED; actor={triple.completion_actor!r} "
                f"(subordinate ceiling is {SUBORDINATE_CEILING})"
            )
        if not triple.parent_ingested_at:
            return Classification(
                "RESULT_COMMITTED",
                True,
                "COMPLETED requires recorded parent ingestion",
                axis_values,
            )

    if triple.acceptance_state in ("ACCEPTED", "REJECTED"):
        if triple.obzio_state != "COMPLETED":
            raise CustodyViolation(
                "independent acceptance cannot be terminal before Obzio COMPLETED "
                f"(obzio_state={triple.obzio_state})"
            )
        if triple.reviewer_id is None or triple.reviewer_id == triple.producer_id:
            raise CustodyViolation(
                "independent acceptance requires a reviewer distinct from the producer"
            )

    if (
        triple.provider_state == "COMPLETED"
        and triple.obzio_state not in DURABLE_OBZIO_STATES
        and triple.obzio_state
        not in ("PROVIDER_COMPLETED_UNCOMMITTED", "RECOVERY_REQUIRED", "FAILED_TERMINAL", "CANCELLED")
        and not has_commit
    ):
        return Classification(
            "PROVIDER_COMPLETED_UNCOMMITTED",
            True,
            f"provider COMPLETED while Obzio is {triple.obzio_state} with no durable commit",
            axis_values,
        )

    return Classification(triple.obzio_state, False, "evidence supports the asserted state", axis_values)


def independent_axes_report(triple: CompletionTriple) -> dict:
    """Emit the three axes side by side so no consumer has to infer one from another."""
    return {
        Axis.PROVIDER.value: {
            "state": triple.provider_state,
            "complete": is_complete(triple, Axis.PROVIDER),
            "meaning": "observation of the provider runtime only",
        },
        Axis.OBZIO.value: {
            "state": classify(triple).effective_obzio_state,
            "asserted_state": triple.obzio_state,
            "complete": classify(triple).effective_obzio_state == "COMPLETED",
            "meaning": "durable custody state backed by a verified result commit",
        },
        Axis.ACCEPTANCE.value: {
            "state": triple.acceptance_state,
            "complete": is_complete(triple, Axis.ACCEPTANCE),
            "meaning": "decision of a different producer, never of the producer itself",
        },
    }
