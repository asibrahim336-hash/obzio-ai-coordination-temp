#!/usr/bin/env python3
"""Build or verify complete acyclic artifact accounting for WA-014."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


UNIT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[6]
MANIFEST = UNIT_ROOT / "result" / "artifact-manifest.json"
READY = UNIT_ROOT / "result" / "ready-to-commit.json"
EXCLUDED = {MANIFEST.resolve(), READY.resolve()}
OWNED_PREFIX = "workstreams/po03/wave-a/units/wa-014"


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _media_type(path: Path) -> str:
    if path.suffix == ".json":
        return "application/json"
    if path.suffix == ".py":
        return "text/x-python; charset=utf-8"
    if path.suffix == ".md":
        return "text/markdown; charset=utf-8"
    if path.suffix == ".txt":
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def _role(relative: str) -> str:
    if relative == "README.md":
        return "documentation"
    if relative.startswith("mechanism/"):
        return "executable_mechanism"
    if relative.startswith("tests/"):
        return "test"
    if relative.startswith("evidence/source-claims"):
        return "source_claim"
    if relative.startswith("evidence/frozen-hypotheses"):
        return "frozen_hypothesis"
    if relative.startswith("evidence/sanitized-reproduction"):
        return "sanitized_reproduction"
    if relative.startswith("evidence/mechanism-changes"):
        return "mechanism_change"
    if relative.startswith("evidence/strategy-proposals"):
        return "strategy_proposal"
    return "result"


def _files() -> list[Path]:
    files = []
    for path in UNIT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.resolve() in EXCLUDED:
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if any(part.startswith(".wa014-") for part in path.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"symlink artifacts are prohibited: {path}")
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(UNIT_ROOT).as_posix())


def build() -> dict[str, Any]:
    artifacts = []
    role_totals: dict[str, dict[str, int]] = {}
    for path in _files():
        data = path.read_bytes()
        if not data:
            raise ValueError(f"empty artifacts are prohibited: {path}")
        relative = path.relative_to(UNIT_ROOT).as_posix()
        content_uri = f"{OWNED_PREFIX}/{relative}"
        digest = hashlib.sha256(data).hexdigest()
        role = _role(relative)
        artifacts.append(
            {
                "artifact_id": (
                    "art-po03-wa-014-"
                    + relative.replace("/", "-").replace(".", "-")
                    + "-"
                    + digest[:12]
                ),
                "logical_name": relative,
                "content_uri": content_uri,
                "role": role,
                "sha256": digest,
                "bytes": len(data),
                "media_type": _media_type(path),
            }
        )
        totals = role_totals.setdefault(role, {"count": 0, "bytes": 0})
        totals["count"] += 1
        totals["bytes"] += len(data)

    return {
        "protocol_version": "PO03-WAVE-A-MATERIAL-MANIFEST-v1",
        "manifest_id": "man-po03-wa-014-a02",
        "task_id": "PO03-WA-014",
        "hypothesis_id": "H-PO03-WA-014",
        "attempt": {
            "attempt_id": "PO03-WA-014-A02",
            "idempotency_key": "po03:100bc2079ced:wa-014:a02",
            "lease_id": "lease-po03-wa-014-a02",
            "fence_token": 2,
            "checkpoint_seq": 0,
        },
        "commission_id": (
            "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
        ),
        "controller_run_id": "bc-b1956656-b897-4889-aeab-82c4556c1a9f",
        "remote_branch": "cursor/po03-wa-014-b195-a02-1a9f",
        "owned_subtree": f"{OWNED_PREFIX}/",
        "source_base": {
            "immutable_controller_base": (
                "2c05988f4fe156c32e8193287c95b8a2c4ff3114"
            ),
            "producer_start_commit": (
                "2c05988f4fe156c32e8193287c95b8a2c4ff3114"
            ),
            "minimum_protocol_ancestor": (
                "100bc2079cedc193af3524234ab833cc9f9f4669"
            ),
        },
        "immutable_input_manifest_sha256": (
            "b20db80d631d80e79ce9b2a7a01b742ac26194e3375f45fdcccb64c9e0d31555"
        ),
        "acceptance_contract_sha256": (
            "b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a"
        ),
        "digest_algorithm": "sha256",
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "total_bytes": sum(artifact["bytes"] for artifact in artifacts),
        "by_role": role_totals,
        "required_artifacts_ledger": [
            {
                "logical_name": "result/result.json",
                "hash_carrier": "this manifest",
            },
            {
                "logical_name": "result/tests.json",
                "hash_carrier": "this manifest",
            },
            {
                "logical_name": "result/limitations.json",
                "hash_carrier": "this manifest",
            },
            {
                "logical_name": "result/artifact-manifest.json",
                "content_uri": f"{OWNED_PREFIX}/result/artifact-manifest.json",
                "sha256": None,
                "bytes": None,
                "hash_carrier": "result/ready-to-commit.json",
            },
            {
                "logical_name": "result/ready-to-commit.json",
                "content_uri": f"{OWNED_PREFIX}/result/ready-to-commit.json",
                "sha256": None,
                "bytes": None,
                "hash_carrier": (
                    "immutable return commit and producer terminal report"
                ),
            },
        ],
        "hash_closure": {
            "excluded_self_referential": [
                f"{OWNED_PREFIX}/result/artifact-manifest.json",
                f"{OWNED_PREFIX}/result/ready-to-commit.json",
            ],
            "rule": (
                "The manifest hashes every non-self-referential file in the "
                "owned subtree. The ready envelope hashes the manifest. The "
                "terminal report hashes the ready envelope at the return commit."
            ),
        },
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    expected = _json_bytes(build())
    if args.write:
        MANIFEST.write_bytes(expected)
        print(
            f"MANIFEST: {build()['artifact_count']} artifacts, "
            f"{build()['total_bytes']} bytes, WRITTEN"
        )
        return 0
    try:
        observed = MANIFEST.read_bytes()
    except OSError as exc:
        print(f"MANIFEST: MISSING: {exc}")
        return 2
    if observed != expected:
        print("MANIFEST: STALE")
        return 1
    report = build()
    print(
        f"MANIFEST: {report['artifact_count']} artifacts, "
        f"{report['total_bytes']} bytes, CURRENT"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
