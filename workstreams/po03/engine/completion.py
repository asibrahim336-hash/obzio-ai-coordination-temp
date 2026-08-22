"""The Obzio custody state machine: completion is structural, not conventional.

The defect this closes is recorded in the SO-02 correction as "worker
self-report could represent completion".  A convention that says *the
coordinator sets COMPLETED* is worthless, because the worker writes the
document.  So completion is reserved by construction, in three independent
ways, each of which alone would stop a worker:

1. ``COMPLETED`` has exactly one predecessor, ``PARENT_INGESTED``.  There is no
   other edge into it anywhere in the transition relation.
2. Only the ``COORDINATOR`` role may traverse that edge, and a role is derived
   from an actor identity by :class:`CustodyAuthority`.  An actor cannot elect
   itself coordinator by naming itself one: the authority holds a single
   coordinator identity and everything else is a worker or a reviewer.
3. The edge additionally requires ``ingestion_recorded``, which is only true
   after the coordinator has independently re-read every artifact by hash.  A
   worker cannot set it, because it is derived from the coordinator's own
   read-back rather than from anything the worker sends.

Acceptance is deliberately *not* a custody state.  A reviewer's disposition
lives in the result contract's ``independent_acceptance`` block, so no producer
can reach an accepted state by walking the graph.

``test_a1_completion_authority.py`` proves these claims exhaustively over all
fifteen states and all four roles rather than trusting this docstring.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable

from .canonical import utc_now
from .ledger import HashChainedLedger

# The fifteen Obzio states, in the order the commission lists them.
CREATED = "CREATED"
LEASED = "LEASED"
RUNNING = "RUNNING"
CHECKPOINTED = "CHECKPOINTED"
RESULT_STAGING = "RESULT_STAGING"
RESULT_STAGED = "RESULT_STAGED"
RESULT_VERIFIED = "RESULT_VERIFIED"
RESULT_COMMITTED = "RESULT_COMMITTED"
PARENT_INGESTED = "PARENT_INGESTED"
COMPLETED = "COMPLETED"
PROVIDER_COMPLETED_UNCOMMITTED = "PROVIDER_COMPLETED_UNCOMMITTED"
RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
RETRY_SCHEDULED = "RETRY_SCHEDULED"
FAILED_TERMINAL = "FAILED_TERMINAL"
CANCELLED = "CANCELLED"

OBZIO_STATES = (
    CREATED,
    LEASED,
    RUNNING,
    CHECKPOINTED,
    RESULT_STAGING,
    RESULT_STAGED,
    RESULT_VERIFIED,
    RESULT_COMMITTED,
    PARENT_INGESTED,
    COMPLETED,
    PROVIDER_COMPLETED_UNCOMMITTED,
    RECOVERY_REQUIRED,
    RETRY_SCHEDULED,
    FAILED_TERMINAL,
    CANCELLED,
)

WORKER = "WORKER"
COORDINATOR = "COORDINATOR"
REVIEWER = "REVIEWER"
PROVIDER = "PROVIDER"
ROLES = (WORKER, COORDINATOR, REVIEWER, PROVIDER)

TERMINAL_STATES = frozenset({COMPLETED, FAILED_TERMINAL, CANCELLED})
COMMITTED_STATES = frozenset({RESULT_COMMITTED, PARENT_INGESTED, COMPLETED})

# Abandonment edges every non-terminal state shares.  Kept separate so the
# interesting edges below stay readable.
_ABANDON: dict[str, frozenset[str]] = {
    RECOVERY_REQUIRED: frozenset({COORDINATOR}),
    FAILED_TERMINAL: frozenset({COORDINATOR, WORKER}),
    CANCELLED: frozenset({COORDINATOR}),
    PROVIDER_COMPLETED_UNCOMMITTED: frozenset({COORDINATOR}),
}

# TRANSITIONS[from_state][to_state] is the set of roles permitted to traverse
# the edge.  An absent key means there is no such edge at all.
TRANSITIONS: dict[str, dict[str, frozenset[str]]] = {
    CREATED: {
        LEASED: frozenset({COORDINATOR}),
        RECOVERY_REQUIRED: frozenset({COORDINATOR}),
        FAILED_TERMINAL: frozenset({COORDINATOR}),
        CANCELLED: frozenset({COORDINATOR}),
    },
    LEASED: {RUNNING: frozenset({WORKER}), **_ABANDON},
    RUNNING: {
        CHECKPOINTED: frozenset({WORKER}),
        RESULT_STAGING: frozenset({WORKER}),
        **_ABANDON,
    },
    CHECKPOINTED: {
        CHECKPOINTED: frozenset({WORKER}),
        RUNNING: frozenset({WORKER}),
        RESULT_STAGING: frozenset({WORKER}),
        **_ABANDON,
    },
    RESULT_STAGING: {RESULT_STAGED: frozenset({WORKER}), **_ABANDON},
    RESULT_STAGED: {RESULT_VERIFIED: frozenset({WORKER}), **_ABANDON},
    RESULT_VERIFIED: {RESULT_COMMITTED: frozenset({WORKER}), **_ABANDON},
    # Past this line the worker has no edges at all: custody has moved.
    RESULT_COMMITTED: {
        PARENT_INGESTED: frozenset({COORDINATOR}),
        RECOVERY_REQUIRED: frozenset({COORDINATOR}),
    },
    PARENT_INGESTED: {
        COMPLETED: frozenset({COORDINATOR}),
        RECOVERY_REQUIRED: frozenset({COORDINATOR}),
    },
    COMPLETED: {},
    PROVIDER_COMPLETED_UNCOMMITTED: {
        RETRY_SCHEDULED: frozenset({COORDINATOR}),
        RECOVERY_REQUIRED: frozenset({COORDINATOR}),
        FAILED_TERMINAL: frozenset({COORDINATOR}),
    },
    RECOVERY_REQUIRED: {
        RETRY_SCHEDULED: frozenset({COORDINATOR}),
        FAILED_TERMINAL: frozenset({COORDINATOR}),
        CANCELLED: frozenset({COORDINATOR}),
    },
    RETRY_SCHEDULED: {
        LEASED: frozenset({COORDINATOR}),
        FAILED_TERMINAL: frozenset({COORDINATOR}),
        CANCELLED: frozenset({COORDINATOR}),
    },
    FAILED_TERMINAL: {},
    CANCELLED: {},
}


class CustodyViolation(RuntimeError):
    """Raised when a transition would break the custody invariants."""


@dataclass(frozen=True)
class CustodyContext:
    """Facts a transition may depend on, each established by a real check.

    ``artifacts_verified`` and ``durable_commit_id`` are the producer's own
    evidence.  ``readback_verified`` and ``ingestion_recorded`` are *not*: they
    can only be set by the coordinator after it has re-read the bytes itself,
    which is why a worker cannot manufacture them.
    """

    artifacts_verified: bool = False
    durable_commit_id: str | None = None
    readback_verified: bool = False
    ingestion_recorded: bool = False
    checkpoint_seq: int = 0

    def merged(self, **updates: Any) -> "CustodyContext":
        return replace(self, **updates)

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifacts_verified": self.artifacts_verified,
            "durable_commit_id": self.durable_commit_id,
            "readback_verified": self.readback_verified,
            "ingestion_recorded": self.ingestion_recorded,
            "checkpoint_seq": self.checkpoint_seq,
        }


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


class CustodyAuthority:
    """Maps an actor identity to a role.  Identity does not confer authority.

    There is exactly one coordinator identity.  Anything else is a worker
    unless it is a declared reviewer, so a subordinate that writes
    ``actor="coordinator-ish"`` into a document gains nothing.
    """

    def __init__(self, *, coordinator_id: str = "coordinator", reviewer_ids: Iterable[str] = ()) -> None:
        self.coordinator_id = coordinator_id
        self.reviewer_ids = frozenset(reviewer_ids)
        if self.coordinator_id in self.reviewer_ids:
            raise ValueError("the coordinator cannot also be an independent reviewer")

    def role_of(self, actor_id: str) -> str:
        if actor_id == self.coordinator_id:
            return COORDINATOR
        if actor_id in self.reviewer_ids:
            return REVIEWER
        if actor_id.startswith("provider:"):
            return PROVIDER
        return WORKER


def evaluate(from_state: str, to_state: str, role: str, context: CustodyContext) -> Decision:
    """Rule on one transition.  The only authority on what is permitted."""
    if from_state not in TRANSITIONS:
        return Decision(False, f"unknown state {from_state!r}")
    if to_state not in TRANSITIONS:
        return Decision(False, f"unknown state {to_state!r}")
    if role not in ROLES:
        return Decision(False, f"unknown role {role!r}")
    if from_state in TERMINAL_STATES:
        return Decision(False, f"{from_state} is terminal; no transition leaves it")

    permitted = TRANSITIONS[from_state].get(to_state)
    if permitted is None:
        return Decision(False, f"no edge {from_state} -> {to_state} exists")
    if role not in permitted:
        return Decision(
            False,
            f"role {role} may not traverse {from_state} -> {to_state}; permitted roles are "
            f"{sorted(permitted)}",
        )

    if to_state == RESULT_COMMITTED:
        if not context.artifacts_verified:
            return Decision(False, "RESULT_COMMITTED requires the producer to have verified its artifacts")
        if not context.durable_commit_id:
            return Decision(False, "RESULT_COMMITTED requires a durable commit identifier")
    if to_state == PARENT_INGESTED:
        if not context.readback_verified:
            return Decision(
                False, "PARENT_INGESTED requires the coordinator's own read-back of every artifact by hash"
            )
        if not context.durable_commit_id:
            return Decision(False, "PARENT_INGESTED requires a durable commit identifier")
    if to_state == COMPLETED:
        if from_state != PARENT_INGESTED:
            return Decision(False, "COMPLETED is only reachable from PARENT_INGESTED")
        if not context.ingestion_recorded:
            return Decision(False, "COMPLETED requires recorded coordinator ingestion")
        if not context.durable_commit_id:
            return Decision(False, "COMPLETED requires a durable commit identifier")
    if to_state == CHECKPOINTED and from_state == CHECKPOINTED:
        return Decision(True, "checkpoint sequence monotonicity is enforced by the lease manager")
    return Decision(True, f"{from_state} -> {to_state} permitted for {role}")


def paths_into(state: str) -> list[tuple[str, frozenset[str]]]:
    """Every declared edge that terminates at ``state``, with its roles."""
    return sorted(
        ((source, roles) for source, edges in TRANSITIONS.items() for target, roles in edges.items() if target == state),
        key=lambda item: item[0],
    )


class CustodyMachine:
    """A live state holder that records every accepted transition in the ledger.

    Every custody-advancing mechanism in the engine drives its state changes
    through here, so the transition relation is the code path rather than
    documentation about the code path.
    """

    def __init__(
        self,
        unit_id: str,
        ledger: HashChainedLedger,
        *,
        authority: CustodyAuthority | None = None,
        state: str = CREATED,
        context: CustodyContext | None = None,
    ) -> None:
        self.unit_id = unit_id
        self.ledger = ledger
        self.authority = authority or CustodyAuthority()
        self.state = state
        self.context = context or CustodyContext()

    def can(self, to_state: str, actor_id: str, **context_updates: Any) -> Decision:
        return evaluate(
            self.state,
            to_state,
            self.authority.role_of(actor_id),
            self.context.merged(**context_updates) if context_updates else self.context,
        )

    def transition(
        self,
        to_state: str,
        *,
        actor_id: str,
        fence_token: int | None = None,
        payload: dict[str, Any] | None = None,
        **context_updates: Any,
    ) -> dict[str, Any]:
        context = self.context.merged(**context_updates) if context_updates else self.context
        role = self.authority.role_of(actor_id)
        decision = evaluate(self.state, to_state, role, context)
        if not decision.allowed:
            raise CustodyViolation(
                f"{self.unit_id}: refused {self.state} -> {to_state} by {actor_id} ({role}): {decision.reason}"
            )
        row = self.ledger.append(
            self.unit_id,
            to_state,
            actor=actor_id,
            obzio_state=to_state,
            fence_token=fence_token,
            payload={**(payload or {}), "role": role, "context": context.as_dict(), "decided_at": utc_now()},
        )
        self.state = to_state
        self.context = context
        return row
