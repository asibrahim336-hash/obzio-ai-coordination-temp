#!/usr/bin/env python3
"""G1: the PO-03 transactional factory, packaged to run from its own entry point.

Why this is a port rather than an import
----------------------------------------
``workstreams/po03/tools/control_plane.py`` binds its ledger, registry, dispatch
and recovery paths to module-level constants under the live
``workstreams/po03/control/`` directory, which is coordinator-owned shared
state.  Importing it would make the generation unable to run from a clean clone
without that directory, and scoring it would write into another owner's files.
So G1 is re-rooted: identical algorithms, identical row schema, identical hash
chain, with every path taken from a constructor argument.

What "fidelity" means here: fidelity to a pin
--------------------------------------------
This port replicates the factory **as of commit dd2fcc6**, the commit recorded
in ``packaging.json`` under ``packaged_from.source_commit``.  It does not track
HEAD and is not meant to: G1 is one endpoint of a measured lift, and an endpoint
that moves with the live tree is not something a score can be attached to.  When
the coordinator later changes ``control_plane.py``, this file stays as it is and
the difference is recorded in ``packaging.json`` under
``divergence_from_head_after_the_pin`` rather than silently absorbed.

Fidelity is tested, not asserted.  ``tests/test_a8_g1_fidelity.py`` materialises
the factory and its validator from git at that pin, verifies them against the
digests recorded in ``packaging.json``, loads them read-only into a scratch
mirror of the tree, and asserts that this port and the pinned factory produce
the same canonical ledger rows, the same chain verdicts and the same admit/reject
decisions with the same grounds.  Two deliberate differences are recorded there:

1. Time comes from an injectable clock instead of ``time.time()``, because a
   lease-expiry score that depends on wall clock is not reproducible.
2. The harness observes admission at ``submit``.  In the live factory the same
   checks are split between ``make_result.py`` (worker side: artifact existence
   and digests) and ``ingest_result`` (parent side: contract, fence, allowlist,
   ownership, read-back).  The custody guarantee is the same - a result that
   fails any check never enters custody - so the port adjudicates once and the
   fidelity test compares decisions rather than call sites.

Gaps preserved on purpose
-------------------------
This file is a measurement instrument, so it must not be quietly better than
the factory it represents.  The following are real properties of the live
factory at ``dd2fcc6`` and are preserved exactly:

* ``ingest_result`` never re-derives the dispatch record's own manifest digest,
  so an edit to dispatched immutable input is not detected;
* ``cmd_complete`` labels the actor ``"coordinator"`` unconditionally, so
  completion authority is a naming convention and not an authorisation check;
* the fence check is ``incoming < current``, so a fence token that was never
  granted is accepted for being larger;
* lease expiry is reported by the recovery scanner but never enforced at commit;
* artifacts are hashed once at ingestion and never re-verified afterwards;
* duplicate detection matches on the result digest, so a replay under the same
  idempotency key carrying different content is ingested a second time;
* ``verify_chain`` validates links between the rows that remain, so losing the
  tail of the ledger leaves a self-consistent chain;
* ``RESULT_COMMITTED`` is a terminal state for the recovery scanner and there is
  no outbox, so a result that was committed but never ingested is neither
  replayed nor re-run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..harness.controller_api import (
    Clock,
    Controller,
    Outcome,
    canonical,
    ok,
    refuse,
    sha256_bytes,
    sha256_text,
)
from ..harness.generation_support import GenerationSupport

PROVENANCE = (
    "port of workstreams/po03/tools/control_plane.py and tools/make_result.py at branch "
    "cursor/po03-wave-a-transactional-factory-ed20 commit dd2fcc6, re-rooted for standalone execution"
)

GENESIS_HASH = "0" * 64

COMMITTED_STATES = {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"}
TERMINAL_STATES = COMMITTED_STATES | {"FAILED_TERMINAL", "CANCELLED"}

ALLOWLIST_PREFIXES = ("workstreams/po03/", "receipts/po03/")
ALLOWLIST_WORKFLOW_DIR = ".github/workflows/"
ALLOWLIST_WORKFLOW_PREFIX = "po03-"
ALLOWLIST_WORKFLOW_SUFFIX = ".yml"


def path_in_allowlist(path: str) -> bool:
    """Verbatim semantics of ``control_plane.path_in_allowlist`` at ``dd2fcc6``.

    ``lstrip("./")`` strips leading ``.`` and ``/`` *characters*, not a leading
    ``./`` segment, so ``.github/...`` loses its dot and falls out of the
    workflow branch below.  That is what the factory did at the pin, and copying
    it is the point: a port that quietly fixed it would manufacture lift for G2.
    The live plane was corrected after the pin; see
    ``packaging.json`` -> ``divergence_from_head_after_the_pin``.
    """
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


def check_allowlist(paths: list[str]) -> list[str]:
    return sorted({path for path in paths if not path_in_allowlist(path)})


def check_ownership(prefixes: tuple[str, ...], paths: list[str]) -> list[str]:
    """Semantics of ``control_plane.check_ownership`` at ``dd2fcc6``: prefix match only."""
    violations = [path.strip().lstrip("./") for path in paths if not path.strip().lstrip("./").startswith(prefixes)]
    return sorted(set(violations))


def verify_chain(rows: list[dict[str, Any]]) -> list[str]:
    """Verbatim semantics of ``control_plane.verify_chain``.

    Note what is and is not covered: each row is checked against its declared
    sequence number and its predecessor's digest.  Nothing anchors the *end* of
    the log, which is the gap case P29 measures.
    """
    errors: list[str] = []
    previous = GENESIS_HASH
    for index, row in enumerate(rows):
        expected_seq = index + 1
        if row.get("seq") != expected_seq:
            errors.append(f"row {index}: seq {row.get('seq')} is not monotonic (expected {expected_seq})")
        if row.get("prev_sha256") != previous:
            errors.append(f"seq {row.get('seq')}: prev_sha256 does not chain to the preceding row")
        body = {key: value for key, value in row.items() if key != "row_sha256"}
        if row.get("row_sha256") != sha256_text(canonical(body)):
            errors.append(f"seq {row.get('seq')}: row_sha256 does not match its canonical body")
        previous = row.get("row_sha256", GENESIS_HASH)
    return errors


class Ledger:
    """Append-only, hash-chained event log with the live factory's row schema."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
        return rows

    def append(
        self,
        unit_id: str,
        event: str,
        *,
        actor: str,
        ts: str,
        provider_state: str | None = None,
        fence_token: int | None = None,
        payload: dict[str, Any] | None = None,
        obzio_state: str | None = None,
    ) -> dict[str, Any]:
        rows = self.rows()
        body = {
            "seq": len(rows) + 1,
            "ts": ts,
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
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(canonical(body) + "\n")
        return body

    def overwrite(self, rows: list[dict[str, Any]]) -> None:
        """Used only by fault injection, which models an attacker or a bad disk."""
        self.path.write_text("".join(canonical(row) + "\n" for row in rows), encoding="utf-8")


def project_units(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Verbatim semantics of ``control_plane.project_units``."""
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
                "lease": None,
                "result_commit_id": None,
                "result_locator": None,
                "artifact_count": 0,
                "total_bytes": 0,
                "acceptance": "NOT_TESTED",
                "reviewer_id": None,
                "ingest_count": 0,
            },
        )
        if row.get("fence_token") is not None:
            unit["fence_token"] = max(unit["fence_token"], int(row["fence_token"]))
        if row.get("provider_state"):
            unit["provider_state"] = row["provider_state"]
        payload = row.get("payload") or {}
        event = row["event"]
        if event in {"DUPLICATE_IGNORED", "FENCE_REJECTED", "FAULT_INJECTED"}:
            continue
        if event == "LEASED":
            unit["lease"] = {
                "lease_id": payload.get("lease_id"),
                "worker_id": payload.get("worker_id"),
                "expires_at": payload.get("expires_at"),
            }
        if event == "LEASE_EXPIRED":
            unit["lease"] = None
            unit["obzio_state"] = "RECOVERY_REQUIRED"
            continue
        if event in {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"}:
            unit["result_commit_id"] = payload.get("result_commit_id") or unit["result_commit_id"]
            unit["result_locator"] = payload.get("result_locator") or unit["result_locator"]
            unit["artifact_count"] = payload.get("artifact_count", unit["artifact_count"])
            unit["total_bytes"] = payload.get("total_bytes", unit["total_bytes"])
        if event == "PARENT_INGESTED":
            unit["ingest_count"] += 1
        if event in {"ACCEPTED", "REJECTED"}:
            unit["acceptance"] = event
            unit["reviewer_id"] = payload.get("reviewer_id")
            continue
        unit["obzio_state"] = row.get("obzio_state") or event
    return units


class G1Controller(Controller, GenerationSupport):
    """The transactional factory, re-rooted and adapted to the scoring contract."""

    generation_id = "G1"
    generation_label = "high-scale transactional factory"
    provenance = PROVENANCE

    def __init__(self, root: Path, clock: Clock) -> None:
        super().__init__(Path(root), clock)
        self.control = Path(root) / "control"
        self.dispatch_dir = self.control / "dispatch"
        self.dispatch_dir.mkdir(parents=True, exist_ok=True)
        self.result_dir = self.control / "results"
        self.result_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.control / "events" / "ledger.jsonl")

    # -- helpers -----------------------------------------------------------

    def _units(self) -> dict[str, dict[str, Any]]:
        return project_units(self.ledger.rows())

    def _dispatch(self, unit_id: str) -> dict[str, Any] | None:
        path = self.dispatch_dir / f"{unit_id}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _result_path(self, unit_id: str) -> Path:
        return self.result_dir / f"{unit_id}.json"

    def _deadline(self, expires_at: str | None) -> float | None:
        if not expires_at:
            return None
        try:
            return (
                datetime.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ")
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
        except ValueError:
            return None

    # -- operations --------------------------------------------------------

    def op_create(self, *, unit_id: str, spec: dict[str, Any] | None = None, **_: Any) -> Outcome:
        """``cmd_create``: write the immutable input manifest and register the unit."""
        spec = dict(spec or {})
        manifest = {
            "unit_id": unit_id,
            "owner": spec.get("owner"),
            "owned_prefixes": spec.get("owned_prefixes", []),
            "acceptance": spec.get("acceptance", {}),
            "source_hashes": spec.get("pinned_inputs", {}),
        }
        manifest_sha = sha256_text(canonical(manifest))
        acceptance_sha = sha256_text(canonical(spec.get("acceptance", {})))
        record = dict(manifest)
        record["immutable_input_manifest_sha256"] = manifest_sha
        record["acceptance_contract_sha256"] = acceptance_sha
        record["idempotency_key"] = f"{unit_id}:{manifest_sha[:16]}"
        (self.dispatch_dir / f"{unit_id}.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.ledger.append(
            unit_id,
            "CREATED",
            actor="coordinator",
            ts=self.clock.iso(),
            provider_state="QUEUED",
            payload={
                "immutable_input_manifest_sha256": manifest_sha,
                "acceptance_contract_sha256": acceptance_sha,
                "idempotency_key": record["idempotency_key"],
            },
        )
        return ok(
            unit_id=unit_id,
            input_manifest_sha256=manifest_sha,
            acceptance_contract_sha256=acceptance_sha,
            idempotency_key=record["idempotency_key"],
        )

    def op_lease(self, *, unit_id: str, worker: str, ttl: int = 5400, **_: Any) -> Outcome:
        """``cmd_lease``: monotonic fence token plus an expiry deadline."""
        units = self._units()
        if unit_id not in units:
            return refuse("UNKNOWN_UNIT", unit_id=unit_id)
        fence = units[unit_id]["fence_token"] + 1
        expires_at = self.clock.iso(offset=ttl)
        self.ledger.append(
            unit_id,
            "LEASED",
            actor="coordinator",
            ts=self.clock.iso(),
            provider_state="RUNNING",
            fence_token=fence,
            payload={
                "lease_id": f"lease-{unit_id}-{fence}",
                "worker_id": worker,
                "expires_at": expires_at,
                "ttl_seconds": ttl,
            },
        )
        return ok(unit_id=unit_id, fence_token=fence, lease_id=f"lease-{unit_id}-{fence}", expires_at=expires_at)

    def op_submit(
        self,
        *,
        unit_id: str,
        worker: str,
        fence_token: int = 1,
        provider_state: str = "COMPLETED",
        claimed_state: str = "RESULT_COMMITTED",
        artifacts: list[dict[str, Any]] | None = None,
        accounting: dict[str, Any] | None = None,
        result_commit_id: str | None = None,
        readback_verified: bool = True,
        idempotency_key: str | None = None,
        **_: Any,
    ) -> Outcome:
        """``make_result.py`` plus ``ingest_result`` verification, adjudicated once."""
        units = self._units()
        unit = units.get(unit_id)
        dispatch = self._dispatch(unit_id)
        if unit is None or dispatch is None:
            return refuse("UNKNOWN_UNIT", unit_id=unit_id)

        # Fence: the live check rejects strictly-lower tokens only.  A token that
        # was never granted passes, which is the gap case P13 measures.
        if fence_token < unit["fence_token"]:
            self.ledger.append(
                unit_id,
                "FENCE_REJECTED",
                actor="coordinator",
                ts=self.clock.iso(),
                fence_token=unit["fence_token"],
                payload={"rejected_fence_token": fence_token},
            )
            return refuse("STALE_FENCE", current_fence_token=unit["fence_token"], offered=fence_token)

        # Lease expiry is deliberately not checked here: the live factory only
        # reports it from the recovery scanner.  Gap case P14.

        claimed = self.resolve_claims(list(artifacts or []))
        derived_bytes = sum(int(entry.get("bytes") or 0) for entry in claimed)
        accounting = dict(accounting or {"artifact_count": len(claimed), "total_bytes": derived_bytes})

        # validate_result: provider completion without a durable commit.
        if provider_state == "COMPLETED" and not result_commit_id:
            self.ledger.append(
                unit_id,
                "PROVIDER_COMPLETED_UNCOMMITTED",
                actor="coordinator",
                ts=self.clock.iso(),
                provider_state=provider_state,
                fence_token=fence_token,
                payload={"reason": "no durable result commit"},
            )
            return refuse("NO_RESULT_COMMIT", unit_id=unit_id, claimed_state=claimed_state)

        if claimed_state in COMMITTED_STATES and not readback_verified:
            return refuse("READBACK_MISSING", unit_id=unit_id)
        if claimed_state in COMMITTED_STATES and not claimed:
            return refuse("ACCOUNTING_MISMATCH", reason="committed result requires at least one artifact")

        seen: set[str] = set()
        for entry in claimed:
            identifier = entry.get("artifact_id")
            if identifier in seen:
                return refuse("DUPLICATE_ARTIFACT_ID", artifact_id=identifier)
            seen.add(identifier)

        if accounting.get("artifact_count") != len(claimed) or accounting.get("total_bytes") != derived_bytes:
            return refuse(
                "ACCOUNTING_MISMATCH",
                declared=accounting,
                observed={"artifact_count": len(claimed), "total_bytes": derived_bytes},
            )

        paths = [entry.get("path", "") for entry in claimed]
        outside = check_allowlist(paths)
        if outside:
            return refuse("OUT_OF_ALLOWLIST", paths=outside)
        not_owned = check_ownership(tuple(dispatch.get("owned_prefixes", [])), paths)
        if not_owned:
            return refuse("NOT_OWNED", owner=dispatch.get("owner"), paths=not_owned)

        verified: list[dict[str, Any]] = []
        for entry in claimed:
            data = self.read_artifact(entry["path"])
            if data is None:
                return refuse("ARTIFACT_MISSING", path=entry["path"])
            if sha256_bytes(data) != entry.get("sha256"):
                return refuse("ARTIFACT_HASH_MISMATCH", path=entry["path"])
            if len(data) != entry.get("bytes"):
                return refuse("ACCOUNTING_MISMATCH", path=entry["path"], observed_bytes=len(data))
            verified.append(
                {
                    "artifact_id": entry["artifact_id"],
                    "path": entry["path"],
                    "sha256": entry["sha256"],
                    "bytes": len(data),
                }
            )

        document = {
            "task_id": unit_id,
            "worker_id": worker,
            "fence_token": fence_token,
            "provider_state": provider_state,
            "obzio_state": "RESULT_COMMITTED",
            "immutable_input_manifest_sha256": dispatch["immutable_input_manifest_sha256"],
            "acceptance_contract_sha256": dispatch["acceptance_contract_sha256"],
            "idempotency_key": idempotency_key or dispatch["idempotency_key"],
            "result_commit_id": result_commit_id,
            "artifacts": verified,
            "artifact_count": len(verified),
            "total_bytes": sum(item["bytes"] for item in verified),
        }
        document_text = json.dumps(document, indent=2, sort_keys=True) + "\n"
        self._result_path(unit_id).write_text(document_text, encoding="utf-8")
        # The worker commits and pushes its result record, so the locator is
        # populated here.  What the live factory never does is read it back from
        # that locator before admitting the result - see ``op_ingest``.
        self.publish_result(f"git:{unit_id}@{result_commit_id}", document_text)
        self.ledger.append(
            unit_id,
            "RESULT_COMMITTED",
            actor=worker,
            ts=self.clock.iso(),
            provider_state=provider_state,
            fence_token=fence_token,
            payload={
                "result_commit_id": result_commit_id,
                "result_locator": f"git:{unit_id}@{result_commit_id}",
                "artifact_count": len(verified),
                "total_bytes": document["total_bytes"],
            },
        )
        return ok(
            unit_id=unit_id,
            obzio_state="RESULT_COMMITTED",
            result_commit_id=result_commit_id,
            verified_artifacts=len(verified),
            result_sha256=sha256_text(canonical(document)),
        )

    def op_ingest(self, *, unit_id: str, actor: str = "coordinator", **_: Any) -> Outcome:
        """``ingest_result``: admit a committed result, deduplicating on its digest.

        The declared locator is recorded but never resolved.  ``ingest_result``
        verifies artifacts against ``artifact_root`` - the working tree - and
        takes ``result_commit_id`` from the submitted document on trust, so a
        result whose record does not exist at its declared commit is still
        admitted.  Cohort a6 hit precisely this while reviewing unit a3-u01, and
        gap case P31 measures it.
        """
        units = self._units()
        unit = units.get(unit_id)
        if unit is None:
            return refuse("UNKNOWN_UNIT", unit_id=unit_id)
        path = self._result_path(unit_id)
        if not path.is_file() or not unit["result_commit_id"]:
            return refuse("NO_RESULT_COMMIT", unit_id=unit_id)
        document = json.loads(path.read_text(encoding="utf-8"))
        result_sha = sha256_text(canonical(document))

        # Duplicate detection matches on the result digest.  A replay under the
        # same idempotency key with *different* content therefore does not match
        # and is ingested again, which is the gap case P26 measures.
        for row in self.ledger.rows():
            if (
                row["unit_id"] == unit_id
                and row["event"] == "PARENT_INGESTED"
                and (row.get("payload") or {}).get("result_sha256") == result_sha
            ):
                self.ledger.append(
                    unit_id,
                    "DUPLICATE_IGNORED",
                    actor=actor,
                    ts=self.clock.iso(),
                    payload={"result_sha256": result_sha},
                )
                return refuse("DUPLICATE_IGNORED", unit_id=unit_id, ingest_count=unit["ingest_count"])

        self.ledger.append(
            unit_id,
            "PARENT_INGESTED",
            actor=actor,
            ts=self.clock.iso(),
            provider_state=document["provider_state"],
            fence_token=document["fence_token"],
            payload={
                "result_sha256": result_sha,
                "result_commit_id": document["result_commit_id"],
                "result_locator": f"git:{unit_id}@{document['result_commit_id']}",
                "artifact_count": document["artifact_count"],
                "total_bytes": document["total_bytes"],
            },
        )
        return ok(unit_id=unit_id, obzio_state="PARENT_INGESTED", result_sha256=result_sha)

    def op_complete(self, *, unit_id: str, actor: str = "coordinator", **_: Any) -> Outcome:
        """``cmd_complete``: preconditions are checked, the actor is not.

        The live command hardcodes ``actor="coordinator"`` on the emitted event,
        so whoever invokes it becomes the coordinator in the record.  Gap case
        P08 measures exactly that.
        """
        units = self._units()
        unit = units.get(unit_id)
        if unit is None:
            return refuse("UNKNOWN_UNIT", unit_id=unit_id)
        if unit["obzio_state"] != "PARENT_INGESTED":
            return refuse("NOT_INGESTED", unit_id=unit_id, obzio_state=unit["obzio_state"])
        if not unit["result_commit_id"]:
            return refuse("NO_RESULT_COMMIT", unit_id=unit_id)
        self.ledger.append(
            unit_id,
            "COMPLETED",
            actor="coordinator",
            ts=self.clock.iso(),
            provider_state="COMPLETED",
            fence_token=unit["fence_token"],
            payload={"result_commit_id": unit["result_commit_id"], "requested_by": actor},
        )
        return ok(unit_id=unit_id, obzio_state="COMPLETED", completion_actor="coordinator", requested_by=actor)

    def op_review(self, *, unit_id: str, reviewer: str, decision: str, **_: Any) -> Outcome:
        """``cmd_review`` plus ``validate_result``'s self-acceptance clause.

        The live factory refuses self-acceptance in two places: the review
        command compares the reviewer to the dispatched owner, and the result
        validator compares ``independent_acceptance.reviewer_id`` to
        ``attempt.worker_id``.  Both are enforced here so the port is not weaker
        than what it represents.
        """
        units = self._units()
        unit = units.get(unit_id)
        dispatch = self._dispatch(unit_id)
        if unit is None or dispatch is None:
            return refuse("UNKNOWN_UNIT", unit_id=unit_id)
        if unit["obzio_state"] != "COMPLETED":
            return refuse("NOT_INGESTED", unit_id=unit_id, obzio_state=unit["obzio_state"])
        if reviewer == dispatch.get("owner"):
            return refuse("SELF_ACCEPTANCE", reviewer=reviewer, owner=dispatch.get("owner"))
        result_path = self._result_path(unit_id)
        if result_path.is_file():
            submitting_worker = json.loads(result_path.read_text(encoding="utf-8")).get("worker_id")
            if reviewer == submitting_worker:
                return refuse("SELF_ACCEPTANCE", reviewer=reviewer, worker_id=submitting_worker)
        self.ledger.append(
            unit_id,
            decision,
            actor=reviewer,
            ts=self.clock.iso(),
            fence_token=unit["fence_token"],
            payload={"reviewer_id": reviewer},
        )
        return ok(unit_id=unit_id, acceptance=decision, reviewer_id=reviewer)

    def op_state(self, *, unit_id: str, **_: Any) -> Outcome:
        unit = self._units().get(unit_id)
        if unit is None:
            return refuse("UNKNOWN_UNIT", unit_id=unit_id)
        return ok(
            unit_id=unit_id,
            obzio_state=unit["obzio_state"],
            provider_state=unit["provider_state"],
            result_commit_id=unit["result_commit_id"],
            acceptance=unit["acceptance"],
            fence_token=unit["fence_token"],
            artifact_count=unit["artifact_count"],
            ingest_count=unit["ingest_count"],
        )

    def op_restart(self, **_: Any) -> Outcome:
        """Rebuild the whole fleet from the ledger, which is the recovery path."""
        units = self._units()
        return ok(units_recovered=len(units), units=sorted(units), source="hash-chained append-only ledger")

    def op_recover(self, **_: Any) -> Outcome:
        """``scan_recovery``.

        ``RESULT_COMMITTED`` is in ``TERMINAL_STATES``, so a result that was
        committed but never ingested is reported as neither resumable nor
        recoverable: it is silently stranded.  Gap case P30 measures that, and it
        is the same shape as the lost PO-02 Code-2 return.
        """
        rows = self.ledger.rows()
        units = project_units(rows)
        now = self.clock.now()
        expired: list[str] = []
        uncommitted: list[str] = []
        orphaned: list[str] = []
        resumable: list[str] = []
        false_completions: list[str] = []
        for unit_id, unit in sorted(units.items()):
            lease = unit.get("lease")
            deadline = self._deadline((lease or {}).get("expires_at"))
            if lease and deadline is not None and deadline < now and unit["obzio_state"] not in TERMINAL_STATES:
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
        return ok(
            ledger_rows=len(rows),
            ledger_chain_valid=not verify_chain(rows),
            expired_leases=expired,
            provider_completed_uncommitted=sorted(set(uncommitted)),
            orphaned_units=orphaned,
            resumable_units=resumable,
            rerun_required=resumable,
            false_completions=sorted(set(false_completions)),
            replayed_ingestions=0,
            stranded_results=[],
        )

    def op_verify(self, **_: Any) -> Outcome:
        """Verify the ledger chain only.

        The live factory has no dispatch-record digest recomputation, no
        artifact re-verification after ingestion and no anchor on the end of the
        log, so all three are reported as zero coverage rather than silently
        omitted.  Gap cases P04, P05, P21 and P29.
        """
        rows = self.ledger.rows()
        errors = verify_chain(rows)
        detail = {
            "ledger_rows": len(rows),
            "ledger_chain_valid": not errors,
            "ledger_chain_errors": errors,
            "ledger_truncated": False,
            "input_tampered": [],
            "input_drift": [],
            "artifacts_reverified": 0,
            "artifact_coverage": 0,
            "drift_detected": [],
        }
        if errors:
            return Outcome(False, "LEDGER_CORRUPT", detail)
        return ok(**detail)

    def op_tamper(self, *, target: str, kind: str = "corrupt", **kwargs: Any) -> Outcome:
        if target == "artifact":
            return self.tamper_artifact(path=kwargs["path"], kind=kind)
        if target == "locator":
            unit_id = kwargs["unit_id"]
            unit = self._units().get(unit_id)
            if unit is None or not unit["result_commit_id"]:
                return refuse("NO_RESULT_COMMIT", unit_id=unit_id)
            return self.tamper_locator(locator=f"git:{unit_id}@{unit['result_commit_id']}", kind=kind)
        if target == "record":
            unit_id = kwargs["unit_id"]
            path = self.dispatch_dir / f"{unit_id}.json"
            if not path.is_file():
                return refuse("UNKNOWN_UNIT", unit_id=unit_id)
            record = json.loads(path.read_text(encoding="utf-8"))
            fields = dict(kwargs.get("fields", {}))
            if "pinned_inputs" in fields:
                record["source_hashes"] = fields.pop("pinned_inputs")
            record.update(fields)
            path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return ok(target=target, unit_id=unit_id, kind=kind)
        if target == "ledger":
            rows = self.ledger.rows()
            if not rows:
                return refuse("INVALID_REQUEST", reason="empty ledger")
            if kind == "truncate":
                self.ledger.overwrite(rows[:-1])
            elif kind == "reorder":
                if len(rows) < 2:
                    return refuse("INVALID_REQUEST", reason="too few rows to reorder")
                rows[-1], rows[-2] = rows[-2], rows[-1]
                self.ledger.overwrite(rows)
            elif kind == "edit":
                rows[-1]["payload"] = {"injected": True}
                self.ledger.overwrite(rows)
            else:
                return refuse("INVALID_REQUEST", kind=kind)
            return ok(target=target, kind=kind, rows_after=len(self.ledger.rows()))
        return refuse("INVALID_REQUEST", target=target)


def build(*, root: Path, clock: Clock) -> G1Controller:
    return G1Controller(root=root, clock=clock)


def digest_of_source() -> str:
    return sha256_bytes(Path(__file__).read_bytes())
