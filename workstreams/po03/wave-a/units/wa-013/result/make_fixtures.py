#!/usr/bin/env python3
"""Deterministically generate sanitized crash fixtures for the recovery scanner.

Every fixture reproduces one fault class from the commission's fault-injection
list against a ledger shaped exactly like the live PO-03 ledger, but populated
only with synthetic identifiers.  No live provider run identifier, branch name,
commit identifier, lease identifier or account detail is copied in.

The generator is deterministic: identifiers are derived by SHA-256 over a stable
label, so a clean clone regenerates byte-identical fixtures and the committed
fixture digests are verifiable rather than asserted.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

FIXTURE_PROTOCOL = "OBZIO-RECOVERY-CRASH-FIXTURE-v1"

COORDINATOR = "controller:fx-coordinator-0001"
VERIFIER = "controller-verifier:fx-assurance-0001"
PRODUCER = "producer:fx-worker-0001"
STALE_PRODUCER = "producer:fx-worker-0002-stale"
PROVIDER = "provider:fx-harness"


def synth_hex(label: str, length: int) -> str:
    """Deterministic synthetic hex identifier of the requested length."""
    out = ""
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(f"obzio-po03-wa-013-fixture::{label}::{counter}".encode()).hexdigest()
        counter += 1
    return out[:length]


def commit_id(label: str) -> str:
    return synth_hex(f"commit::{label}", 40)


def digest(label: str) -> str:
    return synth_hex(f"sha256::{label}", 64)


class LedgerBuilder:
    """Appends events the way the live controller and producers append them."""

    def __init__(self, task_prefix: str) -> None:
        self.task_prefix = task_prefix
        self.seq = 0
        self.lines: list[str] = []
        self._event_no: dict[str, int] = {}

    def append(
        self,
        *,
        task_id: str,
        actor: str,
        to_state: str,
        from_state: str | None,
        at: str,
        fence_token: int = 1,
        event_id: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        self.seq += 1
        index = self._event_no.get(task_id, 0) + 1
        self._event_no[task_id] = index
        event: dict[str, Any] = {
            "actor": actor,
            "at": at,
            "event_id": event_id or f"evt-{task_id.lower()}-{index:04d}",
            "event_seq": self.seq,
            "fence_token": fence_token,
            "from_state": from_state,
            "task_id": task_id,
            "to_state": to_state,
        }
        event.update(extra)
        self.lines.append(json.dumps(event, sort_keys=True, separators=(",", ":")))
        return event

    def raw_append(self, line: str) -> None:
        self.lines.append(line)

    def text(self, *, trailing_newline: bool = True) -> str:
        body = "\n".join(self.lines)
        return body + "\n" if trailing_newline else body


def _lifecycle(
    builder: LedgerBuilder,
    task_id: str,
    *,
    attempt: str = "a01",
    fence: int = 1,
    lease_expires_at: str = "2026-08-22T14:00:00Z",
    stop_after: str,
    base_minute: int = 0,
) -> None:
    """Append the main-line lifecycle up to and including ``stop_after``."""
    key = f"po03:fx:{task_id.lower()}:{attempt}"
    attempt_id = f"{task_id}-{attempt.upper()}"
    run_id = f"fx-run-{synth_hex(f'run::{task_id}::{attempt}', 12)}"

    def stamp(offset: int) -> str:
        total = base_minute + offset
        return f"2026-08-22T{9 + total // 60:02d}:{total % 60:02d}:00Z"

    steps: list[tuple[str, str | None, str, dict[str, Any]]] = [
        (
            "CREATED",
            None,
            COORDINATOR,
            {
                "idempotency_key": key,
                "attempt_id": attempt_id,
                "immutable_input_uri": f"workstreams/po03/control/inputs/fixtures/{task_id.lower()}.json",
                "immutable_input_manifest_sha256": digest(f"input::{task_id}::{attempt}"),
            },
        ),
        (
            "LEASED",
            "CREATED",
            COORDINATOR,
            {
                "idempotency_key": key,
                "attempt_id": attempt_id,
                "lease_id": f"lease-{task_id.lower()}-{attempt}",
                "lease_expires_at": lease_expires_at,
            },
        ),
        ("RUNNING", "LEASED", PRODUCER, {"provider_run_id": run_id}),
        ("CHECKPOINTED", "RUNNING", PRODUCER, {"checkpoint_seq": 1}),
        ("RESULT_STAGING", "CHECKPOINTED", PRODUCER, {"checkpoint_seq": 2}),
        ("RESULT_STAGED", "RESULT_STAGING", PRODUCER, {"checkpoint_seq": 3}),
        (
            "RESULT_VERIFIED",
            "RESULT_STAGED",
            PRODUCER,
            {"checkpoint_seq": 4, "manifest_sha256": digest(f"manifest::{task_id}::{attempt}")},
        ),
        (
            "RESULT_COMMITTED",
            "RESULT_VERIFIED",
            PRODUCER,
            {
                "result_commit_id": commit_id(f"result::{task_id}::{attempt}"),
                "return_commit_id": commit_id(f"return::{task_id}::{attempt}"),
                "manifest_sha256": digest(f"manifest::{task_id}::{attempt}"),
            },
        ),
        ("PARENT_INGESTED", "RESULT_COMMITTED", COORDINATOR, {}),
        ("COMPLETED", "PARENT_INGESTED", COORDINATOR, {}),
        ("ACCEPTED", "COMPLETED", VERIFIER, {}),
    ]

    for offset, (to_state, from_state, actor, extra) in enumerate(steps):
        builder.append(
            task_id=task_id,
            actor=actor,
            to_state=to_state,
            from_state=from_state,
            at=stamp(offset),
            fence_token=fence,
            **extra,
        )
        if to_state == stop_after:
            return


# --------------------------------------------------------------------------
# Fixture definitions.  Each returns (ledger_text, sidecar_files, description).
# --------------------------------------------------------------------------


def fx_clean_full_lifecycle() -> tuple[str, dict[str, Any], str]:
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-001", stop_after="ACCEPTED")
    return (
        builder.text(),
        {},
        "Control fixture: one unit traverses the entire lifecycle to ACCEPTED with no fault injected.",
    )


def fx_committed_not_ingested() -> tuple[str, dict[str, Any], str]:
    """Lost return callback: durable commit exists, parent never ingested."""
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-002", stop_after="RESULT_COMMITTED")
    return (
        builder.text(),
        {},
        "Lost return callback after a durable result commit. The producer committed and pushed; "
        "the parent never recorded PARENT_INGESTED. The result is recoverable without rerunning "
        "the producer, so the scanner must emit REPLAY_PARENT_INGESTION and never RERUN.",
    )


def fx_provider_completed_uncommitted() -> tuple[str, dict[str, Any], str]:
    """Provider reports completion; no durable result commit exists."""
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-003", stop_after="CHECKPOINTED")
    observations = {"PO03-FX-003": {"provider_state": "COMPLETED"}}
    return (
        builder.text(),
        {"fx-03-provider-observations.json": observations},
        "Sanitized analogue of the frozen PO-02 Code-2 packaging loss: the provider runtime "
        "reported COMPLETED while the ledger stops at CHECKPOINTED with no result commit. Obzio "
        "state must be PROVIDER_COMPLETED_UNCOMMITTED and never COMPLETED.",
    )


def fx_false_completion() -> tuple[str, dict[str, Any], str]:
    """COMPLETED asserted with no durable result commit behind it."""
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-004", stop_after="RESULT_STAGED")
    builder.append(
        task_id="PO03-FX-004",
        actor=COORDINATOR,
        to_state="COMPLETED",
        from_state="RESULT_STAGED",
        at="2026-08-22T09:20:00Z",
    )
    return (
        builder.text(),
        {},
        "False completion: a coordinator event asserts COMPLETED directly from RESULT_STAGED with "
        "no RESULT_COMMITTED and no result_commit_id. Acceptance requires zero false completion, so "
        "the scanner must refuse the transition and raise a CRITICAL finding.",
    )


def fx_stale_lease_commit() -> tuple[str, dict[str, Any], str]:
    """A fenced worker tries to commit after ownership transferred."""
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-005", stop_after="CHECKPOINTED")
    builder.append(
        task_id="PO03-FX-005",
        actor=COORDINATOR,
        to_state="FENCED",
        from_state="CHECKPOINTED",
        at="2026-08-22T09:30:00Z",
        fence_token=2,
        attempt_id="PO03-FX-005-A01",
        reason="LEASE_EXPIRED_OWNERSHIP_TRANSFERRED",
        stale_fence_token=1,
    )
    # The evicted worker wakes up and tries to finish its transaction.
    builder.append(
        task_id="PO03-FX-005",
        actor=STALE_PRODUCER,
        to_state="RESULT_COMMITTED",
        from_state="RESULT_VERIFIED",
        at="2026-08-22T09:31:00Z",
        fence_token=1,
        attempt_id="PO03-FX-005-A01",
        result_commit_id=commit_id("stale::PO03-FX-005"),
        return_commit_id=commit_id("stale-return::PO03-FX-005"),
    )
    builder.append(
        task_id="PO03-FX-005",
        actor=STALE_PRODUCER,
        to_state="PARENT_INGESTED",
        from_state="RESULT_COMMITTED",
        at="2026-08-22T09:32:00Z",
        fence_token=1,
        attempt_id="PO03-FX-005-A01",
    )
    return (
        builder.text(),
        {},
        "Stale lease: after the coordinator fences attempt A01 at token 2, the evicted worker "
        "attempts RESULT_COMMITTED and PARENT_INGESTED at token 1. Both must be refused so the "
        "stale worker cannot commit after ownership transfers.",
    )


def fx_duplicate_callback() -> tuple[str, dict[str, Any], str]:
    """Exact redelivery of commit and ingest callbacks must be harmless."""
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-006", stop_after="COMPLETED")
    # At-least-once delivery replays three earlier lines verbatim.
    replays = [line for line in builder.lines if '"RESULT_COMMITTED"' in line or '"PARENT_INGESTED"' in line]
    for line in replays:
        builder.raw_append(line)
    for line in replays:
        builder.raw_append(line)
    return (
        builder.text(),
        {},
        "Duplicate callbacks: the RESULT_COMMITTED and PARENT_INGESTED events are redelivered "
        "verbatim twice by an at-least-once transport. Deduplication by event_id must leave the "
        "reconstructed state unchanged and raise no defect.",
    )


def fx_torn_tail() -> tuple[str, dict[str, Any], str]:
    """Process loss mid-append leaves a truncated final line."""
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-007", stop_after="RESULT_COMMITTED")
    body = builder.text(trailing_newline=True)
    partial = json.dumps(
        {
            "actor": COORDINATOR,
            "at": "2026-08-22T09:40:00Z",
            "event_id": "evt-po03-fx-007-0009",
            "event_seq": builder.seq + 1,
            "fence_token": 1,
            "from_state": "RESULT_COMMITTED",
            "task_id": "PO03-FX-007",
            "to_state": "PARENT_INGESTED",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    truncated = partial[: len(partial) // 2]
    return (
        body + truncated,
        {},
        "Partial write: the process died while appending the PARENT_INGESTED event, leaving half a "
        "JSON object and no trailing newline. The scanner must truncate the torn tail safely, "
        "report it as recoverable, and still reconstruct COMMITTED_NOT_INGESTED from the durable "
        "prefix rather than refusing to scan.",
    )


def fx_corrupt_interior_line() -> tuple[str, dict[str, Any], str]:
    """A complete but malformed line in the middle of the ledger."""
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-008", stop_after="RESULT_STAGED")
    builder.raw_append('{"actor":"controller:fx-coordinator-0001","event_seq":99,"to_state":')
    builder.append(
        task_id="PO03-FX-008",
        actor=PRODUCER,
        to_state="RESULT_VERIFIED",
        from_state="RESULT_STAGED",
        at="2026-08-22T09:50:00Z",
        manifest_sha256=digest("manifest::PO03-FX-008::a01"),
    )
    return (
        builder.text(),
        {},
        "Interior corruption: a complete newline-terminated line in the middle of the ledger is "
        "not valid JSON. Unlike a torn tail this cannot be a crash artefact of the last append, so "
        "it is a CRITICAL append-only integrity violation, not a skippable line.",
    )


def fx_checkpoint_regression() -> tuple[str, dict[str, Any], str]:
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-009", stop_after="RESULT_STAGING")
    builder.append(
        task_id="PO03-FX-009",
        actor=PRODUCER,
        to_state="RESULT_STAGED",
        from_state="RESULT_STAGING",
        at="2026-08-22T10:00:00Z",
        checkpoint_seq=1,
    )
    return (
        builder.text(),
        {},
        "Checkpoint regression: a later event carries a lower checkpoint_seq than one already "
        "durable. Checkpoints must be monotonic, so the regression is a defect and the retained "
        "checkpoint must not move backwards.",
    )


def fx_orphaned_lease_expired() -> tuple[str, dict[str, Any], str]:
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(
        builder,
        "PO03-FX-010",
        stop_after="RUNNING",
        lease_expires_at="2026-08-22T09:05:00Z",
    )
    return (
        builder.text(),
        {},
        "Entire provider-runtime loss: the unit is RUNNING, its lease has expired, and no result "
        "commit exists. The scanner must classify it ORPHANED_LEASE_EXPIRED and emit a redispatch "
        "directive that raises the fence token.",
    )


def fx_event_id_conflict() -> tuple[str, dict[str, Any], str]:
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-011", stop_after="RESULT_COMMITTED")
    builder.append(
        task_id="PO03-FX-011",
        actor=COORDINATOR,
        to_state="PARENT_INGESTED",
        from_state="RESULT_COMMITTED",
        at="2026-08-22T10:10:00Z",
        event_id="evt-po03-fx-011-0008",
    )
    return (
        builder.text(),
        {},
        "Identifier reuse: a second event reuses the event_id of the RESULT_COMMITTED event while "
        "carrying different content. Idempotent deduplication must not silently absorb it, because "
        "that would let a rewritten event hide behind a delivered one.",
    )


def fx_unauthorized_completion_actor() -> tuple[str, dict[str, Any], str]:
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-012", stop_after="PARENT_INGESTED")
    builder.append(
        task_id="PO03-FX-012",
        actor=PRODUCER,
        to_state="COMPLETED",
        from_state="PARENT_INGESTED",
        at="2026-08-22T10:20:00Z",
    )
    return (
        builder.text(),
        {},
        "Self-promotion: the producer records COMPLETED for its own unit. Only the coordinator may "
        "record COMPLETED, so the event must be refused even though the lifecycle position and the "
        "durable result commit are both valid.",
    )


def fx_producer_self_acceptance() -> tuple[str, dict[str, Any], str]:
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-013", stop_after="COMPLETED")
    builder.append(
        task_id="PO03-FX-013",
        actor=PRODUCER,
        to_state="ACCEPTED",
        from_state="COMPLETED",
        at="2026-08-22T10:30:00Z",
    )
    return (
        builder.text(),
        {},
        "Self-acceptance: the same producer actor that generated the result records ACCEPTED. A "
        "producer cannot independently accept its own result, so the review event must be refused.",
    )


def fx_file_order_shuffled() -> tuple[str, dict[str, Any], str]:
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-014", stop_after="RESULT_COMMITTED")
    lines = list(builder.lines)
    # A concurrent writer flushed two lines out of order.
    lines[3], lines[6] = lines[6], lines[3]
    return (
        "\n".join(lines) + "\n",
        {},
        "Storage reordering: two lines are persisted out of event_seq order. Ordering by event_seq "
        "must still reconstruct the correct lifecycle while the file-order divergence is reported.",
    )


def fx_committed_artifact_missing() -> tuple[str, dict[str, Any], str]:
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-015", stop_after="RESULT_COMMITTED")
    return (
        builder.text(),
        {},
        "Missing artifact behind a durable commit: the ledger declares a manifest digest for a "
        "committed result, but read-back finds no artifact. Recovery must not treat the commit as "
        "trustworthy; the test supplies an empty artifact root as the probe surface.",
    )


def fx_mixed_fleet() -> tuple[str, dict[str, Any], str]:
    """The realistic scan: many units, several distinct faults, one pass."""
    builder = LedgerBuilder("PO03-FX")
    _lifecycle(builder, "PO03-FX-101", stop_after="ACCEPTED", base_minute=0)
    _lifecycle(builder, "PO03-FX-102", stop_after="RESULT_COMMITTED", base_minute=20)
    _lifecycle(builder, "PO03-FX-103", stop_after="CHECKPOINTED", base_minute=40)
    _lifecycle(
        builder,
        "PO03-FX-104",
        stop_after="RUNNING",
        lease_expires_at="2026-08-22T09:05:00Z",
        base_minute=60,
    )
    _lifecycle(builder, "PO03-FX-105", stop_after="PARENT_INGESTED", base_minute=80)
    _lifecycle(builder, "PO03-FX-106", stop_after="LEASED", base_minute=100)
    # PO03-FX-107: attempt A01 fenced and superseded, A02 committed but not ingested.
    _lifecycle(builder, "PO03-FX-107", attempt="a01", stop_after="RUNNING", base_minute=120)
    builder.append(
        task_id="PO03-FX-107",
        actor=COORDINATOR,
        to_state="FENCED",
        from_state="RUNNING",
        at="2026-08-22T11:10:00Z",
        fence_token=2,
        attempt_id="PO03-FX-107-A01",
        reason="LEASE_EXPIRED_OWNERSHIP_TRANSFERRED",
        stale_fence_token=1,
    )
    builder.append(
        task_id="PO03-FX-107",
        actor=COORDINATOR,
        to_state="SUPERSEDED_BEFORE_DISPATCH",
        from_state="FENCED",
        at="2026-08-22T11:11:00Z",
        fence_token=2,
        attempt_id="PO03-FX-107-A01",
        successor_attempt_id="PO03-FX-107-A02",
    )
    _lifecycle(builder, "PO03-FX-107", attempt="a02", fence=2, stop_after="RESULT_COMMITTED", base_minute=140)
    observations = {
        "PO03-FX-103": {"provider_state": "COMPLETED"},
        "PO03-FX-104": {"provider_state": "UNKNOWN"},
        "PO03-FX-101": {"provider_state": "COMPLETED"},
        "PO03-FX-102": {"provider_state": "COMPLETED"},
    }
    return (
        builder.text(),
        {"fx-16-provider-observations.json": observations},
        "Mixed fleet in one pass: an accepted unit, a committed-not-ingested unit, a "
        "provider-completed-uncommitted unit, an orphaned expired lease, an ingested-not-completed "
        "unit, an undispatched lease, and a task whose first attempt was fenced and superseded "
        "before its second attempt committed without ingestion. Provider observation COMPLETED is "
        "also present on units that do hold durable commits, so the scanner must not let a provider "
        "observation override durable evidence in either direction.",
    )


FIXTURES: list[tuple[str, Any]] = [
    ("fx-01-clean-full-lifecycle.jsonl", fx_clean_full_lifecycle),
    ("fx-02-committed-not-ingested.jsonl", fx_committed_not_ingested),
    ("fx-03-provider-completed-uncommitted.jsonl", fx_provider_completed_uncommitted),
    ("fx-04-false-completion.jsonl", fx_false_completion),
    ("fx-05-stale-lease-commit.jsonl", fx_stale_lease_commit),
    ("fx-06-duplicate-callback.jsonl", fx_duplicate_callback),
    ("fx-07-torn-tail.jsonl", fx_torn_tail),
    ("fx-08-corrupt-interior-line.jsonl", fx_corrupt_interior_line),
    ("fx-09-checkpoint-regression.jsonl", fx_checkpoint_regression),
    ("fx-10-orphaned-lease-expired.jsonl", fx_orphaned_lease_expired),
    ("fx-11-event-id-conflict.jsonl", fx_event_id_conflict),
    ("fx-12-unauthorized-completion-actor.jsonl", fx_unauthorized_completion_actor),
    ("fx-13-producer-self-acceptance.jsonl", fx_producer_self_acceptance),
    ("fx-14-file-order-shuffled.jsonl", fx_file_order_shuffled),
    ("fx-15-committed-artifact-missing.jsonl", fx_committed_artifact_missing),
    ("fx-16-mixed-fleet.jsonl", fx_mixed_fleet),
]


def build(target: Path) -> dict[str, Any]:
    target.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for name, factory in FIXTURES:
        text, sidecars, description = factory()
        raw = text.encode("utf-8")
        (target / name).write_bytes(raw)
        entry = {
            "fixture": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "lines": text.count("\n") + (0 if text.endswith("\n") else 1),
            "newline_terminated": text.endswith("\n"),
            "fault_class": name.split("-", 2)[2].removesuffix(".jsonl"),
            "description": description,
            "sidecars": [],
        }
        for sidecar_name, payload in sorted(sidecars.items()):
            sidecar_raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
            (target / sidecar_name).write_bytes(sidecar_raw)
            entry["sidecars"].append(
                {
                    "file": sidecar_name,
                    "sha256": hashlib.sha256(sidecar_raw).hexdigest(),
                    "bytes": len(sidecar_raw),
                }
            )
        entries.append(entry)

    manifest = {
        "protocol_version": FIXTURE_PROTOCOL,
        "task_id": "PO03-WA-013",
        "attempt_id": "PO03-WA-013-A02",
        "generator": "make_fixtures.py",
        "deterministic": True,
        "regenerate_command": "PYTHONDONTWRITEBYTECODE=1 python3 make_fixtures.py fixtures",
        "sanitization": {
            "policy": "NO_LIVE_IDENTIFIERS_COPIED",
            "task_ids": "synthetic PO03-FX-* namespace",
            "actors": "synthetic fx-coordinator / fx-worker / fx-assurance / fx-harness",
            "provider_run_ids": "derived by SHA-256 over a fixture label",
            "commit_ids": "40-hex derived by SHA-256 over a fixture label; not real git objects",
            "manifest_digests": "64-hex derived by SHA-256 over a fixture label; not real artifacts",
            "secrets_present": False,
            "external_effects": "NONE",
        },
        "fixture_count": len(entries),
        "total_fixture_bytes": sum(entry["bytes"] for entry in entries),
        "fixtures": entries,
    }
    payload = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    (target / "manifest.json").write_bytes(payload)
    return manifest


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent / "fixtures"
    manifest = build(target)
    print(
        f"generated {manifest['fixture_count']} fixtures "
        f"({manifest['total_fixture_bytes']} bytes) in {target}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
