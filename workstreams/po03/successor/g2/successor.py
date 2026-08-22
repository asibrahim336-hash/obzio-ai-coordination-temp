#!/usr/bin/env python3
"""G2: the successor, compiled only from G1's measured failures and accepted lessons.

Compilation rule
----------------
Every change in this file traces to a specific case G1 was observed to fail, or
to a lesson independently supported by an evaluator cohort of a different owner,
or to both.  Nothing was added because it seemed like a good idea.  ``CHANGES``
below is the machine readable form of that rule and ``lineage.json`` is its
committed projection; ``tests/test_a8_g2_lineage.py`` asserts the two agree and
that every change is covered by a recurrence test, so an untraceable change
fails the build rather than quietly shipping.

C-10 and C-11 arrived after the suites were frozen and after the first scoring
run, from cohort a10's audit of the same control plane this file ports.  They
have no frozen case, because there was no case to write by then; their evidence
is the audit finding and the recurrence test that reproduces it.  Both leave the
measured scores unchanged, which is recorded in the lesson register rather than
left for a reader to verify.

G2 subclasses G1 on purpose.  A successor that is meant to be *compiled from*
its predecessor should be diffable against it: everything inherited is a part of
G1 that was measured to work, and everything overridden is a named change with a
cause.  That makes the successor's claim auditable instead of rhetorical.

Honest boundaries, stated here rather than discovered later
----------------------------------------------------------
* Principal identity is asserted by the caller.  ``C-03`` closes the hole where
  authority was a *label on an event* by making it an authorisation decision
  against a registry, but binding an identity to a credential needs a transport
  this in-process, dependency-free controller does not have.
* The ledger head anchor in ``C-07`` lives in the same durable store as the
  ledger.  It detects truncation from a partial write, a crash or an attacker
  who misses the anchor.  It does not detect an attacker who rewrites both; that
  needs an anchor outside the store, such as a signed remote ref.
* ``C-09`` resolves a locator against the modelled immutable store.  In the live
  repository the equivalent is ``git cat-file blob <commit>:<path>``, which is
  what the integration proposal recommends.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..harness.controller_api import (
    Clock,
    Outcome,
    canonical,
    ok,
    refuse,
    sha256_bytes,
    sha256_text,
)
from ..g1.factory import (
    COMMITTED_STATES,
    TERMINAL_STATES,
    G1Controller,
    Ledger,
    check_allowlist,
    check_ownership,
    project_units,
    verify_chain,
)

PROVENANCE = (
    "successor compiled from G1's measured failures on the frozen public suite, cohort a6's "
    "independently authored holdout, and cohort a10's published audit of the same control plane; "
    "see workstreams/po03/successor/g2/lineage.json and successor/lessons/lessons.json"
)

COORDINATOR_PRINCIPAL = "coordinator"

# C-11.  G1 inherited a single ``TERMINAL_STATES`` set that mixed "this unit has
# a durable result" with "this unit is closed".  Replay adjudication has to stay
# reachable for the first group - that is what C-06 does - so the closed set is
# named separately and is the only one that refuses new work outright.
CLOSED_STATES = {"COMPLETED", "FAILED_TERMINAL", "CANCELLED"}

# Authority is a decision against this table, not a string written onto an event.
CAPABILITIES: dict[str, set[str]] = {
    "coordinator": {"create", "lease", "ingest", "complete", "recover", "verify"},
    "worker": {"submit"},
    "reviewer": {"review"},
}

CHANGES: tuple[dict[str, Any], ...] = (
    {
        "change_id": "C-01",
        "name": "grant-bound fencing",
        "caused_by_failures": ["P13-forged-fence-token-refused"],
        "caused_by_lessons": ["L-04"],
        "g1_behaviour": "the fence check was `incoming < current`, so any token above the current grant was accepted",
        "change": "a commit is admitted only if the ledger shows that exact (unit, worker, fence) grant, so a token that was never issued is refused instead of being trusted for being large",
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c01_forged_fence_is_refused",
    },
    {
        "change_id": "C-02",
        "name": "lease expiry enforced at commit",
        "caused_by_failures": ["P14-expired-lease-cannot-commit"],
        "caused_by_lessons": ["L-04"],
        "g1_behaviour": "expiry was reported by the recovery scanner but never checked when a result was offered",
        "change": "the lease deadline is evaluated at the moment of commit, so an expired worker cannot enter custody even holding the newest fence",
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c02_expired_lease_cannot_commit",
    },
    {
        "change_id": "C-03",
        "name": "authenticated transition authority",
        "caused_by_failures": ["P08-completion-authority-is-enforced-not-labelled", "H02-noncoordinator-completion"],
        "caused_by_lessons": ["L-01"],
        "g1_behaviour": "`cmd_complete` wrote actor=\"coordinator\" unconditionally, so whoever invoked it became the coordinator in the record",
        "change": "each transition is authorised against a principal-to-capability table before it is recorded, so a worker driving completion is refused rather than relabelled",
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c03_worker_cannot_complete",
    },
    {
        "change_id": "C-04",
        "name": "dispatch input seal",
        "caused_by_failures": ["P04-acceptance-contract-tamper-detected", "P05-pinned-input-drift-detected"],
        "caused_by_lessons": ["L-05"],
        "g1_behaviour": "the dispatch record carried its own manifest digest but nothing ever recomputed it, so an edit to dispatched immutable input was invisible; G0 detected pinned-input drift and G1 had lost that check",
        "change": "the dispatch record is sealed over its own canonical body and the pinned inputs are re-hashed on every verification sweep, so tampering with the frozen acceptance contract or a pinned source is detected",
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c04_dispatch_tamper_and_input_drift_detected",
    },
    {
        "change_id": "C-05",
        "name": "continuous artifact re-verification",
        "caused_by_failures": ["P21-drift-after-admission-is-detected", "H09-corrupt_readback"],
        "caused_by_lessons": ["L-02"],
        "g1_behaviour": "artifacts were hashed once at ingestion and never looked at again, so bytes that changed afterwards stayed in custody unnoticed",
        "change": "admitted artifacts are recorded in a custody manifest and re-hashed on every verification sweep, so drift after admission is reported instead of assumed away",
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c05_post_admission_drift_detected",
    },
    {
        "change_id": "C-06",
        "name": "idempotency-keyed replay adjudication",
        "caused_by_failures": ["P26-conflicting-replay-refused"],
        "caused_by_lessons": ["L-06"],
        "g1_behaviour": "duplicates were matched on the result digest, so a replay under the same idempotency key carrying different content did not match and was ingested a second time",
        "change": "replays are adjudicated on the idempotency key: identical content is a harmless duplicate, different content is a refused conflict, and neither produces a second ingestion",
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c06_conflicting_replay_refused",
    },
    {
        "change_id": "C-07",
        "name": "ledger head anchor",
        "caused_by_failures": ["P29-log-tail-truncation-detected"],
        "caused_by_lessons": ["L-07"],
        "g1_behaviour": "`verify_chain` validated links between the rows that remained, so losing the tail of the log left a self-consistent chain",
        "change": "the row count and head digest are anchored after every append and compared on verification, so a lost tail is reported rather than accepted as a shorter valid history",
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c07_tail_truncation_detected",
    },
    {
        "change_id": "C-08",
        "name": "transactional outbox with recovery replay",
        "caused_by_failures": ["P30-lost-callback-is-replayed-not-rerun", "H10-parent-restart"],
        "caused_by_lessons": ["L-03"],
        "g1_behaviour": "RESULT_COMMITTED was terminal for the recovery scanner and there was no outbox, so a result that was committed but never ingested was neither replayed nor re-run: it was stranded, which is the shape of the lost PO-02 Code-2 return",
        "change": "a commit writes a pending outbox entry and recovery replays it into ingestion exactly once, so a lost callback costs a replay rather than a result",
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c08_lost_callback_is_replayed_once",
    },
    {
        "change_id": "C-09",
        "name": "locator resolution before admission",
        "caused_by_failures": ["P31-declared-locator-must-resolve-before-ingestion"],
        "caused_by_lessons": ["L-08"],
        "g1_behaviour": "the declared result locator was recorded and never resolved; artifacts were verified against the working tree while `result_commit_id` was taken on trust",
        "change": "admission requires the result record to be readable at the immutable locator it declares and to match the submitted bytes, so a locator that holds nothing is refused",
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c09_unresolvable_locator_refused",
    },
    {
        "change_id": "C-10",
        "name": "path scope judged with filesystem semantics",
        "caused_by_failures": [],
        "caused_by_lessons": ["L-11"],
        "g1_behaviour": "`path_in_allowlist` and `check_ownership` normalised with `str.lstrip('./')`, which strips a *character set* rather than a prefix; a declared path whose leading run is only dots and slashes was judged in-allowlist and owned, while the raw string was joined to the artifact root and the filesystem walked out of it",
        "change": "a declared path is normalised with the same semantics the filesystem join uses and must resolve inside the artifact store; the allowlist and ownership checks then run on that resolved relative path, so the string judged and the bytes read are the same file",
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c10_path_escape_refused",
    },
    {
        "change_id": "C-11",
        "name": "terminal states are not re-enterable",
        "caused_by_failures": [],
        "caused_by_lessons": ["L-12"],
        "g1_behaviour": "the state projection assigned `obzio_state` from the newest matching row with no monotonicity guard, so a resubmission against an already COMPLETED unit reset the projection to RESULT_COMMITTED and a second completion could be recorded against a different result_commit_id",
        "change": "a submission against a closed unit is refused before anything is written, and `COMPLETED`, `FAILED_TERMINAL` and `CANCELLED` are named as closed separately from the merely committed states so that replay adjudication stays reachable",
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c11_terminal_state_cannot_be_re_entered",
    },
)


def contained_relative_path(store: Path, declared: str) -> str | None:
    """Normalise ``declared`` the way the filesystem join will, or refuse it.

    C-10.  The defect this replaces was not a missing check but a check that
    reasoned about a *different string* than the one handed to the filesystem.
    Returning the resolved relative path, rather than a boolean, is what forces
    the caller to judge and to read the same file: there is no second
    normalisation left for the two to disagree about.
    """
    text = declared.strip()
    if not text or text.startswith("/") or Path(text).is_absolute():
        return None
    resolved = os.path.normpath(os.path.join("/anchor", text))
    if not resolved.startswith("/anchor/"):
        return None
    relative = resolved[len("/anchor/") :]
    if not relative:
        return None
    # Belt and braces against symlinks and platform quirks: the join actually
    # used for I/O must land inside the store.
    base = store.resolve()
    try:
        candidate = (base / relative).resolve()
    except OSError:
        return None
    if candidate != base and base not in candidate.parents:
        return None
    return relative


class AnchoredLedger(Ledger):
    """Append-only log that anchors its own length and head after every append.

    C-07.  The anchor is what makes a *shorter* history distinguishable from a
    *correct* history, which per-row chaining alone cannot do.
    """

    def __init__(self, path: Path, anchor_path: Path) -> None:
        super().__init__(path)
        self.anchor_path = Path(anchor_path)

    def append(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        row = super().append(*args, **kwargs)
        self.anchor_path.parent.mkdir(parents=True, exist_ok=True)
        self.anchor_path.write_text(
            canonical({"rows": row["seq"], "head_sha256": row["row_sha256"]}) + "\n", encoding="utf-8"
        )
        return row

    def anchor(self) -> dict[str, Any] | None:
        if not self.anchor_path.is_file():
            return None
        return json.loads(self.anchor_path.read_text(encoding="utf-8"))


class G2Controller(G1Controller):
    """G1 plus the changes in ``CHANGES``, and nothing else."""

    generation_id = "G2"
    generation_label = "successor custody engine compiled from G1 failures"
    provenance = PROVENANCE

    def __init__(self, root: Path, clock: Clock) -> None:
        super().__init__(root=root, clock=clock)
        self.ledger = AnchoredLedger(
            self.control / "events" / "ledger.jsonl",
            self.control / "events" / "head-anchor.json",
        )
        self.outbox_dir = self.control / "outbox"
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        self.custody_path = self.control / "custody-manifest.json"

    # -- C-03: authority ---------------------------------------------------

    def _role(self, actor: str) -> str:
        if actor == COORDINATOR_PRINCIPAL:
            return "coordinator"
        if actor in self._lease_grantees():
            return "worker"
        return "reviewer"

    def _lease_grantees(self) -> set[str]:
        return {
            (row.get("payload") or {}).get("worker_id")
            for row in self.ledger.rows()
            if row["event"] == "LEASED"
        }

    def _authorise(self, actor: str, transition: str) -> Outcome | None:
        role = self._role(actor)
        if transition in CAPABILITIES.get(role, set()):
            return None
        if transition == "complete":
            return refuse("NOT_COORDINATOR", actor=actor, role=role, transition=transition)
        return refuse("NOT_COORDINATOR", actor=actor, role=role, transition=transition)

    # -- C-01, C-02: grants ------------------------------------------------

    def _grants(self, unit_id: str) -> dict[int, dict[str, Any]]:
        grants: dict[int, dict[str, Any]] = {}
        for row in self.ledger.rows():
            if row["unit_id"] == unit_id and row["event"] == "LEASED":
                payload = row.get("payload") or {}
                grants[int(row["fence_token"])] = {
                    "worker_id": payload.get("worker_id"),
                    "expires_at": payload.get("expires_at"),
                }
        return grants

    # -- C-04: dispatch seal -----------------------------------------------

    @staticmethod
    def _seal(record: dict[str, Any]) -> str:
        body = {key: value for key, value in record.items() if key != "record_seal_sha256"}
        return sha256_text(canonical(body))

    # -- C-05: custody manifest --------------------------------------------

    def _custody(self) -> dict[str, Any]:
        if not self.custody_path.is_file():
            return {}
        return json.loads(self.custody_path.read_text(encoding="utf-8"))

    def _record_custody(self, unit_id: str, artifacts: list[dict[str, Any]]) -> None:
        manifest = self._custody()
        manifest[unit_id] = {
            entry["path"]: {"sha256": entry["sha256"], "bytes": entry["bytes"]} for entry in artifacts
        }
        self.custody_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    # -- C-10: path scope --------------------------------------------------

    def read_artifact(self, path: str) -> bytes | None:
        """Never read bytes the scope guard would have refused.

        Overriding the read, not only the check, is the point of C-10: every
        later sweep re-reads artifacts, and a guard that protects admission but
        not re-verification would leave the escape reachable one step further
        along.  An escaping path reads as absent, which is the safe answer.
        """
        relative = contained_relative_path(self.artifact_dir, path)
        if relative is None:
            return None
        return super().read_artifact(relative)

    # -- C-08: outbox ------------------------------------------------------

    def _outbox_path(self, unit_id: str) -> Path:
        return self.outbox_dir / f"{unit_id}.json"

    def _write_outbox(self, unit_id: str, entry: dict[str, Any]) -> None:
        self._outbox_path(unit_id).write_text(
            json.dumps(entry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def _read_outbox(self, unit_id: str) -> dict[str, Any] | None:
        path = self._outbox_path(unit_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # -- operations --------------------------------------------------------

    def op_create(self, *, unit_id: str, spec: dict[str, Any] | None = None, actor: str = COORDINATOR_PRINCIPAL, **_: Any) -> Outcome:
        denied = self._authorise(actor, "create")
        if denied is not None:
            return denied
        outcome = super().op_create(unit_id=unit_id, spec=spec)
        if not outcome.admitted:
            return outcome
        # C-04: seal the record over its own body so an edit is detectable.
        path = self.dispatch_dir / f"{unit_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["source_pin_sha256"] = sha256_text(canonical(record.get("source_hashes", {})))
        record["record_seal_sha256"] = self._seal(record)
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        outcome.detail["record_seal_sha256"] = record["record_seal_sha256"]
        return outcome

    def op_lease(self, *, unit_id: str, worker: str, ttl: int = 5400, actor: str = COORDINATOR_PRINCIPAL, **_: Any) -> Outcome:
        denied = self._authorise(actor, "lease")
        if denied is not None:
            return denied
        return super().op_lease(unit_id=unit_id, worker=worker, ttl=ttl)

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
        """Adjudicate a commit attempt.

        Order matters and is deliberate.  Truthfulness of the claim is settled
        first, because "you say you completed but nothing was committed" is true
        regardless of who is speaking and must be recorded as
        PROVIDER_COMPLETED_UNCOMMITTED even from an unauthorised caller.  Only
        then is the caller's standing examined, and only then the content.
        """
        units = self._units()
        unit = units.get(unit_id)
        dispatch = self._dispatch(unit_id)
        if unit is None or dispatch is None:
            return refuse("UNKNOWN_UNIT", unit_id=unit_id)

        # C-11: a closed unit takes no further work.  This is checked before
        # anything is written, because the harm in G1 was not the second result
        # but the projection being walked backwards to accept it.
        if unit["obzio_state"] in CLOSED_STATES:
            return refuse(
                "TERMINAL_STATE",
                unit_id=unit_id,
                obzio_state=unit["obzio_state"],
                admitted_result_commit_id=unit["result_commit_id"],
                offered_result_commit_id=result_commit_id,
            )

        if provider_state == "COMPLETED" and not result_commit_id:
            self.ledger.append(
                unit_id,
                "PROVIDER_COMPLETED_UNCOMMITTED",
                actor="coordinator",
                ts=self.clock.iso(),
                provider_state=provider_state,
                fence_token=None,
                payload={"reason": "no durable result commit", "reported_by": worker},
            )
            return refuse("NO_RESULT_COMMIT", unit_id=unit_id, claimed_state=claimed_state)

        # C-01: the fence must correspond to a grant actually issued to this
        # worker.  A lower token is a stale worker; an unissued token is forged.
        grants = self._grants(unit_id)
        if fence_token < unit["fence_token"]:
            self.ledger.append(
                unit_id,
                "FENCE_REJECTED",
                actor="coordinator",
                ts=self.clock.iso(),
                fence_token=unit["fence_token"],
                payload={"rejected_fence_token": fence_token, "reason": "stale worker after ownership transfer"},
            )
            return refuse("STALE_FENCE", current_fence_token=unit["fence_token"], offered=fence_token)
        grant = grants.get(fence_token)
        if grant is None or grant["worker_id"] != worker:
            self.ledger.append(
                unit_id,
                "FENCE_REJECTED",
                actor="coordinator",
                ts=self.clock.iso(),
                fence_token=unit["fence_token"],
                payload={"rejected_fence_token": fence_token, "reason": "no matching lease grant"},
            )
            return refuse("FORGED_FENCE", offered=fence_token, granted_fences=sorted(grants))

        # C-02: the grant must still be live at the moment of commit.
        deadline = self._deadline(grant["expires_at"])
        if deadline is not None and deadline < self.clock.now():
            self.ledger.append(
                unit_id,
                "LEASE_EXPIRED",
                actor="coordinator",
                ts=self.clock.iso(),
                fence_token=fence_token,
                payload={"worker_id": worker, "expires_at": grant["expires_at"]},
            )
            return refuse("EXPIRED_LEASE", expires_at=grant["expires_at"], now=self.clock.iso())

        claimed = self.resolve_claims(list(artifacts or []))
        derived_bytes = sum(int(entry.get("bytes") or 0) for entry in claimed)
        accounting = dict(accounting or {"artifact_count": len(claimed), "total_bytes": derived_bytes})

        if claimed_state in COMMITTED_STATES and not readback_verified:
            return refuse("READBACK_MISSING", unit_id=unit_id)
        if claimed_state in COMMITTED_STATES and not claimed:
            return refuse("ACCOUNTING_MISMATCH", reason="committed result requires at least one artifact")

        seen: set[str] = set()
        for entry in claimed:
            if entry.get("artifact_id") in seen:
                return refuse("DUPLICATE_ARTIFACT_ID", artifact_id=entry.get("artifact_id"))
            seen.add(entry.get("artifact_id"))

        if accounting.get("artifact_count") != len(claimed) or accounting.get("total_bytes") != derived_bytes:
            return refuse(
                "ACCOUNTING_MISMATCH",
                declared=accounting,
                observed={"artifact_count": len(claimed), "total_bytes": derived_bytes},
            )

        # C-10: resolve every declared path with filesystem semantics first, then
        # judge the resolved path.  A path that leaves the store is refused here
        # rather than being scope-checked as one file and read as another.
        declared_paths = [entry.get("path", "") for entry in claimed]
        resolved_paths: dict[str, str] = {}
        escapes: list[str] = []
        for declared in declared_paths:
            relative = contained_relative_path(self.artifact_dir, declared)
            if relative is None:
                escapes.append(declared)
            else:
                resolved_paths[declared] = relative
        if escapes:
            # A path that resolves outside the repository is outside the
            # allowlist by construction, so the existing reason code is the
            # accurate one; the detail records why it was refused.
            return refuse(
                "OUT_OF_ALLOWLIST",
                paths=sorted(escapes),
                reason="the declared path resolves outside the artifact store it would be verified against",
            )

        paths = [resolved_paths[declared] for declared in declared_paths]
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

        key = idempotency_key or dispatch["idempotency_key"]
        locator = f"git:{unit_id}@{result_commit_id}"
        document = {
            "task_id": unit_id,
            "worker_id": worker,
            "fence_token": fence_token,
            "provider_state": provider_state,
            "obzio_state": "RESULT_COMMITTED",
            "immutable_input_manifest_sha256": dispatch["immutable_input_manifest_sha256"],
            "acceptance_contract_sha256": dispatch["acceptance_contract_sha256"],
            "idempotency_key": key,
            "result_commit_id": result_commit_id,
            "result_locator": locator,
            "artifacts": verified,
            "artifact_count": len(verified),
            "total_bytes": sum(item["bytes"] for item in verified),
        }
        document_text = json.dumps(document, indent=2, sort_keys=True) + "\n"
        self._result_path(unit_id).write_text(document_text, encoding="utf-8")
        self.publish_result(locator, document_text)

        result_sha = sha256_text(canonical(document))
        # C-08: the commit and the intent to deliver it are recorded together, so
        # a lost callback leaves a pending entry rather than a stranded result.
        self._write_outbox(
            unit_id,
            {
                "unit_id": unit_id,
                "idempotency_key": key,
                "result_locator": locator,
                "result_sha256": result_sha,
                "delivery_state": "PENDING_INGEST",
                "committed_at": self.clock.iso(),
            },
        )
        self.ledger.append(
            unit_id,
            "RESULT_COMMITTED",
            actor=worker,
            ts=self.clock.iso(),
            provider_state=provider_state,
            fence_token=fence_token,
            payload={
                "result_commit_id": result_commit_id,
                "result_locator": locator,
                "result_sha256": result_sha,
                "idempotency_key": key,
                "artifact_count": len(verified),
                "total_bytes": document["total_bytes"],
            },
        )
        return ok(
            unit_id=unit_id,
            obzio_state="RESULT_COMMITTED",
            result_commit_id=result_commit_id,
            verified_artifacts=len(verified),
            result_sha256=result_sha,
            outbox_state="PENDING_INGEST",
        )

    def op_ingest(self, *, unit_id: str, actor: str = COORDINATOR_PRINCIPAL, **_: Any) -> Outcome:
        denied = self._authorise(actor, "ingest")
        if denied is not None:
            return denied
        return self._ingest(unit_id=unit_id, actor=actor, replay=False)

    def _ingest(self, *, unit_id: str, actor: str, replay: bool) -> Outcome:
        units = self._units()
        unit = units.get(unit_id)
        if unit is None:
            return refuse("UNKNOWN_UNIT", unit_id=unit_id)
        path = self._result_path(unit_id)
        if not path.is_file() or not unit["result_commit_id"]:
            return refuse("NO_RESULT_COMMIT", unit_id=unit_id)
        document_text = path.read_text(encoding="utf-8")
        document = json.loads(document_text)
        result_sha = sha256_text(canonical(document))

        # C-09: the record must be readable at the locator it declares, and the
        # bytes there must be the bytes being admitted.
        locator = document.get("result_locator") or f"git:{unit_id}@{document['result_commit_id']}"
        published = self.resolve_locator(locator)
        if published is None:
            return refuse("LOCATOR_UNRESOLVED", unit_id=unit_id, locator=locator, reason="nothing exists at the declared locator")
        if published != document_text:
            return refuse("LOCATOR_UNRESOLVED", unit_id=unit_id, locator=locator, reason="bytes at the declared locator differ from the submitted result")

        # C-06: adjudicate on the idempotency key, not on the content digest, so
        # a conflicting retry is refused instead of ingested a second time.
        key = document["idempotency_key"]
        for row in self.ledger.rows():
            if row["unit_id"] != unit_id or row["event"] != "PARENT_INGESTED":
                continue
            payload = row.get("payload") or {}
            if payload.get("idempotency_key") != key:
                continue
            if payload.get("result_sha256") == result_sha:
                self.ledger.append(
                    unit_id,
                    "DUPLICATE_IGNORED",
                    actor=actor,
                    ts=self.clock.iso(),
                    payload={"idempotency_key": key, "result_sha256": result_sha},
                )
                return refuse("DUPLICATE_IGNORED", unit_id=unit_id, ingest_count=unit["ingest_count"])
            self.ledger.append(
                unit_id,
                "DUPLICATE_IGNORED",
                actor=actor,
                ts=self.clock.iso(),
                payload={
                    "idempotency_key": key,
                    "rejected_result_sha256": result_sha,
                    "admitted_result_sha256": payload.get("result_sha256"),
                    "reason": "same idempotency key, different content",
                },
            )
            return refuse(
                "CONFLICTING_REPLAY",
                unit_id=unit_id,
                idempotency_key=key,
                ingest_count=unit["ingest_count"],
            )

        for entry in document["artifacts"]:
            data = self.read_artifact(entry["path"])
            if data is None:
                return refuse("ARTIFACT_MISSING", path=entry["path"])
            if sha256_bytes(data) != entry["sha256"]:
                return refuse("ARTIFACT_HASH_MISMATCH", path=entry["path"])

        self.ledger.append(
            unit_id,
            "PARENT_INGESTED",
            actor=actor,
            ts=self.clock.iso(),
            provider_state=document["provider_state"],
            fence_token=document["fence_token"],
            payload={
                "result_sha256": result_sha,
                "idempotency_key": key,
                "result_commit_id": document["result_commit_id"],
                "result_locator": locator,
                "artifact_count": document["artifact_count"],
                "total_bytes": document["total_bytes"],
                "replayed": replay,
            },
        )
        # C-05: what is in custody is recorded so it can be re-checked later.
        self._record_custody(unit_id, document["artifacts"])
        entry = self._read_outbox(unit_id)
        if entry is not None:
            entry["delivery_state"] = "DELIVERED"
            entry["delivered_at"] = self.clock.iso()
            self._write_outbox(unit_id, entry)
        return ok(unit_id=unit_id, obzio_state="PARENT_INGESTED", result_sha256=result_sha, replayed=replay)

    def op_complete(self, *, unit_id: str, actor: str = COORDINATOR_PRINCIPAL, **_: Any) -> Outcome:
        """C-03: authority is decided before the transition is recorded."""
        denied = self._authorise(actor, "complete")
        if denied is not None:
            return denied
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
            actor=actor,
            ts=self.clock.iso(),
            provider_state="COMPLETED",
            fence_token=unit["fence_token"],
            payload={"result_commit_id": unit["result_commit_id"], "authorised_role": self._role(actor)},
        )
        return ok(unit_id=unit_id, obzio_state="COMPLETED", completion_actor=actor)

    def op_review(self, *, unit_id: str, reviewer: str, decision: str, **_: Any) -> Outcome:
        """C-03 extended to acceptance: the producer and its workers are excluded."""
        role = self._role(reviewer)
        if role != "reviewer":
            return refuse("SELF_ACCEPTANCE", reviewer=reviewer, role=role, reason="only an independent principal may dispose of a result")
        return super().op_review(unit_id=unit_id, reviewer=reviewer, decision=decision)

    def op_recover(self, **_: Any) -> Outcome:
        """Recovery scan, plus C-08 outbox replay.

        The scan no longer treats RESULT_COMMITTED as the end of the story: a
        pending outbox entry means a durable result exists that custody has not
        admitted, and the answer to that is a replay, not a re-run.
        """
        replayed: list[str] = []
        for path in sorted(self.outbox_dir.glob("*.json")):
            entry = json.loads(path.read_text(encoding="utf-8"))
            if entry.get("delivery_state") != "PENDING_INGEST":
                continue
            outcome = self._ingest(unit_id=entry["unit_id"], actor=COORDINATOR_PRINCIPAL, replay=True)
            if outcome.admitted:
                replayed.append(entry["unit_id"])

        rows = self.ledger.rows()
        units = project_units(rows)
        now = self.clock.now()
        expired: list[str] = []
        uncommitted: list[str] = []
        orphaned: list[str] = []
        resumable: list[str] = []
        stranded: list[str] = []
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
            entry = self._read_outbox(unit_id)
            if entry is not None and entry.get("delivery_state") == "PENDING_INGEST":
                stranded.append(unit_id)
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
            replayed_ingestions=len(replayed),
            replayed_units=replayed,
            stranded_results=stranded,
        )

    def op_verify(self, **_: Any) -> Outcome:
        """Verify the log, the sealed dispatch input and the bytes in custody.

        Check order encodes severity.  A broken chain means the history cannot be
        trusted at all, so it is reported before anything derived from it.  A lost
        tail is next, then tampered input, then drifted bytes.
        """
        rows = self.ledger.rows()
        chain_errors = verify_chain(rows)
        anchor = self.ledger.anchor()
        truncated = False
        if anchor is not None and not chain_errors:
            head = rows[-1]["row_sha256"] if rows else "0" * 64
            truncated = len(rows) < anchor["rows"] or head != anchor["head_sha256"]

        # C-04: recompute the seal and the pinned-input digest.
        tampered: list[str] = []
        drifted_inputs: list[str] = []
        for path in sorted(self.dispatch_dir.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if "record_seal_sha256" in record and self._seal(record) != record["record_seal_sha256"]:
                tampered.append(record["unit_id"])
            recorded_pin = record.get("source_pin_sha256")
            if recorded_pin and sha256_text(canonical(record.get("source_hashes", {}))) != recorded_pin:
                drifted_inputs.append(record["unit_id"])

        # C-05: re-hash everything currently in custody.
        custody = self._custody()
        reverified = 0
        drift: list[str] = []
        for entries in custody.values():
            for artifact_path, expected in sorted(entries.items()):
                reverified += 1
                data = self.read_artifact(artifact_path)
                if data is None or sha256_bytes(data) != expected["sha256"] or len(data) != expected["bytes"]:
                    drift.append(artifact_path)

        detail = {
            "ledger_rows": len(rows),
            "ledger_chain_valid": not chain_errors,
            "ledger_chain_errors": chain_errors,
            "ledger_truncated": truncated,
            "ledger_anchor": anchor,
            "input_tampered": sorted(tampered),
            "input_drift": sorted(drifted_inputs),
            "artifacts_reverified": reverified,
            "artifact_coverage": reverified,
            "drift_detected": sorted(drift),
        }
        if chain_errors:
            return Outcome(False, "LEDGER_CORRUPT", detail)
        if truncated:
            return Outcome(False, "LEDGER_TRUNCATED", detail)
        if tampered:
            return Outcome(False, "INPUT_TAMPERED", detail)
        if drift:
            return Outcome(False, "ARTIFACT_DRIFT", detail)
        if drifted_inputs:
            return Outcome(False, "INPUT_TAMPERED", detail)
        return ok(**detail)


def build(*, root: Path, clock: Clock) -> G2Controller:
    return G2Controller(root=root, clock=clock)


def digest_of_source() -> str:
    return sha256_bytes(Path(__file__).read_bytes())
