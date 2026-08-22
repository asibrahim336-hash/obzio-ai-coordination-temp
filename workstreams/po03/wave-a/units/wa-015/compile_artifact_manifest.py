#!/usr/bin/env python3
"""Compile the deterministic artifact manifest for PO-03 Wave A unit WA-015.

Every payload file in the owned subtree is hashed exactly once.  The two return
envelopes are excluded from their own hash closure: this manifest hashes every
payload predecessor, ``result/ready-to-commit.json`` hashes this manifest, and
the terminal report carries the ready-envelope digest, because no document can
contain its own digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any


UNIT_ROOT = Path(__file__).resolve().parent
REPO_PREFIX = "workstreams/po03/wave-a/units/wa-015"

MANIFEST_PROTOCOL = "OBZIO-ARTIFACT-MANIFEST-v1"
TASK_ID = "PO03-WA-015"
COMMISSION_ID = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
ACCEPTANCE_CONTRACT_SHA256 = (
    "b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a"
)
IMMUTABLE_INPUT_SHA256 = (
    "f06c344679f09cf4bc523fe904a98970b3fe82dce4026115ccd5d787da08e2f5"
)
SOURCE_BASE_COMMIT = "7f9425655d6faa95219dc16d820bfbe18b91553f"

ATTEMPT = {
    "attempt_id": "PO03-WA-015-A02",
    "idempotency_key": "po03:100bc2079ced:wa-015:a02",
    "lease_id": "lease-po03-wa-015-a02",
    "fence_token": 2,
}

#: Envelopes that cannot appear inside their own hash closure.  The custody
#: document joins them because it can only be written once the result commit it
#: describes exists, which is strictly after this manifest is frozen.
EXCLUDED_ENVELOPES = (
    "result/artifact-manifest.json",
    "result/ready-to-commit.json",
    "result/transactional-result.json",
)

EXCLUDED_DIRECTORY_NAMES = frozenset({"__pycache__", ".git", ".pytest_cache"})
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".orig", ".rej", ".swp", ".tmp")

MEDIA_TYPES = {
    ".py": "text/x-python; charset=utf-8",
    ".json": "application/json",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}
DEFAULT_MEDIA_TYPE = "application/octet-stream"


class ManifestError(ValueError):
    """The subtree contains something a deterministic manifest cannot carry."""


def media_type(name: str) -> str:
    return MEDIA_TYPES.get(PurePosixPath(name).suffix, DEFAULT_MEDIA_TYPE)


def artifact_id(logical_name: str) -> str:
    stem = hashlib.sha256(logical_name.encode("utf-8")).hexdigest()[:12]
    return f"art-po03-wa-015-{stem}"


def discover(unit_root: Path) -> list[str]:
    """Return every payload path, sorted by UTF-8 bytes of its logical name."""
    unit_root = Path(unit_root)
    names: list[str] = []
    for path in sorted(unit_root.rglob("*"), key=lambda p: p.as_posix()):
        relative = path.relative_to(unit_root).as_posix()
        if any(part in EXCLUDED_DIRECTORY_NAMES for part in path.relative_to(unit_root).parts):
            continue
        if path.is_dir():
            continue
        if path.is_symlink():
            raise ManifestError(f"symlink refused: {relative}")
        if not path.is_file():
            raise ManifestError(f"not a regular file: {relative}")
        if relative.endswith(EXCLUDED_SUFFIXES):
            raise ManifestError(f"temporary artifact refused: {relative}")
        if PurePosixPath(relative).name.startswith("."):
            raise ManifestError(f"hidden artifact refused: {relative}")
        if unicodedata.normalize("NFC", relative) != relative:
            raise ManifestError(f"path is not NFC normalised: {relative}")
        if relative in EXCLUDED_ENVELOPES:
            continue
        names.append(relative)
    if not names:
        raise ManifestError("no payload artifacts discovered")
    return sorted(names, key=lambda name: name.encode("utf-8"))


def content_tree_sha256(rows: list[dict[str, Any]]) -> str:
    """Length-framed digest over (logical_name, content digest) pairs."""
    accumulator = hashlib.sha256()
    for row in rows:
        name = row["logical_name"].encode("utf-8")
        accumulator.update(len(name).to_bytes(8, "big"))
        accumulator.update(name)
        accumulator.update(bytes.fromhex(row["sha256"]))
    return accumulator.hexdigest()


def compile_manifest(unit_root: Path = UNIT_ROOT) -> dict[str, Any]:
    unit_root = Path(unit_root)
    artifacts: list[dict[str, Any]] = []
    for logical_name in discover(unit_root):
        data = (unit_root / logical_name).read_bytes()
        if not data:
            raise ManifestError(f"empty artifact refused: {logical_name}")
        artifacts.append(
            {
                "artifact_id": artifact_id(logical_name),
                "bytes": len(data),
                "content_uri": f"{REPO_PREFIX}/{logical_name}",
                "logical_name": logical_name,
                "media_type": media_type(logical_name),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    identifiers = [row["artifact_id"] for row in artifacts]
    if len(set(identifiers)) != len(identifiers):
        raise ManifestError("artifact id collision")
    return {
        "acceptance_contract_sha256": ACCEPTANCE_CONTRACT_SHA256,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "attempt": dict(ATTEMPT),
        "commission_id": COMMISSION_ID,
        "decision_changed": [],
        "hash_algorithm": "sha256",
        "hash_closure": {
            "excluded_envelopes": list(EXCLUDED_ENVELOPES),
            "rule": (
                "This manifest hashes every payload predecessor including "
                "result/result.json. result/ready-to-commit.json hashes this "
                "manifest and the custody document, and the terminal "
                "READY_TO_COMMIT report carries the ready-envelope digest, "
                "because no document can contain its own digest."
            ),
        },
        "immutable_input_manifest_sha256": IMMUTABLE_INPUT_SHA256,
        "manifest_content_tree_sha256": content_tree_sha256(artifacts),
        "protocol_version": MANIFEST_PROTOCOL,
        "source_base_commit": SOURCE_BASE_COMMIT,
        "task_id": TASK_ID,
        "total_bytes": sum(row["bytes"] for row in artifacts),
    }


def render(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--unit-root", type=Path, default=UNIT_ROOT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when the output file is not already current.",
    )
    args = parser.parse_args(argv)
    rendered = render(compile_manifest(args.unit_root))
    if args.output is None:
        sys.stdout.buffer.write(rendered)
        return 0
    if args.check:
        current = args.output.read_bytes() if args.output.exists() else b""
        if current != rendered:
            sys.stdout.buffer.write(b"STALE " + args.output.as_posix().encode() + b"\n")
            return 1
        sys.stdout.buffer.write(b"CURRENT " + args.output.as_posix().encode() + b"\n")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(rendered)
    args.output.chmod(0o644)
    sys.stdout.buffer.write(
        f"{hashlib.sha256(rendered).hexdigest()} {len(rendered)}\n".encode()
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
