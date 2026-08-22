#!/usr/bin/env python3
"""Facilities shared by every scored generation, so differences are real.

Anything in here is deliberately *not* part of what is being measured: an
artifact store is filesystem access, and clock advance is test scaffolding.
Both were equally available to the pre-amendment controller and to this
factory.  Keeping them in one place stops an accidental harness advantage from
being read as generational progress.

The measured differences live in each generation's custody logic: whether a
result is verified, whether authority is checked, whether a lost callback is
replayed, whether drift after admission is ever noticed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .controller_api import Outcome, ok, refuse, sha256_bytes

AUTO = "@auto"


class GenerationSupport:
    """Artifact store, clock control and claim resolution shared by generations."""

    @property
    def artifact_dir(self) -> Path:
        path = Path(self.root) / "artifacts"  # type: ignore[attr-defined]
        path.mkdir(parents=True, exist_ok=True)
        return path

    # -- shared operations --------------------------------------------------

    def op_advance_clock(self, *, seconds: float) -> Outcome:
        self.clock.advance(seconds)  # type: ignore[attr-defined]
        return ok(now=self.clock.now())  # type: ignore[attr-defined]

    def op_write_artifact(self, *, path: str, content: str) -> Outcome:
        target = self.artifact_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        target.write_bytes(data)
        return ok(path=path, sha256=sha256_bytes(data), bytes=len(data))

    # -- helpers -----------------------------------------------------------

    def read_artifact(self, path: str) -> bytes | None:
        target = self.artifact_dir / path
        if not target.is_file():
            return None
        return target.read_bytes()

    def resolve_claims(self, artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace ``@auto`` placeholders with the store's actual bytes.

        Cases declare what a worker *claims* about its artifacts.  ``@auto``
        means "claim the truth", which lets a case be written without embedding
        a digest, so the same case text works for every generation and stays
        readable.  A case that wants to model a lying worker states the false
        value literally instead.
        """
        resolved: list[dict[str, Any]] = []
        for artifact in artifacts:
            entry = dict(artifact)
            data = self.read_artifact(entry.get("path", ""))
            if entry.get("sha256") == AUTO:
                entry["sha256"] = sha256_bytes(data) if data is not None else AUTO
            if entry.get("bytes") == AUTO:
                entry["bytes"] = len(data) if data is not None else 0
            resolved.append(entry)
        return resolved

    # -- immutable locator store -------------------------------------------
    #
    # A result document records the locator it can be read back from.  Modelling
    # the locator as a separate store, rather than trusting the string, is what
    # makes "the record was absent at its declared result_commit_id" a testable
    # condition.  Cohort a6 observed exactly that failure on unit a3-u01 while
    # reviewing another cohort, which is why it is represented here.

    @property
    def locator_dir(self) -> Path:
        path = Path(self.root) / "locators"  # type: ignore[attr-defined]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _locator_path(self, locator: str) -> Path:
        return self.locator_dir / (sha256_bytes(locator.encode("utf-8")) + ".json")

    def publish_result(self, locator: str, payload: str) -> None:
        self._locator_path(locator).write_text(payload, encoding="utf-8")

    def resolve_locator(self, locator: str) -> str | None:
        target = self._locator_path(locator)
        if not target.is_file():
            return None
        return target.read_text(encoding="utf-8")

    def tamper_locator(self, *, locator: str, kind: str) -> Outcome:
        target = self._locator_path(locator)
        if kind == "delete":
            if target.is_file():
                target.unlink()
            return ok(locator=locator, kind=kind)
        if kind == "corrupt":
            if not target.is_file():
                return refuse("LOCATOR_UNRESOLVED", locator=locator)
            target.write_text(target.read_text(encoding="utf-8") + "\ntampered", encoding="utf-8")
            return ok(locator=locator, kind=kind)
        return refuse("INVALID_REQUEST", locator=locator, kind=kind)

    def tamper_artifact(self, *, path: str, kind: str) -> Outcome:
        target = self.artifact_dir / path
        if kind == "delete":
            if target.is_file():
                target.unlink()
            return ok(target=path, kind=kind)
        if kind == "corrupt":
            if not target.is_file():
                return refuse("ARTIFACT_MISSING", target=path)
            data = target.read_bytes()
            target.write_bytes(data + b"\x00tampered")
            return ok(target=path, kind=kind, new_sha256=sha256_bytes(target.read_bytes()))
        return refuse("INVALID_REQUEST", target=path, kind=kind)
