"""Executable probes against read-only repository controls.

A probe is how this unit decides whether a candidate claim is true. It does not
consult a summary of what a control does; it runs the control on a document it
constructs and reads the exit status and the reported errors.

Every probe here is read-only with respect to the repository. Documents are
written into a private temporary directory outside the working tree, the
interpreter is invoked with bytecode writing disabled so no ``__pycache__``
appears next to a read-only control, and nothing is modified in
``workstreams/po03/tools`` or ``workstreams/po03/contracts``.

The baseline document is a valid, fully committed transactional result that the
seeded validator accepts. Each probe applies exactly one mutation to a copy, so
the observation isolates the field under test: if the baseline were already
rejected, an admitted mutation would prove nothing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .canonical import canonical_bytes, digest, digest_bytes

VALIDATOR_RELPATH = "workstreams/po03/tools/validate_contracts.py"
SCHEMA_RELPATH = "workstreams/po03/contracts/transactional-result.schema.json"
SEEDED_TESTS_RELPATH = "workstreams/po03/tests"
WORKFLOW_RELPATH = ".github/workflows/po03-contracts.yml"

ADMITTED = "ADMITTED"
REJECTED = "REJECTED"


class ProbeUnavailable(Exception):
    """A probe could not be run in this runtime, so it asserts nothing."""


def repository_root(start: Path | None = None) -> Path:
    """Locate the repository root by walking up for a .git entry."""
    here = (start or Path(__file__).resolve()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / ".git").exists():
            return candidate
    raise ProbeUnavailable(f"no repository root above {here}")


def baseline_document() -> dict[str, Any]:
    """A minimal transactional result the seeded validator accepts unmodified."""
    return {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": "PROBE-BASELINE",
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "immutable_input_manifest_sha256": "0" * 64,
        "acceptance_contract_sha256": "1" * 64,
        "provider_state": "COMPLETED",
        "obzio_state": "COMPLETED",
        "attempt": {
            "attempt_id": "PROBE-BASELINE-A01",
            "idempotency_key": "probe:baseline:a01",
            "lease_id": "lease-probe-baseline",
            "fence_token": 1,
            "provider_run_id": "probe-run",
            "worker_id": "probe-worker",
            "heartbeat_at": None,
            "checkpoint_seq": 0,
        },
        "result_transaction": {
            "result_txn_id": "txn-probe-baseline",
            "state": "INGESTED",
            "manifest_uri": "refs/probe/baseline@commit:manifest.json",
            "manifest_sha256": "2" * 64,
            "artifact_count": 1,
            "total_bytes": 11,
            "committed_at": "2026-08-22T09:00:00Z",
            "verified_at": "2026-08-22T09:00:01Z",
            "parent_ingested_at": "2026-08-22T09:00:02Z",
            "result_commit_id": "3" * 40,
        },
        "artifacts": [
            {
                "artifact_id": "af-probe-1",
                "logical_name": "probe.txt",
                "content_uri": f"refs/probe/baseline@{'3' * 40}:probe.txt",
                "sha256": "4" * 64,
                "bytes": 11,
                "media_type": "text/plain; charset=utf-8",
                "readback_verified_at": "2026-08-22T09:00:03Z",
            }
        ],
        "completion_actor": "coordinator",
        "independent_acceptance": {
            "state": "NOT_TESTED",
            "reviewer_id": None,
            "receipt_uri": None,
        },
    }


@dataclass(frozen=True)
class ProbeObservation:
    """What a probe saw, in enough detail to re-run it."""

    probe_id: str
    command: list[str]
    returncode: int
    disposition: str
    reported_errors: list[str]
    detail: dict[str, Any]

    def as_record(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "detail": self.detail,
            "disposition": self.disposition,
            "observation_sha256": digest(
                {
                    "detail": self.detail,
                    "disposition": self.disposition,
                    "probe_id": self.probe_id,
                    "reported_errors": self.reported_errors,
                    "returncode": self.returncode,
                }
            ),
            "probe_id": self.probe_id,
            "reported_errors": list(self.reported_errors),
            "returncode": self.returncode,
        }


class RepositoryProbes:
    """The probe registry, bound to one repository checkout."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or repository_root()).resolve()
        self.validator = self.root / VALIDATOR_RELPATH
        self.schema = self.root / SCHEMA_RELPATH
        if not self.validator.is_file():
            raise ProbeUnavailable(f"read-only control missing: {VALIDATOR_RELPATH}")
        if not self.schema.is_file():
            raise ProbeUnavailable(f"read-only control missing: {SCHEMA_RELPATH}")

    # -- plumbing ---------------------------------------------------------

    def _run_validator(self, document: dict[str, Any]) -> tuple[list[str], int, list[str]]:
        workdir = Path(tempfile.mkdtemp(prefix="wa020-probe-"))
        try:
            target = workdir / "document.json"
            target.write_bytes(canonical_bytes(document))
            command = [sys.executable, "-I", "-B", str(self.validator), "result", str(target)]
            environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(workdir),
                env=environment,
                check=False,
            )
            lines = [line for line in completed.stdout.splitlines() if line.strip()]
            errors = [line.removeprefix("INVALID: ") for line in lines if line.startswith("INVALID: ")]
            # The absolute temporary path is runtime noise, not evidence.
            printable = [str(part) for part in command[:-1]] + ["<temporary document>"]
            return printable, completed.returncode, errors
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _validator_probe(
        self,
        probe_id: str,
        mutate: Callable[[dict[str, Any]], None],
        mutation: str,
    ) -> ProbeObservation:
        document = baseline_document()
        mutate(document)
        command, returncode, errors = self._run_validator(document)
        return ProbeObservation(
            probe_id=probe_id,
            command=command,
            returncode=returncode,
            disposition=ADMITTED if returncode == 0 else REJECTED,
            reported_errors=errors,
            detail={
                "control": VALIDATOR_RELPATH,
                "control_sha256": digest_bytes(self.validator.read_bytes()),
                "document_sha256": digest(document),
                "mutation": mutation,
            },
        )

    def baseline_is_admitted(self) -> ProbeObservation:
        """Control probe: the unmutated baseline must be admitted."""
        return self._validator_probe(
            "PROBE-BASELINE-ADMITTED",
            lambda document: None,
            "none; the unmutated baseline",
        )

    # -- probes -----------------------------------------------------------

    def completion_actor(self) -> ProbeObservation:
        def mutate(document: dict[str, Any]) -> None:
            document["completion_actor"] = "the-producer-itself"

        return self._validator_probe(
            "PROBE-VALIDATOR-COMPLETION-ACTOR",
            mutate,
            "completion_actor set to a non-coordinator while obzio_state is COMPLETED",
        )

    def transaction_state_enum(self) -> ProbeObservation:
        def mutate(document: dict[str, Any]) -> None:
            document["result_transaction"]["state"] = "DEFINITELY_NOT_A_STATE"

        return self._validator_probe(
            "PROBE-VALIDATOR-TRANSACTION-STATE-ENUM",
            mutate,
            "result_transaction.state set to a value absent from the schema enumeration",
        )

    def byte_accounting(self) -> ProbeObservation:
        def mutate(document: dict[str, Any]) -> None:
            document["result_transaction"]["total_bytes"] = 999

        return self._validator_probe(
            "PROBE-VALIDATOR-BYTE-ACCOUNTING",
            mutate,
            "result_transaction.total_bytes disagrees with the sum of artifact bytes",
        )

    def logical_name_uniqueness(self) -> ProbeObservation:
        def mutate(document: dict[str, Any]) -> None:
            first = document["artifacts"][0]
            duplicate = dict(first)
            duplicate["artifact_id"] = "af-probe-2"
            document["artifacts"].append(duplicate)
            document["result_transaction"]["artifact_count"] = 2
            document["result_transaction"]["total_bytes"] = 22

        return self._validator_probe(
            "PROBE-VALIDATOR-LOGICAL-NAME-UNIQUENESS",
            mutate,
            "a second artifact repeats the first artifact's logical_name and content_uri",
        )

    def producer_self_acceptance(self) -> ProbeObservation:
        def mutate(document: dict[str, Any]) -> None:
            document["independent_acceptance"] = {
                "state": "ACCEPTED",
                "reviewer_id": document["attempt"]["worker_id"],
                "receipt_uri": "refs/probe/baseline@commit:receipt.json",
            }

        return self._validator_probe(
            "PROBE-VALIDATOR-SELF-ACCEPTANCE",
            mutate,
            "independent_acceptance.reviewer_id equals attempt.worker_id",
        )

    def provider_completion_without_commit(self) -> ProbeObservation:
        def mutate(document: dict[str, Any]) -> None:
            document["obzio_state"] = "RUNNING"
            document["result_transaction"]["result_commit_id"] = None
            document["result_transaction"]["state"] = "STAGING"

        return self._validator_probe(
            "PROBE-VALIDATOR-PROVIDER-COMPLETION-WITHOUT-COMMIT",
            mutate,
            "provider_state COMPLETED with no result_commit_id and obzio_state RUNNING",
        )

    def schema_declares_state_enum(self) -> ProbeObservation:
        payload = self.schema.read_bytes()
        schema = json.loads(payload.decode("utf-8"))
        enum = (
            schema.get("properties", {})
            .get("result_transaction", {})
            .get("properties", {})
            .get("state", {})
            .get("enum")
        )
        declared = isinstance(enum, list) and bool(enum)
        return ProbeObservation(
            probe_id="PROBE-SCHEMA-DECLARES-STATE-ENUM",
            command=["read", SCHEMA_RELPATH, "$.properties.result_transaction.properties.state.enum"],
            returncode=0,
            disposition="DECLARED" if declared else "ABSENT",
            reported_errors=[],
            detail={
                "control": SCHEMA_RELPATH,
                "control_sha256": digest_bytes(payload),
                "enum": enum if declared else None,
            },
        )

    def control_digests(self) -> ProbeObservation:
        observed: dict[str, str] = {}
        for relpath in (VALIDATOR_RELPATH, SCHEMA_RELPATH, WORKFLOW_RELPATH):
            path = self.root / relpath
            observed[relpath] = digest_bytes(path.read_bytes()) if path.is_file() else "ABSENT"
        return ProbeObservation(
            probe_id="PROBE-CONTROL-DIGESTS",
            command=["sha256", VALIDATOR_RELPATH, SCHEMA_RELPATH, WORKFLOW_RELPATH],
            returncode=0,
            disposition="OBSERVED",
            reported_errors=[],
            detail={"observed_sha256": observed},
        )

    def seeded_control_suite(self) -> ProbeObservation:
        command = [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "unittest",
            "discover",
            "-s",
            SEEDED_TESTS_RELPATH,
            "-p",
            "test_*.py",
        ]
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(self.root),
            env=environment,
            check=False,
        )
        summary = next(
            (line for line in completed.stderr.splitlines() if line.startswith("Ran ")),
            "",
        )
        total = int(summary.split()[1]) if summary else 0
        return ProbeObservation(
            probe_id="PROBE-SEEDED-CONTROL-SUITE",
            command=command,
            returncode=completed.returncode,
            disposition="PASS" if completed.returncode == 0 else "FAIL",
            reported_errors=[],
            detail={"summary_line": summary, "test_count": total},
        )

    # -- registry ---------------------------------------------------------

    def registry(self) -> dict[str, Callable[[], ProbeObservation]]:
        return {
            "PROBE-BASELINE-ADMITTED": self.baseline_is_admitted,
            "PROBE-CONTROL-DIGESTS": self.control_digests,
            "PROBE-SCHEMA-DECLARES-STATE-ENUM": self.schema_declares_state_enum,
            "PROBE-SEEDED-CONTROL-SUITE": self.seeded_control_suite,
            "PROBE-VALIDATOR-BYTE-ACCOUNTING": self.byte_accounting,
            "PROBE-VALIDATOR-COMPLETION-ACTOR": self.completion_actor,
            "PROBE-VALIDATOR-LOGICAL-NAME-UNIQUENESS": self.logical_name_uniqueness,
            "PROBE-VALIDATOR-PROVIDER-COMPLETION-WITHOUT-COMMIT": self.provider_completion_without_commit,
            "PROBE-VALIDATOR-SELF-ACCEPTANCE": self.producer_self_acceptance,
            "PROBE-VALIDATOR-TRANSACTION-STATE-ENUM": self.transaction_state_enum,
        }

    def run(self, probe_id: str) -> ProbeObservation:
        registry = self.registry()
        if probe_id not in registry:
            raise ProbeUnavailable(f"no probe named {probe_id}")
        return registry[probe_id]()

    def run_all(self) -> dict[str, ProbeObservation]:
        return {probe_id: probe() for probe_id, probe in sorted(self.registry().items())}
