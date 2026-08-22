#!/usr/bin/env python3
"""PO03-WA-006 -- post-commit process loss without rerunning external effects.

Frozen hypothesis
-----------------
"Post-commit process loss is recovered without rerunning external effects."

An external effect -- pushing a commit, posting a callback, spending money --
cannot be undone by the recovering process.  So the dangerous window is not the
effect itself but the gap between *performing* it and *recording that it was
performed*.  A process that dies in that gap comes back believing the effect is
still outstanding.  If recovery simply resumes the workflow, the effect happens
twice.

Design -- write-ahead intent, then reconcile by probe
-----------------------------------------------------
Every effect is wrapped in a three-phase journal protocol:

1. **INTENT** is journalled *before* the effect is attempted, carrying a
   deterministic ``effect_key``.  A dying process therefore always leaves
   evidence that it was about to act.
2. The effect executes.
3. **APPLIED** is journalled after it returns.

Recovery reads the journal.  For any key with an ``INTENT`` and no ``APPLIED``
the outcome is genuinely unknown, and guessing either way is wrong: assuming it
failed double-spends, assuming it succeeded loses the work.  So recovery
**probes the external system** by effect key and reconciles from the observed
truth.  The probe is the part that makes at-most-once achievable; without an
externally observable key, recovery can only report ``NOT_SUPPORTED``, which
this component does rather than guessing.

``ExternalSystem`` counts real executions per key.  Every test asserts on that
counter, so "did not rerun the effect" is measured at the effect itself rather
than inferred from a status field.

Executable entry point::

    python3 effect_journal.py --demo
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class ProcessLost(Exception):
    """A deliberate process death at a chosen point in the protocol."""


class EffectNotProbeable(Exception):
    """The external system cannot be queried by effect key."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class ExternalSystem:
    """An effect target that records how many times each key really executed."""

    def __init__(self, probeable: bool = True) -> None:
        self.executions: dict[str, int] = {}
        self.records: dict[str, dict[str, Any]] = {}
        self.probeable = probeable
        self.probes = 0

    def apply(self, effect_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.executions[effect_key] = self.executions.get(effect_key, 0) + 1
        self.records[effect_key] = {"effect_key": effect_key, "payload": payload, "at": _utc_now()}
        return self.records[effect_key]

    def probe(self, effect_key: str) -> dict[str, Any] | None:
        """Ask the external system whether this key was already applied."""
        if not self.probeable:
            raise EffectNotProbeable(f"{effect_key} cannot be observed externally")
        self.probes += 1
        return self.records.get(effect_key)

    def total_executions(self) -> int:
        return sum(self.executions.values())


class EffectJournal:
    """A durable append-only journal of effect intents and applications."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch()

    def append(self, record: dict[str, Any]) -> None:
        with self.path.open("ab", buffering=0) as stream:
            stream.write(json.dumps(record, sort_keys=True).encode() + b"\n")
            os.fsync(stream.fileno())

    def entries(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.path.read_text().splitlines() if line]

    def phase_of(self, effect_key: str) -> str:
        """``NONE``, ``INTENT`` (outcome unknown) or ``APPLIED`` (confirmed)."""
        phase = "NONE"
        for entry in self.entries():
            if entry["effect_key"] != effect_key:
                continue
            if entry["phase"] == "INTENT" and phase == "NONE":
                phase = "INTENT"
            elif entry["phase"] == "APPLIED":
                phase = "APPLIED"
        return phase


class CommitWorkflow:
    """Commits a result, then performs one external effect, under the journal."""

    #: Points at which the process may be lost, in protocol order.
    CRASH_POINTS = (
        "before_commit",
        "after_commit_before_intent",
        "after_intent_before_effect",
        "after_effect_before_applied",
        "after_applied",
    )

    def __init__(self, directory: Path, external: ExternalSystem) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.journal = EffectJournal(self.directory / "effects.jsonl")
        self.commit_path = self.directory / "commit.json"
        self.external = external

    # -- durable commit -----------------------------------------------------

    def committed(self) -> dict[str, Any] | None:
        if not self.commit_path.exists():
            return None
        return json.loads(self.commit_path.read_text())

    def _commit(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = {"task_id": task_id, "payload": payload, "committed_at": _utc_now()}
        descriptor, temporary = tempfile.mkstemp(dir=self.directory)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json.dumps(record, sort_keys=True).encode() + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.commit_path)
        return record

    # -- the protocol -------------------------------------------------------

    def run(self, task_id: str, payload: dict[str, Any], crash_at: str | None = None) -> dict[str, Any]:
        """Commit then apply the effect, dying at ``crash_at`` if given."""
        effect_key = f"effect:{task_id}"

        def die(point: str) -> None:
            if crash_at == point:
                raise ProcessLost(f"process lost {point}")

        die("before_commit")
        if self.committed() is None:
            self._commit(task_id, payload)
        die("after_commit_before_intent")

        if self.journal.phase_of(effect_key) == "NONE":
            self.journal.append({"phase": "INTENT", "effect_key": effect_key, "at": _utc_now()})
        die("after_intent_before_effect")

        self.external.apply(effect_key, payload)
        die("after_effect_before_applied")

        self.journal.append({"phase": "APPLIED", "effect_key": effect_key, "at": _utc_now()})
        die("after_applied")
        return {"task_id": task_id, "effect_key": effect_key, "state": "RESULT_COMMITTED"}

    # -- recovery -----------------------------------------------------------

    def recover(self, task_id: str) -> dict[str, Any]:
        """Resume after a loss without repeating a confirmed external effect."""
        effect_key = f"effect:{task_id}"
        commit = self.committed()
        phase = self.journal.phase_of(effect_key)

        if commit is None:
            return {
                "effect_key": effect_key,
                "journal_phase": phase,
                "action": "RESTART_FROM_SCRATCH",
                "effect_reapplied": False,
                "obzio_state": "RETRY_SCHEDULED",
            }

        if phase == "APPLIED":
            return {
                "effect_key": effect_key,
                "journal_phase": phase,
                "action": "ALREADY_COMPLETE_NO_ACTION",
                "effect_reapplied": False,
                "obzio_state": "RESULT_COMMITTED",
            }

        if phase == "NONE":
            # Committed but the intent was never journalled, so the effect
            # cannot have started.  Applying it now is safe and necessary.
            self.journal.append({"phase": "INTENT", "effect_key": effect_key, "at": _utc_now()})
            self.external.apply(effect_key, commit["payload"])
            self.journal.append({"phase": "APPLIED", "effect_key": effect_key, "at": _utc_now()})
            return {
                "effect_key": effect_key,
                "journal_phase": phase,
                "action": "EFFECT_APPLIED_FIRST_TIME",
                "effect_reapplied": False,
                "obzio_state": "RESULT_COMMITTED",
            }

        # phase == "INTENT": genuinely unknown.  Ask the external system.
        try:
            observed = self.external.probe(effect_key)
        except EffectNotProbeable:
            return {
                "effect_key": effect_key,
                "journal_phase": phase,
                "action": "RECONCILIATION_NOT_SUPPORTED",
                "effect_reapplied": False,
                "obzio_state": "RECOVERY_REQUIRED",
            }

        if observed is not None:
            # It did happen; only the record was lost.  Close the journal
            # without touching the external system again.
            self.journal.append({"phase": "APPLIED", "effect_key": effect_key, "at": _utc_now()})
            return {
                "effect_key": effect_key,
                "journal_phase": phase,
                "action": "CONFIRMED_BY_PROBE_JOURNAL_REPAIRED",
                "effect_reapplied": False,
                "obzio_state": "RESULT_COMMITTED",
            }

        self.external.apply(effect_key, commit["payload"])
        self.journal.append({"phase": "APPLIED", "effect_key": effect_key, "at": _utc_now()})
        return {
            "effect_key": effect_key,
            "journal_phase": phase,
            "action": "PROBE_SHOWED_NOT_APPLIED_SO_APPLIED",
            "effect_reapplied": False,
            "obzio_state": "RESULT_COMMITTED",
        }


def reproduce_crash_matrix(directory: Path, probeable: bool = True) -> dict[str, Any]:
    """Kill the process at every protocol point and recover in a fresh one."""
    outcomes = []
    for point in CommitWorkflow.CRASH_POINTS:
        slot = directory / f"crash-{point}"
        external = ExternalSystem(probeable=probeable)
        workflow = CommitWorkflow(slot, external)
        crashed = False
        try:
            workflow.run("PO03-WA-006", {"artifact_sha256": "e" * 64}, crash_at=point)
        except ProcessLost:
            crashed = True

        executions_before = external.total_executions()
        # A genuinely fresh workflow object over the same durable directory.
        recovered = CommitWorkflow(slot, external).recover("PO03-WA-006")
        outcomes.append(
            {
                "crash_point": point,
                "crashed": crashed,
                "executions_before_recovery": executions_before,
                "executions_after_recovery": external.total_executions(),
                "recovery_action": recovered["action"],
                "obzio_state": recovered["obzio_state"],
                "probes": external.probes,
            }
        )
    return {
        "probeable": probeable,
        "outcomes": outcomes,
        "max_executions_for_any_key": max(item["executions_after_recovery"] for item in outcomes),
    }


def demo() -> int:
    with tempfile.TemporaryDirectory() as directory:
        report = {
            "probeable_external_system": reproduce_crash_matrix(Path(directory) / "probeable"),
            "unprobeable_external_system": reproduce_crash_matrix(Path(directory) / "blind", probeable=False),
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv)
    if args.demo:
        return demo()
    parser.error("use --demo")
    return 2


if __name__ == "__main__":
    sys.exit(main())
