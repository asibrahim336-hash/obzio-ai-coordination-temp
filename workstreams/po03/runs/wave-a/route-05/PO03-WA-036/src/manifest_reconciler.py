#!/usr/bin/env python3
"""Independent reconciliation of an artifact manifest against a tree on disk.

A manifest is a claim.  This component re-derives every claim from the bytes
themselves and reports the difference, in both directions:

* forward  - every manifested artifact must exist, and its SHA-256 and byte
  count must match a fresh streamed read of the file;
* reverse  - every file present under the reconciled root must appear in the
  manifest, so a manifest cannot be made to pass by omitting artifacts.

Hashing streams in fixed-size chunks so a large artifact is never held in
memory, and the byte count is taken from the same read as the hash rather
than from ``stat``.  That matters: a manifest whose ``bytes`` field agrees
with ``stat`` but disagrees with the hashed stream is exactly the corruption
this component is meant to surface.

Per-artifact findings:

    MATCH                  hash and byte count both re-derive
    SHA_MISMATCH           byte count agrees, content does not
    BYTES_MISMATCH         byte count disagrees (hash also recomputed)
    MISSING                manifested path is absent
    NOT_A_REGULAR_FILE     manifested path is a directory, symlink or device
    NON_CANONICAL_SHA      manifest hash is not 64 lowercase hex characters
    DUPLICATE_ARTIFACT_ID  two entries share an artifact_id
    DUPLICATE_CONTENT_URI  two entries claim the same path
    PATH_ESCAPES_ROOT      manifested path leaves the reconciled root

Tree-level findings: UNMANIFESTED_FILE, ARTIFACT_COUNT_MISMATCH,
TOTAL_BYTES_MISMATCH.

Exit codes: 0 fully reconciled, 1 discrepancies found, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CHUNK_BYTES = 1024 * 1024

MATCH = "MATCH"
SHA_MISMATCH = "SHA_MISMATCH"
BYTES_MISMATCH = "BYTES_MISMATCH"
MISSING = "MISSING"
NOT_A_REGULAR_FILE = "NOT_A_REGULAR_FILE"
NON_CANONICAL_SHA = "NON_CANONICAL_SHA"
DUPLICATE_ARTIFACT_ID = "DUPLICATE_ARTIFACT_ID"
DUPLICATE_CONTENT_URI = "DUPLICATE_CONTENT_URI"
PATH_ESCAPES_ROOT = "PATH_ESCAPES_ROOT"
UNMANIFESTED_FILE = "UNMANIFESTED_FILE"


class ManifestError(ValueError):
    """Raised when the manifest document itself is unusable."""


@dataclass(frozen=True)
class ArtifactFinding:
    artifact_id: str | None
    content_uri: str
    finding: str
    claimed_sha256: str | None
    observed_sha256: str | None
    claimed_bytes: int | None
    observed_bytes: int | None
    detail: str

    def reconciled(self) -> bool:
        return self.finding == MATCH


def hash_and_count(path: Path, chunk_bytes: int = CHUNK_BYTES) -> tuple[str, int]:
    """Stream the file once, deriving hash and length from the same read."""
    digest = hashlib.sha256()
    total = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def load_manifest(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"unreadable manifest: {exc}") from exc
    if not isinstance(document, dict):
        raise ManifestError("manifest root must be a JSON object")
    if not isinstance(document.get("artifacts"), list):
        raise ManifestError("manifest.artifacts must be an array")
    return document


def _relative_within(root: Path, content_uri: str) -> Path | None:
    """Lexical containment only.

    Deliberately does not call ``resolve()``: following symlinks here would
    collapse two distinct defects into one verdict.  A ``content_uri`` that
    lexically leaves the root is PATH_ESCAPES_ROOT; a path that exists but is
    a symlink is NOT_A_REGULAR_FILE and is never hashed.  Proving that a
    symlink target stays inside an owned subtree is PO03-WA-034's guard, not
    this reconciler's.
    """
    if os.path.isabs(content_uri):
        return None
    candidate = os.path.normpath(os.path.join(str(root), content_uri))
    root_text = os.path.normpath(str(root))
    if candidate != root_text and not candidate.startswith(root_text + os.sep):
        return None
    return Path(candidate)


def reconcile_artifacts(root: Path, artifacts: Iterable[dict]) -> list[ArtifactFinding]:
    findings: list[ArtifactFinding] = []
    seen_ids: set[str] = set()
    seen_uris: set[str] = set()

    for entry in artifacts:
        if not isinstance(entry, dict):
            raise ManifestError("each manifest artifact must be an object")
        artifact_id = entry.get("artifact_id")
        content_uri = entry.get("content_uri")
        claimed_sha = entry.get("sha256")
        claimed_bytes = entry.get("bytes")
        if not isinstance(content_uri, str) or not content_uri:
            raise ManifestError("each manifest artifact needs a non-empty content_uri")

        if isinstance(artifact_id, str) and artifact_id in seen_ids:
            findings.append(
                ArtifactFinding(
                    artifact_id, content_uri, DUPLICATE_ARTIFACT_ID, claimed_sha, None,
                    claimed_bytes, None, "artifact_id appears more than once",
                )
            )
            continue
        if isinstance(artifact_id, str):
            seen_ids.add(artifact_id)
        if content_uri in seen_uris:
            findings.append(
                ArtifactFinding(
                    artifact_id, content_uri, DUPLICATE_CONTENT_URI, claimed_sha, None,
                    claimed_bytes, None, "content_uri appears more than once",
                )
            )
            continue
        seen_uris.add(content_uri)

        if not isinstance(claimed_sha, str) or not SHA256_RE.fullmatch(claimed_sha):
            findings.append(
                ArtifactFinding(
                    artifact_id, content_uri, NON_CANONICAL_SHA, claimed_sha if isinstance(claimed_sha, str) else None,
                    None, claimed_bytes if isinstance(claimed_bytes, int) else None, None,
                    "sha256 must be 64 lowercase hexadecimal characters",
                )
            )
            continue

        target = _relative_within(root, content_uri)
        if target is None:
            findings.append(
                ArtifactFinding(
                    artifact_id, content_uri, PATH_ESCAPES_ROOT, claimed_sha, None,
                    claimed_bytes, None, "content_uri resolves outside the reconciled root",
                )
            )
            continue
        if not target.exists():
            findings.append(
                ArtifactFinding(
                    artifact_id, content_uri, MISSING, claimed_sha, None, claimed_bytes, None,
                    "manifested artifact is not present on disk",
                )
            )
            continue
        if target.is_symlink() or not target.is_file():
            findings.append(
                ArtifactFinding(
                    artifact_id, content_uri, NOT_A_REGULAR_FILE, claimed_sha, None,
                    claimed_bytes, None, "manifested path is not a regular file",
                )
            )
            continue

        observed_sha, observed_bytes = hash_and_count(target)
        if not isinstance(claimed_bytes, int) or claimed_bytes != observed_bytes:
            finding = BYTES_MISMATCH
            detail = f"claimed {claimed_bytes!r} bytes, observed {observed_bytes}"
        elif observed_sha != claimed_sha:
            finding = SHA_MISMATCH
            detail = "byte count agrees but content differs"
        else:
            finding = MATCH
            detail = "hash and byte count re-derived from disk"
        findings.append(
            ArtifactFinding(
                artifact_id, content_uri, finding, claimed_sha, observed_sha,
                claimed_bytes if isinstance(claimed_bytes, int) else None, observed_bytes, detail,
            )
        )
    return findings


def find_unmanifested(root: Path, manifested: set[str], excludes: Iterable[str]) -> list[str]:
    exclude_set = {e.strip("/") for e in excludes}
    extras: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in exclude_set and d != ".git")
        for name in sorted(filenames):
            relative = os.path.relpath(os.path.join(dirpath, name), root)
            if relative in exclude_set or relative in manifested:
                continue
            if any(relative.startswith(prefix + "/") for prefix in exclude_set):
                continue
            extras.append(relative)
    return extras


def reconcile(manifest_path: Path, root: Path, excludes: Iterable[str] = ()) -> dict:
    document = load_manifest(manifest_path)
    artifacts = document["artifacts"]
    findings = reconcile_artifacts(root, artifacts)
    manifested = {str(entry.get("content_uri")) for entry in artifacts if isinstance(entry, dict)}
    extras = find_unmanifested(root, manifested, excludes)

    observed_total = sum(f.observed_bytes or 0 for f in findings)
    claimed_count = document.get("artifact_count")
    claimed_total = document.get("total_bytes")

    tree_findings: list[dict] = [
        {"finding": UNMANIFESTED_FILE, "content_uri": extra, "detail": "present on disk, absent from manifest"}
        for extra in extras
    ]
    if isinstance(claimed_count, int) and claimed_count != len(artifacts):
        tree_findings.append(
            {
                "finding": "ARTIFACT_COUNT_MISMATCH",
                "detail": f"manifest declares {claimed_count}, contains {len(artifacts)}",
            }
        )
    if isinstance(claimed_total, int) and claimed_total != observed_total:
        tree_findings.append(
            {
                "finding": "TOTAL_BYTES_MISMATCH",
                "detail": f"manifest declares {claimed_total}, observed {observed_total}",
            }
        )

    unreconciled = [f for f in findings if not f.reconciled()]
    return {
        "component": "manifest_reconciler",
        "manifest_uri": str(manifest_path),
        "root": str(root),
        "artifacts_examined": len(findings),
        "artifacts_matched": len(findings) - len(unreconciled),
        "artifacts_unreconciled": len(unreconciled),
        "observed_total_bytes": observed_total,
        "reconciled": not unreconciled and not tree_findings,
        "artifact_findings": [asdict(f) for f in findings],
        "tree_findings": tree_findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independently reconcile a manifest against bytes on disk.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--exclude", action="append", default=[], help="path relative to root to skip in the reverse check")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print(f"USAGE_ERROR: root is not a directory: {args.root}", file=sys.stderr)
        return 2
    try:
        report = reconcile(args.manifest, args.root, args.exclude)
    except ManifestError as exc:
        print(f"USAGE_ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for finding in report["artifact_findings"]:
            marker = "ok  " if finding["finding"] == MATCH else "FAIL"
            print(f"{marker} {finding['finding']:<22} {finding['content_uri']}  ({finding['detail']})")
        for finding in report["tree_findings"]:
            print(f"FAIL {finding['finding']:<22} {finding.get('content_uri', '-')}  ({finding['detail']})")
        print(
            f"summary: examined={report['artifacts_examined']} matched={report['artifacts_matched']} "
            f"unreconciled={report['artifacts_unreconciled']} bytes={report['observed_total_bytes']}"
        )
    return 0 if report["reconciled"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
