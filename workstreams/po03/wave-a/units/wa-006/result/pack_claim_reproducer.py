#!/usr/bin/env python3
"""Read-only reproducer for operator-pack manifest claims at immutable commits.

Task: PO03-WA-006.  Hypothesis H-PO03-WA-006 — pack claims can be checked from
immutable commits without branch mutation or producer narrative.

The reproducer reads *only* git object bytes at a caller-pinned commit through a
hard allowlist of read-only plumbing subcommands.  It never checks out, fetches,
writes a ref, touches the index or reads any prose written by the producer of
the packs: the only inputs are `MANIFEST.json` documents and the payload blobs
whose digests those documents claim.

Two manifest dialects are seen in the corpus and both are normalised here:

* ``obzio.manifest.v2``       — ``files`` is an object keyed by relative path.
* per-pack generated dialect — ``files`` is an array of ``{path, sha256, bytes}``.

An aggregate manifest additionally carries ``root``, ``packs`` and ``totals``,
which are checked as coverage and portability claims rather than file claims.

Every finding is a typed discrepancy with the exact claim it falsifies, so a
consumer can act on the report without trusting this module's own narrative.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


# Only these git subcommands can be issued.  Everything that could move a ref,
# populate a working tree, mutate the index or reach the network is absent, so a
# reproduction cannot mutate the branches whose claims it is checking.
READ_ONLY_GIT_SUBCOMMANDS = frozenset(
    {"cat-file", "ls-tree", "rev-parse", "rev-list", "for-each-ref", "symbolic-ref"}
)

# Flags that would turn a read into a write even under an allowlisted subcommand.
FORBIDDEN_GIT_ARGS = frozenset({"-w", "--write", "--textconv", "--filters"})

SHA256_HEX_LENGTH = 64

ABSOLUTE_PATH_PREFIXES = ("/tmp/", "/home/", "/root/", "/Users/", "/var/folders/", "/private/")

DISCREPANCY_KINDS = (
    "MISSING_AT_CLAIMED_PATH_CONTENT_RELOCATED",
    "MISSING_AT_CLAIMED_PATH_CONTENT_ABSENT",
    "DIGEST_MISMATCH",
    "BYTE_COUNT_MISMATCH",
    "FILE_COUNT_MISMATCH",
    "TOTAL_BYTES_MISMATCH",
    "NON_PORTABLE_ABSOLUTE_PATH_CLAIM",
    "AGGREGATE_COVERAGE_GAP",
    "UNVERIFIABLE_MANIFEST_DIALECT",
)


class ReadOnlyViolation(RuntimeError):
    """Raised when a caller attempts a git operation that is not a pure read."""


class ClaimReadError(RuntimeError):
    """Raised when a manifest cannot be parsed into checkable claims."""


class ReadOnlyGit:
    """A git façade that can only read objects and refs.

    The guard is deliberately positive: an argument vector is rejected unless
    its subcommand is allowlisted.  Adding a write path therefore requires
    editing this class, not merely calling git differently.
    """

    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo).resolve()
        if not (self.repo / ".git").exists() and not (self.repo / "HEAD").exists():
            raise ClaimReadError(f"{self.repo} is not a git repository")
        self.call_count = 0

    def _run(self, args: list[str], *, text: bool) -> subprocess.CompletedProcess:
        if not args:
            raise ReadOnlyViolation("empty git argument vector")
        subcommand = args[0]
        if subcommand not in READ_ONLY_GIT_SUBCOMMANDS:
            raise ReadOnlyViolation(f"git subcommand not read-only: {subcommand}")
        forbidden = FORBIDDEN_GIT_ARGS.intersection(args)
        if forbidden:
            raise ReadOnlyViolation(f"forbidden git argument(s): {sorted(forbidden)}")
        self.call_count += 1
        return subprocess.run(
            ["git", "--no-pager", "-C", str(self.repo), *args],
            capture_output=True,
            text=text,
            check=False,
        )

    def text(self, args: list[str]) -> str:
        completed = self._run(args, text=True)
        if completed.returncode != 0:
            raise ClaimReadError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
        return completed.stdout

    def resolve_commit(self, revision: str) -> str:
        commit_id = self.text(["rev-parse", f"{revision}^{{commit}}"]).strip()
        if len(commit_id) != 40 and len(commit_id) != 64:
            raise ClaimReadError(f"unexpected commit id for {revision}: {commit_id!r}")
        return commit_id

    def list_tree(self, commit: str) -> list[str]:
        return sorted(
            line for line in self.text(["ls-tree", "-r", "--name-only", "-z", commit]).split("\0") if line
        )

    def blob(self, commit: str, path: str) -> bytes | None:
        """Return exact blob bytes at ``commit:path``, or None when absent."""
        completed = self._run(["cat-file", "blob", f"{commit}:{path}"], text=False)
        if completed.returncode != 0:
            return None
        return completed.stdout

    def refs_digest(self) -> str:
        """Digest every ref so a caller can prove no ref moved during a scan."""
        listing = self.text(["for-each-ref", "--format=%(refname) %(objectname)"])
        normalised = "\n".join(sorted(listing.splitlines()))
        return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

    def head_state(self) -> dict[str, str | None]:
        head = self.text(["rev-parse", "HEAD"]).strip()
        symbolic = self._run(["symbolic-ref", "-q", "HEAD"], text=True)
        return {
            "head_commit": head,
            "head_ref": symbolic.stdout.strip() or None,
        }


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_HEX_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def normalise_file_claims(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten either manifest dialect into ``{relative_path, sha256, bytes}``."""
    files = manifest.get("files")
    claims: list[dict[str, Any]] = []
    if isinstance(files, dict):
        for relative_path, entry in files.items():
            if not isinstance(entry, dict):
                raise ClaimReadError(f"file entry for {relative_path!r} is not an object")
            claims.append(
                {
                    "relative_path": relative_path,
                    "sha256": entry.get("sha256"),
                    "bytes": entry.get("bytes"),
                }
            )
    elif isinstance(files, list):
        for entry in files:
            if not isinstance(entry, dict) or "path" not in entry:
                raise ClaimReadError("array-dialect file entry lacks a path")
            claims.append(
                {
                    "relative_path": entry["path"],
                    "sha256": entry.get("sha256"),
                    "bytes": entry.get("bytes"),
                }
            )
    else:
        raise ClaimReadError("manifest has no recognised files claim")
    for claim in claims:
        if not _is_sha256(claim["sha256"]):
            raise ClaimReadError(f"claim for {claim['relative_path']!r} lacks a lowercase SHA-256")
        if not isinstance(claim["bytes"], int) or claim["bytes"] < 0:
            raise ClaimReadError(f"claim for {claim['relative_path']!r} lacks a byte count")
    return sorted(claims, key=lambda claim: claim["relative_path"])


def collect_absolute_path_claims(node: Any, pointer: str = "$") -> list[dict[str, str]]:
    """Report every string in a manifest that embeds a build-host absolute path."""
    found: list[dict[str, str]] = []
    if isinstance(node, dict):
        for key in sorted(node):
            found.extend(collect_absolute_path_claims(node[key], f"{pointer}.{key}"))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(collect_absolute_path_claims(item, f"{pointer}[{index}]"))
    elif isinstance(node, str) and node.startswith(ABSOLUTE_PATH_PREFIXES):
        found.append({"json_pointer": pointer, "value": node})
    return found


class ContentIndex:
    """Digest-to-path index over one immutable tree.

    A relocated file is indistinguishable from a lost file if a checker only
    tests the claimed path.  Indexing the whole tree by content digest lets the
    report separate "the bytes moved" from "the bytes are gone", which are very
    different defects for a consumer of the packs.
    """

    def __init__(self, git: ReadOnlyGit, commit: str, paths: Iterable[str]) -> None:
        self._by_digest: dict[str, list[str]] = {}
        for path in paths:
            payload = git.blob(commit, path)
            if payload is None:
                continue
            self._by_digest.setdefault(sha256_hex(payload), []).append(path)

    def paths_for(self, digest: str) -> list[str]:
        return sorted(self._by_digest.get(digest, []))


def _discrepancy(
    kind: str,
    manifest_path: str,
    claim: str,
    expected: Any,
    observed: Any,
    *,
    subject: str | None = None,
) -> dict[str, Any]:
    if kind not in DISCREPANCY_KINDS:
        raise ValueError(f"unknown discrepancy kind: {kind}")
    return {
        "kind": kind,
        "manifest_path": manifest_path,
        "claim": claim,
        "subject": subject,
        "expected": expected,
        "observed": observed,
    }


def check_manifest(
    git: ReadOnlyGit,
    commit: str,
    manifest_path: str,
    manifest: dict[str, Any],
    index: ContentIndex,
) -> dict[str, Any]:
    """Check one per-pack manifest's file, count and portability claims."""
    manifest_dir = manifest_path.rsplit("/", 1)[0] if "/" in manifest_path else ""
    discrepancies: list[dict[str, Any]] = []
    try:
        claims = normalise_file_claims(manifest)
    except ClaimReadError as error:
        return {
            "manifest_path": manifest_path,
            "checked_claim_count": 0,
            "verified_claim_count": 0,
            "discrepancies": [
                _discrepancy(
                    "UNVERIFIABLE_MANIFEST_DIALECT",
                    manifest_path,
                    "files",
                    "a recognised v2 object or array dialect",
                    str(error),
                )
            ],
        }

    verified = 0
    observed_total_bytes = 0
    for claim in claims:
        relative_path = claim["relative_path"]
        full_path = f"{manifest_dir}/{relative_path}" if manifest_dir else relative_path
        payload = git.blob(commit, full_path)
        if payload is None:
            relocated = index.paths_for(claim["sha256"])
            if relocated:
                discrepancies.append(
                    _discrepancy(
                        "MISSING_AT_CLAIMED_PATH_CONTENT_RELOCATED",
                        manifest_path,
                        "files[].path",
                        full_path,
                        {"present_at": relocated, "content_identical": True},
                        subject=relative_path,
                    )
                )
            else:
                discrepancies.append(
                    _discrepancy(
                        "MISSING_AT_CLAIMED_PATH_CONTENT_ABSENT",
                        manifest_path,
                        "files[].path",
                        full_path,
                        None,
                        subject=relative_path,
                    )
                )
            continue

        observed_digest = sha256_hex(payload)
        observed_bytes = len(payload)
        observed_total_bytes += observed_bytes
        digest_ok = observed_digest == claim["sha256"]
        bytes_ok = observed_bytes == claim["bytes"]
        if not digest_ok:
            discrepancies.append(
                _discrepancy(
                    "DIGEST_MISMATCH",
                    manifest_path,
                    "files[].sha256",
                    claim["sha256"],
                    observed_digest,
                    subject=relative_path,
                )
            )
        if not bytes_ok:
            discrepancies.append(
                _discrepancy(
                    "BYTE_COUNT_MISMATCH",
                    manifest_path,
                    "files[].bytes",
                    claim["bytes"],
                    observed_bytes,
                    subject=relative_path,
                )
            )
        if digest_ok and bytes_ok:
            verified += 1

    claimed_file_count = manifest.get("file_count")
    if isinstance(claimed_file_count, int) and claimed_file_count != len(claims):
        discrepancies.append(
            _discrepancy(
                "FILE_COUNT_MISMATCH",
                manifest_path,
                "file_count",
                claimed_file_count,
                len(claims),
            )
        )

    claimed_total_bytes = manifest.get("total_bytes")
    enumerated_bytes = sum(claim["bytes"] for claim in claims)
    if isinstance(claimed_total_bytes, int) and claimed_total_bytes != enumerated_bytes:
        discrepancies.append(
            _discrepancy(
                "TOTAL_BYTES_MISMATCH",
                manifest_path,
                "total_bytes",
                claimed_total_bytes,
                enumerated_bytes,
            )
        )

    for absolute in collect_absolute_path_claims(manifest):
        discrepancies.append(
            _discrepancy(
                "NON_PORTABLE_ABSOLUTE_PATH_CLAIM",
                manifest_path,
                absolute["json_pointer"],
                "a repository-relative path",
                absolute["value"],
            )
        )

    return {
        "manifest_path": manifest_path,
        "checked_claim_count": len(claims),
        "verified_claim_count": verified,
        "observed_present_bytes": observed_total_bytes,
        "discrepancies": discrepancies,
    }


def check_aggregate_manifest(
    manifest_path: str,
    manifest: dict[str, Any],
    pack_directories: list[str],
) -> dict[str, Any]:
    """Check an aggregate manifest's coverage and portability claims."""
    discrepancies: list[dict[str, Any]] = []
    claimed_packs = manifest.get("packs")
    covered = sorted(claimed_packs) if isinstance(claimed_packs, dict) else []
    uncovered = sorted(set(pack_directories) - set(covered))
    if covered and uncovered:
        discrepancies.append(
            _discrepancy(
                "AGGREGATE_COVERAGE_GAP",
                manifest_path,
                "packs",
                sorted(pack_directories),
                {"covered": covered, "uncovered": uncovered},
            )
        )
    for absolute in collect_absolute_path_claims(manifest):
        discrepancies.append(
            _discrepancy(
                "NON_PORTABLE_ABSOLUTE_PATH_CLAIM",
                manifest_path,
                absolute["json_pointer"],
                "a repository-relative path",
                absolute["value"],
            )
        )
    return {
        "manifest_path": manifest_path,
        "covered_pack_count": len(covered),
        "uncovered_packs": uncovered,
        "discrepancies": discrepancies,
    }


def _pack_directories(tree_paths: list[str], pack_root: str) -> list[str]:
    prefix = f"{pack_root}/"
    names: set[str] = set()
    for path in tree_paths:
        if not path.startswith(prefix):
            continue
        remainder = path[len(prefix) :]
        if "/" in remainder:
            names.add(remainder.split("/", 1)[0])
    return sorted(names)


def reproduce(repo: Path, revision: str, pack_root: str) -> dict[str, Any]:
    """Check every pack manifest under ``pack_root`` at ``revision``.

    Returns a deterministic report.  The caller supplies the revision; the
    reproducer resolves it once to an immutable commit id and reads nothing
    else, so a moving branch tip cannot silently change what was checked.
    """
    git = ReadOnlyGit(repo)
    refs_before = git.refs_digest()
    head_before = git.head_state()

    commit = git.resolve_commit(revision)
    tree_paths = git.list_tree(commit)
    scoped_paths = [path for path in tree_paths if path == pack_root or path.startswith(f"{pack_root}/")]
    if not scoped_paths:
        raise ClaimReadError(f"commit {commit} has no paths under {pack_root!r}")

    index = ContentIndex(git, commit, scoped_paths)
    manifest_paths = sorted(path for path in scoped_paths if path.rsplit("/", 1)[-1] == "MANIFEST.json")
    pack_directories = _pack_directories(scoped_paths, pack_root)

    per_pack: list[dict[str, Any]] = []
    aggregate: list[dict[str, Any]] = []
    for manifest_path in manifest_paths:
        payload = git.blob(commit, manifest_path)
        if payload is None:
            raise ClaimReadError(f"manifest disappeared from immutable tree: {manifest_path}")
        try:
            manifest = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            per_pack.append(
                {
                    "manifest_path": manifest_path,
                    "checked_claim_count": 0,
                    "verified_claim_count": 0,
                    "discrepancies": [
                        _discrepancy(
                            "UNVERIFIABLE_MANIFEST_DIALECT",
                            manifest_path,
                            "$",
                            "parseable UTF-8 JSON",
                            str(error),
                        )
                    ],
                }
            )
            continue
        if isinstance(manifest.get("files"), (dict, list)):
            per_pack.append(check_manifest(git, commit, manifest_path, manifest, index))
        else:
            aggregate.append(check_aggregate_manifest(manifest_path, manifest, pack_directories))

    refs_after = git.refs_digest()
    head_after = git.head_state()

    discrepancies = [
        discrepancy
        for report in (*per_pack, *aggregate)
        for discrepancy in report["discrepancies"]
    ]
    kind_counts = {kind: 0 for kind in DISCREPANCY_KINDS}
    for discrepancy in discrepancies:
        kind_counts[discrepancy["kind"]] += 1

    checked = sum(report["checked_claim_count"] for report in per_pack)
    verified = sum(report["verified_claim_count"] for report in per_pack)

    return {
        "protocol_version": "OBZIO-PACK-CLAIM-REPRODUCTION-v1",
        "task_id": "PO03-WA-006",
        "hypothesis_id": "H-PO03-WA-006",
        "target": {
            "requested_revision": revision,
            "resolved_commit": commit,
            "pack_root": pack_root,
            "tree_path_count": len(scoped_paths),
            "pack_directory_count": len(pack_directories),
            "pack_directories": pack_directories,
            "manifest_count": len(manifest_paths),
        },
        "non_mutation_witness": {
            "refs_digest_before": refs_before,
            "refs_digest_after": refs_after,
            "refs_unchanged": refs_before == refs_after,
            "head_before": head_before,
            "head_after": head_after,
            "head_unchanged": head_before == head_after,
            "checkout_performed": False,
            "producer_narrative_read": False,
            "read_only_git_calls": git.call_count,
            "allowed_git_subcommands": sorted(READ_ONLY_GIT_SUBCOMMANDS),
        },
        "totals": {
            "file_claims_checked": checked,
            "file_claims_verified": verified,
            "file_claims_falsified": checked - verified,
            "discrepancy_count": len(discrepancies),
            "discrepancy_kind_counts": {
                kind: count for kind, count in sorted(kind_counts.items()) if count
            },
        },
        "per_pack_manifests": per_pack,
        "aggregate_manifests": aggregate,
        "discrepancies": discrepancies,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="repository to read objects from")
    parser.add_argument("--revision", required=True, help="revision pinned by the caller")
    parser.add_argument("--pack-root", default="packs", help="tree prefix holding the packs")
    parser.add_argument("--out", type=Path, help="write the report here instead of stdout")
    parser.add_argument(
        "--expect-clean",
        action="store_true",
        help="exit non-zero when any claim is falsified",
    )
    args = parser.parse_args(argv)

    try:
        report = reproduce(args.repo, args.revision, args.pack_root)
    except (ClaimReadError, ReadOnlyViolation) as error:
        print(f"REPRODUCTION_FAILED: {error}", file=sys.stderr)
        return 2

    serialised = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(serialised, encoding="utf-8")
    else:
        sys.stdout.write(serialised)

    if not report["non_mutation_witness"]["refs_unchanged"]:
        print("REPRODUCTION_FAILED: refs moved during a read-only scan", file=sys.stderr)
        return 2
    if args.expect_clean and report["totals"]["discrepancy_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
