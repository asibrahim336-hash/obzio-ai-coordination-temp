#!/usr/bin/env python3
"""Create and resolve immutable source capsules using read-only git plumbing."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


PROTOCOL_VERSION = "OBZIO-GIT-SOURCE-CAPSULE-v1"
OBJECT_ID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ROOT_FIELDS = {"protocol_version", "capsule_id", "version", "lineage", "entries"}
LINEAGE_FIELDS = {
    "predecessor_capsule_id",
    "predecessor_manifest_sha256",
    "reason",
}
ENTRY_FIELDS = {"path", "blob_sha", "commit_sha"}


class CapsuleError(ValueError):
    """Raised when a capsule cannot be constructed or resolved."""


def _git(repo: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise CapsuleError(f"git {' '.join(args)} failed: {detail or exc}") from exc


def canonical_bytes(capsule: dict[str, Any]) -> bytes:
    return (
        json.dumps(capsule, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def manifest_sha256(capsule: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(capsule)).hexdigest()


def _normalise_path(path: str) -> str:
    if not isinstance(path, str) or not path:
        raise CapsuleError("capsule paths must be non-empty strings")
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
        raise CapsuleError(f"capsule path is not repository-relative: {path!r}")
    normalised = candidate.as_posix()
    if normalised != path or normalised == ".":
        raise CapsuleError(f"capsule path is not canonical: {path!r}")
    return normalised


def _full_commit(repo: Path, commit_sha: str) -> str:
    resolved = _git(repo, "rev-parse", "--verify", f"{commit_sha}^{{commit}}").decode().strip()
    if not OBJECT_ID_RE.fullmatch(resolved):
        raise CapsuleError(f"git returned a non-canonical commit object id: {resolved!r}")
    return resolved


def _tree_blob(repo: Path, commit_sha: str, path: str) -> str:
    output = _git(repo, "ls-tree", "-z", commit_sha, "--", path)
    rows = [row for row in output.split(b"\x00") if row]
    if len(rows) != 1:
        raise CapsuleError(f"{path}: expected one blob at commit {commit_sha}, found {len(rows)}")
    try:
        metadata, observed_path = rows[0].split(b"\t", 1)
        _mode, object_type, object_id = metadata.decode("ascii").split(" ")
        decoded_path = observed_path.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise CapsuleError(f"{path}: malformed git ls-tree output") from exc
    if decoded_path != path or object_type != "blob" or not OBJECT_ID_RE.fullmatch(object_id):
        raise CapsuleError(f"{path}: commit entry is not the expected blob")
    return object_id


def _entry(repo: Path, commit_sha: str, path: str) -> dict[str, str]:
    normalised = _normalise_path(path)
    full_commit = _full_commit(repo, commit_sha)
    return {
        "path": normalised,
        "blob_sha": _tree_blob(repo, full_commit, normalised),
        "commit_sha": full_commit,
    }


def create_capsule(
    repo: Path,
    *,
    capsule_id: str,
    version: int,
    commit_sha: str,
    paths: Iterable[str],
    reason: str,
) -> dict[str, Any]:
    """Issue the initial capsule in a lineage without writing to the repository."""
    if not isinstance(capsule_id, str) or not capsule_id:
        raise CapsuleError("capsule_id must be a non-empty string")
    if version != 1:
        raise CapsuleError("an initial capsule must have version 1")
    if not isinstance(reason, str) or not reason:
        raise CapsuleError("lineage reason must be a non-empty string")
    canonical_paths = sorted({_normalise_path(path) for path in paths})
    if not canonical_paths:
        raise CapsuleError("a capsule requires at least one source path")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "capsule_id": capsule_id,
        "version": 1,
        "lineage": {
            "predecessor_capsule_id": None,
            "predecessor_manifest_sha256": None,
            "reason": reason,
        },
        "entries": [_entry(repo, commit_sha, path) for path in canonical_paths],
    }


def issue_successor(
    repo: Path,
    *,
    predecessor: dict[str, Any],
    capsule_id: str,
    commit_sha: str,
    reason: str,
) -> dict[str, Any]:
    """Create a new version; never modify the predecessor object or its bytes."""
    predecessor_errors = validate_capsule(repo, predecessor)
    if predecessor_errors:
        raise CapsuleError("invalid predecessor: " + "; ".join(predecessor_errors))
    if capsule_id == predecessor["capsule_id"]:
        raise CapsuleError("a successor must have a new capsule_id")
    if not isinstance(capsule_id, str) or not capsule_id:
        raise CapsuleError("capsule_id must be a non-empty string")
    if not isinstance(reason, str) or not reason:
        raise CapsuleError("lineage reason must be a non-empty string")
    paths = [entry["path"] for entry in predecessor["entries"]]
    return {
        "protocol_version": PROTOCOL_VERSION,
        "capsule_id": capsule_id,
        "version": predecessor["version"] + 1,
        "lineage": {
            "predecessor_capsule_id": predecessor["capsule_id"],
            "predecessor_manifest_sha256": manifest_sha256(predecessor),
            "reason": reason,
        },
        "entries": [_entry(repo, commit_sha, path) for path in paths],
    }


def _shape_errors(capsule: Any) -> list[str]:
    if not isinstance(capsule, dict):
        return ["$: capsule must be an object"]
    errors: list[str] = []
    missing = ROOT_FIELDS - set(capsule)
    extra = set(capsule) - ROOT_FIELDS
    errors.extend(f"$.{name}: missing" for name in sorted(missing))
    errors.extend(f"$.{name}: undeclared field" for name in sorted(extra))
    if missing:
        return errors
    if capsule["protocol_version"] != PROTOCOL_VERSION:
        errors.append("$.protocol_version: unsupported")
    if not isinstance(capsule["capsule_id"], str) or not capsule["capsule_id"]:
        errors.append("$.capsule_id: must be non-empty")
    if (
        not isinstance(capsule["version"], int)
        or isinstance(capsule["version"], bool)
        or capsule["version"] < 1
    ):
        errors.append("$.version: must be an integer >= 1")

    lineage = capsule["lineage"]
    if not isinstance(lineage, dict):
        errors.append("$.lineage: must be an object")
    else:
        errors.extend(
            f"$.lineage.{name}: missing"
            for name in sorted(LINEAGE_FIELDS - set(lineage))
        )
        errors.extend(
            f"$.lineage.{name}: undeclared field"
            for name in sorted(set(lineage) - LINEAGE_FIELDS)
        )
        if LINEAGE_FIELDS <= set(lineage):
            predecessor_id = lineage["predecessor_capsule_id"]
            predecessor_hash = lineage["predecessor_manifest_sha256"]
            if capsule["version"] == 1:
                if predecessor_id is not None or predecessor_hash is not None:
                    errors.append("$.lineage: version 1 cannot name a predecessor")
            else:
                if not isinstance(predecessor_id, str) or not predecessor_id:
                    errors.append("$.lineage.predecessor_capsule_id: required")
                if not isinstance(predecessor_hash, str) or not SHA256_RE.fullmatch(
                    predecessor_hash
                ):
                    errors.append("$.lineage.predecessor_manifest_sha256: invalid")
            if not isinstance(lineage["reason"], str) or not lineage["reason"]:
                errors.append("$.lineage.reason: must be non-empty")

    entries = capsule["entries"]
    if not isinstance(entries, list) or not entries:
        errors.append("$.entries: must be a non-empty array")
        return errors
    observed_paths: list[str] = []
    for index, entry in enumerate(entries):
        prefix = f"$.entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        errors.extend(f"{prefix}.{name}: missing" for name in sorted(ENTRY_FIELDS - set(entry)))
        errors.extend(
            f"{prefix}.{name}: undeclared field"
            for name in sorted(set(entry) - ENTRY_FIELDS)
        )
        if not ENTRY_FIELDS <= set(entry):
            continue
        try:
            observed_paths.append(_normalise_path(entry["path"]))
        except CapsuleError as exc:
            errors.append(f"{prefix}.path: {exc}")
        for name in ("blob_sha", "commit_sha"):
            if not isinstance(entry[name], str) or not OBJECT_ID_RE.fullmatch(entry[name]):
                errors.append(f"{prefix}.{name}: invalid git object id")
    if observed_paths != sorted(set(observed_paths)):
        errors.append("$.entries: paths must be unique and sorted")
    return errors


def validate_capsule(repo: Path, capsule: Any) -> list[str]:
    errors = _shape_errors(capsule)
    if errors or not isinstance(capsule, dict):
        return errors
    for index, entry in enumerate(capsule["entries"]):
        if not isinstance(entry, dict) or not ENTRY_FIELDS <= set(entry):
            continue
        prefix = f"$.entries[{index}]"
        try:
            full_commit = _full_commit(repo, entry["commit_sha"])
            if full_commit != entry["commit_sha"]:
                errors.append(f"{prefix}.commit_sha: not a full commit object id")
                continue
            observed_blob = _tree_blob(repo, full_commit, entry["path"])
            if observed_blob != entry["blob_sha"]:
                errors.append(
                    f"{prefix}.blob_sha: expected {entry['blob_sha']}, observed {observed_blob}"
                )
        except CapsuleError as exc:
            errors.append(f"{prefix}: {exc}")
    return errors


def validate_lineage(
    predecessor: dict[str, Any], successor: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    if successor.get("version") != predecessor.get("version", 0) + 1:
        errors.append("$.version: successor must increment predecessor by one")
    lineage = successor.get("lineage")
    if not isinstance(lineage, dict):
        return errors + ["$.lineage: missing successor lineage"]
    if lineage.get("predecessor_capsule_id") != predecessor.get("capsule_id"):
        errors.append("$.lineage.predecessor_capsule_id: discrepancy")
    if lineage.get("predecessor_manifest_sha256") != manifest_sha256(predecessor):
        errors.append("$.lineage.predecessor_manifest_sha256: discrepancy")
    predecessor_paths = [
        entry.get("path") for entry in predecessor.get("entries", []) if isinstance(entry, dict)
    ]
    successor_paths = [
        entry.get("path") for entry in successor.get("entries", []) if isinstance(entry, dict)
    ]
    if successor_paths != predecessor_paths:
        errors.append("$.entries: successor source set differs from predecessor")
    return errors


def resolve_capsule(repo: Path, capsule: dict[str, Any]) -> dict[str, bytes]:
    """Resolve bytes from object storage; no worktree path is ever read."""
    errors = validate_capsule(repo, capsule)
    if errors:
        raise CapsuleError("; ".join(errors))
    return {
        entry["path"]: _git(repo, "cat-file", "blob", entry["blob_sha"])
        for entry in capsule["entries"]
    }


def load_capsule(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapsuleError(f"cannot load capsule {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CapsuleError("capsule root must be an object")
    return value


def _write_new(path: Path, capsule: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(canonical_bytes(capsule))
    except FileExistsError as exc:
        raise CapsuleError(
            f"refusing to mutate existing frozen capsule; issue a new output path: {path}"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--repo", type=Path, required=True)
    create.add_argument("--capsule-id", required=True)
    create.add_argument("--commit", required=True)
    create.add_argument("--path", action="append", default=[])
    create.add_argument("--reason", required=True)
    create.add_argument("--predecessor", type=Path)
    create.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--repo", type=Path, required=True)
    verify.add_argument("--capsule", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            if args.predecessor:
                predecessor = load_capsule(args.predecessor)
                capsule = issue_successor(
                    args.repo,
                    predecessor=predecessor,
                    capsule_id=args.capsule_id,
                    commit_sha=args.commit,
                    reason=args.reason,
                )
            else:
                capsule = create_capsule(
                    args.repo,
                    capsule_id=args.capsule_id,
                    version=1,
                    commit_sha=args.commit,
                    paths=args.path,
                    reason=args.reason,
                )
            _write_new(args.output, capsule)
            print(
                f"WROTE {args.output} capsule_id={capsule['capsule_id']} "
                f"version={capsule['version']} sha256={manifest_sha256(capsule)}"
            )
            return 0

        capsule = load_capsule(args.capsule)
        errors = validate_capsule(args.repo, capsule)
        if errors:
            for error in errors:
                print(f"INVALID: {error}")
            return 1
        print(
            f"VALID capsule_id={capsule['capsule_id']} version={capsule['version']} "
            f"entries={len(capsule['entries'])} sha256={manifest_sha256(capsule)}"
        )
        return 0
    except CapsuleError as exc:
        print(f"INVALID: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
