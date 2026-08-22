#!/usr/bin/env python3
"""Crash-consistent write primitives with injectable durability boundaries.

Every durable write in the custody machine goes through this module so that a
fault can be placed on either side of the boundary that actually decides what
survives a crash:

* append-only journal records are flushed and fsynced, and a partial-write fault
  leaves a torn trailing record with no newline, which is what a killed process
  actually leaves behind;
* snapshots are written to a temporary file, fsynced, then renamed, so a crash
  before the rename leaves the *previous* snapshot intact plus an orphan temp
  file, and a crash after it leaves the new one.

The asymmetry matters: it is why the journal, not the snapshot, has to be the
source of truth during recovery.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .fault_injector import FaultInjector, ProcessLoss


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(payload: Any) -> bytes:
    """Deterministic JSON bytes, so hashes are stable across processes."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass
class JournalRead:
    records: list[dict[str, Any]]
    torn_bytes: int
    healthy_bytes: int

    @property
    def torn(self) -> bool:
        return self.torn_bytes > 0


class DurableIO:
    """Filesystem writes with announced fault points."""

    def __init__(self, root: Path, injector: FaultInjector) -> None:
        self.root = Path(root)
        self.injector = injector
        self.fsync_count = 0
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- helpers
    def path(self, rel: str) -> Path:
        return self.root / rel

    def _fsync_file(self, handle) -> None:
        handle.flush()
        os.fsync(handle.fileno())
        self.fsync_count += 1

    def _fsync_dir(self, directory: Path) -> None:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
            self.fsync_count += 1
        finally:
            os.close(fd)

    # ---------------------------------------------------------------- journal
    def append_record(self, rel: str, record: dict[str, Any], *, pre: str, partial: str, post: str) -> int:
        """Append one canonical JSON line, fsynced.

        Returns the number of bytes appended.  ``pre``/``partial``/``post`` name
        the fault points around the durability boundary.
        """
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = canonical_json(record) + b"\n"

        self.injector.crash_if(pre, rel=rel, bytes=len(data))
        tear = self.injector.arrive(partial, rel=rel, bytes=len(data))
        with open(target, "ab") as handle:
            if tear is not None and tear.kind == "PARTIAL_WRITE":
                fraction = float(tear.params.get("fraction", 0.5))
                cut = max(1, min(len(data) - 1, int(len(data) * fraction)))
                handle.write(data[:cut])
                self._fsync_file(handle)
                raise ProcessLoss(partial, tear.kind)
            handle.write(data)
            self._fsync_file(handle)
        self.injector.crash_if(post, rel=rel, bytes=len(data))
        return len(data)

    def read_records(self, rel: str) -> JournalRead:
        """Read an append-only log, tolerating a torn trailing record.

        A record is trusted only when it is newline terminated and parses.  The
        first record that fails either test ends the trusted prefix; nothing
        after it is replayed, because a crash can leave arbitrary bytes there.
        """
        target = self.path(rel)
        if not target.exists():
            return JournalRead([], 0, 0)
        raw = target.read_bytes()
        records: list[dict[str, Any]] = []
        healthy = 0
        torn = 0
        offset = 0
        while offset < len(raw):
            newline = raw.find(b"\n", offset)
            if newline == -1:
                torn = len(raw) - offset
                break
            line = raw[offset:newline]
            try:
                parsed = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                torn = len(raw) - offset
                break
            if not isinstance(parsed, dict):
                torn = len(raw) - offset
                break
            records.append(parsed)
            offset = newline + 1
            healthy = offset
        return JournalRead(records, torn, healthy)

    def heal_records(self, rel: str) -> int:
        """Truncate a log to its last trusted record; return bytes discarded."""
        read = self.read_records(rel)
        if not read.torn:
            return 0
        target = self.path(rel)
        with open(target, "r+b") as handle:
            handle.truncate(read.healthy_bytes)
            self._fsync_file(handle)
        self._fsync_dir(target.parent)
        return read.torn_bytes

    # --------------------------------------------------------------- snapshot
    def atomic_write(self, rel: str, data: bytes, *, pre: str, mid: str, post: str) -> None:
        """Write via temp-file + rename so a crash cannot leave a half snapshot."""
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")

        self.injector.crash_if(pre, rel=rel, bytes=len(data))
        with open(tmp, "wb") as handle:
            handle.write(data)
            self._fsync_file(handle)
        self.injector.crash_if(mid, rel=rel, bytes=len(data))
        os.replace(tmp, target)
        self._fsync_dir(target.parent)
        self.injector.crash_if(post, rel=rel, bytes=len(data))

    def read_json(self, rel: str) -> dict[str, Any] | None:
        target = self.path(rel)
        if not target.exists():
            return None
        try:
            parsed = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def orphan_temp_files(self) -> list[str]:
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*.tmp"))

    # --------------------------------------------------------------- artifacts
    def write_artifact(self, rel: str, data: bytes) -> int:
        """Write staged artifact bytes with pre/partial/post fault points."""
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.injector.crash_if("pre_artifact_write", rel=rel, bytes=len(data))
        tear = self.injector.arrive("artifact_write_partial", rel=rel, bytes=len(data))
        with open(target, "wb") as handle:
            if tear is not None and tear.kind == "PARTIAL_WRITE":
                fraction = float(tear.params.get("fraction", 0.5))
                cut = max(0, min(len(data) - 1, int(len(data) * fraction)))
                handle.write(data[:cut])
                self._fsync_file(handle)
                raise ProcessLoss("artifact_write_partial", tear.kind)
            handle.write(data)
            self._fsync_file(handle)
        self.injector.crash_if("post_artifact_write", rel=rel, bytes=len(data))
        return len(data)

    def read_artifact(self, rel: str) -> bytes | None:
        target = self.path(rel)
        if not target.exists():
            return None
        return target.read_bytes()
