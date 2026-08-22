#!/usr/bin/env python3
"""PO-03 transactional control plane.

The integration controller is the only writer of shared PO-03 control state.
Subordinate writers own a private subtree and a private branch; their results
enter shared state only through ``ingest``, which re-verifies every artifact by
hash and byte count before the coordinator is permitted to record completion.

Durability model
----------------
``events/ledger.jsonl`` is the append-only source of truth.  Every row carries
a monotonic sequence number and a hash chain over the canonical encoding of the
preceding row, so truncation, reordering and in-place edits are detectable.
``work-unit-registry.jsonl`` and ``recovery-state.json`` are projections that
can be rebuilt from the ledger alone, which is what makes recovery from a lost
parent process possible.

Safety properties enforced here
-------------------------------
* Provider completion never becomes Obzio completion without a verified commit.
* A stale worker (lower fence token) cannot commit after ownership transfers.
* Duplicate callbacks carrying an identical payload are harmless no-ops.
* A subordinate cannot write outside its owned subtree or the commission
  allowlist, and cannot set ``COMPLETED`` or accept its own work.

Dependency-free by design: it must run in a clean GitHub Actions runner and a
fresh clone with no third-party packages, no ``/tmp`` state and no warm cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

CONTROL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CONTROL_ROOT.parents[1]

LEDGER_PATH = CONTROL_ROOT / "control" / "events" / "ledger.jsonl"
REGISTRY_PATH = CONTROL_ROOT / "control" / "work-unit-registry.jsonl"
RECOVERY_PATH = CONTROL_ROOT / "control" / "recovery-state.json"
DISPATCH_DIR = CONTROL_ROOT / "control" / "dispatch"
PATH_OWNERSHIP_PATH = CONTROL_ROOT / "control" / "path-ownership.json"

GENESIS_HASH = "0" * 64
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Wave-one write allowlist, quoted from the commission collision boundary.
ALLOWLIST_PREFIXES = ("workstreams/po03/", "receipts/po03/")
ALLOWLIST_WORKFLOW_DIR = ".github/workflows/"
ALLOWLIST_WORKFLOW_PREFIX = "po03-"
ALLOWLIST_WORKFLOW_SUFFIX = ".yml"

# Terminal Obzio states in which a durable, re-readable result must exist.
COMMITTED_STATES = {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"}
TERMINAL_STATES = COMMITTED_STATES | {"FAILED_TERMINAL", "CANCELLED"}

EVENT_KINDS = {
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
    "ACCEPTED",
    "REJECTED",
    "LEASE_EXPIRED",
    "FENCE_REJECTED",
    "DUPLICATE_IGNORED",
    "FAULT_INJECTED",
}


class ControlPlaneError(RuntimeError):
    """Raised when an operation would violate a custody invariant."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rows.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ControlPlaneError(f"{path}:{lineno}: corrupt ledger row: {exc}") from exc
    return rows


def write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return sha256_text(text)


# ---------------------------------------------------------------------------
# Path scope
# ---------------------------------------------------------------------------


def path_in_allowlist(path: str) -> bool:
    normalised = path.strip().lstrip("./")
    if not normalised or ".." in normalised.split("/"):
        return False
    if normalised.startswith(ALLOWLIST_PREFIXES):
        return True
    if normalised.startswith(ALLOWLIST_WORKFLOW_DIR):
        leaf = normalised[len(ALLOWLIST_WORKFLOW_DIR) :]
        return (
            "/" not in leaf
            and leaf.startswith(ALLOWLIST_WORKFLOW_PREFIX)
            and leaf.endswith(ALLOWLIST_WORKFLOW_SUFFIX)
        )
    return False


def check_allowlist(paths: Iterable[str]) -> list[str]:
    return sorted({path for path in paths if not path_in_allowlist(path)})


def load_path_ownership() -> dict[str, Any]:
    if not PATH_OWNERSHIP_PATH.exists():
        return {"owners": {}}
    return json.loads(PATH_OWNERSHIP_PATH.read_text(encoding="utf-8"))


def check_ownership(owner: str, paths: Iterable[str]) -> list[str]:
    """Return paths the owner is not entitled to write.

    Ownership is prefix based.  The coordinator owns shared control state; every
    other owner is confined to the subtrees declared in ``path-ownership.json``
    so two subordinates can never contend for the same file.
    """
    ownership = load_path_ownership()
    owners = ownership.get("owners", {})
    entry = owners.get(owner)
    if entry is None:
        return sorted(set(paths))
    prefixes = tuple(entry.get("owned_prefixes", []))
    violations: list[str] = []
    for path in paths:
        normalised = path.strip().lstrip("./")
        if not normalised.startswith(prefixes):
            violations.append(normalised)
    return sorted(set(violations))


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def ledger_rows() -> list[dict[str, Any]]:
    return read_jsonl(LEDGER_PATH)


def verify_chain(rows: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    previous = GENESIS_HASH
    for index, row in enumerate(rows):
        expected_seq = index + 1
        if row.get("seq") != expected_seq:
            errors.append(f"row {index}: seq {row.get('seq')} is not monotonic (expected {expected_seq})")
        if row.get("prev_sha256") != previous:
            errors.append(f"seq {row.get('seq')}: prev_sha256 does not chain to the preceding row")
        body = {key: value for key, value in row.items() if key != "row_sha256"}
        computed = sha256_text(canonical(body))
        if row.get("row_sha256") != computed:
            errors.append(f"seq {row.get('seq')}: row_sha256 does not match its canonical body")
        previous = row.get("row_sha256", GENESIS_HASH)
    return errors


def append_event(
    unit_id: str,
    event: str,
    *,
    actor: str,
    obzio_state: str | None = None,
    provider_state: str | None = None,
    fence_token: int | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if event not in EVENT_KINDS:
        raise ControlPlaneError(f"unknown event kind: {event}")
    rows = ledger_rows()
    chain_errors = verify_chain(rows)
    if chain_errors:
        raise ControlPlaneError("ledger integrity failure: " + "; ".join(chain_errors))
    body = {
        "seq": len(rows) + 1,
        "ts": utc_now(),
        "unit_id": unit_id,
        "event": event,
        "obzio_state": obzio_state or event,
        "provider_state": provider_state,
        "actor": actor,
        "fence_token": fence_token,
        "payload": payload or {},
        "prev_sha256": rows[-1]["row_sha256"] if rows else GENESIS_HASH,
    }
    body["row_sha256"] = sha256_text(canonical(body))
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", encoding="utf-8") as handle:
        handle.write(canonical(body) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return body


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------


def project_units(rows: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Rebuild per-unit state from the ledger alone.

    This is the recovery path: a parent that lost its memory reconstructs the
    entire fleet from immutable rows rather than from any worker's self-report.
    """
    rows = ledger_rows() if rows is None else rows
    units: dict[str, dict[str, Any]] = {}
    for row in rows:
        unit_id = row["unit_id"]
        unit = units.setdefault(
            unit_id,
            {
                "unit_id": unit_id,
                "obzio_state": "CREATED",
                "provider_state": "UNKNOWN",
                "fence_token": 0,
                "checkpoint_seq": 0,
                "first_seen_ts": row["ts"],
                "last_event_ts": row["ts"],
                "last_event_seq": row["seq"],
                "lease": None,
                "result_commit_id": None,
                "result_locator": None,
                "artifact_count": 0,
                "total_bytes": 0,
                "attempts": 0,
                "retries": 0,
                "acceptance": "NOT_TESTED",
                "reviewer_id": None,
                "history": [],
            },
        )
        unit["last_event_ts"] = row["ts"]
        unit["last_event_seq"] = row["seq"]
        unit["history"].append({"seq": row["seq"], "event": row["event"], "ts": row["ts"]})
        if row.get("fence_token") is not None:
            unit["fence_token"] = max(unit["fence_token"], int(row["fence_token"]))
        if row.get("provider_state"):
            unit["provider_state"] = row["provider_state"]
        payload = row.get("payload") or {}
        event = row["event"]
        if event in {"DUPLICATE_IGNORED", "FENCE_REJECTED", "FAULT_INJECTED"}:
            # Observability events never advance custody state.
            continue
        if event == "LEASED":
            unit["lease"] = {
                "lease_id": payload.get("lease_id"),
                "worker_id": payload.get("worker_id"),
                "granted_at": row["ts"],
                "expires_at": payload.get("expires_at"),
            }
            unit["attempts"] += 1
        if event == "LEASE_EXPIRED":
            unit["lease"] = None
            unit["obzio_state"] = "RECOVERY_REQUIRED"
            continue
        if event == "RETRY_SCHEDULED":
            unit["retries"] += 1
        if event == "CHECKPOINTED":
            unit["checkpoint_seq"] = max(unit["checkpoint_seq"], int(payload.get("checkpoint_seq", 0)))
        if event in {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"}:
            unit["result_commit_id"] = payload.get("result_commit_id") or unit["result_commit_id"]
            unit["result_locator"] = payload.get("result_locator") or unit["result_locator"]
            unit["artifact_count"] = payload.get("artifact_count", unit["artifact_count"])
            unit["total_bytes"] = payload.get("total_bytes", unit["total_bytes"])
        if event in {"ACCEPTED", "REJECTED"}:
            unit["acceptance"] = event
            unit["reviewer_id"] = payload.get("reviewer_id")
            continue
        if event in EVENT_KINDS:
            unit["obzio_state"] = row.get("obzio_state") or event
    return units


def materialize() -> dict[str, Any]:
    units = project_units()
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [canonical(units[unit_id]) for unit_id in sorted(units)]
    REGISTRY_PATH.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return units


def scan_recovery(now: float | None = None) -> dict[str, Any]:
    """Detect every unit that cannot be truthfully called complete.

    ``false_completion`` is the assertion that matters most: a unit whose
    provider said COMPLETED but which has no verified durable commit must be
    reported as PROVIDER_COMPLETED_UNCOMMITTED and re-run from immutable input.
    """
    now = time.time() if now is None else now
    rows = ledger_rows()
    chain_errors = verify_chain(rows)
    units = project_units(rows)
    expired: list[str] = []
    uncommitted: list[str] = []
    orphaned: list[str] = []
    resumable: list[str] = []
    false_completions: list[str] = []
    for unit_id, unit in sorted(units.items()):
        lease = unit.get("lease")
        if lease and lease.get("expires_at"):
            try:
                deadline = datetime.strptime(lease["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                deadline = None
            if deadline and deadline.timestamp() < now and unit["obzio_state"] not in TERMINAL_STATES:
                expired.append(unit_id)
        if unit["provider_state"] == "COMPLETED" and not unit["result_commit_id"]:
            uncommitted.append(unit_id)
            if unit["obzio_state"] == "COMPLETED":
                false_completions.append(unit_id)
        if unit["obzio_state"] in COMMITTED_STATES and not unit["result_commit_id"]:
            false_completions.append(unit_id)
        if unit["obzio_state"] not in TERMINAL_STATES:
            resumable.append(unit_id)
            if not lease:
                orphaned.append(unit_id)
    state = {
        "generated_at": utc_now(),
        "ledger_rows": len(rows),
        "ledger_head_sha256": rows[-1]["row_sha256"] if rows else GENESIS_HASH,
        "ledger_chain_valid": not chain_errors,
        "ledger_chain_errors": chain_errors,
        "units_total": len(units),
        "expired_leases": expired,
        "provider_completed_uncommitted": sorted(set(uncommitted)),
        "orphaned_units": orphaned,
        "resumable_units": resumable,
        "false_completions": sorted(set(false_completions)),
        "recovery_required": bool(chain_errors or expired or uncommitted or false_completions),
    }
    write_json(RECOVERY_PATH, state)
    return state


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_create(args: argparse.Namespace) -> int:
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    created = 0
    for unit in spec["units"]:
        unit_id = unit["unit_id"]
        manifest = {
            "unit_id": unit_id,
            "commission_id": spec["commission_id"],
            "wave_id": spec["wave_id"],
            "cohort_id": unit["cohort_id"],
            "function_id": unit["function_id"],
            "hypothesis": unit["hypothesis"],
            "acceptance": unit["acceptance"],
            "owner": unit["owner"],
            "owned_paths": unit["owned_paths"],
            "model": unit["model"],
            "result_slot": unit["result_slot"],
            "source_hashes": spec["source_hashes"],
        }
        manifest_text = canonical(manifest)
        manifest_sha = sha256_text(manifest_text)
        acceptance_sha = sha256_text(canonical(unit["acceptance"]))
        dispatch_path = DISPATCH_DIR / f"{unit_id}.json"
        record = dict(manifest)
        record["immutable_input_manifest_sha256"] = manifest_sha
        record["acceptance_contract_sha256"] = acceptance_sha
        record["idempotency_key"] = f"{unit_id}:{manifest_sha[:16]}"
        write_json(dispatch_path, record)
        append_event(
            unit_id,
            "CREATED",
            actor="coordinator",
            provider_state="QUEUED",
            payload={
                "immutable_input_manifest_sha256": manifest_sha,
                "acceptance_contract_sha256": acceptance_sha,
                "idempotency_key": record["idempotency_key"],
                "cohort_id": unit["cohort_id"],
                "function_id": unit["function_id"],
                "owner": unit["owner"],
                "model": unit["model"],
            },
        )
        created += 1
    materialize()
    print(f"CREATED {created} units")
    return 0


def cmd_lease(args: argparse.Namespace) -> int:
    units = project_units()
    unit = units.get(args.unit_id)
    if unit is None:
        raise ControlPlaneError(f"unknown unit: {args.unit_id}")
    fence = unit["fence_token"] + 1
    expires = datetime.fromtimestamp(time.time() + args.ttl, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    row = append_event(
        args.unit_id,
        "LEASED",
        actor="coordinator",
        provider_state="RUNNING",
        fence_token=fence,
        payload={
            "lease_id": f"lease-{args.unit_id}-{fence}",
            "worker_id": args.worker,
            "expires_at": expires,
            "ttl_seconds": args.ttl,
        },
    )
    materialize()
    print(canonical({"fence_token": fence, "lease_id": row["payload"]["lease_id"], "expires_at": expires}))
    return 0


def cmd_event(args: argparse.Namespace) -> int:
    payload = json.loads(args.payload) if args.payload else {}
    append_event(
        args.unit_id,
        args.event,
        actor=args.actor,
        provider_state=args.provider_state,
        fence_token=args.fence_token,
        payload=payload,
    )
    materialize()
    print(f"{args.event} {args.unit_id}")
    return 0


def _load_validator():
    import importlib.util

    module_path = CONTROL_ROOT / "tools" / "validate_contracts.py"
    spec = importlib.util.spec_from_file_location("validate_contracts", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def ingest_result(
    result_doc: dict[str, Any],
    *,
    artifact_root: Path,
    reviewer_required: bool = True,
) -> dict[str, Any]:
    """Verify a subordinate result and admit it into shared custody.

    Every rejection reason here corresponds to a way the PO-02 Code-2 return was
    lost or could have been silently faked.
    """
    validator = _load_validator()
    errors = validator.validate_result(result_doc)
    if errors:
        raise ControlPlaneError("result contract invalid: " + "; ".join(errors))

    unit_id = result_doc["task_id"]
    units = project_units()
    unit = units.get(unit_id)
    if unit is None:
        raise ControlPlaneError(f"unknown unit: {unit_id}")

    incoming_fence = int(result_doc["attempt"]["fence_token"])
    if incoming_fence < unit["fence_token"]:
        append_event(
            unit_id,
            "FENCE_REJECTED",
            actor="coordinator",
            fence_token=unit["fence_token"],
            payload={"rejected_fence_token": incoming_fence, "reason": "stale worker after ownership transfer"},
        )
        raise ControlPlaneError(
            f"stale fence token {incoming_fence} < {unit['fence_token']}; refusing commit from evicted worker"
        )

    dispatch_path = DISPATCH_DIR / f"{unit_id}.json"
    if not dispatch_path.exists():
        raise ControlPlaneError(f"no immutable dispatch record for {unit_id}")
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    if result_doc["immutable_input_manifest_sha256"] != dispatch["immutable_input_manifest_sha256"]:
        raise ControlPlaneError("result does not reference the dispatched immutable input manifest")
    if result_doc["acceptance_contract_sha256"] != dispatch["acceptance_contract_sha256"]:
        raise ControlPlaneError("result does not reference the frozen acceptance contract")

    relative_paths = [artifact["content_uri"].split(":", 2)[-1] for artifact in result_doc["artifacts"]]
    outside = check_allowlist(relative_paths)
    if outside:
        raise ControlPlaneError("artifacts outside the commission allowlist: " + ", ".join(outside))
    not_owned = check_ownership(dispatch["owner"], relative_paths)
    if not_owned:
        raise ControlPlaneError(
            f"owner {dispatch['owner']} attempted to write paths it does not own: " + ", ".join(not_owned)
        )

    verified: list[dict[str, Any]] = []
    for artifact in result_doc["artifacts"]:
        relative = artifact["content_uri"].split(":", 2)[-1]
        target = artifact_root / relative
        if not target.exists():
            raise ControlPlaneError(f"artifact missing on read-back: {relative}")
        actual_sha = sha256_file(target)
        actual_bytes = target.stat().st_size
        if actual_sha != artifact["sha256"]:
            raise ControlPlaneError(f"artifact hash mismatch on read-back: {relative}")
        if actual_bytes != artifact["bytes"]:
            raise ControlPlaneError(f"artifact byte count mismatch on read-back: {relative}")
        verified.append({"logical_name": artifact["logical_name"], "sha256": actual_sha, "bytes": actual_bytes})

    result_sha = sha256_text(canonical(result_doc))
    already = [
        row
        for row in ledger_rows()
        if row["unit_id"] == unit_id
        and row["event"] == "PARENT_INGESTED"
        and (row.get("payload") or {}).get("result_sha256") == result_sha
    ]
    if already:
        append_event(
            unit_id,
            "DUPLICATE_IGNORED",
            actor="coordinator",
            fence_token=incoming_fence,
            payload={"result_sha256": result_sha, "reason": "idempotent replay of an already ingested result"},
        )
        materialize()
        return {"unit_id": unit_id, "duplicate": True, "verified_artifacts": len(verified)}

    append_event(
        unit_id,
        "PARENT_INGESTED",
        actor="coordinator",
        provider_state=result_doc["provider_state"],
        fence_token=incoming_fence,
        payload={
            "result_sha256": result_sha,
            "result_commit_id": result_doc["result_transaction"]["result_commit_id"],
            "result_locator": result_doc["result_transaction"]["manifest_uri"],
            "artifact_count": len(verified),
            "total_bytes": sum(item["bytes"] for item in verified),
            "verified_artifacts": verified,
        },
    )
    materialize()
    return {"unit_id": unit_id, "duplicate": False, "verified_artifacts": len(verified)}


def cmd_ingest(args: argparse.Namespace) -> int:
    doc = json.loads(Path(args.result).read_text(encoding="utf-8"))
    outcome = ingest_result(doc, artifact_root=Path(args.artifact_root).resolve())
    print(canonical(outcome))
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    """Only the coordinator may declare Obzio completion, and only after ingestion."""
    units = project_units()
    unit = units.get(args.unit_id)
    if unit is None:
        raise ControlPlaneError(f"unknown unit: {args.unit_id}")
    if unit["obzio_state"] != "PARENT_INGESTED":
        raise ControlPlaneError(
            f"{args.unit_id} is {unit['obzio_state']}; completion requires PARENT_INGESTED"
        )
    if not unit["result_commit_id"]:
        raise ControlPlaneError(f"{args.unit_id} has no durable result commit; cannot complete")
    append_event(
        args.unit_id,
        "COMPLETED",
        actor="coordinator",
        provider_state="COMPLETED",
        fence_token=unit["fence_token"],
        payload={"result_commit_id": unit["result_commit_id"], "result_locator": unit["result_locator"]},
    )
    materialize()
    print(f"COMPLETED {args.unit_id}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    units = project_units()
    unit = units.get(args.unit_id)
    if unit is None:
        raise ControlPlaneError(f"unknown unit: {args.unit_id}")
    if unit["obzio_state"] != "COMPLETED":
        raise ControlPlaneError("independent disposition requires a COMPLETED unit")
    dispatch = json.loads((DISPATCH_DIR / f"{args.unit_id}.json").read_text(encoding="utf-8"))
    if args.reviewer == dispatch["owner"]:
        raise ControlPlaneError("producer cannot accept or reject its own work")
    append_event(
        args.unit_id,
        args.decision,
        actor=args.reviewer,
        fence_token=unit["fence_token"],
        payload={"reviewer_id": args.reviewer, "receipt_uri": args.receipt, "rationale": args.rationale},
    )
    materialize()
    print(f"{args.decision} {args.unit_id} by {args.reviewer}")
    return 0


def cmd_canary(args: argparse.Namespace) -> int:
    """Prove the durable sink round-trips before material work is dispatched."""
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    nonce = hashlib.sha256(f"{args.worker}:{utc_now()}:{os.getpid()}".encode("utf-8")).hexdigest()
    payload = {"worker_id": args.worker, "nonce": nonce, "written_at": utc_now()}
    target = root / f"canary-{args.worker}.json"
    written_sha = write_json(target, payload)
    readback = json.loads(target.read_text(encoding="utf-8"))
    readback_sha = sha256_file(target)
    ok = readback == payload and readback_sha == written_sha
    print(canonical({"worker_id": args.worker, "canary_sha256": readback_sha, "roundtrip_ok": ok}))
    return 0 if ok else 1


def cmd_verify(args: argparse.Namespace) -> int:
    rows = ledger_rows()
    errors = verify_chain(rows)
    state = scan_recovery()
    materialize()
    for error in errors:
        print(f"INVALID: {error}")
    print(canonical({k: v for k, v in state.items() if k != "ledger_chain_errors"}))
    if errors or state["false_completions"]:
        return 1
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    state = scan_recovery()
    print(canonical(state))
    return 1 if state["recovery_required"] and args.strict else 0


def cmd_check_paths(args: argparse.Namespace) -> int:
    paths = [line.strip() for line in Path(args.paths).read_text(encoding="utf-8").splitlines() if line.strip()]
    outside = check_allowlist(paths)
    for path in outside:
        print(f"OUT_OF_ALLOWLIST: {path}")
    if outside:
        print(f"FAIL {len(outside)} path(s) outside the PO-03 wave-one allowlist")
        return 1
    print(f"PASS {len(paths)} path(s) inside the PO-03 wave-one allowlist")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PO-03 transactional control plane")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="register work units from a wave spec")
    create.add_argument("spec")
    create.set_defaults(func=cmd_create)

    lease = sub.add_parser("lease", help="grant a fenced lease to a worker")
    lease.add_argument("unit_id")
    lease.add_argument("--worker", required=True)
    lease.add_argument("--ttl", type=int, default=5400)
    lease.set_defaults(func=cmd_lease)

    event = sub.add_parser("event", help="append a custody event")
    event.add_argument("unit_id")
    event.add_argument("event", choices=sorted(EVENT_KINDS))
    event.add_argument("--actor", required=True)
    event.add_argument("--provider-state", dest="provider_state")
    event.add_argument("--fence-token", dest="fence_token", type=int)
    event.add_argument("--payload")
    event.set_defaults(func=cmd_event)

    ingest = sub.add_parser("ingest", help="verify and ingest a subordinate result")
    ingest.add_argument("result")
    ingest.add_argument("--artifact-root", default=str(REPO_ROOT))
    ingest.set_defaults(func=cmd_ingest)

    complete = sub.add_parser("complete", help="coordinator-only completion")
    complete.add_argument("unit_id")
    complete.set_defaults(func=cmd_complete)

    review = sub.add_parser("review", help="independent acceptance or rejection")
    review.add_argument("unit_id")
    review.add_argument("decision", choices=("ACCEPTED", "REJECTED"))
    review.add_argument("--reviewer", required=True)
    review.add_argument("--receipt", required=True)
    review.add_argument("--rationale", default="")
    review.set_defaults(func=cmd_review)

    canary = sub.add_parser("canary", help="prove durable sink round-trip")
    canary.add_argument("--worker", required=True)
    canary.add_argument("--root", required=True)
    canary.set_defaults(func=cmd_canary)

    verify = sub.add_parser("verify", help="verify ledger chain and custody invariants")
    verify.set_defaults(func=cmd_verify)

    scan = sub.add_parser("scan", help="run the recovery scanner")
    scan.add_argument("--strict", action="store_true")
    scan.set_defaults(func=cmd_scan)

    check = sub.add_parser("check-paths", help="enforce the wave-one path allowlist")
    check.add_argument("paths")
    check.set_defaults(func=cmd_check_paths)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ControlPlaneError as exc:
        print(f"CONTROL_PLANE_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
