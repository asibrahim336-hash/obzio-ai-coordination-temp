#!/usr/bin/env python3
"""Fence undispatched defective Wave A A01 inputs behind immutable A02 successors.

The tool is dependency-free and dry-run by default.  It validates the complete
64-task control surface, builds every successor and projection in memory, then
uses adjacent temporary files plus atomic replacement and rollback on apply.
Existing A01 input bytes are read-only evidence and are never write targets.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any


INVALID_PROTOCOL_ANCESTOR = "100bc20ad5eec62a4f35b60921423135cc0b9d9a"
CORRECTED_PROTOCOL_ANCESTOR = "100bc2079cedc193af3524234ab833cc9f9f4669"
COMMISSION_COMMIT = "552b12eacee637716451492a98980fb0da19ff3e"
COMMISSION_ID = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
CONTROLLER_RUN_ID = "bc-b1956656-b897-4889-aeab-82c4556c1a9f"
PROTECTED_TASK_NUMBERS = frozenset({1, 2, 3, 4, 12, 16, 23, 24, 25})
ALL_TASK_NUMBERS = frozenset(range(1, 65))
FULL_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
A01_NAME_RE = re.compile(r"^wa-(\d{3})\.json$")
MATERIAL_TASK_RE = re.compile(r"^PO03-WA-(\d{3})$")
EVENT_KINDS = (
    "PROVENANCE_DEFECT_CONFIRMED",
    "ATTEMPT_FENCED",
    "INPUT_SUPERSEDED",
    "CREATED",
    "LEASED",
)
LEASE_DURATION = timedelta(hours=6)

REGISTRY_REL = "control/work-unit-registry.jsonl"
OUTBOX_REL = "control/outbox.jsonl"
EVENTS_REL = "control/events/ledger.jsonl"
OWNERSHIP_REL = "control/path-ownership.json"
RECOVERY_REL = "control/recovery-state.json"
PORTFOLIO_REL = "control/wave-a-portfolio.json"


class MigrationError(RuntimeError):
    """A fail-closed validation or transaction error."""


@dataclass(frozen=True)
class Mutation:
    relative: str
    before: bytes | None
    after: bytes


@dataclass(frozen=True)
class Plan:
    root: Path
    selected: tuple[int, ...]
    new_successors: tuple[int, ...]
    existing_successors: tuple[int, ...]
    read_set: dict[str, bytes | None]
    mutations: tuple[Mutation, ...]
    last_event_seq: int


class Reader:
    """Path-confined reader that retains bytes for pre-commit revalidation."""

    def __init__(self, root: Path):
        self.root = root
        self.snapshots: dict[str, bytes | None] = {}

    def optional_bytes(self, relative: str) -> bytes | None:
        if relative in self.snapshots:
            return self.snapshots[relative]
        path = _safe_path(self.root, relative)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            data = None
        except OSError as exc:
            raise MigrationError(f"unable to read {relative}: {exc}") from exc
        self.snapshots[relative] = data
        return data

    def bytes(self, relative: str) -> bytes:
        data = self.optional_bytes(relative)
        if data is None:
            raise MigrationError(f"required control file is missing: {relative}")
        return data

    def json(self, relative: str) -> dict[str, Any]:
        data = self.bytes(relative)
        try:
            value = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MigrationError(f"invalid JSON in {relative}: {exc}") from exc
        if not isinstance(value, dict):
            raise MigrationError(f"{relative} must contain a JSON object")
        return value

    def optional_json(self, relative: str) -> dict[str, Any] | None:
        data = self.optional_bytes(relative)
        if data is None:
            return None
        try:
            value = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MigrationError(f"invalid JSON in {relative}: {exc}") from exc
        if not isinstance(value, dict):
            raise MigrationError(f"{relative} must contain a JSON object")
        return value

    def jsonl(self, relative: str) -> list[dict[str, Any]]:
        data = self.bytes(relative)
        rows: list[dict[str, Any]] = []
        try:
            lines = data.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise MigrationError(f"invalid UTF-8 in {relative}: {exc}") from exc
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MigrationError(
                    f"invalid JSONL in {relative}:{line_number}: {exc}"
                ) from exc
            if not isinstance(row, dict):
                raise MigrationError(
                    f"{relative}:{line_number} must contain a JSON object"
                )
            rows.append(row)
        return rows


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    ).encode("utf-8")


def _safe_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise MigrationError(f"path escape refused: {relative!r}")
    candidate = root.joinpath(*pure.parts)
    try:
        parent = candidate.parent.resolve(strict=False)
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise MigrationError(f"unable to resolve path {relative}: {exc}") from exc
    if parent != root and root not in parent.parents:
        raise MigrationError(f"path escape refused through parent: {relative}")
    if resolved != root and root not in resolved.parents:
        raise MigrationError(f"path escape refused through symlink: {relative}")
    return candidate


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _repo_root(cwd: Path) -> Path:
    result = _git(cwd, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        detail = result.stderr.strip() or "not inside a Git worktree"
        raise MigrationError(f"cannot resolve repository root: {detail}")
    try:
        return Path(result.stdout.strip()).resolve(strict=True)
    except OSError as exc:
        raise MigrationError(f"invalid repository root: {exc}") from exc


def resolve_po03_root(argument: Path) -> tuple[Path, Path]:
    try:
        supplied = argument.resolve(strict=True)
    except OSError as exc:
        raise MigrationError(f"--root does not resolve: {argument}: {exc}") from exc
    repo = _repo_root(supplied)
    expected = (repo / "workstreams" / "po03").resolve(strict=True)
    root = expected if supplied == repo else supplied
    if root != expected:
        raise MigrationError(
            "--root must be the repository root or its workstreams/po03 directory"
        )
    if not (root / "control").is_dir():
        raise MigrationError(f"PO-03 control directory is missing under {root}")
    return root, repo


def _resolve_exact_commit(repo: Path, value: str, label: str) -> str:
    if not FULL_COMMIT_RE.fullmatch(value):
        raise MigrationError(
            f"{label} must be a full lowercase 40-character commit SHA"
        )
    result = _git(repo, "rev-parse", "--verify", f"{value}^{{commit}}")
    resolved = result.stdout.strip()
    if result.returncode != 0 or resolved != value:
        detail = result.stderr.strip() or "object did not resolve exactly"
        raise MigrationError(
            f"{label} is not an exact resolvable commit: {value}: {detail}"
        )
    return resolved


def validate_git_provenance(
    repo: Path,
    protocol_ancestor: str = CORRECTED_PROTOCOL_ANCESTOR,
    commission_commit: str = COMMISSION_COMMIT,
) -> None:
    ancestor = _resolve_exact_commit(repo, protocol_ancestor, "corrected ancestor")
    commission = _resolve_exact_commit(repo, commission_commit, "commission commit")
    head = _resolve_exact_commit(
        repo,
        _git(repo, "rev-parse", "--verify", "HEAD^{commit}").stdout.strip(),
        "controller HEAD",
    )
    chronology = _git(repo, "merge-base", "--is-ancestor", commission, ancestor)
    if chronology.returncode == 1:
        raise MigrationError(
            f"commission commit {commission} is not an ancestor of "
            f"corrected protocol commit {ancestor}"
        )
    if chronology.returncode != 0:
        detail = chronology.stderr.strip() or "git chronology check failed"
        raise MigrationError(f"unable to validate commission chronology: {detail}")
    ancestry = _git(repo, "merge-base", "--is-ancestor", ancestor, head)
    if ancestry.returncode == 1:
        raise MigrationError(
            f"corrected protocol commit {ancestor} is not an ancestor of "
            f"controller HEAD {head}"
        )
    if ancestry.returncode != 0:
        detail = ancestry.stderr.strip() or "git ancestry check failed"
        raise MigrationError(f"unable to validate corrected ancestry: {detail}")


def _task_id(number: int) -> str:
    return f"PO03-WA-{number:03d}"


def _slug(number: int) -> str:
    return f"wa-{number:03d}"


def _a01_rel(number: int) -> str:
    return f"control/inputs/wave-a/{_slug(number)}.json"


def _a02_rel(number: int) -> str:
    return f"control/inputs/wave-a/{_slug(number)}-a02.json"


def _result_rel(number: int) -> str:
    return f"control/results/wave-a/{_slug(number)}.json"


def _review_rel(number: int) -> str:
    return (
        f"control/reviews/wave-a/{_slug(number)}-a02-"
        "provenance-supersession.json"
    )


def _uri(relative: str) -> str:
    return f"workstreams/po03/{relative}"


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise MigrationError(f"{label} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MigrationError(f"invalid timestamp for {label}: {value}") from exc
    if parsed.tzinfo is None:
        raise MigrationError(f"{label} must include a timezone: {value}")
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise MigrationError(
            f"{label} mismatch: expected {expected!r}, observed {actual!r}"
        )


def _require_empty_decision_changed(document: dict[str, Any], label: str) -> None:
    if document.get("decision_changed") != []:
        raise MigrationError(f"{label}.decision_changed must remain exactly []")


def _one_row(
    rows: list[dict[str, Any]], field: str, value: str, label: str
) -> tuple[int, dict[str, Any]]:
    matches = [
        (index, row) for index, row in enumerate(rows) if row.get(field) == value
    ]
    if len(matches) != 1:
        raise MigrationError(
            f"{label} requires exactly one {field}={value!r}; found {len(matches)}"
        )
    return matches[0]


def _optional_row(
    rows: list[dict[str, Any]], field: str, value: str, label: str
) -> tuple[int, dict[str, Any]] | None:
    matches = [
        (index, row) for index, row in enumerate(rows) if row.get(field) == value
    ]
    if len(matches) > 1:
        raise MigrationError(
            f"{label} permits at most one {field}={value!r}; found {len(matches)}"
        )
    return matches[0] if matches else None


def _validate_selected(selected: set[int]) -> tuple[int, ...]:
    if not selected:
        raise MigrationError("at least one task number must be selected explicitly")
    outside = selected - ALL_TASK_NUMBERS
    if outside:
        raise MigrationError(f"task numbers must be within 1..64: {sorted(outside)}")
    protected = selected & PROTECTED_TASK_NUMBERS
    if protected:
        raise MigrationError(
            "protected/materially-dispatched A01 tasks cannot be superseded: "
            f"{sorted(protected)}"
        )
    return tuple(sorted(selected))


def _validate_portfolio(portfolio: dict[str, Any]) -> None:
    _require_empty_decision_changed(portfolio, PORTFOLIO_REL)
    _require_equal(portfolio.get("wave_id"), "PO03-WAVE-A", "portfolio wave_id")
    _require_equal(portfolio.get("count"), 64, "portfolio task cardinality")
    tasks = portfolio.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 64:
        raise MigrationError("portfolio must contain exactly 64 task rows")
    numbers = {task.get("number") for task in tasks if isinstance(task, dict)}
    task_ids = {task.get("task_id") for task in tasks if isinstance(task, dict)}
    if numbers != ALL_TASK_NUMBERS or task_ids != {
        _task_id(number) for number in ALL_TASK_NUMBERS
    }:
        raise MigrationError("portfolio task identities are not exactly Wave A 1..64")


def _validate_a01(
    number: int,
    document: dict[str, Any],
    commission_commit: str,
) -> None:
    label = _a01_rel(number)
    _require_equal(
        document.get("protocol_version"),
        "OBZIO-IMMUTABLE-TASK-INPUT-v1",
        f"{label} protocol_version",
    )
    _require_equal(document.get("task_id"), _task_id(number), f"{label} task_id")
    _require_equal(document.get("wave_id"), "PO03-WAVE-A", f"{label} wave_id")
    _require_equal(
        document.get("commission_id"), COMMISSION_ID, f"{label} commission_id"
    )
    _require_empty_decision_changed(document, label)
    source = document.get("source_base")
    if not isinstance(source, dict):
        raise MigrationError(f"{label}.source_base must be an object")
    _require_equal(
        source.get("minimum_protocol_ancestor"),
        INVALID_PROTOCOL_ANCESTOR,
        f"{label} confirmed defective ancestor",
    )
    _require_equal(
        source.get("commission_commit"),
        commission_commit,
        f"{label} commission_commit",
    )
    attempt = document.get("attempt")
    if not isinstance(attempt, dict):
        raise MigrationError(f"{label}.attempt must be an object")
    expected = {
        "attempt_id": f"{_task_id(number)}-A01",
        "idempotency_key": f"po03:100bc20:{_slug(number)}:a01",
        "lease_id": f"lease-po03-{_slug(number)}-a01",
        "fence_token": 1,
        "checkpoint_seq": 0,
    }
    for field, value in expected.items():
        _require_equal(attempt.get(field), value, f"{label}.attempt.{field}")


def _validate_global_state(
    root: Path,
    reader: Reader,
    a01_documents: dict[int, dict[str, Any]],
    registry: list[dict[str, Any]],
    outbox: list[dict[str, Any]],
    events: list[dict[str, Any]],
    recovery: dict[str, Any],
    ownership: dict[str, Any] | None,
    commission_commit: str,
) -> None:
    input_dir = _safe_path(root, "control/inputs/wave-a")
    try:
        a01_names = {
            child.name
            for child in input_dir.iterdir()
            if child.is_file() and A01_NAME_RE.fullmatch(child.name)
        }
    except OSError as exc:
        raise MigrationError(f"unable to enumerate Wave A inputs: {exc}") from exc
    expected_names = {_slug(number) + ".json" for number in ALL_TASK_NUMBERS}
    if a01_names != expected_names:
        raise MigrationError(
            "Wave A must contain exactly the 64 canonical A01 input paths"
        )

    for number in sorted(ALL_TASK_NUMBERS):
        _validate_a01(number, a01_documents[number], commission_commit)

    material_registry = [
        row
        for row in registry
        if MATERIAL_TASK_RE.fullmatch(str(row.get("task_id", "")))
    ]
    if len(material_registry) != 64 or {
        row.get("task_id") for row in material_registry
    } != {_task_id(number) for number in ALL_TASK_NUMBERS}:
        raise MigrationError("registry Wave A task cardinality must remain exactly 64")

    material_outbox = [
        row
        for row in outbox
        if MATERIAL_TASK_RE.fullmatch(str(row.get("task_id", "")))
        and row.get("operation") == "DISPATCH_MATERIAL"
    ]
    task_ids = {row.get("task_id") for row in material_outbox}
    if not {_task_id(number) for number in ALL_TASK_NUMBERS}.issubset(task_ids):
        raise MigrationError("every Wave A task requires an outbox projection")

    seqs: list[int] = []
    event_ids: set[str] = set()
    for row in events:
        seq = row.get("event_seq")
        event_id = row.get("event_id")
        if not isinstance(seq, int) or seq < 1:
            raise MigrationError("every ledger event requires event_seq >= 1")
        if not isinstance(event_id, str) or not event_id:
            raise MigrationError("every ledger event requires event_id")
        if event_id in event_ids:
            raise MigrationError(f"duplicate event_id in ledger: {event_id}")
        event_ids.add(event_id)
        seqs.append(seq)
        _parse_time(row.get("at"), f"event {event_id}.at")
    if seqs != sorted(seqs) or len(seqs) != len(set(seqs)):
        raise MigrationError("event ledger sequence must be strictly increasing")
    last_seq = seqs[-1] if seqs else 0
    _require_equal(
        recovery.get("last_event_seq"),
        last_seq,
        "recovery-state last_event_seq",
    )
    _require_empty_decision_changed(recovery, RECOVERY_REL)
    wave = recovery.get("wave_a")
    if not isinstance(wave, dict) or wave.get("registered") != 64:
        raise MigrationError("recovery Wave A registered cardinality must remain 64")
    if ownership is not None:
        _require_empty_decision_changed(ownership, OWNERSHIP_REL)


def _validate_a01_projection(
    number: int,
    a01: dict[str, Any],
    a01_sha: str,
    registry_row: dict[str, Any],
    outbox_row: dict[str, Any],
    result: dict[str, Any],
    task_events: list[dict[str, Any]],
    active_lease: dict[str, Any],
    pending_outbox: list[Any],
    stale_attempts: list[dict[str, Any]],
    owner_row: dict[str, Any] | None,
) -> None:
    task_id = _task_id(number)
    slug = _slug(number)
    attempt_id = f"{task_id}-A01"
    lease_id = f"lease-po03-{slug}-a01"
    idempotency = f"po03:100bc20:{slug}:a01"
    input_uri = _uri(_a01_rel(number))

    if outbox_row.get("state") == "DELIVERED" or outbox_row.get("delivered_at"):
        raise MigrationError(f"{task_id} A01 was delivered and is protected")
    if int(outbox_row.get("attempts", 0)) != 0:
        raise MigrationError(f"{task_id} A01 has material outbox attempts")
    expected_outbox = {
        "outbox_id": f"outbox-po03-{slug}-dispatch-a01",
        "task_id": task_id,
        "operation": "DISPATCH_MATERIAL",
        "idempotency_key": idempotency,
        "fence_token": 1,
        "payload_uri": input_uri,
        "payload_sha256": a01_sha,
        "state": "PENDING",
        "attempts": 0,
        "created_at": a01.get("created_at"),
        "last_attempt_at": None,
        "delivered_at": None,
        "cohort": a01["portfolio"]["cohort"],
    }
    _require_equal(outbox_row, expected_outbox, f"{task_id} A01 outbox")

    expected_registry = _a01_registry(a01, a01_sha)
    _require_equal(registry_row, expected_registry, f"{task_id} A01 registry")

    expected_result = _set_acceptance_hash(
        _reserved_result(
            number,
            a01_sha,
            attempt_id,
            idempotency,
            lease_id,
            1,
            "a01",
        ),
        a01,
    )
    _require_equal(result, expected_result, f"{task_id} A01 result reservation")

    if len(task_events) != 2 or [row.get("to_state") for row in task_events] != [
        "CREATED",
        "LEASED",
    ]:
        raise MigrationError(
            f"{task_id} has dispatch/activity evidence beyond CREATED/LEASED"
        )
    for row in task_events:
        _require_equal(row.get("fence_token"), 1, f"{task_id} A01 event fence")

    expected_lease = {
        "task_id": task_id,
        "lease_id": lease_id,
        "fence_token": 1,
        "expires_at": a01["attempt"]["lease_expires_at"],
        "state": "LEASED",
        "cohort": a01["portfolio"]["cohort"],
    }
    _require_equal(active_lease, expected_lease, f"{task_id} A01 recovery lease")
    if pending_outbox.count(expected_outbox["outbox_id"]) != 1:
        raise MigrationError(f"{task_id} A01 pending outbox projection is inconsistent")
    if any(row.get("task_id") == task_id for row in stale_attempts):
        raise MigrationError(f"{task_id} unexpectedly has a stale-attempt block")
    if owner_row is not None:
        expected_owner = {
            "task_id": task_id,
            "lease_id": lease_id,
            "fence_token": 1,
            "owned_globs": a01["ownership"]["allowed_write_globs"],
            "write_mode": "BEST_OF_N_ISOLATED_WORKTREE_ONLY",
        }
        _require_equal(owner_row, expected_owner, f"{task_id} A01 ownership")


def _a01_registry(a01: dict[str, Any], a01_sha: str) -> dict[str, Any]:
    return {
        "task_id": a01["task_id"],
        "parent_id": a01["wave_id"],
        "function": a01["assignment"]["standing_function"],
        "group": a01["assignment"]["group"],
        "material": True,
        "hypothesis_id": a01["hypothesis_id"],
        "immutable_input_uri": _uri(
            f"control/inputs/wave-a/{a01['task_id'].lower().replace('po03-', '')}.json"
        ),
        "immutable_input_manifest_sha256": a01_sha,
        "acceptance_contract_uri": a01["acceptance_contract"]["path"],
        "acceptance_contract_sha256": a01["acceptance_contract"]["sha256"],
        "model_requested": a01["configuration"]["model_slug"],
        "reasoning_requested": a01["configuration"]["reasoning"],
        "environment_requested": "best-of-n isolated git worktree",
        "owned_paths": a01["ownership"]["allowed_write_globs"],
        "result_slot": a01["ownership"]["result_slot"],
        "idempotency_key": a01["attempt"]["idempotency_key"],
        "lease_id": a01["attempt"]["lease_id"],
        "fence_token": 1,
        "lease_expires_at": a01["attempt"]["lease_expires_at"],
        "provider_run_id": "PENDING_PROVIDER_ASSIGNMENT",
        "provider_state": "UNKNOWN",
        "obzio_state": "LEASED",
        "checkpoint_seq": 0,
        "dispatch_order": a01["portfolio"]["dispatch_order"],
        "cohort": a01["portfolio"]["cohort"],
        "created_at": a01["created_at"],
        "updated_at": a01["created_at"],
        "independent_acceptance": "NOT_TESTED",
    }


def _reserved_result(
    number: int,
    input_sha: str,
    attempt_id: str,
    idempotency_key: str,
    lease_id: str,
    fence_token: int,
    attempt_suffix: str,
) -> dict[str, Any]:
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": _task_id(number),
        "commission_id": COMMISSION_ID,
        "immutable_input_manifest_sha256": input_sha,
        "acceptance_contract_sha256": None,
        "provider_state": "UNKNOWN",
        "obzio_state": "LEASED",
        "attempt": {
            "attempt_id": attempt_id,
            "idempotency_key": idempotency_key,
            "lease_id": lease_id,
            "fence_token": fence_token,
            "provider_run_id": "PENDING_PROVIDER_ASSIGNMENT",
            "worker_id": "PENDING_PROVIDER_ASSIGNMENT",
            "heartbeat_at": None,
            "checkpoint_seq": 0,
        },
        "result_transaction": {
            "result_txn_id": f"txn-po03-{_slug(number)}-{attempt_suffix}",
            "state": "RESERVED",
            "manifest_uri": None,
            "manifest_sha256": None,
            "artifact_count": 0,
            "total_bytes": 0,
            "committed_at": None,
            "verified_at": None,
            "parent_ingested_at": None,
            "result_commit_id": None,
        },
        "artifacts": [],
        "completion_actor": None,
        "independent_acceptance": {
            "state": "NOT_TESTED",
            "reviewer_id": None,
            "receipt_uri": None,
        },
    }


def _set_acceptance_hash(result: dict[str, Any], a01: dict[str, Any]) -> dict[str, Any]:
    result["acceptance_contract_sha256"] = a01["acceptance_contract"]["sha256"]
    return result


def _event_specs(
    number: int,
    start_seq: int,
    start_at: datetime,
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for offset, kind in enumerate(EVENT_KINDS):
        seq = start_seq + offset
        at = _format_time(start_at + timedelta(seconds=offset))
        event_id = (
            f"evt-po03-{_slug(number)}-a02-{seq:04d}-"
            f"{kind.lower().replace('_', '-')}"
        )
        specs.append(
            {
                "event_id": event_id,
                "event_seq": seq,
                "event_type": kind,
                "at": at,
            }
        )
    return specs


def _specs_from_review(number: int, review: dict[str, Any]) -> list[dict[str, Any]]:
    raw = review.get("events")
    if not isinstance(raw, list) or len(raw) != len(EVENT_KINDS):
        raise MigrationError(f"{_task_id(number)} A02 review has invalid event plan")
    specs: list[dict[str, Any]] = []
    for index, kind in enumerate(EVENT_KINDS):
        item = raw[index]
        if not isinstance(item, dict):
            raise MigrationError(f"{_task_id(number)} A02 review event must be an object")
        spec = {
            "event_id": item.get("event_id"),
            "event_seq": item.get("event_seq"),
            "event_type": item.get("event_type"),
            "at": item.get("at"),
        }
        if spec["event_type"] != kind:
            raise MigrationError(f"{_task_id(number)} A02 review event order diverged")
        if not isinstance(spec["event_seq"], int):
            raise MigrationError(f"{_task_id(number)} A02 review event_seq is invalid")
        expected_id = (
            f"evt-po03-{_slug(number)}-a02-{spec['event_seq']:04d}-"
            f"{kind.lower().replace('_', '-')}"
        )
        _require_equal(
            spec["event_id"], expected_id, f"{_task_id(number)} review event_id"
        )
        _parse_time(spec["at"], f"{_task_id(number)} review event at")
        specs.append(spec)
    seqs = [int(spec["event_seq"]) for spec in specs]
    if seqs != list(range(seqs[0], seqs[0] + len(EVENT_KINDS))):
        raise MigrationError(f"{_task_id(number)} review event sequence is not monotonic")
    times = [_parse_time(spec["at"], "review event") for spec in specs]
    if any(times[index + 1] - times[index] != timedelta(seconds=1) for index in range(4)):
        raise MigrationError(f"{_task_id(number)} review timestamps are not monotonic")
    return specs


def _successor_input(
    number: int,
    a01: dict[str, Any],
    a01_sha: str,
    specs: list[dict[str, Any]],
    protocol_ancestor: str,
) -> dict[str, Any]:
    task_id = _task_id(number)
    slug = _slug(number)
    created_at = specs[3]["at"]
    lease_at = _parse_time(specs[4]["at"], f"{task_id} A02 lease time")
    successor = copy.deepcopy(a01)
    successor["created_at"] = created_at
    successor["source_base"]["minimum_protocol_ancestor"] = protocol_ancestor
    successor["attempt"] = {
        "attempt_id": f"{task_id}-A02",
        "idempotency_key": f"po03:{protocol_ancestor[:12]}:{slug}:a02",
        "lease_id": f"lease-po03-{slug}-a02",
        "fence_token": 2,
        "lease_expires_at": _format_time(lease_at + LEASE_DURATION),
        "checkpoint_seq": 0,
    }
    successor["supersedes"] = {
        "attempt_id": f"{task_id}-A01",
        "immutable_input": {
            "path": _uri(_a01_rel(number)),
            "sha256": a01_sha,
        },
        "defect": "UNRESOLVABLE_MINIMUM_PROTOCOL_ANCESTOR",
        "fenced_before_dispatch": True,
    }
    successor["decision_changed"] = []
    return successor


def _a02_registry(
    number: int,
    a01: dict[str, Any],
    a01_sha: str,
    a02: dict[str, Any],
    a02_sha: str,
    specs: list[dict[str, Any]],
) -> dict[str, Any]:
    row = _a01_registry(a01, a01_sha)
    row.update(
        attempt_id=f"{_task_id(number)}-A02",
        immutable_input_uri=_uri(_a02_rel(number)),
        immutable_input_manifest_sha256=a02_sha,
        idempotency_key=a02["attempt"]["idempotency_key"],
        lease_id=a02["attempt"]["lease_id"],
        fence_token=2,
        lease_expires_at=a02["attempt"]["lease_expires_at"],
        updated_at=specs[4]["at"],
        supersedes={
            "attempt_id": f"{_task_id(number)}-A01",
            "immutable_input_uri": _uri(_a01_rel(number)),
            "immutable_input_manifest_sha256": a01_sha,
            "disposition": "SUPERSEDED_BEFORE_DISPATCH",
        },
    )
    return row


def _outbox_rows(
    number: int,
    a01: dict[str, Any],
    a01_sha: str,
    a02: dict[str, Any],
    a02_sha: str,
    specs: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    task_id = _task_id(number)
    slug = _slug(number)
    old_id = f"outbox-po03-{slug}-dispatch-a01"
    new_id = f"outbox-po03-{slug}-dispatch-a02"
    old = {
        "outbox_id": old_id,
        "task_id": task_id,
        "operation": "DISPATCH_MATERIAL",
        "idempotency_key": a01["attempt"]["idempotency_key"],
        "fence_token": 1,
        "payload_uri": _uri(_a01_rel(number)),
        "payload_sha256": a01_sha,
        "state": "FENCED",
        "attempts": 0,
        "created_at": a01["created_at"],
        "last_attempt_at": None,
        "delivered_at": None,
        "cohort": a01["portfolio"]["cohort"],
        "disposition": "SUPERSEDED_BEFORE_DISPATCH",
        "fenced_at": specs[1]["at"],
        "fenced_by_token": 2,
        "superseded_by_outbox_id": new_id,
        "successor_payload_uri": _uri(_a02_rel(number)),
        "successor_payload_sha256": a02_sha,
    }
    new = {
        "outbox_id": new_id,
        "task_id": task_id,
        "operation": "DISPATCH_MATERIAL",
        "attempt_id": f"{task_id}-A02",
        "idempotency_key": a02["attempt"]["idempotency_key"],
        "fence_token": 2,
        "payload_uri": _uri(_a02_rel(number)),
        "payload_sha256": a02_sha,
        "state": "PENDING",
        "attempts": 0,
        "created_at": specs[3]["at"],
        "last_attempt_at": None,
        "delivered_at": None,
        "cohort": a01["portfolio"]["cohort"],
        "supersedes_outbox_id": old_id,
    }
    return old, new


def _owner_row(number: int, a01: dict[str, Any], a02: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": _task_id(number),
        "lease_id": a02["attempt"]["lease_id"],
        "fence_token": 2,
        "owned_globs": a01["ownership"]["allowed_write_globs"],
        "write_mode": "BEST_OF_N_ISOLATED_WORKTREE_ONLY",
        "attempt_id": f"{_task_id(number)}-A02",
        "supersedes_lease_id": a01["attempt"]["lease_id"],
    }


def _active_lease(number: int, a01: dict[str, Any], a02: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": _task_id(number),
        "lease_id": a02["attempt"]["lease_id"],
        "fence_token": 2,
        "expires_at": a02["attempt"]["lease_expires_at"],
        "state": "LEASED",
        "cohort": a01["portfolio"]["cohort"],
        "attempt_id": f"{_task_id(number)}-A02",
    }


def _stale_block(number: int, a01: dict[str, Any], specs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "task_id": _task_id(number),
        "attempt_id": f"{_task_id(number)}-A01",
        "idempotency_key": a01["attempt"]["idempotency_key"],
        "lease_id": a01["attempt"]["lease_id"],
        "fence_token": 1,
        "blocked_by_fence_token": 2,
        "blocked_at": specs[1]["at"],
        "reason": "SUPERSEDED_BEFORE_DISPATCH_PROVENANCE_DEFECT",
        "successor_attempt_id": f"{_task_id(number)}-A02",
    }


def _event_rows(
    number: int,
    a01: dict[str, Any],
    a01_sha: str,
    a02: dict[str, Any],
    a02_sha: str,
    specs: list[dict[str, Any]],
    protocol_ancestor: str,
    commission_commit: str,
) -> list[dict[str, Any]]:
    task_id = _task_id(number)
    actor = f"controller:{CONTROLLER_RUN_ID}"
    base = [
        {
            "task_id": task_id,
            "attempt_id": f"{task_id}-A01",
            "from_state": "LEASED",
            "to_state": "LEASED",
            "actor": actor,
            "fence_token": 1,
            "declared_ancestor": INVALID_PROTOCOL_ANCESTOR,
            "corrected_ancestor": protocol_ancestor,
            "commission_commit": commission_commit,
        },
        {
            "task_id": task_id,
            "attempt_id": f"{task_id}-A01",
            "from_state": "LEASED",
            "to_state": "FENCED",
            "actor": actor,
            "fence_token": 2,
            "stale_fence_token": 1,
            "reason": "UNRESOLVABLE_MINIMUM_PROTOCOL_ANCESTOR",
        },
        {
            "task_id": task_id,
            "attempt_id": f"{task_id}-A01",
            "from_state": "FENCED",
            "to_state": "SUPERSEDED_BEFORE_DISPATCH",
            "actor": actor,
            "fence_token": 2,
            "immutable_input_uri": _uri(_a01_rel(number)),
            "immutable_input_manifest_sha256": a01_sha,
            "successor_attempt_id": f"{task_id}-A02",
            "successor_input_uri": _uri(_a02_rel(number)),
            "successor_input_manifest_sha256": a02_sha,
        },
        {
            "task_id": task_id,
            "attempt_id": f"{task_id}-A02",
            "from_state": None,
            "to_state": "CREATED",
            "actor": actor,
            "fence_token": 2,
            "immutable_input_manifest_sha256": a02_sha,
            "idempotency_key": a02["attempt"]["idempotency_key"],
            "supersedes_attempt_id": f"{task_id}-A01",
        },
        {
            "task_id": task_id,
            "attempt_id": f"{task_id}-A02",
            "from_state": "CREATED",
            "to_state": "LEASED",
            "actor": actor,
            "fence_token": 2,
            "lease_id": a02["attempt"]["lease_id"],
            "lease_expires_at": a02["attempt"]["lease_expires_at"],
            "idempotency_key": a02["attempt"]["idempotency_key"],
        },
    ]
    rows: list[dict[str, Any]] = []
    for detail, spec in zip(base, specs):
        row = dict(detail)
        row.update(spec)
        rows.append(row)
    return rows


def _review(
    number: int,
    a01_sha: str,
    a02_sha: str,
    specs: list[dict[str, Any]],
    protocol_ancestor: str,
    commission_commit: str,
    ownership_updated: bool,
) -> dict[str, Any]:
    task_id = _task_id(number)
    return {
        "schema_version": "1.0",
        "review_id": f"{task_id}-A02-PROVENANCE-SUPERSESSION-REVIEW-001",
        "review_type": "CONTROLLER_PROVENANCE_CORRECTION",
        "review_state": "RECORDED_NOT_INDEPENDENT_ACCEPTANCE",
        "controller_id": CONTROLLER_RUN_ID,
        "recorded_at": specs[0]["at"],
        "task_id": task_id,
        "old_attempt_id": f"{task_id}-A01",
        "successor_attempt_id": f"{task_id}-A02",
        "disposition": "SUPERSEDE_UNDISPATCHED_A01_BEFORE_DISPATCH",
        "selection_basis": "EXPLICIT_CALLER_SELECTION_VALIDATED_AGAINST_PROTECTED_SET",
        "protected_task_numbers": sorted(PROTECTED_TASK_NUMBERS),
        "provenance": {
            "defective_declared_ancestor": INVALID_PROTOCOL_ANCESTOR,
            "corrected_resolved_ancestor": protocol_ancestor,
            "commission_commit": commission_commit,
            "commission_is_ancestor_of_corrected_protocol": True,
            "corrected_protocol_is_ancestor_of_controller_head": True,
        },
        "a01_input": {
            "path": _uri(_a01_rel(number)),
            "sha256": a01_sha,
            "preserved_byte_identical": True,
        },
        "a02_input": {
            "path": _uri(_a02_rel(number)),
            "sha256": a02_sha,
            "attempt_id": f"{task_id}-A02",
            "fence_token": 2,
        },
        "events": specs,
        "ownership_projection_updated": ownership_updated,
        "task_cardinality_before": 64,
        "task_cardinality_after": 64,
        "independent_acceptance": "NOT_PERFORMED",
        "decision_changed": [],
    }


def _bundle(
    number: int,
    a01: dict[str, Any],
    a01_sha: str,
    specs: list[dict[str, Any]],
    protocol_ancestor: str,
    commission_commit: str,
    ownership_updated: bool,
) -> dict[str, Any]:
    a02 = _successor_input(number, a01, a01_sha, specs, protocol_ancestor)
    a02_bytes = _json_bytes(a02)
    a02_sha = _sha(a02_bytes)
    result = _set_acceptance_hash(
        _reserved_result(
            number,
            a02_sha,
            f"{_task_id(number)}-A02",
            a02["attempt"]["idempotency_key"],
            a02["attempt"]["lease_id"],
            2,
            "a02",
        ),
        a01,
    )
    old_outbox, new_outbox = _outbox_rows(
        number, a01, a01_sha, a02, a02_sha, specs
    )
    return {
        "a02": a02,
        "a02_bytes": a02_bytes,
        "a02_sha": a02_sha,
        "result": result,
        "registry": _a02_registry(
            number, a01, a01_sha, a02, a02_sha, specs
        ),
        "old_outbox": old_outbox,
        "new_outbox": new_outbox,
        "owner": _owner_row(number, a01, a02),
        "active_lease": _active_lease(number, a01, a02),
        "stale_block": _stale_block(number, a01, specs),
        "events": _event_rows(
            number,
            a01,
            a01_sha,
            a02,
            a02_sha,
            specs,
            protocol_ancestor,
            commission_commit,
        ),
        "review": _review(
            number,
            a01_sha,
            a02_sha,
            specs,
            protocol_ancestor,
            commission_commit,
            ownership_updated,
        ),
    }


def _validate_existing_bundle(
    number: int,
    bundle: dict[str, Any],
    a02_bytes: bytes,
    review: dict[str, Any],
    registry_row: dict[str, Any],
    task_outbox: list[dict[str, Any]],
    result: dict[str, Any],
    task_events: list[dict[str, Any]],
    owner_row: dict[str, Any] | None,
    active_lease: dict[str, Any],
    pending_outbox: list[Any],
    stale_attempts: list[dict[str, Any]],
) -> None:
    task_id = _task_id(number)
    _require_equal(a02_bytes, bundle["a02_bytes"], f"{task_id} divergent A02 bytes")
    _require_equal(review, bundle["review"], f"{task_id} A02 review")
    _require_equal(registry_row, bundle["registry"], f"{task_id} A02 registry")
    expected_outbox = [bundle["old_outbox"], bundle["new_outbox"]]
    _require_equal(task_outbox, expected_outbox, f"{task_id} A02 outbox rows")
    _require_equal(result, bundle["result"], f"{task_id} A02 result reservation")
    expected_events = bundle["events"]
    actual_events = [
        row
        for row in task_events
        if row.get("attempt_id") in {f"{task_id}-A01", f"{task_id}-A02"}
        and row.get("event_type") in EVENT_KINDS
    ]
    _require_equal(actual_events, expected_events, f"{task_id} A02 ledger events")
    if bundle["review"]["ownership_projection_updated"]:
        _require_equal(owner_row, bundle["owner"], f"{task_id} A02 ownership")
    elif owner_row is not None:
        raise MigrationError(f"{task_id} has unexpected A02 ownership projection")
    _require_equal(active_lease, bundle["active_lease"], f"{task_id} A02 lease")
    if pending_outbox.count(bundle["new_outbox"]["outbox_id"]) != 1:
        raise MigrationError(f"{task_id} A02 pending outbox is inconsistent")
    if bundle["old_outbox"]["outbox_id"] in pending_outbox:
        raise MigrationError(f"{task_id} fenced A01 remains pending")
    matching_blocks = [
        row for row in stale_attempts if row.get("task_id") == task_id
    ]
    _require_equal(
        matching_blocks, [bundle["stale_block"]], f"{task_id} stale-attempt block"
    )


def _add_mutation(
    mutations: list[Mutation],
    reader: Reader,
    relative: str,
    after: bytes,
) -> None:
    before = reader.optional_bytes(relative)
    if before != after:
        mutations.append(Mutation(relative, before, after))


def build_plan(
    root_argument: Path,
    selected_task_numbers: set[int],
    *,
    protocol_ancestor: str | None = None,
    commission_commit: str | None = None,
) -> Plan:
    if protocol_ancestor is None:
        protocol_ancestor = CORRECTED_PROTOCOL_ANCESTOR
    if commission_commit is None:
        commission_commit = COMMISSION_COMMIT
    selected = _validate_selected(selected_task_numbers)
    root, repo = resolve_po03_root(root_argument)
    validate_git_provenance(repo, protocol_ancestor, commission_commit)
    reader = Reader(root)

    portfolio = reader.json(PORTFOLIO_REL)
    _validate_portfolio(portfolio)
    a01_documents = {
        number: reader.json(_a01_rel(number)) for number in sorted(ALL_TASK_NUMBERS)
    }
    a01_hashes = {
        number: _sha(reader.bytes(_a01_rel(number)))
        for number in sorted(ALL_TASK_NUMBERS)
    }
    registry = reader.jsonl(REGISTRY_REL)
    outbox = reader.jsonl(OUTBOX_REL)
    events = reader.jsonl(EVENTS_REL)
    recovery = reader.json(RECOVERY_REL)
    ownership = reader.optional_json(OWNERSHIP_REL)
    _validate_global_state(
        root,
        reader,
        a01_documents,
        registry,
        outbox,
        events,
        recovery,
        ownership,
        commission_commit,
    )

    registry_work = copy.deepcopy(registry)
    outbox_work = copy.deepcopy(outbox)
    events_work = copy.deepcopy(events)
    recovery_work = copy.deepcopy(recovery)
    ownership_work = copy.deepcopy(ownership)
    result_updates: dict[int, dict[str, Any]] = {}
    created_files: dict[str, bytes] = {}
    new_successors: list[int] = []
    existing_successors: list[int] = []

    event_seq_cursor = max((int(row["event_seq"]) for row in events_work), default=0)
    latest_event_at = max(
        (_parse_time(row["at"], f"event {row['event_id']}.at") for row in events_work),
        default=datetime(1970, 1, 1, tzinfo=timezone.utc),
    )

    active_leases = recovery_work.get("active_leases")
    pending_outbox = recovery_work.get("pending_outbox")
    stale_attempts = recovery_work.get("stale_attempts_blocked")
    if not isinstance(active_leases, list):
        raise MigrationError("recovery active_leases must be an array")
    if not isinstance(pending_outbox, list):
        raise MigrationError("recovery pending_outbox must be an array")
    if not isinstance(stale_attempts, list):
        raise MigrationError("recovery stale_attempts_blocked must be an array")
    owners = None
    if ownership_work is not None:
        owners = ownership_work.get("subordinate_owners")
        if not isinstance(owners, list):
            raise MigrationError("path ownership subordinate_owners must be an array")

    for number in selected:
        task_id = _task_id(number)
        a01 = a01_documents[number]
        a01_sha = a01_hashes[number]
        a02_rel = _a02_rel(number)
        review_rel = _review_rel(number)
        existing_a02_bytes = reader.optional_bytes(a02_rel)
        existing_review = reader.optional_json(review_rel)
        if (existing_a02_bytes is None) != (existing_review is None):
            raise MigrationError(
                f"{task_id} has an incomplete or divergent pre-existing A02 successor"
            )

        registry_index, registry_row = _one_row(
            registry_work, "task_id", task_id, "registry"
        )
        result = reader.json(_result_rel(number))
        result_updates[number] = result
        task_outbox = [row for row in outbox_work if row.get("task_id") == task_id]
        task_events = [row for row in events_work if row.get("task_id") == task_id]
        _, active_lease = _one_row(
            active_leases, "task_id", task_id, "recovery active leases"
        )
        owner_match = (
            _optional_row(owners, "task_id", task_id, "path ownership")
            if owners is not None
            else None
        )
        owner_row = owner_match[1] if owner_match is not None else None

        if existing_review is not None and existing_a02_bytes is not None:
            ownership_updated = existing_review.get("ownership_projection_updated")
            if not isinstance(ownership_updated, bool):
                raise MigrationError(
                    f"{task_id} review ownership_projection_updated must be boolean"
                )
            specs = _specs_from_review(number, existing_review)
            bundle = _bundle(
                number,
                a01,
                a01_sha,
                specs,
                protocol_ancestor,
                commission_commit,
                ownership_updated,
            )
            _validate_existing_bundle(
                number,
                bundle,
                existing_a02_bytes,
                existing_review,
                registry_row,
                task_outbox,
                result,
                task_events,
                owner_row,
                active_lease,
                pending_outbox,
                stale_attempts,
            )
            result_updates[number] = bundle["result"]
            existing_successors.append(number)
            continue

        outbox_index, old_outbox = _one_row(
            outbox_work,
            "outbox_id",
            f"outbox-po03-{_slug(number)}-dispatch-a01",
            "outbox",
        )
        owner_present = owner_match is not None
        _validate_a01_projection(
            number,
            a01,
            a01_sha,
            registry_row,
            old_outbox,
            result,
            task_events,
            active_lease,
            pending_outbox,
            stale_attempts,
            owner_row,
        )
        if any(
            row.get("outbox_id")
            == f"outbox-po03-{_slug(number)}-dispatch-a02"
            for row in outbox_work
        ):
            raise MigrationError(f"{task_id} has a colliding A02 outbox row")

        specs = _event_specs(
            number,
            event_seq_cursor + 1,
            latest_event_at + timedelta(seconds=1),
        )
        event_seq_cursor += len(EVENT_KINDS)
        latest_event_at = _parse_time(specs[-1]["at"], f"{task_id} last A02 event")
        bundle = _bundle(
            number,
            a01,
            a01_sha,
            specs,
            protocol_ancestor,
            commission_commit,
            owner_present,
        )

        registry_work[registry_index] = bundle["registry"]
        outbox_work[outbox_index] = bundle["old_outbox"]
        outbox_work.insert(outbox_index + 1, bundle["new_outbox"])
        events_work.extend(bundle["events"])
        result_updates[number] = bundle["result"]
        created_files[a02_rel] = bundle["a02_bytes"]
        created_files[review_rel] = _json_bytes(bundle["review"])

        lease_index, _ = _one_row(
            active_leases, "task_id", task_id, "recovery active leases"
        )
        active_leases[lease_index] = bundle["active_lease"]
        old_outbox_id = bundle["old_outbox"]["outbox_id"]
        if pending_outbox.count(old_outbox_id) != 1:
            raise MigrationError(f"{task_id} A01 pending outbox is inconsistent")
        pending_index = pending_outbox.index(old_outbox_id)
        pending_outbox[pending_index] = bundle["new_outbox"]["outbox_id"]
        stale_attempts.append(bundle["stale_block"])
        if owner_match is not None and owners is not None:
            owners[owner_match[0]] = bundle["owner"]
        new_successors.append(number)

    if new_successors:
        recovery_work["last_event_seq"] = event_seq_cursor
        recovery_work["scanned_at"] = _format_time(latest_event_at)

    material_registry = [
        row
        for row in registry_work
        if MATERIAL_TASK_RE.fullmatch(str(row.get("task_id", "")))
    ]
    if len(material_registry) != 64 or len(
        {row.get("task_id") for row in material_registry}
    ) != 64:
        raise MigrationError("planned registry would change Wave A task cardinality")

    mutations: list[Mutation] = []
    _add_mutation(mutations, reader, REGISTRY_REL, _jsonl_bytes(registry_work))
    _add_mutation(mutations, reader, OUTBOX_REL, _jsonl_bytes(outbox_work))
    _add_mutation(mutations, reader, EVENTS_REL, _jsonl_bytes(events_work))
    _add_mutation(mutations, reader, RECOVERY_REL, _json_bytes(recovery_work))
    if ownership_work is not None:
        _add_mutation(
            mutations, reader, OWNERSHIP_REL, _json_bytes(ownership_work)
        )
    for number in selected:
        _add_mutation(
            mutations,
            reader,
            _result_rel(number),
            _json_bytes(result_updates[number]),
        )
    for relative, data in created_files.items():
        _add_mutation(mutations, reader, relative, data)

    a01_targets = {_a01_rel(number) for number in ALL_TASK_NUMBERS}
    if any(mutation.relative in a01_targets for mutation in mutations):
        raise MigrationError("internal error: an immutable A01 input became a write target")
    return Plan(
        root=root,
        selected=selected,
        new_successors=tuple(new_successors),
        existing_successors=tuple(existing_successors),
        read_set=dict(reader.snapshots),
        mutations=tuple(mutations),
        last_event_seq=event_seq_cursor,
    )


def _current_bytes(root: Path, relative: str) -> bytes | None:
    path = _safe_path(root, relative)
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise MigrationError(f"unable to revalidate {relative}: {exc}") from exc


def _validate_read_set(plan: Plan) -> None:
    for relative, expected in plan.read_set.items():
        observed = _current_bytes(plan.root, relative)
        if observed != expected:
            raise MigrationError(
                f"control state changed after planning; transaction aborted: {relative}"
            )


def _stage_mutations(plan: Plan) -> list[tuple[Mutation, Path]]:
    staged: list[tuple[Mutation, Path]] = []
    try:
        for index, mutation in enumerate(plan.mutations):
            target = _safe_path(plan.root, mutation.relative)
            if not target.parent.is_dir():
                raise MigrationError(
                    f"transaction target parent is missing: {mutation.relative}"
                )
            temporary = target.with_name(
                f".{target.name}.po03-supersession-{os.getpid()}-{index}.tmp"
            )
            if temporary.exists():
                raise MigrationError(f"staging collision: {temporary.name}")
            with temporary.open("xb") as handle:
                handle.write(mutation.after)
                handle.flush()
                os.fsync(handle.fileno())
            staged.append((mutation, temporary))
        return staged
    except BaseException:
        for _, temporary in staged:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        raise


def _validate_staged_payloads(staged: list[tuple[Mutation, Path]]) -> None:
    for mutation, temporary in staged:
        try:
            observed = temporary.read_bytes()
        except OSError as exc:
            raise MigrationError(
                f"unable to validate staged {mutation.relative}: {exc}"
            ) from exc
        if observed != mutation.after:
            raise MigrationError(f"staged payload mismatch: {mutation.relative}")


def _restore(root: Path, mutation: Mutation, index: int) -> None:
    target = _safe_path(root, mutation.relative)
    if mutation.before is None:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return
    temporary = target.with_name(
        f".{target.name}.po03-rollback-{os.getpid()}-{index}.tmp"
    )
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
    with temporary.open("xb") as handle:
        handle.write(mutation.before)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def apply_plan(plan: Plan) -> None:
    if not plan.mutations:
        _validate_read_set(plan)
        return
    _validate_read_set(plan)
    staged = _stage_mutations(plan)
    replaced: list[Mutation] = []
    try:
        _validate_staged_payloads(staged)
        _validate_read_set(plan)
        for mutation, temporary in staged:
            target = _safe_path(plan.root, mutation.relative)
            os.replace(temporary, target)
            replaced.append(mutation)
        for mutation in plan.mutations:
            if _current_bytes(plan.root, mutation.relative) != mutation.after:
                raise MigrationError(
                    f"post-replace verification failed: {mutation.relative}"
                )
    except BaseException as exc:
        rollback_errors: list[str] = []
        for index, mutation in enumerate(reversed(replaced)):
            try:
                _restore(plan.root, mutation, index)
            except BaseException as rollback_exc:
                rollback_errors.append(f"{mutation.relative}: {rollback_exc}")
        for _, temporary in staged:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError as cleanup_exc:
                rollback_errors.append(f"{temporary.name}: {cleanup_exc}")
        if rollback_errors:
            raise MigrationError(
                f"transaction failed ({exc}); rollback also failed: "
                + "; ".join(rollback_errors)
            ) from exc
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError(f"transaction failed and was rolled back: {exc}") from exc
    finally:
        for _, temporary in staged:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def parse_task_numbers(value: str) -> set[int]:
    selected: set[int] = set()
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            raise argparse.ArgumentTypeError("empty task-number component")
        if "-" in part:
            pieces = part.split("-", 1)
            try:
                start, end = int(pieces[0]), int(pieces[1])
            except ValueError as exc:
                raise argparse.ArgumentTypeError(
                    f"invalid task range: {part}"
                ) from exc
            if start > end:
                raise argparse.ArgumentTypeError(f"descending task range: {part}")
            selected.update(range(start, end + 1))
        else:
            try:
                selected.add(int(part))
            except ValueError as exc:
                raise argparse.ArgumentTypeError(
                    f"invalid task number: {part}"
                ) from exc
    return selected


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create fenced A02 successors for explicitly selected, undispatched "
            "PO-03 Wave A tasks. Dry-run unless --apply is supplied."
        )
    )
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="repository root or workstreams/po03 directory",
    )
    parser.add_argument(
        "--tasks",
        required=True,
        type=parse_task_numbers,
        help="explicit comma-separated task numbers/ranges, for example 5-11,13",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="atomically apply the validated plan (default: dry-run)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        plan = build_plan(args.root, args.tasks)
        if args.apply:
            apply_plan(plan)
        output = {
            "mode": "APPLIED" if args.apply else "DRY_RUN",
            "selected_task_numbers": list(plan.selected),
            "new_successor_task_numbers": list(plan.new_successors),
            "already_applied_task_numbers": list(plan.existing_successors),
            "files_to_change": len(plan.mutations),
            "last_event_seq": plan.last_event_seq,
            "task_cardinality": 64,
            "a01_inputs_rewritten": 0,
            "decision_changed": [],
        }
        print(json.dumps(output, sort_keys=True))
        return 0
    except MigrationError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
