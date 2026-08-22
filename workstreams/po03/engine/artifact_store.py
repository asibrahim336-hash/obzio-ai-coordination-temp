"""Content-addressed artifact store: corruption becomes a named diagnostic.

An artifact whose bytes have rotted is worse than a missing one.  A missing
artifact fails loudly at the next read; a corrupted one is served happily and
poisons whatever consumes it, and the result document that pinned its hash
still looks perfect.

So the address *is* the hash.  ``put`` stores bytes at a path derived from their
digest, and ``get`` recomputes the digest on the way out and refuses to return
bytes that do not match.  There is no unchecked read path in the public API; a
caller cannot opt out of verification by accident, because the verification is
the retrieval.

Diagnostics name the artifact.  A message like "checksum mismatch" is useless
in a fleet with sixty-four concurrent units, so :class:`ArtifactCorruption`
carries the artifact id, the logical name, the store path, the expected and
observed digest and byte count, and a classification distinguishing truncation
and extension from equal-length content damage.  ``NOT_SUPPORTED`` is the
honest answer for locating a flipped bit within the file: the original bytes are
gone, so the offset is not recoverable from the corrupted copy alone.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .canonical import (
    append_line_durably,
    atomic_write_bytes,
    canonical,
    fsync_dir,
    read_json,
    sha256_bytes,
    sha256_file,
    utc_now,
)
from .ledger import HashChainedLedger

INDEX_NAME = "index.jsonl"
OBJECT_DIR = "objects"

BYTE_COUNT_MISMATCH = "BYTE_COUNT_MISMATCH"
CONTENT_MISMATCH = "CONTENT_MISMATCH"
OBJECT_ABSENT = "OBJECT_ABSENT"
UNREADABLE = "UNREADABLE"


class ArtifactStoreError(RuntimeError):
    """Raised when the store itself is used incorrectly."""


class ArtifactCorruption(ArtifactStoreError):
    """A stored artifact failed verification on read-back."""

    def __init__(
        self,
        *,
        artifact_id: str,
        logical_name: str,
        store_path: str,
        classification: str,
        expected_sha256: str,
        observed_sha256: str | None,
        expected_bytes: int,
        observed_bytes: int | None,
        detail: str = "",
    ) -> None:
        self.artifact_id = artifact_id
        self.logical_name = logical_name
        self.store_path = store_path
        self.classification = classification
        self.expected_sha256 = expected_sha256
        self.observed_sha256 = observed_sha256
        self.expected_bytes = expected_bytes
        self.observed_bytes = observed_bytes
        self.corrupt_byte_offset = "NOT_SUPPORTED"
        self.detail = detail
        super().__init__(self.diagnostic())

    def diagnostic(self) -> str:
        parts = [
            f"artifact {self.artifact_id} ('{self.logical_name}') failed read-back verification",
            f"classification={self.classification}",
            f"store_path={self.store_path}",
            f"expected sha256={self.expected_sha256} bytes={self.expected_bytes}",
            f"observed sha256={self.observed_sha256} bytes={self.observed_bytes}",
            (
                "corrupt_byte_offset=NOT_SUPPORTED (the original bytes are gone, so an offset is not "
                "recoverable from the damaged copy alone)"
            ),
        ]
        if self.detail:
            parts.append(self.detail)
        return "; ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "logical_name": self.logical_name,
            "store_path": self.store_path,
            "classification": self.classification,
            "expected_sha256": self.expected_sha256,
            "observed_sha256": self.observed_sha256,
            "expected_bytes": self.expected_bytes,
            "observed_bytes": self.observed_bytes,
            "corrupt_byte_offset": self.corrupt_byte_offset,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    logical_name: str
    sha256: str
    bytes: int
    media_type: str
    stored_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "logical_name": self.logical_name,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "media_type": self.media_type,
            "stored_at": self.stored_at,
        }


class ArtifactStore:
    """Stores bytes under their own digest and verifies on every read."""

    def __init__(self, root: Path | str, ledger: HashChainedLedger | None = None) -> None:
        self.root = Path(root)
        self.objects_root = self.root / OBJECT_DIR
        self.index_path = self.root / INDEX_NAME
        self.ledger = ledger
        self.objects_root.mkdir(parents=True, exist_ok=True)

    def object_path(self, digest: str) -> Path:
        return self.objects_root / digest[:2] / digest[2:]

    # -- writing -----------------------------------------------------------

    def put(
        self,
        artifact_id: str,
        logical_name: str,
        data: bytes,
        *,
        unit_id: str | None = None,
        media_type: str = "application/octet-stream",
        actor: str = "po03-worker-a1",
    ) -> ArtifactRef:
        if not data:
            raise ArtifactStoreError(f"{artifact_id}: refusing to store an empty artifact")
        digest = sha256_bytes(data)
        target = self.object_path(digest)
        if target.exists():
            # Content addressing makes a re-put of identical bytes a no-op
            # rather than a rewrite, so a retry cannot damage a good object.
            observed = sha256_file(target)
            if observed != digest:
                raise ArtifactCorruption(
                    artifact_id=artifact_id,
                    logical_name=logical_name,
                    store_path=str(target.relative_to(self.root)),
                    classification=CONTENT_MISMATCH,
                    expected_sha256=digest,
                    observed_sha256=observed,
                    expected_bytes=len(data),
                    observed_bytes=target.stat().st_size,
                    detail="an existing object at this address does not match its own address",
                )
        else:
            atomic_write_bytes(target, data)
            fsync_dir(target.parent)

        ref = ArtifactRef(
            artifact_id=artifact_id,
            logical_name=logical_name,
            sha256=digest,
            bytes=len(data),
            media_type=media_type,
            stored_at=utc_now(),
        )
        append_line_durably(self.index_path, canonical({**ref.as_dict(), "unit_id": unit_id}))
        if self.ledger is not None and unit_id is not None:
            self.ledger.append(
                unit_id,
                "ARTIFACT_STORED",
                actor=actor,
                payload={
                    "artifact_id": artifact_id,
                    "logical_name": logical_name,
                    "sha256": digest,
                    "bytes": len(data),
                },
            )
        return ref

    # -- reading -----------------------------------------------------------

    def get(self, ref: ArtifactRef, *, unit_id: str | None = None, actor: str = "po03-worker-a1") -> bytes:
        """Return the bytes, or raise a diagnostic naming the artifact.

        Byte count is checked before the digest so truncation and extension are
        reported as such instead of collapsing into a generic hash mismatch,
        and so a damaged object cannot be reported as merely "different".
        """
        target = self.object_path(ref.sha256)
        if not target.exists():
            failure = ArtifactCorruption(
                artifact_id=ref.artifact_id,
                logical_name=ref.logical_name,
                store_path=str(target.relative_to(self.root)),
                classification=OBJECT_ABSENT,
                expected_sha256=ref.sha256,
                observed_sha256=None,
                expected_bytes=ref.bytes,
                observed_bytes=None,
                detail="no object exists at the content address",
            )
            self._record(failure, unit_id, actor)
            raise failure
        try:
            data = target.read_bytes()
        except OSError as exc:
            failure = ArtifactCorruption(
                artifact_id=ref.artifact_id,
                logical_name=ref.logical_name,
                store_path=str(target.relative_to(self.root)),
                classification=UNREADABLE,
                expected_sha256=ref.sha256,
                observed_sha256=None,
                expected_bytes=ref.bytes,
                observed_bytes=None,
                detail=f"read failed: {exc}",
            )
            self._record(failure, unit_id, actor)
            raise failure from exc

        observed_bytes = len(data)
        if observed_bytes != ref.bytes:
            failure = ArtifactCorruption(
                artifact_id=ref.artifact_id,
                logical_name=ref.logical_name,
                store_path=str(target.relative_to(self.root)),
                classification=BYTE_COUNT_MISMATCH,
                expected_sha256=ref.sha256,
                observed_sha256=sha256_bytes(data),
                expected_bytes=ref.bytes,
                observed_bytes=observed_bytes,
                detail=(
                    f"truncated by {ref.bytes - observed_bytes} bytes"
                    if observed_bytes < ref.bytes
                    else f"extended by {observed_bytes - ref.bytes} bytes"
                ),
            )
            self._record(failure, unit_id, actor)
            raise failure

        observed_sha = sha256_bytes(data)
        if observed_sha != ref.sha256:
            failure = ArtifactCorruption(
                artifact_id=ref.artifact_id,
                logical_name=ref.logical_name,
                store_path=str(target.relative_to(self.root)),
                classification=CONTENT_MISMATCH,
                expected_sha256=ref.sha256,
                observed_sha256=observed_sha,
                expected_bytes=ref.bytes,
                observed_bytes=observed_bytes,
                detail="byte count is correct, so the damage is in-place content change",
            )
            self._record(failure, unit_id, actor)
            raise failure
        return data

    def _record(self, failure: ArtifactCorruption, unit_id: str | None, actor: str) -> None:
        if self.ledger is not None and unit_id is not None:
            self.ledger.append(unit_id, "ARTIFACT_CORRUPT", actor=actor, payload=failure.as_dict())

    # -- auditing ----------------------------------------------------------

    def index(self) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def refs(self) -> list[ArtifactRef]:
        seen: set[str] = set()
        refs: list[ArtifactRef] = []
        for row in self.index():
            if row["artifact_id"] in seen:
                continue
            seen.add(row["artifact_id"])
            refs.append(
                ArtifactRef(
                    artifact_id=row["artifact_id"],
                    logical_name=row["logical_name"],
                    sha256=row["sha256"],
                    bytes=int(row["bytes"]),
                    media_type=row["media_type"],
                    stored_at=row["stored_at"],
                )
            )
        return refs

    def verify_all(self, refs: Iterable[ArtifactRef] | None = None) -> list[ArtifactCorruption]:
        """Scan the store and return one diagnostic per damaged artifact."""
        failures: list[ArtifactCorruption] = []
        for ref in refs if refs is not None else self.refs():
            try:
                self.get(ref)
            except ArtifactCorruption as failure:
                failures.append(failure)
        return failures

    def audit(self, refs: Iterable[ArtifactRef] | None = None) -> dict[str, Any]:
        candidates = list(refs) if refs is not None else self.refs()
        failures = self.verify_all(candidates)
        return {
            "checked_at": utc_now(),
            "artifacts_checked": len(candidates),
            "intact": len(candidates) - len(failures),
            "corrupt": len(failures),
            "diagnostics": [failure.as_dict() for failure in failures],
            "ok": not failures,
        }


def corrupt_in_place(path: Path, *, offset: int, bit: int) -> None:
    """Flip one bit in a stored object.  Test-fixture support, not a repair.

    Lives beside the store so the corruption fixtures used in the a1-u07 tests
    damage real bytes on disk through a real write, rather than simulating
    damage by faking a hash.
    """
    with path.open("r+b") as handle:
        handle.seek(offset)
        original = handle.read(1)
        if not original:
            raise ValueError(f"{path}: offset {offset} is past the end of the object")
        handle.seek(offset)
        handle.write(bytes([original[0] ^ (1 << bit)]))
        handle.flush()
        os.fsync(handle.fileno())


def truncate_in_place(path: Path, *, keep_bytes: int) -> None:
    """Truncate a stored object.  Test-fixture support, not a repair."""
    with path.open("r+b") as handle:
        handle.truncate(keep_bytes)
        handle.flush()
        os.fsync(handle.fileno())


def read_index_json(path: Path) -> Any:
    return read_json(path)
