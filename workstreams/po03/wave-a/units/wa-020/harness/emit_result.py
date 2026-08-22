"""Build the five required result documents with complete digest and byte accounting.

No document can contain its own digest, so the accounting is a chain rather than a
single list:

    every owned file  -> result/artifact-manifest.json
    artifact-manifest -> result/ready-to-commit.json:manifest_sha256
    ready-to-commit   -> the git tree of the return commit

``artifact-manifest.json`` and ``ready-to-commit.json`` are therefore the two files
the manifest cannot cover, and both exclusions are declared in the manifest itself
rather than left for a reader to notice. Every other owned file appears in the
manifest exactly once.

The manifest and the artifacts it lists must be immutable at the result commit, so
``ready-to-commit.json`` is written afterwards, in a distinct return commit, and
names the files that lie beyond the result commit.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .canonical import digest_bytes, write_json

UNIT_RELPATH = "workstreams/po03/wave-a/units/wa-020"
RESULT_RELPATH = f"{UNIT_RELPATH}/result"

SELF_EXCLUDED = {
    "result/artifact-manifest.json": "a manifest cannot contain its own digest",
    "result/ready-to-commit.json": (
        "written after the result commit exists, so that the manifest and the artifacts it lists "
        "are immutable at the result commit; digested by the git tree of the return commit"
    ),
}

MEDIA_TYPES = {".json": "application/json", ".py": "text/x-python", ".txt": "text/plain"}


def media_type(path: Path) -> str:
    return MEDIA_TYPES.get(path.suffix, "application/octet-stream")


def owned_files(unit_root: Path) -> list[str]:
    """Every file the unit owns, as a sorted list of unit-relative paths."""
    found = []
    for path in sorted(unit_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(unit_root).as_posix()
        if "__pycache__" in relative:
            continue
        found.append(relative)
    return found


def describe(unit_root: Path, relative: str) -> dict[str, Any]:
    payload = (unit_root / relative).read_bytes()
    return {
        "bytes": len(payload),
        "logical_name": relative,
        "media_type": media_type(Path(relative)),
        "sha256": digest_bytes(payload),
    }


def build_manifest(unit_root: Path, attempt: dict[str, Any], task_id: str) -> dict[str, Any]:
    """The manifest over every owned file the manifest is able to cover."""
    covered = [name for name in owned_files(unit_root) if name not in SELF_EXCLUDED]
    artifacts = [describe(unit_root, name) for name in covered]

    groups: dict[str, list[str]] = {}
    for name in covered:
        head, _, tail = name.partition("/")
        groups.setdefault(head if tail else ".", []).append(name)

    required: dict[str, Any] = {}
    for document in ("result.json", "tests.json", "limitations.json"):
        record = describe(unit_root, f"result/{document}")
        required[document] = {
            "bytes": record["bytes"],
            "digest_recorded_here": True,
            "media_type": record["media_type"],
            "present": True,
            "sha256": record["sha256"],
        }
    for document, reason in (
        ("artifact-manifest.json", SELF_EXCLUDED["result/artifact-manifest.json"]),
        ("ready-to-commit.json", SELF_EXCLUDED["result/ready-to-commit.json"]),
    ):
        required[document] = {
            "digest_recorded_here": False,
            "present": document == "artifact-manifest.json",
            "reason": reason,
        }

    return {
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "attempt_id": attempt["attempt_id"],
        "coverage": (
            "Every file in the owned subtree except this manifest, which cannot hash itself, and "
            "ready-to-commit.json, which is written afterwards so that this manifest and the artifacts "
            "it lists stay immutable at the result commit."
        ),
        "excluded": [
            {"logical_name": name, "reason": reason} for name, reason in sorted(SELF_EXCLUDED.items())
        ],
        "groups": {key: sorted(value) for key, value in sorted(groups.items())},
        "hash_algorithm": "sha256",
        # Counted as covered plus the two declared exclusions rather than by globbing
        # the tree: this manifest is built before it and ready-to-commit.json exist,
        # so a glob here would undercount the tree the reader ends up holding.
        "owned_file_count": len(covered) + len(SELF_EXCLUDED),
        "owned_subtree": UNIT_RELPATH,
        "protocol_version": "OBZIO-ARTIFACT-MANIFEST-v1",
        "required_result_documents": required,
        "task_id": task_id,
        "total_bytes": sum(item["bytes"] for item in artifacts),
    }


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], capture_output=True, check=True, cwd=root, text=True
    )
    return completed.stdout.strip()


def readback(root: Path, commit: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """Read every manifest artifact out of an immutable commit and reconcile it.

    The bytes are taken from ``git show <commit>:<path>`` rather than from the working
    tree, so a working-tree edit after the commit cannot make this reconcile.
    """
    rows = []
    for artifact in manifest["artifacts"]:
        blob = subprocess.run(
            ["git", "show", f"{commit}:{UNIT_RELPATH}/{artifact['logical_name']}"],
            capture_output=True,
            check=True,
            cwd=root,
        ).stdout
        rows.append(
            {
                "disposition": (
                    "MATCHES"
                    if digest_bytes(blob) == artifact["sha256"] and len(blob) == artifact["bytes"]
                    else "MISMATCH"
                ),
                "expected_bytes": artifact["bytes"],
                "expected_sha256": artifact["sha256"],
                "logical_name": artifact["logical_name"],
                "observed_bytes": len(blob),
                "observed_sha256": digest_bytes(blob),
            }
        )

    manifest_blob = subprocess.run(
        ["git", "show", f"{commit}:{RESULT_RELPATH}/artifact-manifest.json"],
        capture_output=True,
        check=True,
        cwd=root,
    ).stdout
    return {
        "all_artifacts_reconcile": all(row["disposition"] == "MATCHES" for row in rows),
        "artifact_count": len(rows),
        "artifacts": rows,
        "manifest_observed_sha256": digest_bytes(manifest_blob),
        "method": (
            "git show <result_commit_id>:<path> for every artifact the manifest lists, digested as "
            "read. The commit is fetched from the remote tracking ref, so the bytes are the ones the "
            "remote holds and not the local working tree."
        ),
        "mismatches": [row for row in rows if row["disposition"] != "MATCHES"],
        "read_from_commit": commit,
    }


def write_documents(unit_root: Path, documents: dict[str, Any]) -> dict[str, tuple[str, int]]:
    """Write result documents in dependency order and return their digests and sizes."""
    written = {}
    for name in ("result.json", "tests.json", "limitations.json", "artifact-manifest.json"):
        if name in documents:
            written[name] = write_json(unit_root / "result" / name, documents[name])
    return written


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
