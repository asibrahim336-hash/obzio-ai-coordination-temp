#!/usr/bin/env python3
"""PO03-WA-005 -- a partial artifact write cannot reach RESULT_STAGED.

Frozen hypothesis
-----------------
"A partial artifact write cannot reach RESULT_STAGED."

A result slot that is half-written is more dangerous than one that is missing.
Missing work is obvious and gets retried; a truncated artifact alongside a
confident ``RESULT_STAGED`` marker looks complete to every downstream consumer
and to any reviewer who checks state rather than bytes.

Design -- stage into the dark, publish atomically
-------------------------------------------------
``StagingGate.stage`` never writes into the published slot.  It writes every
artifact into a sibling scratch directory, fsyncs each one, then runs a
**full readback verification** of every declared artifact -- recomputing the
SHA-256 from the bytes on disk and comparing the byte count -- before the
scratch directory is promoted with a single ``os.rename``.

Three properties follow, and each is asserted separately by the suite:

1. Verification reads the *file*, not the buffer it thinks it wrote.  A
   truncating filesystem, a short write or a crash mid-artifact is therefore
   detected rather than assumed away.
2. Promotion is one rename.  There is no window in which the published slot
   contains some artifacts and not others.
3. A failed stage leaves ``RESULT_STAGING``.  It never advances the state, and
   it never leaves scratch debris behind for a later run to mistake for output.

Crash injection is real control flow, not a mock: ``CrashInjector`` raises from
inside the write loop at a chosen artifact index and truncation point.

Executable entry point::

    python3 staging_gate.py --demo
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class StagingRefused(Exception):
    """Staging did not complete; the slot remains RESULT_STAGING."""

    def __init__(self, reason: str, detail: str, failures: list[dict[str, Any]] | None = None) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail
        self.failures = failures or []


class InjectedCrash(Exception):
    """A deliberate mid-write process loss."""


@dataclass(frozen=True)
class DeclaredArtifact:
    """What the producer claims it will write, hashed before any write."""

    logical_name: str
    payload: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()

    @property
    def bytes(self) -> int:
        return len(self.payload)

    def declaration(self) -> dict[str, Any]:
        return {"logical_name": self.logical_name, "sha256": self.sha256, "bytes": self.bytes}


@dataclass
class CrashInjector:
    """Inject one of two independent fault families into the write loop.

    The two are deliberately separate because they fail closed by different
    mechanisms, and a gate that only survives the loud one is not safe:

    * ``truncate_at_index`` / ``truncate_to`` -- a **silent short write**.  The
      loop completes normally and nothing raises, so only readback
      verification can detect it.  This is the dangerous case.
    * ``crash_at_index`` / ``crash_after_index`` -- a **loud process loss**
      before or after a given artifact.  Control flow aborts immediately.
    """

    crash_at_index: int | None = None
    crash_after_index: int | None = None
    truncate_at_index: int | None = None
    truncate_to: int | None = None

    def intercept(self, index: int, payload: bytes) -> bytes:
        if self.crash_at_index == index:
            raise InjectedCrash(f"process lost before writing artifact {index}")
        if self.truncate_at_index == index and self.truncate_to is not None:
            return payload[: self.truncate_to]
        return payload

    def crash_after_write(self, index: int) -> None:
        if self.crash_after_index == index:
            raise InjectedCrash(f"process lost after writing artifact {index}")


class StagingGate:
    """Publishes a result slot only when every declared artifact verifies."""

    def __init__(self, slot: Path) -> None:
        self.slot = Path(slot)
        self.slot.parent.mkdir(parents=True, exist_ok=True)
        self.state = "RESULT_STAGING"
        self.verification_report: list[dict[str, Any]] = []

    @property
    def scratch(self) -> Path:
        return self.slot.parent / f".{self.slot.name}.staging"

    def _write_artifact(self, directory: Path, name: str, payload: bytes) -> None:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    def _verify(self, directory: Path, declared: list[DeclaredArtifact]) -> list[dict[str, Any]]:
        """Recompute every hash from bytes on disk.  Returns the failures."""
        failures: list[dict[str, Any]] = []
        self.verification_report = []
        for artifact in declared:
            path = directory / artifact.logical_name
            if not path.exists():
                failures.append({"logical_name": artifact.logical_name, "reason": "MISSING_ARTIFACT"})
                self.verification_report.append({"logical_name": artifact.logical_name, "verified": False})
                continue
            observed = path.read_bytes()
            observed_sha = hashlib.sha256(observed).hexdigest()
            ok = observed_sha == artifact.sha256 and len(observed) == artifact.bytes
            if not ok:
                failures.append(
                    {
                        "logical_name": artifact.logical_name,
                        "reason": "BYTES_TRUNCATED" if len(observed) < artifact.bytes else "HASH_MISMATCH",
                        "declared_sha256": artifact.sha256,
                        "observed_sha256": observed_sha,
                        "declared_bytes": artifact.bytes,
                        "observed_bytes": len(observed),
                    }
                )
            self.verification_report.append({"logical_name": artifact.logical_name, "verified": ok})
        return failures

    def _discard_scratch(self) -> None:
        if self.scratch.exists():
            shutil.rmtree(self.scratch)

    def stage(self, declared: list[DeclaredArtifact], injector: CrashInjector | None = None) -> str:
        """Attempt to reach RESULT_STAGED.  Any shortfall keeps RESULT_STAGING."""
        if not declared:
            raise StagingRefused("EMPTY_DECLARATION", "a staged result requires at least one artifact")
        injector = injector or CrashInjector()

        self._discard_scratch()
        self.scratch.mkdir(parents=True)
        try:
            for index, artifact in enumerate(declared):
                payload = injector.intercept(index, artifact.payload)
                self._write_artifact(self.scratch, artifact.logical_name, payload)
                injector.crash_after_write(index)
        except InjectedCrash as crash:
            # A crashed writer does not get to clean up after itself; leave the
            # scratch directory exactly as the dead process left it and prove
            # recovery handles it.
            raise StagingRefused("PROCESS_LOST_MID_WRITE", str(crash)) from crash

        failures = self._verify(self.scratch, declared)
        if failures:
            self._discard_scratch()
            raise StagingRefused(
                "ARTIFACT_VERIFICATION_FAILED",
                f"{len(failures)} of {len(declared)} artifacts failed readback",
                failures,
            )

        # Single atomic promotion: the slot never exists half-populated.
        if self.slot.exists():
            raise StagingRefused("SLOT_ALREADY_PUBLISHED", f"{self.slot} already exists")
        os.rename(self.scratch, self.slot)
        directory_fd = os.open(self.slot.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        self.state = "RESULT_STAGED"
        return self.state

    def recover(self, declared: list[DeclaredArtifact]) -> dict[str, Any]:
        """Re-entry after a crash: verify what survived and discard debris."""
        if self.slot.exists():
            failures = self._verify(self.slot, declared)
            return {"action": "PUBLISHED_SLOT_VERIFIED", "failures": failures, "state": self.state}
        debris = sorted(path.name for path in self.scratch.rglob("*")) if self.scratch.exists() else []
        self._discard_scratch()
        return {
            "action": "SCRATCH_DISCARDED",
            "debris_found": debris,
            "slot_published": self.slot.exists(),
            "state": self.state,
        }


def _sample_artifacts() -> list[DeclaredArtifact]:
    return [
        DeclaredArtifact("component.py", b"# component\n" + b"x" * 400),
        DeclaredArtifact("evidence/output.txt", b"observed output\n" + b"y" * 900),
        DeclaredArtifact("FINDING.md", b"# finding\n" + b"z" * 250),
    ]


def reproduce_partial_write(directory: Path) -> dict[str, Any]:
    """Truncate each artifact in turn and confirm the slot is never published."""
    declared = _sample_artifacts()
    attempts = []
    for index, artifact in enumerate(declared):
        gate = StagingGate(directory / f"slot-truncate-{index}")
        injector = CrashInjector(truncate_at_index=index, truncate_to=artifact.bytes // 2)
        try:
            gate.stage(declared, injector)
        except StagingRefused as refusal:
            attempts.append(
                {
                    "truncated_artifact": artifact.logical_name,
                    "state": gate.state,
                    "reason": refusal.reason,
                    "slot_published": gate.slot.exists(),
                    "recovery": gate.recover(declared),
                }
            )
        else:
            attempts.append(
                {
                    "truncated_artifact": artifact.logical_name,
                    "state": gate.state,
                    "reason": "NONE",
                    "slot_published": gate.slot.exists(),
                    "recovery": None,
                }
            )

    clean = StagingGate(directory / "slot-clean")
    clean_state = clean.stage(declared)
    return {
        "truncation_attempts": attempts,
        "any_reached_staged": any(item["state"] == "RESULT_STAGED" for item in attempts),
        "any_slot_published": any(item["slot_published"] for item in attempts),
        "clean_stage_state": clean_state,
        "clean_slot_files": sorted(
            path.relative_to(clean.slot).as_posix() for path in clean.slot.rglob("*") if path.is_file()
        ),
    }


def demo() -> int:
    with tempfile.TemporaryDirectory() as directory:
        report = reproduce_partial_write(Path(directory))
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
