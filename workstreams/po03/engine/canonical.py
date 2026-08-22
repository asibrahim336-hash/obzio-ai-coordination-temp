"""Durability primitives shared by every custody mechanism.

Two rules are enforced here rather than restated in each caller.

Canonical encoding
    A hash is only evidence if two honest processes derive the same bytes from
    the same value.  ``canonical`` is byte-identical to the encoding the
    coordinator's control plane uses, so a hash computed by a subordinate and a
    hash computed by the integration controller are comparable.

Durability
    ``atomic_write_bytes`` never leaves a reader looking at a half-written
    file: bytes land in a sibling temporary file, are flushed and fsynced, and
    become visible through a single ``os.replace``.  The containing directory
    is fsynced too, because on POSIX the rename itself is only durable once the
    directory entry is.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import json
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64
SHA256_HEX_LENGTH = 64
_READ_CHUNK = 65536


def utc_now() -> str:
    """Second-resolution UTC stamp, matching the control plane's format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_bytes(payload: Any) -> bytes:
    return canonical(payload).encode("utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_payload(payload: Any) -> str:
    return sha256_text(canonical(payload))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fsync_dir(path: Path) -> None:
    """Make a directory entry durable, tolerating platforms that refuse it."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError as exc:  # pragma: no cover - platform dependent
        if exc.errno not in (errno.EINVAL, errno.ENOTSUP, errno.EACCES):
            raise
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> str:
    """Publish ``data`` at ``path`` in one observable step; return its sha256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}-{os.urandom(6).hex()}"
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_dir(path.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
    return sha256_bytes(data)


def atomic_write_text(path: Path, text: str) -> str:
    return atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, payload: Any) -> str:
    """Write indented JSON for human review; hash the exact bytes written."""
    return atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def append_line_durably(path: Path, line: str) -> None:
    """Append one newline-terminated record and fsync before returning.

    Appending a single line shorter than the filesystem block size is the
    closest a portable pure-Python process gets to an atomic record write; the
    fsync is what makes the record survive process and machine loss.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line if line.endswith("\n") else line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def create_exclusive(path: Path, data: bytes) -> bool:
    """Create ``path`` exactly once.

    Returns ``True`` for the caller that created the file and ``False`` for
    every later caller.  This is the single atomic primitive that turns
    at-least-once delivery into exactly-once effect: the winner is decided by
    the filesystem, not by an application-level check that can race.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}-{os.urandom(6).hex()}"
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        fsync_dir(path.parent)
        return True
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@contextlib.contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    """Serialise a read-modify-append critical section across threads and processes.

    ``flock`` is held on a dedicated lock file rather than on the data file, so
    a reader never has to open the data file for writing, and a crash releases
    the lock with the file descriptor instead of leaving a stale marker behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)
