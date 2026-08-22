"""Two-phase result staging: a partial write is never observable as committed.

The SO-02 correction lists "task schema allowed completed with null result and
empty artifacts".  The deeper version of that defect is a *partially* written
result: bytes that exist, are incomplete, and look finished.

So committed-ness is not a flag anyone sets.  It is a derived property of the
bytes, and a parent can only learn it through :meth:`ResultStager.observe`,
which recomputes it every time:

    ``RESULT_COMMITTED`` requires the published directory to exist, to hold a
    commit marker, to hold a manifest whose digest matches the marker, and for
    every artifact named in the manifest to re-read at exactly the recorded
    digest and byte count, with no extra and no missing artifact.

Any shortfall is reported as ``CORRUPT`` or as a staging state.  There is no
code path that returns ``RESULT_COMMITTED`` without having just re-read the
bytes, which is why no injection point can produce one.

Ordering
--------
Publication is a single ``os.replace`` of a fully built directory, so there is
no window in which a reader sees a half-populated published result.  The ledger
row is appended *after* the rename, not before.  The reverse order would be a
false-completion generator: a crash in between would leave the ledger asserting
a commit that no bytes support.  Recording after the rename can instead lose a
*callback*, which :meth:`recover` detects and :meth:`reconcile` repairs
idempotently — losing a notification is recoverable, lying about custody is not.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .canonical import (
    atomic_write_json,
    canonical,
    fsync_dir,
    read_json,
    sha256_bytes,
    sha256_file,
    sha256_payload,
    utc_now,
)
from .ledger import HashChainedLedger

MANIFEST_NAME = "manifest.json"
COMMIT_MARKER_NAME = "COMMIT.json"
ARTIFACT_DIR = "artifacts"

ABSENT = "ABSENT"
RESULT_STAGING = "RESULT_STAGING"
RESULT_STAGED = "RESULT_STAGED"
RESULT_VERIFIED = "RESULT_VERIFIED"
RESULT_COMMITTED = "RESULT_COMMITTED"
CORRUPT = "CORRUPT"

# Every point at which a fault may be injected during staging and publication.
INJECTION_POINTS = (
    "after_reserve",
    "before_artifact_write",
    "mid_artifact_write",
    "after_artifact_write",
    "before_manifest",
    "after_manifest",
    "before_verify",
    "after_verify",
    "before_commit_marker",
    "after_commit_marker",
    "before_publish_rename",
    "after_publish_rename",
    "after_ledger_commit_event",
)

_CHUNK = 4096


class StagingError(RuntimeError):
    """Raised when staging or publication would break the custody invariants."""


@dataclass
class StagedResult:
    txn_id: str
    unit_id: str
    staging_dir: Path
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    manifest_sha256: str | None = None
    verified: bool = False

    @property
    def total_bytes(self) -> int:
        return sum(int(item["bytes"]) for item in self.artifacts)


@dataclass(frozen=True)
class Observation:
    """What a parent is allowed to conclude, recomputed from bytes each time."""

    txn_id: str
    state: str
    reason: str
    artifact_count: int = 0
    total_bytes: int = 0
    manifest_sha256: str | None = None
    result_commit_id: str | None = None
    problems: tuple[str, ...] = ()

    @property
    def committed(self) -> bool:
        return self.state == RESULT_COMMITTED

    def as_dict(self) -> dict[str, Any]:
        return {
            "txn_id": self.txn_id,
            "state": self.state,
            "reason": self.reason,
            "artifact_count": self.artifact_count,
            "total_bytes": self.total_bytes,
            "manifest_sha256": self.manifest_sha256,
            "result_commit_id": self.result_commit_id,
            "problems": list(self.problems),
        }


@dataclass(frozen=True)
class Recoverable:
    txn_id: str
    disposition: str
    detail: str


class ResultStager:
    """Builds a result out of sight and publishes it in one atomic step."""

    def __init__(
        self,
        root: Path | str,
        ledger: HashChainedLedger,
        *,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.root = Path(root)
        self.staging_root = self.root / "staging"
        self.committed_root = self.root / "committed"
        self.ledger = ledger
        self.fault_hook = fault_hook
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.committed_root.mkdir(parents=True, exist_ok=True)

    def _fire(self, point: str) -> None:
        if self.fault_hook is not None:
            self.fault_hook(point)

    # -- phase one: build out of sight ------------------------------------

    def reserve(self, txn_id: str, unit_id: str, *, actor: str = "po03-worker-a1") -> StagedResult:
        staging_dir = self.staging_root / txn_id
        if (self.committed_root / txn_id).exists():
            raise StagingError(f"{txn_id} is already published; a result transaction is single-use")
        if staging_dir.exists():
            raise StagingError(f"{txn_id} is already staging; resume it or discard it explicitly")
        (staging_dir / ARTIFACT_DIR).mkdir(parents=True)
        fsync_dir(staging_dir)
        self.ledger.append(
            unit_id,
            "RESULT_STAGING",
            actor=actor,
            payload={"result_txn_id": txn_id, "staging_dir": str(staging_dir.relative_to(self.root))},
        )
        self._fire("after_reserve")
        return StagedResult(txn_id=txn_id, unit_id=unit_id, staging_dir=staging_dir)

    def stage_artifact(self, staged: StagedResult, logical_name: str, data: bytes) -> dict[str, Any]:
        """Write one artifact so that a partial write is never visible.

        Bytes go to a dot-prefixed temporary file and become visible only via
        ``os.replace``.  On a crash the temporary file is *not* cleaned up,
        because a crash would not have run a cleanup handler either; the
        manifest ignores it, so it can never be mistaken for an artifact.
        """
        if any(item["logical_name"] == logical_name for item in staged.artifacts):
            raise StagingError(f"{staged.txn_id}: {logical_name} is already staged")
        target = staged.staging_dir / ARTIFACT_DIR / logical_name
        temporary = target.parent / f".{logical_name}.partial"
        self._fire("before_artifact_write")
        with temporary.open("wb") as handle:
            written = 0
            for offset in range(0, len(data), _CHUNK):
                handle.write(data[offset : offset + _CHUNK])
                written += len(data[offset : offset + _CHUNK])
                if written * 2 >= len(data):
                    handle.flush()
                    os.fsync(handle.fileno())
                    self._fire("mid_artifact_write")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        fsync_dir(target.parent)
        self._fire("after_artifact_write")
        entry = {
            "logical_name": logical_name,
            "sha256": sha256_bytes(data),
            "bytes": len(data),
            "relative_path": f"{ARTIFACT_DIR}/{logical_name}",
        }
        staged.artifacts.append(entry)
        return entry

    def seal(self, staged: StagedResult, *, actor: str = "po03-worker-a1") -> dict[str, Any]:
        """Write the manifest; the result is now completely described."""
        if not staged.artifacts:
            raise StagingError(f"{staged.txn_id}: a result must stage at least one artifact")
        manifest = {
            "txn_id": staged.txn_id,
            "unit_id": staged.unit_id,
            "artifacts": sorted(staged.artifacts, key=lambda item: item["logical_name"]),
            "artifact_count": len(staged.artifacts),
            "total_bytes": staged.total_bytes,
        }
        self._fire("before_manifest")
        atomic_write_json(staged.staging_dir / MANIFEST_NAME, manifest)
        staged.manifest_sha256 = sha256_payload(manifest)
        self._fire("after_manifest")
        self.ledger.append(
            staged.unit_id,
            "RESULT_STAGED",
            actor=actor,
            payload={
                "result_txn_id": staged.txn_id,
                "manifest_sha256": staged.manifest_sha256,
                "artifact_count": manifest["artifact_count"],
                "total_bytes": manifest["total_bytes"],
            },
        )
        return manifest

    def verify(self, staged: StagedResult, *, actor: str = "po03-worker-a1") -> list[str]:
        """Re-read every staged artifact from disk and compare to the manifest."""
        self._fire("before_verify")
        problems = self._verify_directory(staged.staging_dir)
        self._fire("after_verify")
        if problems:
            staged.verified = False
            return problems
        staged.verified = True
        self.ledger.append(
            staged.unit_id,
            "RESULT_VERIFIED",
            actor=actor,
            payload={
                "result_txn_id": staged.txn_id,
                "manifest_sha256": staged.manifest_sha256,
                "artifact_count": len(staged.artifacts),
                "total_bytes": staged.total_bytes,
            },
        )
        return []

    # -- phase two: publish atomically ------------------------------------

    def publish(
        self,
        staged: StagedResult,
        *,
        result_commit_id: str,
        result_locator: str,
        actor: str = "po03-worker-a1",
        fence_token: int | None = None,
    ) -> Path:
        if not staged.verified:
            raise StagingError(f"{staged.txn_id}: refusing to publish an unverified result")
        published = self.committed_root / staged.txn_id
        if published.exists():
            existing = self.observe(staged.txn_id)
            if existing.committed:
                return published
            raise StagingError(f"{staged.txn_id}: a damaged publication already occupies {published}")

        marker = {
            "txn_id": staged.txn_id,
            "unit_id": staged.unit_id,
            "manifest_sha256": staged.manifest_sha256,
            "artifact_count": len(staged.artifacts),
            "total_bytes": staged.total_bytes,
            "result_commit_id": result_commit_id,
            "result_locator": result_locator,
            "committed_at": utc_now(),
        }
        self._fire("before_commit_marker")
        atomic_write_json(staged.staging_dir / COMMIT_MARKER_NAME, marker)
        fsync_dir(staged.staging_dir)
        self._fire("after_commit_marker")

        self._fire("before_publish_rename")
        os.replace(staged.staging_dir, published)
        fsync_dir(self.committed_root)
        self._fire("after_publish_rename")

        self.ledger.append(
            staged.unit_id,
            "RESULT_COMMITTED",
            actor=actor,
            provider_state="COMPLETED",
            fence_token=fence_token,
            payload={
                "result_txn_id": staged.txn_id,
                "result_commit_id": result_commit_id,
                "result_locator": result_locator,
                "manifest_sha256": staged.manifest_sha256,
                "artifact_count": len(staged.artifacts),
                "total_bytes": staged.total_bytes,
            },
        )
        self._fire("after_ledger_commit_event")
        return published

    # -- observation -------------------------------------------------------

    def _verify_directory(self, directory: Path) -> list[str]:
        problems: list[str] = []
        manifest_path = directory / MANIFEST_NAME
        if not manifest_path.exists():
            return [f"{directory.name}: manifest is absent"]
        try:
            manifest = read_json(manifest_path)
        except (OSError, ValueError) as exc:
            return [f"{directory.name}: manifest is unreadable: {exc}"]

        expected = {item["logical_name"]: item for item in manifest.get("artifacts", [])}
        artifact_dir = directory / ARTIFACT_DIR
        present = (
            {path.name for path in artifact_dir.iterdir() if path.is_file() and not path.name.startswith(".")}
            if artifact_dir.is_dir()
            else set()
        )
        for missing in sorted(set(expected) - present):
            problems.append(f"{directory.name}: artifact {missing} named in the manifest is absent")
        for extra in sorted(present - set(expected)):
            problems.append(f"{directory.name}: artifact {extra} is present but not named in the manifest")

        total = 0
        for name in sorted(set(expected) & present):
            entry = expected[name]
            path = artifact_dir / name
            observed_bytes = path.stat().st_size
            if observed_bytes != int(entry["bytes"]):
                problems.append(
                    f"{directory.name}: artifact {name} is {observed_bytes} bytes, manifest records "
                    f"{entry['bytes']}"
                )
                continue
            observed_sha = sha256_file(path)
            if observed_sha != entry["sha256"]:
                problems.append(
                    f"{directory.name}: artifact {name} digests to {observed_sha}, manifest records "
                    f"{entry['sha256']}"
                )
                continue
            total += observed_bytes
        if not problems and total != int(manifest.get("total_bytes", -1)):
            problems.append(f"{directory.name}: byte total {total} does not match the manifest")
        return problems

    def observe(self, txn_id: str) -> Observation:
        """The only route by which a parent may conclude anything about a result."""
        published = self.committed_root / txn_id
        staging = self.staging_root / txn_id

        if published.exists():
            marker_path = published / COMMIT_MARKER_NAME
            if not marker_path.exists():
                return Observation(
                    txn_id,
                    CORRUPT,
                    "published directory exists without a commit marker",
                    problems=("commit marker absent",),
                )
            try:
                marker = read_json(marker_path)
            except (OSError, ValueError) as exc:
                return Observation(txn_id, CORRUPT, f"commit marker unreadable: {exc}", problems=(str(exc),))
            problems = list(self._verify_directory(published))
            manifest_path = published / MANIFEST_NAME
            if manifest_path.exists():
                try:
                    recomputed = sha256_payload(read_json(manifest_path))
                    if recomputed != marker.get("manifest_sha256"):
                        problems.append(
                            f"manifest digests to {recomputed} but the commit marker pins "
                            f"{marker.get('manifest_sha256')}"
                        )
                except (OSError, ValueError) as exc:
                    problems.append(f"manifest unreadable: {exc}")
            if problems:
                return Observation(
                    txn_id,
                    CORRUPT,
                    "published bytes do not match the commit marker",
                    manifest_sha256=marker.get("manifest_sha256"),
                    result_commit_id=marker.get("result_commit_id"),
                    problems=tuple(problems),
                )
            return Observation(
                txn_id,
                RESULT_COMMITTED,
                "published, marker present, every artifact re-read at its recorded digest and byte count",
                artifact_count=int(marker["artifact_count"]),
                total_bytes=int(marker["total_bytes"]),
                manifest_sha256=marker.get("manifest_sha256"),
                result_commit_id=marker.get("result_commit_id"),
            )

        if not staging.exists():
            return Observation(txn_id, ABSENT, "no staged or published result transaction")

        if not (staging / MANIFEST_NAME).exists():
            return Observation(
                txn_id,
                RESULT_STAGING,
                "artifacts are being staged; the result is not yet completely described",
            )
        problems = self._verify_directory(staging)
        if problems:
            return Observation(
                txn_id,
                RESULT_STAGING,
                "staged bytes are incomplete or inconsistent with the manifest",
                problems=tuple(problems),
            )
        state = RESULT_VERIFIED if self._ledger_saw(txn_id, "RESULT_VERIFIED") else RESULT_STAGED
        manifest = read_json(staging / MANIFEST_NAME)
        return Observation(
            txn_id,
            state,
            "staged and internally consistent, but not published",
            artifact_count=int(manifest["artifact_count"]),
            total_bytes=int(manifest["total_bytes"]),
            manifest_sha256=sha256_payload(manifest),
        )

    def _ledger_saw(self, txn_id: str, event: str) -> bool:
        return any(
            row["event"] == event and (row.get("payload") or {}).get("result_txn_id") == txn_id
            for row in self.ledger.rows()
        )

    # -- recovery ----------------------------------------------------------

    def recover(self) -> list[Recoverable]:
        """Classify every transaction a crash could have left behind."""
        found: list[Recoverable] = []
        for directory in sorted(self.staging_root.iterdir()) if self.staging_root.is_dir() else []:
            if not directory.is_dir():
                continue
            observation = self.observe(directory.name)
            found.append(
                Recoverable(
                    directory.name,
                    "RESTAGE_FROM_IMMUTABLE_INPUT",
                    f"unpublished staging directory in state {observation.state}: {observation.reason}",
                )
            )
        for directory in sorted(self.committed_root.iterdir()) if self.committed_root.is_dir() else []:
            if not directory.is_dir():
                continue
            observation = self.observe(directory.name)
            if observation.state == CORRUPT:
                found.append(
                    Recoverable(directory.name, "QUARANTINE_AND_RESTAGE", "; ".join(observation.problems))
                )
            elif not self._ledger_saw(directory.name, "RESULT_COMMITTED"):
                found.append(
                    Recoverable(
                        directory.name,
                        "RECONCILE_LEDGER",
                        "bytes are published and verify, but no RESULT_COMMITTED row was recorded",
                    )
                )
        return found

    def reconcile(self, txn_id: str, *, actor: str = "po03-worker-a1") -> bool:
        """Append the missing commit row for published bytes; idempotent.

        This is the lost-callback repair.  It can only ever *add* a row for a
        result whose bytes have just been re-read and verified, so it cannot
        manufacture a commit.
        """
        observation = self.observe(txn_id)
        if not observation.committed:
            raise StagingError(
                f"{txn_id}: refusing to reconcile a result that does not verify as committed "
                f"(observed {observation.state}: {observation.reason})"
            )
        if self._ledger_saw(txn_id, "RESULT_COMMITTED"):
            return False
        marker = read_json(self.committed_root / txn_id / COMMIT_MARKER_NAME)
        self.ledger.append(
            marker["unit_id"],
            "RESULT_COMMITTED",
            actor=actor,
            provider_state="COMPLETED",
            payload={
                "result_txn_id": txn_id,
                "result_commit_id": marker["result_commit_id"],
                "result_locator": marker["result_locator"],
                "manifest_sha256": marker["manifest_sha256"],
                "artifact_count": marker["artifact_count"],
                "total_bytes": marker["total_bytes"],
                "reconciled": True,
            },
        )
        return True

    def discard(self, txn_id: str) -> None:
        shutil.rmtree(self.staging_root / txn_id, ignore_errors=True)

    def published_manifest(self, txn_id: str) -> dict[str, Any]:
        return read_json(self.committed_root / txn_id / MANIFEST_NAME)

    def read_published(self, txn_id: str, logical_name: str) -> bytes:
        observation = self.observe(txn_id)
        if not observation.committed:
            raise StagingError(
                f"{txn_id}: refusing to serve bytes from a result observed as {observation.state}"
            )
        return (self.committed_root / txn_id / ARTIFACT_DIR / logical_name).read_bytes()


def stage_and_publish(
    stager: ResultStager,
    txn_id: str,
    unit_id: str,
    artifacts: dict[str, bytes],
    *,
    result_commit_id: str,
    result_locator: str,
    fence_token: int | None = None,
) -> Path:
    """The whole two-phase sequence, driven from immutable input.

    Recovery re-runs exactly this, which is why the inputs are a plain mapping:
    a rerun must not depend on anything the crashed attempt held in memory.
    """
    staged = stager.reserve(txn_id, unit_id)
    for logical_name in sorted(artifacts):
        stager.stage_artifact(staged, logical_name, artifacts[logical_name])
    stager.seal(staged)
    problems = stager.verify(staged)
    if problems:
        raise StagingError(f"{txn_id}: staged result failed verification: {canonical(problems)}")
    return stager.publish(
        staged,
        result_commit_id=result_commit_id,
        result_locator=result_locator,
        fence_token=fence_token,
    )
