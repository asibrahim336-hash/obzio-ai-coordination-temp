#!/usr/bin/env python3
"""G0: the pre-amendment PO-03 controller, reconstructed from immutable source.

Reconstruction basis
--------------------
The pre-amendment tree is pinned at ``prior_observed_head``
``d627119351a6dc0e90158705abf6aab96e26b3dd``.  Read read-only, the entire
PO-03 surface at that commit is two files::

    workstreams/po03/COMMISSION.md
    receipts/po03/2026-08-22/appointment-seed.json

There is no executable code at that commit.  The pre-amendment controller was
therefore a *receipt-file controller*: coordination state was whatever the
latest committed receipt said, and the receipt was written from the producer's
own report.  That is the honest answer to "what was the controller before the
amendment", and it is the reason this file exists as code rather than prose:
the absence of durable result custody is a measurable property, and it can only
be measured by running it.

What G0 genuinely has, and where it comes from
---------------------------------------------
* Receipt records with a declared ``state`` field - the worked example is
  ``appointment-seed.json``, whose fields include ``state``, ``acceptance``,
  ``execution_started`` and ``next_provider_action``.
* Input pinning by repository and SHA - ``appointment-seed.json`` pins
  ``pinned_start_sha``, ``commission_commit_sha`` and ``environment_base_sha``;
  v001 mission item 2 requires freezing "exact source SHAs" and the acceptance
  controls require "Every claimed input is pinned by repository and SHA".
* A manifest digest over pinned inputs - v001 requires
  ``workstreams/po03/MANIFEST.sha256``.
* An acceptance field that starts at ``NOT_TESTED`` and a prose rule that PO-03
  "must not self-mark the work independently accepted".

What G0 genuinely lacks, and why
--------------------------------
Every item below is absent from the pinned tree.  None of it is withheld to
flatter the successor; there is simply no code at ``d627119`` that could
implement it:

* no append-only ledger and no hash chain, so history is a mutable file;
* no leases and no fence tokens, so ownership transfer is unrepresentable;
* no result submission verification and no artifact read-back, so a result is
  admitted on the producer's word;
* no distinction between provider completion and Obzio completion - the v001
  text never draws it, so a provider report of COMPLETED becomes the recorded
  state;
* no parent ingestion step, no recovery scanner, no idempotency handling and no
  code enforcement of the allowlist, the ownership partition or the
  self-acceptance prohibition, all of which exist only as prose.

The v001 acceptance controls do require that "Injected corruption, missing-file
and interrupted-run cases are detected", so ``verify`` is implemented - but it
covers only the inputs G0 hashed, because G0 never receives subordinate results
as hashed artifacts.  Its reported ``artifact_coverage`` is therefore zero, and
that is the finding rather than a stub.
"""

from __future__ import annotations

import json
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
    unsupported,
)
from ..harness.generation_support import GenerationSupport

PROVENANCE = (
    "reconstructed from prior_observed_head d627119351a6dc0e90158705abf6aab96e26b3dd "
    "(workstreams/po03/COMMISSION.md v001 and receipts/po03/2026-08-22/appointment-seed.json); "
    "no executable controller code exists at that commit"
)


class G0Controller(Controller, GenerationSupport):
    """A receipt-file controller: the record is the producer's latest report."""

    generation_id = "G0"
    generation_label = "pre-amendment receipt-file controller"
    provenance = PROVENANCE

    def __init__(self, root: Path, clock: Clock) -> None:
        super().__init__(Path(root), clock)
        self.receipt_dir = Path(root) / "receipts"
        self.receipt_dir.mkdir(parents=True, exist_ok=True)

    # -- receipt storage ---------------------------------------------------

    def _receipt_path(self, unit_id: str) -> Path:
        return self.receipt_dir / f"{unit_id}.json"

    def _read(self, unit_id: str) -> dict[str, Any] | None:
        path = self._receipt_path(unit_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # A corrupt receipt is simply unreadable; v001 has no hash chain
            # that could tell corruption from a legitimate later edit.
            return None

    def _write(self, unit_id: str, receipt: dict[str, Any]) -> None:
        # Overwrite in place.  This is the defining weakness of the generation:
        # the record of what happened has no immutable history behind it.
        self._receipt_path(unit_id).write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    # -- operations --------------------------------------------------------

    def op_create(self, *, unit_id: str, spec: dict[str, Any] | None = None, **_: Any) -> Outcome:
        """Write a dispatch receipt pinning the inputs by SHA.

        v001 mission item 2 and the acceptance controls are satisfied for
        *inputs*: the pinned sources are hashed into a manifest digest.  Nothing
        here constrains what a producer may later report about its results.
        """
        spec = dict(spec or {})
        pinned = spec.get("pinned_inputs", {})
        manifest_sha = sha256_text(canonical(pinned))
        receipt = {
            "receipt_id": f"RCP-PO03-{unit_id.upper()}-v001",
            "unit_id": unit_id,
            "state": "COMMISSIONED_NOT_YET_EXECUTING",
            "acceptance": "NOT_TESTED",
            "execution_started": False,
            "pinned_inputs": pinned,
            "input_manifest_sha256": manifest_sha,
            "recorded_at": self.clock.iso(),
        }
        self._write(unit_id, receipt)
        return ok(
            unit_id=unit_id,
            input_manifest_sha256=manifest_sha,
            # v001 has no acceptance-contract digest and no idempotency key.
            acceptance_contract_sha256=None,
            idempotency_key=None,
        )

    def op_submit(
        self,
        *,
        unit_id: str,
        worker: str = "worker",
        provider_state: str = "COMPLETED",
        claimed_state: str = "COMPLETED",
        artifacts: list[dict[str, Any]] | None = None,
        accounting: dict[str, Any] | None = None,
        result_commit_id: str | None = None,
        **_: Any,
    ) -> Outcome:
        """Record the producer's self-report as the coordination state.

        No verification happens: no artifact is read back, no digest is
        recomputed, no accounting is reconciled, and the claimed state is
        written through unchanged.  A provider report of COMPLETED becomes
        recorded COMPLETED even with no durable result commit, because the v001
        text never separates the two.
        """
        receipt = self._read(unit_id)
        if receipt is None:
            return refuse("UNKNOWN_UNIT", unit_id=unit_id)
        claimed = self.resolve_claims(list(artifacts or []))
        receipt.update(
            {
                "execution_started": True,
                "state": claimed_state,
                "provider_state": provider_state,
                "reported_by": worker,
                "reported_artifacts": claimed,
                "reported_accounting": dict(accounting or {}),
                "result_commit_id": result_commit_id,
                "reported_at": self.clock.iso(),
            }
        )
        self._write(unit_id, receipt)
        return ok(
            unit_id=unit_id,
            obzio_state=claimed_state,
            provider_state=provider_state,
            result_commit_id=result_commit_id,
            verified_artifacts=0,
            artifacts_read_back=False,
        )

    def op_complete(self, *, unit_id: str, actor: str = "coordinator", **_: Any) -> Outcome:
        """Mark completion with no authority check and no ingestion requirement."""
        receipt = self._read(unit_id)
        if receipt is None:
            return refuse("UNKNOWN_UNIT", unit_id=unit_id)
        receipt["state"] = "COMPLETED"
        receipt["completion_actor"] = actor
        receipt["completed_at"] = self.clock.iso()
        self._write(unit_id, receipt)
        return ok(
            unit_id=unit_id,
            obzio_state="COMPLETED",
            completion_actor=actor,
            result_commit_id=receipt.get("result_commit_id"),
            parent_ingested=False,
        )

    def op_review(self, *, unit_id: str, reviewer: str, decision: str, **_: Any) -> Outcome:
        """Record an acceptance decision. The self-acceptance rule is prose only."""
        receipt = self._read(unit_id)
        if receipt is None:
            return refuse("UNKNOWN_UNIT", unit_id=unit_id)
        receipt["acceptance"] = decision
        receipt["reviewer_id"] = reviewer
        self._write(unit_id, receipt)
        return ok(unit_id=unit_id, acceptance=decision, reviewer_id=reviewer)

    def op_state(self, *, unit_id: str, **_: Any) -> Outcome:
        receipt = self._read(unit_id)
        if receipt is None:
            return refuse("UNKNOWN_UNIT", unit_id=unit_id)
        return ok(
            unit_id=unit_id,
            obzio_state=receipt.get("state"),
            provider_state=receipt.get("provider_state"),
            result_commit_id=receipt.get("result_commit_id"),
            acceptance=receipt.get("acceptance"),
            completion_actor=receipt.get("completion_actor"),
            artifact_count=len(receipt.get("reported_artifacts", [])),
            verified_artifacts=0,
        )

    def op_restart(self, **_: Any) -> Outcome:
        """Re-read receipts from disk.

        G0 does recover *something* after process loss, which is why this is
        implemented rather than declared missing.  What it recovers is the last
        self-report, so a false completion survives the restart intact.
        """
        units = sorted(path.stem for path in self.receipt_dir.glob("*.json"))
        return ok(units_recovered=len(units), units=units, source="mutable receipt files")

    def op_verify(self, **_: Any) -> Outcome:
        """Check pinned *input* manifests only.

        This is the whole of v001's corruption detection as it applies to the
        controller: inputs were hashed, results were not.  ``artifact_coverage``
        is reported so a scorer can see the gap instead of inferring it.
        """
        checked = 0
        drifted: list[str] = []
        for path in sorted(self.receipt_dir.glob("*.json")):
            receipt = json.loads(path.read_text(encoding="utf-8"))
            recorded = receipt.get("input_manifest_sha256")
            if recorded is None:
                continue
            checked += 1
            if sha256_text(canonical(receipt.get("pinned_inputs", {}))) != recorded:
                drifted.append(receipt["unit_id"])
        return ok(
            inputs_checked=checked,
            input_drift=drifted,
            artifact_coverage=0,
            artifacts_reverified=0,
            drift_detected=[],
            ledger_chain_valid=None,
        )

    def op_tamper(self, *, target: str, kind: str = "corrupt", **kwargs: Any) -> Outcome:
        if target == "artifact":
            return self.tamper_artifact(path=kwargs["path"], kind=kind)
        if target == "record":
            unit_id = kwargs["unit_id"]
            receipt = self._read(unit_id)
            if receipt is None:
                return refuse("UNKNOWN_UNIT", unit_id=unit_id)
            receipt.update(kwargs.get("fields", {}))
            self._write(unit_id, receipt)
            return ok(target=target, unit_id=unit_id, kind=kind)
        # G0 has no ledger, so there is no log to truncate, reorder or edit.
        return unsupported(f"tamper:{target}")

    # Capabilities that do not exist at the pinned pre-amendment commit are
    # left unimplemented on purpose: lease, ingest and recover.  The base class
    # reports NOT_SUPPORTED for each, which is the measurement.


def build(*, root: Path, clock: Clock) -> G0Controller:
    return G0Controller(root=root, clock=clock)


def digest_of_source() -> str:
    """Digest this generation's own source, so a score names the code it scored."""
    return sha256_bytes(Path(__file__).read_bytes())
