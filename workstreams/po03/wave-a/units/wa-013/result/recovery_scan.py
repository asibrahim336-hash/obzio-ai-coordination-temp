#!/usr/bin/env python3
"""Append-only recovery scanner for PO-03 transactional work-unit custody.

Reconstructs the current Obzio state of every work unit from the append-only
event ledger alone, then classifies each unit into a recovery disposition.  The
two dispositions this scanner exists to prove detectable are:

``COMMITTED_NOT_INGESTED``
    A durable result commit exists but the parent never recorded ingestion.
    The return callback was lost; the ledger still holds enough information to
    replay ingestion without rerunning the producer.

``PROVIDER_COMPLETED_UNCOMMITTED``
    The provider observed completion but no verified durable result commit
    exists.  Per the commission this is never ``COMPLETED``; it must be rerun
    from immutable input.

Design constraints that follow from the commission:

* Ordering authority is ``event_seq``, not ``at``.  Wall-clock stamps in the
  live ledger are written by several actors and are not monotonic with respect
  to append order, so timestamp ordering would silently reorder a lifecycle.
* Fence tokens are task-scoped and monotonic.  An event carrying a fence token
  below the highest token seen for its task is refused and cannot advance
  state, so a stale worker cannot commit after ownership transfers.
* Duplicate delivery is harmless.  Events are deduplicated by ``event_id``;
  a repeat of the same identifier carrying different bytes is instead a
  critical integrity violation.
* The scan is a pure function of (ledger bytes, provider observations,
  artifact probe, evaluation instant).  No wall-clock, environment or path
  leaks into the report, so the report digest is reproducible from a clean
  clone.

Dependency-free: standard library only, so it runs in a clean runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

REPORT_PROTOCOL_VERSION = "OBZIO-RECOVERY-SCAN-REPORT-v1"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})$"
)

# Main-line lifecycle from the commission, in order.
MAIN_LINE: tuple[str, ...] = (
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
)
MAIN_LINE_RANK = {state: index for index, state in enumerate(MAIN_LINE, start=1)}
REVIEW_STATES = frozenset({"ACCEPTED", "REJECTED"})

# Off-main-line control states the controller may record.
CONTROL_STATES = frozenset(
    {
        "FENCED",
        "SUPERSEDED_BEFORE_DISPATCH",
        "RECOVERY_REQUIRED",
        "RETRY_SCHEDULED",
        "FAILED_TERMINAL",
        "CANCELLED",
        "PROVIDER_COMPLETED_UNCOMMITTED",
    }
)
KNOWN_STATES = frozenset(MAIN_LINE) | REVIEW_STATES | CONTROL_STATES

# Attempt-terminal states: the attempt is closed and carries no live work.
ATTEMPT_CLOSED = frozenset(
    {"FENCED", "SUPERSEDED_BEFORE_DISPATCH", "FAILED_TERMINAL", "CANCELLED"}
)

# In-flight states: a producer holds the unit and no result commit exists yet.
IN_FLIGHT = frozenset(
    {"RUNNING", "CHECKPOINTED", "RESULT_STAGING", "RESULT_STAGED", "RESULT_VERIFIED"}
)

ALLOWED_MAIN_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"CREATED"}),
    "CREATED": frozenset({"LEASED"}),
    "LEASED": frozenset({"RUNNING"}),
    "RUNNING": frozenset({"CHECKPOINTED", "RESULT_STAGING"}),
    "CHECKPOINTED": frozenset({"CHECKPOINTED", "RESULT_STAGING"}),
    "RESULT_STAGING": frozenset({"RESULT_STAGED"}),
    "RESULT_STAGED": frozenset({"RESULT_VERIFIED"}),
    "RESULT_VERIFIED": frozenset({"RESULT_COMMITTED"}),
    "RESULT_COMMITTED": frozenset({"PARENT_INGESTED"}),
    "PARENT_INGESTED": frozenset({"COMPLETED"}),
    "COMPLETED": frozenset({"ACCEPTED", "REJECTED"}),
    "ACCEPTED": frozenset(),
    "REJECTED": frozenset(),
}

# Control states reachable from a live attempt regardless of main-line position.
CONTROL_ENTRY = frozenset(
    {
        "FENCED",
        "SUPERSEDED_BEFORE_DISPATCH",
        "RECOVERY_REQUIRED",
        "RETRY_SCHEDULED",
        "FAILED_TERMINAL",
        "CANCELLED",
        "PROVIDER_COMPLETED_UNCOMMITTED",
    }
)
ALLOWED_CONTROL_EXITS: dict[str, frozenset[str]] = {
    "FENCED": frozenset({"SUPERSEDED_BEFORE_DISPATCH", "CREATED", "RECOVERY_REQUIRED"}),
    "SUPERSEDED_BEFORE_DISPATCH": frozenset({"CREATED"}),
    "RECOVERY_REQUIRED": frozenset({"CREATED", "LEASED", "RETRY_SCHEDULED", "RUNNING"}),
    "RETRY_SCHEDULED": frozenset({"CREATED", "LEASED", "RUNNING"}),
    "PROVIDER_COMPLETED_UNCOMMITTED": frozenset(
        {"CREATED", "LEASED", "RECOVERY_REQUIRED", "RETRY_SCHEDULED"}
    ),
    "FAILED_TERMINAL": frozenset({"CREATED"}),
    "CANCELLED": frozenset({"CREATED"}),
}

# Actors permitted to record specific states.  A producer cannot promote its own
# work to COMPLETED, and a producer cannot accept its own work.
COORDINATOR_ACTOR_PREFIXES = ("controller", "coordinator")
REVIEWER_ACTOR_PREFIXES = ("controller-verifier", "reviewer", "assurance")

CRITICAL = "CRITICAL"
DEFECT = "DEFECT"
ADVISORY = "ADVISORY"

REQUIRED_EVENT_FIELDS = ("event_id", "event_seq", "task_id", "to_state")


class LedgerIntegrityError(ValueError):
    """Raised only for input the scanner cannot scan at all."""


def _actor_prefix(actor: Any) -> str:
    if not isinstance(actor, str):
        return ""
    return actor.split(":", 1)[0].strip()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def parse_instant(value: Any) -> int | None:
    """Return a comparable epoch-second integer, or None when unparseable.

    Accepts the ``Z`` and ``+00:00`` forms that both appear in the live ledger.
    Implemented directly so the scanner does not depend on the host platform's
    ``fromisoformat`` behaviour for trailing ``Z``.
    """
    if not isinstance(value, str):
        return None
    match = ISO_RE.fullmatch(value.strip())
    if match is None:
        return None
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    offset_text = match.group(8)
    if offset_text == "Z":
        offset_seconds = 0
    else:
        sign = 1 if offset_text[0] == "+" else -1
        digits = offset_text[1:].replace(":", "")
        offset_seconds = sign * (int(digits[:2]) * 3600 + int(digits[2:4]) * 60)
    # Days-from-civil (Howard Hinnant's algorithm) keeps this pure-integer.
    shifted_year = year - (1 if month <= 2 else 0)
    era = (shifted_year if shifted_year >= 0 else shifted_year - 399) // 400
    year_of_era = shifted_year - era * 400
    day_of_year = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    days = era * 146097 + day_of_era - 719468
    return days * 86400 + hour * 3600 + minute * 60 + second - offset_seconds


def parse_ledger(raw: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse JSONL ledger bytes into events plus parse findings.

    A malformed final line in a file with no trailing newline is a torn tail:
    the recoverable signature of a crash during append.  A malformed line
    anywhere else, or a malformed final line in a newline-terminated file, is an
    integrity violation and is reported as such rather than skipped quietly.
    """
    findings: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    if raw == b"":
        return events, findings

    text = raw.decode("utf-8", errors="replace")
    newline_terminated = text.endswith("\n")
    lines = text.split("\n")
    if newline_terminated:
        lines = lines[:-1]
    last_index = len(lines) - 1

    for index, line in enumerate(lines):
        line_no = index + 1
        if line.strip() == "":
            findings.append(
                {
                    "code": "BLANK_LINE",
                    "severity": ADVISORY,
                    "line": line_no,
                    "detail": "blank ledger line ignored",
                }
            )
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            is_torn_tail = index == last_index and not newline_terminated
            findings.append(
                {
                    "code": "TORN_TAIL" if is_torn_tail else "CORRUPT_INTERIOR_LINE",
                    "severity": ADVISORY if is_torn_tail else CRITICAL,
                    "line": line_no,
                    "detail": (
                        "final line is an incomplete append and was truncated safely"
                        if is_torn_tail
                        else f"complete line is not valid JSON: {exc.msg}"
                    ),
                }
            )
            continue
        if not isinstance(parsed, dict):
            findings.append(
                {
                    "code": "NON_OBJECT_EVENT",
                    "severity": CRITICAL,
                    "line": line_no,
                    "detail": f"ledger line root is {type(parsed).__name__}, not an object",
                }
            )
            continue
        missing = [name for name in REQUIRED_EVENT_FIELDS if name not in parsed]
        if missing:
            findings.append(
                {
                    "code": "EVENT_MISSING_REQUIRED_FIELD",
                    "severity": CRITICAL,
                    "line": line_no,
                    "detail": f"missing {','.join(missing)}",
                }
            )
            continue
        if not isinstance(parsed["event_seq"], int) or isinstance(parsed["event_seq"], bool):
            findings.append(
                {
                    "code": "EVENT_SEQ_NOT_INTEGER",
                    "severity": CRITICAL,
                    "line": line_no,
                    "detail": f"event_seq={parsed['event_seq']!r}",
                }
            )
            continue
        if parsed["event_seq"] < 1:
            findings.append(
                {
                    "code": "EVENT_SEQ_NOT_POSITIVE",
                    "severity": CRITICAL,
                    "line": line_no,
                    "detail": f"event_seq={parsed['event_seq']!r}",
                }
            )
            continue
        parsed["_line"] = line_no
        events.append(parsed)

    return events, findings


ATTEMPT_SUFFIX_RE = re.compile(r"[-_:]([aA]\d+)$")


def _attempt_key(event: dict[str, Any], inherited: str | None) -> str:
    """Resolve the attempt an event belongs to.

    The live ledger identifies one attempt three different ways: an explicit
    ``attempt_id`` such as ``PO03-WA-005-A01``, the trailing segment of an
    idempotency key such as ``po03:100bc20:wa-005:a01``, or nothing at all on
    producer lifecycle events that continue the task's live attempt.  All three
    are normalised to one key, otherwise the same attempt splits in two and a
    legitimate ``LEASED -> FENCED`` transition looks like an illegal
    ``None -> FENCED`` on a phantom attempt.
    """
    task_id = event["task_id"]
    attempt_id = event.get("attempt_id")
    if isinstance(attempt_id, str) and attempt_id.strip():
        text = attempt_id.strip()
        match = ATTEMPT_SUFFIX_RE.search(text)
        return f"{task_id}::{match.group(1).lower()}" if match else text
    key = event.get("idempotency_key")
    if isinstance(key, str) and ":" in key:
        suffix = key.rsplit(":", 1)[-1].strip()
        if suffix:
            return f"{task_id}::{suffix.lower()}"
    if inherited is not None:
        return inherited
    return f"{task_id}::unattributed"


class _Attempt:
    __slots__ = (
        "attempt_key",
        "attempt_id",
        "state",
        "main_rank",
        "fence_token",
        "lease_id",
        "lease_expires_at",
        "checkpoint_seq",
        "provider_run_ids",
        "immutable_input_uri",
        "immutable_input_manifest_sha256",
        "result_commit_id",
        "return_commit_id",
        "manifest_sha256",
        "parent_ingested",
        "completed",
        "completion_actor",
        "review_state",
        "reviewer_actor",
        "producer_actors",
        "last_event_seq",
        "first_event_seq",
        "reached",
        "provider_error",
        "remote_branch_readback",
        "source_base_commit",
        "successor_attempt_id",
        "supersedes_attempt_id",
        "reason",
        "event_count",
    )

    def __init__(self, attempt_key: str) -> None:
        self.attempt_key = attempt_key
        self.attempt_id: str | None = None
        self.state: str | None = None
        self.main_rank = 0
        self.fence_token: int | None = None
        self.lease_id: str | None = None
        self.lease_expires_at: str | None = None
        self.checkpoint_seq = 0
        self.provider_run_ids: list[str] = []
        self.immutable_input_uri: str | None = None
        self.immutable_input_manifest_sha256: str | None = None
        self.result_commit_id: str | None = None
        self.return_commit_id: str | None = None
        self.manifest_sha256: str | None = None
        self.parent_ingested = False
        self.completed = False
        self.completion_actor: str | None = None
        self.review_state: str | None = None
        self.reviewer_actor: str | None = None
        self.producer_actors: list[str] = []
        self.last_event_seq = 0
        self.first_event_seq = 0
        self.reached: list[str] = []
        self.provider_error: str | None = None
        self.remote_branch_readback: str | None = None
        self.source_base_commit: str | None = None
        self.successor_attempt_id: str | None = None
        self.supersedes_attempt_id: str | None = None
        self.reason: str | None = None
        self.event_count = 0


class _Task:
    __slots__ = ("task_id", "attempts", "order", "max_fence_token", "live_attempt")

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.attempts: dict[str, _Attempt] = {}
        self.order: list[str] = []
        self.max_fence_token = 0
        self.live_attempt: str | None = None

    def attempt(self, key: str) -> _Attempt:
        found = self.attempts.get(key)
        if found is None:
            found = _Attempt(key)
            self.attempts[key] = found
            self.order.append(key)
        return found


def _transition_allowed(current: str | None, target: str) -> bool:
    if target in CONTROL_ENTRY:
        return True
    if current in ALLOWED_CONTROL_EXITS:
        return target in ALLOWED_CONTROL_EXITS[current]
    return target in ALLOWED_MAIN_TRANSITIONS.get(current, frozenset())


def scan(
    raw_ledger: bytes,
    *,
    now: str,
    provider_observations: dict[str, Any] | None = None,
    artifact_probe: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reconstruct task state from an append-only ledger and classify recovery."""
    now_epoch = parse_instant(now)
    if now_epoch is None:
        raise LedgerIntegrityError(f"unparseable evaluation instant: {now!r}")

    events, findings = parse_ledger(raw_ledger)
    provider_observations = provider_observations or {}

    seen_event_ids: dict[str, str] = {}
    seen_event_seqs: dict[int, str] = {}
    tasks: dict[str, _Task] = {}
    accepted = 0
    refused_stale_fence = 0
    duplicate_events = 0
    duplicate_transitions = 0
    false_completion_refused: dict[str, int] = {}

    # event_seq is the append-order authority.  Sort defensively but record any
    # divergence between file order and sequence order, and any divergence
    # between sequence order and timestamp order.  Redelivered duplicates are
    # excluded: an at-least-once transport legitimately re-appends an earlier
    # event id late in the file, and that is not storage reordering.
    first_occurrence: set[str] = set()
    file_order_seqs: list[int] = []
    for event in events:
        identifier = event["event_id"]
        if not isinstance(identifier, str) or identifier in first_occurrence:
            continue
        first_occurrence.add(identifier)
        file_order_seqs.append(event["event_seq"])
    if file_order_seqs != sorted(file_order_seqs):
        findings.append(
            {
                "code": "FILE_ORDER_NOT_SEQ_ORDER",
                "severity": DEFECT,
                "detail": "ledger lines are not stored in event_seq order; scanner reordered by event_seq",
            }
        )
    ordered = sorted(events, key=lambda event: (event["event_seq"], event["_line"]))

    previous_instant: int | None = None
    timestamp_inversions = 0
    for event in ordered:
        instant = parse_instant(event.get("at"))
        if instant is not None:
            if previous_instant is not None and instant < previous_instant:
                timestamp_inversions += 1
            previous_instant = instant
    if timestamp_inversions:
        findings.append(
            {
                "code": "TIMESTAMP_NOT_MONOTONIC_WITH_SEQ",
                "severity": ADVISORY,
                "detail": (
                    f"{timestamp_inversions} event(s) carry a wall-clock stamp earlier than a "
                    "lower-sequence predecessor; event_seq ordering is authoritative"
                ),
                "count": timestamp_inversions,
            }
        )

    for event in ordered:
        line = event["_line"]
        event_id = event["event_id"]
        seq = event["event_seq"]
        task_id = event["task_id"]
        to_state = event["to_state"]

        if not isinstance(event_id, str) or not event_id.strip():
            findings.append(
                {
                    "code": "EVENT_ID_EMPTY",
                    "severity": CRITICAL,
                    "line": line,
                    "detail": "event_id must be a non-empty string",
                }
            )
            continue
        if not isinstance(task_id, str) or not task_id.strip():
            findings.append(
                {
                    "code": "TASK_ID_EMPTY",
                    "severity": CRITICAL,
                    "line": line,
                    "detail": "task_id must be a non-empty string",
                }
            )
            continue

        payload = {key: value for key, value in event.items() if key != "_line"}
        fingerprint = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
        if event_id in seen_event_ids:
            if seen_event_ids[event_id] == fingerprint:
                duplicate_events += 1
                findings.append(
                    {
                        "code": "DUPLICATE_EVENT_IGNORED",
                        "severity": ADVISORY,
                        "line": line,
                        "task_id": task_id,
                        "detail": f"exact redelivery of {event_id} ignored idempotently",
                    }
                )
            else:
                findings.append(
                    {
                        "code": "EVENT_ID_CONFLICT",
                        "severity": CRITICAL,
                        "line": line,
                        "task_id": task_id,
                        "detail": f"event_id {event_id} reused with different content",
                    }
                )
            continue
        seen_event_ids[event_id] = fingerprint

        if seq in seen_event_seqs:
            findings.append(
                {
                    "code": "DUPLICATE_EVENT_SEQ",
                    "severity": DEFECT,
                    "line": line,
                    "task_id": task_id,
                    "detail": f"event_seq {seq} already used by {seen_event_seqs[seq]}",
                }
            )
        else:
            seen_event_seqs[seq] = event_id

        if to_state not in KNOWN_STATES:
            findings.append(
                {
                    "code": "UNKNOWN_STATE",
                    "severity": CRITICAL,
                    "line": line,
                    "task_id": task_id,
                    "detail": f"to_state {to_state!r} is outside the declared lifecycle",
                }
            )
            continue

        task = tasks.get(task_id)
        if task is None:
            task = _Task(task_id)
            tasks[task_id] = task

        fence_token = event.get("fence_token")
        if fence_token is not None and (
            not isinstance(fence_token, int) or isinstance(fence_token, bool) or fence_token < 1
        ):
            findings.append(
                {
                    "code": "FENCE_TOKEN_INVALID",
                    "severity": CRITICAL,
                    "line": line,
                    "task_id": task_id,
                    "detail": f"fence_token={fence_token!r} must be an integer >= 1",
                }
            )
            continue

        if fence_token is not None and fence_token < task.max_fence_token:
            refused_stale_fence += 1
            severity = CRITICAL if to_state in {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"} else DEFECT
            findings.append(
                {
                    "code": "STALE_FENCE_EVENT_REFUSED",
                    "severity": severity,
                    "line": line,
                    "task_id": task_id,
                    "detail": (
                        f"fence_token {fence_token} is below the task's current token "
                        f"{task.max_fence_token}; refused to_state {to_state}"
                    ),
                    "refused_to_state": to_state,
                    "stale_fence_token": fence_token,
                    "current_fence_token": task.max_fence_token,
                }
            )
            continue
        if fence_token is not None:
            task.max_fence_token = max(task.max_fence_token, fence_token)

        inherited = task.live_attempt
        attempt_key = _attempt_key(event, inherited)
        attempt = task.attempt(attempt_key)
        if attempt.first_event_seq == 0:
            attempt.first_event_seq = seq
        if isinstance(event.get("attempt_id"), str) and event["attempt_id"].strip():
            attempt.attempt_id = event["attempt_id"].strip()

        current = attempt.state
        actor_prefix = _actor_prefix(event.get("actor"))

        # The false-completion guard outranks lifecycle legality: no actor at any
        # position may turn a unit COMPLETED without a verified durable result
        # commit behind it.  Acceptance requires zero false completion.
        if to_state == "COMPLETED" and not (
            bool(attempt.result_commit_id) and "RESULT_COMMITTED" in attempt.reached
        ):
            false_completion_refused[task_id] = false_completion_refused.get(task_id, 0) + 1
            findings.append(
                {
                    "code": "FALSE_COMPLETION_REFUSED",
                    "severity": CRITICAL,
                    "line": line,
                    "task_id": task_id,
                    "detail": (
                        f"COMPLETED asserted from {current!r} with no verified durable result commit; "
                        "Obzio state remains uncommitted"
                    ),
                }
            )
            continue

        # Actor authority.  Only a coordinator may record COMPLETED; only an
        # independent reviewer may record a terminal review, and never the
        # producer that generated the result.
        if to_state == "COMPLETED" and actor_prefix not in COORDINATOR_ACTOR_PREFIXES:
            findings.append(
                {
                    "code": "UNAUTHORIZED_COMPLETION_ACTOR",
                    "severity": CRITICAL,
                    "line": line,
                    "task_id": task_id,
                    "detail": f"actor {event.get('actor')!r} is not a coordinator and may not record COMPLETED",
                }
            )
            continue
        if to_state in REVIEW_STATES:
            if event.get("actor") in attempt.producer_actors:
                findings.append(
                    {
                        "code": "PRODUCER_SELF_ACCEPTANCE",
                        "severity": CRITICAL,
                        "line": line,
                        "task_id": task_id,
                        "detail": f"actor {event.get('actor')!r} produced this attempt and cannot review it",
                    }
                )
                continue
            if actor_prefix not in REVIEWER_ACTOR_PREFIXES:
                findings.append(
                    {
                        "code": "UNAUTHORIZED_REVIEW_ACTOR",
                        "severity": CRITICAL,
                        "line": line,
                        "task_id": task_id,
                        "detail": f"actor {event.get('actor')!r} may not record {to_state}",
                    }
                )
                continue

        if actor_prefix == "producer":
            if event.get("actor") not in attempt.producer_actors:
                attempt.producer_actors.append(event["actor"])

        declared_from = event.get("from_state")
        if current is not None and declared_from is not None and declared_from != current:
            findings.append(
                {
                    "code": "FROM_STATE_MISMATCH",
                    "severity": ADVISORY,
                    "line": line,
                    "task_id": task_id,
                    "detail": (
                        f"event declares from_state {declared_from!r} but reconstructed state is "
                        f"{current!r}; reconstruction is authoritative"
                    ),
                }
            )

        # Monotonic checkpoints.
        checkpoint_seq = event.get("checkpoint_seq")
        if checkpoint_seq is not None:
            if not isinstance(checkpoint_seq, int) or isinstance(checkpoint_seq, bool) or checkpoint_seq < 0:
                findings.append(
                    {
                        "code": "CHECKPOINT_SEQ_INVALID",
                        "severity": DEFECT,
                        "line": line,
                        "task_id": task_id,
                        "detail": f"checkpoint_seq={checkpoint_seq!r} must be an integer >= 0",
                    }
                )
            elif checkpoint_seq < attempt.checkpoint_seq:
                findings.append(
                    {
                        "code": "CHECKPOINT_REGRESSION",
                        "severity": DEFECT,
                        "line": line,
                        "task_id": task_id,
                        "detail": (
                            f"checkpoint_seq {checkpoint_seq} regresses below "
                            f"{attempt.checkpoint_seq}"
                        ),
                    }
                )
            else:
                attempt.checkpoint_seq = checkpoint_seq

        # Idempotent re-assertion of the state the attempt already holds.  A
        # self-declared ``from_state == to_state`` event is a deliberate
        # annotation the controller attaches to a live state; anything else is a
        # redelivered or replayed transition.  Both leave state unchanged.
        if to_state == current:
            duplicate_transitions += 1
            is_annotation = declared_from == to_state
            findings.append(
                {
                    "code": "ANNOTATION_EVENT" if is_annotation else "DUPLICATE_TRANSITION_IGNORED",
                    "severity": ADVISORY,
                    "line": line,
                    "task_id": task_id,
                    "detail": (
                        f"annotation {event.get('event_type') or 'unspecified'} attached to {to_state}"
                        if is_annotation
                        else f"re-assertion of {to_state} left state unchanged"
                    ),
                }
            )
            attempt.last_event_seq = seq
            attempt.event_count += 1
            _absorb_facts(attempt, event)
            task.live_attempt = attempt_key if attempt.state not in ATTEMPT_CLOSED else task.live_attempt
            accepted += 1
            continue

        if not _transition_allowed(current, to_state):
            rank_target = MAIN_LINE_RANK.get(to_state, 0)
            if rank_target and rank_target <= attempt.main_rank:
                findings.append(
                    {
                        "code": "BACKWARD_TRANSITION_REFUSED",
                        "severity": DEFECT,
                        "line": line,
                        "task_id": task_id,
                        "detail": f"{current} -> {to_state} would move the lifecycle backwards",
                    }
                )
            else:
                findings.append(
                    {
                        "code": "ILLEGAL_TRANSITION_REFUSED",
                        "severity": CRITICAL if to_state in {"RESULT_COMMITTED", "COMPLETED"} else DEFECT,
                        "line": line,
                        "task_id": task_id,
                        "detail": f"{current} -> {to_state} skips or violates the declared lifecycle",
                    }
                )
            continue

        attempt.state = to_state
        attempt.last_event_seq = seq
        attempt.event_count += 1
        if to_state not in attempt.reached:
            attempt.reached.append(to_state)
        rank = MAIN_LINE_RANK.get(to_state)
        if rank is not None:
            attempt.main_rank = max(attempt.main_rank, rank)
        if fence_token is not None:
            attempt.fence_token = fence_token
        if to_state == "PARENT_INGESTED":
            attempt.parent_ingested = True
        if to_state == "COMPLETED":
            attempt.completed = True
            attempt.completion_actor = event.get("actor")
        if to_state in REVIEW_STATES:
            attempt.review_state = to_state
            attempt.reviewer_actor = event.get("actor")
        _absorb_facts(attempt, event)

        if to_state == "CREATED" or attempt.state not in ATTEMPT_CLOSED:
            task.live_attempt = attempt_key
        accepted += 1

    return _build_report(
        raw_ledger=raw_ledger,
        events_seen=len(events),
        accepted=accepted,
        duplicate_events=duplicate_events,
        duplicate_transitions=duplicate_transitions,
        refused_stale_fence=refused_stale_fence,
        false_completion_refused=false_completion_refused,
        findings=findings,
        tasks=tasks,
        now=now,
        now_epoch=now_epoch,
        provider_observations=provider_observations,
        artifact_probe=artifact_probe,
    )


def _absorb_facts(attempt: _Attempt, event: dict[str, Any]) -> None:
    for field, target in (
        ("lease_id", "lease_id"),
        ("lease_expires_at", "lease_expires_at"),
        ("immutable_input_uri", "immutable_input_uri"),
        ("immutable_input_manifest_sha256", "immutable_input_manifest_sha256"),
        ("manifest_sha256", "manifest_sha256"),
        ("result_commit_id", "result_commit_id"),
        ("return_commit_id", "return_commit_id"),
        ("provider_error", "provider_error"),
        ("remote_branch_readback", "remote_branch_readback"),
        ("source_base_commit", "source_base_commit"),
        ("successor_attempt_id", "successor_attempt_id"),
        ("supersedes_attempt_id", "supersedes_attempt_id"),
        ("reason", "reason"),
    ):
        value = event.get(field)
        if isinstance(value, str) and value.strip():
            setattr(attempt, target, value)
    run_id = event.get("provider_run_id")
    if isinstance(run_id, str) and run_id.strip() and run_id not in attempt.provider_run_ids:
        attempt.provider_run_ids.append(run_id)
    previous = event.get("previous_provider_run_id")
    if isinstance(previous, str) and previous.strip() and previous not in attempt.provider_run_ids:
        attempt.provider_run_ids.append(previous)


def _select_live_attempt(task: _Task) -> _Attempt:
    open_attempts = [
        task.attempts[key] for key in task.order if task.attempts[key].state not in ATTEMPT_CLOSED
    ]
    pool = open_attempts or [task.attempts[key] for key in task.order]
    return max(pool, key=lambda attempt: (attempt.last_event_seq, attempt.first_event_seq))


def _classify(
    attempt: _Attempt,
    *,
    now_epoch: int,
    provider_state: str | None,
    artifact_findings: list[dict[str, Any]],
    false_completion_refusals: int = 0,
) -> tuple[str, str, list[str]]:
    """Return (obzio_state, recovery_action, reasons)."""
    reasons: list[str] = []
    if false_completion_refusals:
        reasons.append(
            f"{false_completion_refusals} COMPLETED assertion(s) refused for lack of a verified "
            "durable result commit"
        )
    has_commit = bool(attempt.result_commit_id) and "RESULT_COMMITTED" in attempt.reached
    lease_epoch = parse_instant(attempt.lease_expires_at)
    lease_expired = lease_epoch is not None and lease_epoch <= now_epoch
    artifact_broken = [
        finding for finding in artifact_findings if finding["severity"] == CRITICAL
    ]

    if attempt.completed and not has_commit:
        reasons.append("COMPLETED recorded without a verified durable result commit")
        return "PROVIDER_COMPLETED_UNCOMMITTED", "RERUN_FROM_IMMUTABLE_INPUT", reasons

    if has_commit and artifact_broken:
        reasons.append("result commit exists but its artifacts do not read back")
        return "RESULT_COMMITTED_ARTIFACTS_UNVERIFIABLE", "REVERIFY_THEN_RERUN_FROM_IMMUTABLE_INPUT", reasons

    if has_commit and not attempt.parent_ingested:
        reasons.append(
            f"durable result commit {attempt.result_commit_id} exists but no PARENT_INGESTED event follows"
        )
        return "COMMITTED_NOT_INGESTED", "REPLAY_PARENT_INGESTION", reasons

    if has_commit and attempt.parent_ingested and not attempt.completed:
        reasons.append("parent ingestion recorded; coordinator has not recorded COMPLETED")
        return "INGESTED_NOT_COMPLETED", "COORDINATOR_RECORD_COMPLETED", reasons

    if attempt.completed and attempt.review_state is None:
        reasons.append("COMPLETED with durable result; awaiting independent disposition")
        return "COMPLETED_AWAITING_INDEPENDENT_ACCEPTANCE", "REQUEST_INDEPENDENT_ACCEPTANCE", reasons

    if attempt.review_state == "ACCEPTED":
        return "ACCEPTED", "NONE", reasons
    if attempt.review_state == "REJECTED":
        reasons.append("independent reviewer rejected the result")
        return "REJECTED", "DISPATCH_SUCCESSOR_ATTEMPT", reasons

    if attempt.state in ATTEMPT_CLOSED:
        if attempt.state in {"FENCED", "SUPERSEDED_BEFORE_DISPATCH"}:
            if attempt.successor_attempt_id:
                reasons.append(
                    f"attempt closed as {attempt.state}; successor "
                    f"{attempt.successor_attempt_id} carries the work"
                )
                return f"ATTEMPT_{attempt.state}", "NONE_SUCCESSOR_CARRIES_WORK", reasons
            reasons.append(
                f"attempt closed as {attempt.state} with no successor attempt and no durable result"
            )
            return f"ATTEMPT_{attempt.state}_NO_SUCCESSOR", "REDISPATCH_UNDER_NEW_FENCE", reasons
        reasons.append(f"attempt closed as {attempt.state} without a durable result")
        return attempt.state, "RERUN_FROM_IMMUTABLE_INPUT", reasons

    if provider_state in {"COMPLETED", "FAILED", "CANCELLED"} and not has_commit:
        reasons.append(
            f"provider observation {provider_state} carries no verified durable result commit"
        )
        state = (
            "PROVIDER_COMPLETED_UNCOMMITTED"
            if provider_state == "COMPLETED"
            else f"PROVIDER_{provider_state}_UNCOMMITTED"
        )
        return state, "RERUN_FROM_IMMUTABLE_INPUT", reasons

    if attempt.state == "RECOVERY_REQUIRED":
        reasons.append(attempt.provider_error or "controller flagged recovery")
        return "RECOVERY_REQUIRED", "RERUN_FROM_IMMUTABLE_INPUT", reasons
    if attempt.state == "RETRY_SCHEDULED":
        reasons.append(attempt.provider_error or "controller scheduled a retry")
        return "RETRY_SCHEDULED", "AWAIT_SCHEDULED_RETRY", reasons
    if attempt.state == "PROVIDER_COMPLETED_UNCOMMITTED":
        reasons.append("controller already recorded provider completion without a commit")
        return "PROVIDER_COMPLETED_UNCOMMITTED", "RERUN_FROM_IMMUTABLE_INPUT", reasons

    if attempt.state in IN_FLIGHT:
        if lease_expired:
            reasons.append(
                f"lease {attempt.lease_id} expired at {attempt.lease_expires_at} while in {attempt.state} "
                "with no durable result commit"
            )
            return "ORPHANED_LEASE_EXPIRED", "REDISPATCH_UNDER_NEW_FENCE", reasons
        return "IN_FLIGHT", "NONE", reasons

    if attempt.state == "LEASED":
        if lease_expired:
            reasons.append(
                f"lease {attempt.lease_id} expired at {attempt.lease_expires_at} before dispatch was observed"
            )
            return "ORPHANED_LEASE_EXPIRED", "REDISPATCH_UNDER_NEW_FENCE", reasons
        return "AWAITING_DISPATCH", "NONE", reasons

    if attempt.state == "CREATED":
        return "AWAITING_LEASE", "NONE", reasons

    reasons.append(f"unclassified reconstructed state {attempt.state!r}")
    return "UNCLASSIFIED", "MANUAL_REVIEW", reasons


def _probe_artifacts(
    task_id: str,
    attempt: _Attempt,
    artifact_probe: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Read back the manifest a committed result claims, when a probe is supplied.

    A durable commit is only trustworthy if its artifacts still read back, so a
    committed result whose manifest is absent or altered is a critical finding
    rather than a recoverable one.
    """
    declared = attempt.manifest_sha256
    if artifact_probe is None or not attempt.result_commit_id or declared is None:
        return []
    descriptor = {
        "task_id": task_id,
        "attempt_id": attempt.attempt_id or attempt.attempt_key,
        "manifest_sha256": declared,
        "result_commit_id": attempt.result_commit_id,
    }
    probe = artifact_probe(descriptor)
    if not probe.get("exists"):
        return [
            {
                "code": "COMMITTED_ARTIFACT_MISSING",
                "severity": CRITICAL,
                "detail": (
                    f"manifest {declared} declared by result commit {attempt.result_commit_id} is "
                    "absent at read-back"
                ),
            }
        ]
    observed = probe.get("sha256")
    if observed != declared:
        return [
            {
                "code": "COMMITTED_ARTIFACT_CORRUPT",
                "severity": CRITICAL,
                "detail": f"manifest reads back as {observed} but the ledger declared {declared}",
            }
        ]
    return [
        {
            "code": "COMMITTED_ARTIFACT_VERIFIED",
            "severity": ADVISORY,
            "detail": f"manifest read back as {observed}",
        }
    ]


def _build_report(
    *,
    raw_ledger: bytes,
    events_seen: int,
    accepted: int,
    duplicate_events: int,
    duplicate_transitions: int,
    refused_stale_fence: int,
    false_completion_refused: dict[str, int],
    findings: list[dict[str, Any]],
    tasks: dict[str, _Task],
    now: str,
    now_epoch: int,
    provider_observations: dict[str, Any],
    artifact_probe: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> dict[str, Any]:
    task_reports: list[dict[str, Any]] = []
    for task_id in sorted(tasks):
        task = tasks[task_id]
        live = _select_live_attempt(task)
        provider_state = provider_observations.get(task_id)
        if isinstance(provider_state, dict):
            provider_state = provider_state.get("provider_state")
        artifact_findings = _probe_artifacts(task_id, live, artifact_probe)
        refusals = false_completion_refused.get(task_id, 0)
        obzio_state, action, reasons = _classify(
            live,
            now_epoch=now_epoch,
            provider_state=provider_state,
            artifact_findings=artifact_findings,
            false_completion_refusals=refusals,
        )
        if refusals and action == "NONE":
            action = "INVESTIGATE_REFUSED_COMPLETION"
        for finding in artifact_findings:
            if finding["severity"] != ADVISORY:
                findings.append({**finding, "task_id": task_id})
        superseded = [
            {
                "attempt_key": key,
                "attempt_id": task.attempts[key].attempt_id,
                "state": task.attempts[key].state,
                "fence_token": task.attempts[key].fence_token,
                "successor_attempt_id": task.attempts[key].successor_attempt_id,
                "reason": task.attempts[key].reason,
            }
            for key in task.order
            if key != live.attempt_key
        ]
        replay: dict[str, Any] | None = None
        if action == "REPLAY_PARENT_INGESTION":
            replay = {
                "operation": "PARENT_INGEST",
                "task_id": task_id,
                "attempt_id": live.attempt_id,
                "fence_token": live.fence_token,
                "result_commit_id": live.result_commit_id,
                "return_commit_id": live.return_commit_id,
                "manifest_sha256": live.manifest_sha256,
                "idempotent": True,
            }
        elif action in {"RERUN_FROM_IMMUTABLE_INPUT", "REDISPATCH_UNDER_NEW_FENCE", "REVERIFY_THEN_RERUN_FROM_IMMUTABLE_INPUT"}:
            replay = {
                "operation": "REDISPATCH",
                "task_id": task_id,
                "supersedes_attempt_id": live.attempt_id,
                "immutable_input_uri": live.immutable_input_uri,
                "immutable_input_manifest_sha256": live.immutable_input_manifest_sha256,
                "required_fence_token": (task.max_fence_token or 0) + 1,
                "idempotent": True,
            }
        task_reports.append(
            {
                "task_id": task_id,
                "obzio_state": obzio_state,
                "recovery_action": action,
                "reasons": reasons,
                "reconstructed_from_events": sum(
                    task.attempts[key].event_count for key in task.order
                ),
                "live_attempt": {
                    "attempt_key": live.attempt_key,
                    "attempt_id": live.attempt_id,
                    "reconstructed_state": live.state,
                    "fence_token": live.fence_token,
                    "lease_id": live.lease_id,
                    "lease_expires_at": live.lease_expires_at,
                    "lease_expired_at_evaluation_instant": (
                        (parse_instant(live.lease_expires_at) or 0) <= now_epoch
                        if live.lease_expires_at
                        else None
                    ),
                    "checkpoint_seq": live.checkpoint_seq,
                    "provider_run_ids": list(live.provider_run_ids),
                    "provider_observation": provider_state,
                    "result_commit_id": live.result_commit_id,
                    "return_commit_id": live.return_commit_id,
                    "manifest_sha256": live.manifest_sha256,
                    "parent_ingested": live.parent_ingested,
                    "completed": live.completed,
                    "completion_actor": live.completion_actor,
                    "review_state": live.review_state,
                    "states_reached": list(live.reached),
                    "last_event_seq": live.last_event_seq,
                },
                "superseded_attempts": superseded,
                "artifact_readback": artifact_findings,
                "replay_directive": replay,
            }
        )

    by_state: dict[str, int] = {}
    by_action: dict[str, int] = {}
    for report in task_reports:
        by_state[report["obzio_state"]] = by_state.get(report["obzio_state"], 0) + 1
        by_action[report["recovery_action"]] = by_action.get(report["recovery_action"], 0) + 1

    findings_sorted = sorted(
        findings,
        key=lambda finding: (finding.get("line", 0), finding.get("code", ""), finding.get("task_id", "")),
    )
    severity_counts = {CRITICAL: 0, DEFECT: 0, ADVISORY: 0}
    for finding in findings_sorted:
        severity_counts[finding["severity"]] = severity_counts.get(finding["severity"], 0) + 1

    committed_not_ingested = sorted(
        report["task_id"] for report in task_reports if report["obzio_state"] == "COMMITTED_NOT_INGESTED"
    )
    provider_completed_uncommitted = sorted(
        report["task_id"]
        for report in task_reports
        if report["obzio_state"] == "PROVIDER_COMPLETED_UNCOMMITTED"
    )
    # An admitted false completion is an acceptance-blocking guardrail breach and
    # must always be empty.  A refused one is the guard working, and is reported
    # separately so the controller can still investigate the attempt.
    false_completion_admitted = sorted(
        report["task_id"]
        for report in task_reports
        if report["live_attempt"]["completed"] and not report["live_attempt"]["result_commit_id"]
    )
    orphaned = sorted(
        report["task_id"] for report in task_reports if report["obzio_state"] == "ORPHANED_LEASE_EXPIRED"
    )

    if severity_counts.get(CRITICAL):
        integrity = "CRITICAL_VIOLATION"
    elif severity_counts.get(DEFECT):
        integrity = "DEFECTIVE"
    else:
        integrity = "CLEAN"

    return {
        "protocol_version": REPORT_PROTOCOL_VERSION,
        "evaluation_instant": now,
        "ledger": {
            "sha256": hashlib.sha256(raw_ledger).hexdigest(),
            "bytes": len(raw_ledger),
            "events_parsed": events_seen,
            "events_applied": accepted,
            "duplicate_events_ignored": duplicate_events,
            "duplicate_transitions_ignored": duplicate_transitions,
            "stale_fence_events_refused": refused_stale_fence,
            "false_completion_assertions_refused": sum(false_completion_refused.values()),
        },
        "integrity": integrity,
        "severity_counts": severity_counts,
        "findings": findings_sorted,
        "task_count": len(task_reports),
        "state_histogram": dict(sorted(by_state.items())),
        "action_histogram": dict(sorted(by_action.items())),
        "committed_not_ingested": committed_not_ingested,
        "provider_completed_uncommitted": provider_completed_uncommitted,
        "false_completion_admitted": false_completion_admitted,
        "false_completion_refused": dict(sorted(false_completion_refused.items())),
        "orphaned_lease_expired": orphaned,
        "recovery_required": sorted(
            report["task_id"] for report in task_reports if report["recovery_action"] != "NONE"
        ),
        "tasks": task_reports,
    }


def report_digest(report: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_report_bytes(report)).hexdigest()


def canonical_report_bytes(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def filesystem_artifact_probe(root: Path) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Read back a committed manifest from ``root/<task_id>/<attempt_id>/manifest.json``."""

    def probe(descriptor: dict[str, Any]) -> dict[str, Any]:
        path = root / str(descriptor["task_id"]) / str(descriptor["attempt_id"]) / "manifest.json"
        if not path.is_file():
            return {"exists": False, "sha256": None, "bytes": 0}
        data = path.read_bytes()
        return {"exists": True, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    return probe


def exit_code_for(report: dict[str, Any]) -> int:
    if report["integrity"] == "CRITICAL_VIOLATION":
        return 2
    if report["integrity"] == "DEFECTIVE" or report["recovery_required"]:
        return 1
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconstruct PO-03 work-unit state from an append-only event ledger."
    )
    parser.add_argument("ledger", type=Path, help="path to the append-only JSONL ledger")
    parser.add_argument(
        "--now",
        required=True,
        help="pinned evaluation instant (ISO-8601); pinning keeps the report digest reproducible",
    )
    parser.add_argument(
        "--provider-observations",
        type=Path,
        default=None,
        help="optional JSON map of task_id -> provider_state or {provider_state: ...}",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="optional directory root for committed-artifact read-back probing",
    )
    parser.add_argument("--out", type=Path, default=None, help="write the canonical report here")
    parser.add_argument(
        "--expect-digest",
        default=None,
        help="fail unless the canonical report digest equals this SHA-256",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress the human summary")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        raw = args.ledger.read_bytes()
    except OSError as exc:
        print(f"UNSCANNABLE: {exc}", file=sys.stderr)
        return 3

    observations: dict[str, Any] = {}
    if args.provider_observations is not None:
        try:
            observations = json.loads(args.provider_observations.read_bytes())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"UNSCANNABLE: provider observations: {exc}", file=sys.stderr)
            return 3
        if not isinstance(observations, dict):
            print("UNSCANNABLE: provider observations must be a JSON object", file=sys.stderr)
            return 3

    probe = filesystem_artifact_probe(args.artifact_root) if args.artifact_root else None

    try:
        report = scan(raw, now=args.now, provider_observations=observations, artifact_probe=probe)
    except LedgerIntegrityError as exc:
        print(f"UNSCANNABLE: {exc}", file=sys.stderr)
        return 3

    payload = canonical_report_bytes(report)
    digest = hashlib.sha256(payload).hexdigest()
    if args.out is not None:
        args.out.write_bytes(payload)

    if not args.quiet:
        print(f"report_sha256={digest}")
        print(f"ledger_sha256={report['ledger']['sha256']} bytes={report['ledger']['bytes']}")
        print(
            f"events_parsed={report['ledger']['events_parsed']} "
            f"applied={report['ledger']['events_applied']} "
            f"stale_fence_refused={report['ledger']['stale_fence_events_refused']} "
            f"duplicates_ignored={report['ledger']['duplicate_events_ignored']}"
        )
        print(f"integrity={report['integrity']} tasks={report['task_count']}")
        print(f"committed_not_ingested={report['committed_not_ingested']}")
        print(f"provider_completed_uncommitted={report['provider_completed_uncommitted']}")
        print(f"false_completion_admitted={report['false_completion_admitted']}")
        print(f"false_completion_refused={json.dumps(report['false_completion_refused'], sort_keys=True)}")
        print(f"orphaned_lease_expired={report['orphaned_lease_expired']}")
        print(f"state_histogram={json.dumps(report['state_histogram'], sort_keys=True)}")

    if args.expect_digest is not None and args.expect_digest != digest:
        print(
            f"DIGEST_MISMATCH expected={args.expect_digest} observed={digest}",
            file=sys.stderr,
        )
        return 4

    return exit_code_for(report)


if __name__ == "__main__":
    raise SystemExit(main())
