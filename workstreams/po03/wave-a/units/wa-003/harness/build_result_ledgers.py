#!/usr/bin/env python3
"""Emit the WA-003 source-claim ledger and artifact manifest with byte accounting.

Both ledgers are generated rather than transcribed so that every SHA-256 and byte
count in the result is computed from the delivered bytes.  The manifest cannot
contain its own hash, and ready-to-commit.json is written after it, so those two
are listed as deferred entries with an explicit hash carrier instead of being
silently omitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

MEDIA_TYPES = {
    ".json": "application/json",
    ".py": "text/x-python; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".candidate": "text/yaml; charset=utf-8",
    ".gitignore": "text/plain; charset=utf-8",
}

DEFERRED = ("artifact-manifest.json", "ready-to-commit.json")

# Sources this unit actually read, with the reason each one was admitted.
SOURCES_READ: tuple[tuple[str, str], ...] = (
    ("workstreams/po03/control/inputs/wave-a/wa-003.json", "immutable task input for this unit"),
    ("workstreams/po03/control/acceptance/wave-a-material-v1.json", "frozen acceptance contract"),
    ("workstreams/po03/COMMISSION.md", "commission revision v002 governing this unit"),
    ("workstreams/po03/control/wave-a-portfolio.json", "portfolio entry and dispatch order"),
    ("workstreams/po03/contracts/transactional-result.schema.json", "seeded result custody contract"),
    ("workstreams/po03/contracts/wave-compounding.schema.json", "seeded wave compounding contract"),
    ("workstreams/po03/tools/validate_contracts.py", "seeded validator and suite closure member"),
    ("workstreams/po03/tests/test_validate_contracts.py", "seeded suite under certification"),
    ("workstreams/po03/tools/prepare_wave_a.py", "generator that emitted the Wave A immutable inputs"),
    ("workstreams/po03/control/path-ownership.json", "declared ownership of this unit's subtree"),
    (".github/workflows/po03-contracts.yml", "existing CI control whose coverage this unit measures"),
    (".github/workflows/operator-taxonomy-currentness.yml", "other repository CI control, read for scope"),
    ("scripts/check_operator_taxonomy.py", "repository taxonomy gate run before commit"),
    ("operations/README.md", "repository-wide operator route resolved before work"),
    ("AGENTS.md", "repository-wide operator instructions"),
    (
        "workstreams/po03/runs/bc-b1956656-b897-4889-aeab-82c4556c1a9f/units/"
        "wa-isolation-canary-001/result/ready-to-commit.json",
        "prior producer return, read for the established return shape",
    ),
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_show(repo: Path, commit: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"],
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def media_type(path: Path) -> str:
    if path.name == ".gitignore":
        return MEDIA_TYPES[".gitignore"]
    return MEDIA_TYPES.get(path.suffix, "application/octet-stream")


def build_source_claims(repo: Path, commit: str) -> dict[str, Any]:
    claims: list[dict[str, Any]] = []
    for path, reason in SOURCES_READ:
        payload = git_show(repo, commit, path)
        claims.append(
            {
                "claim_type": "repository_source_read",
                "path": path,
                "read_at_commit": commit,
                "sha256": sha256_bytes(payload) if payload is not None else None,
                "bytes": len(payload) if payload is not None else None,
                "resolved": payload is not None,
                "reason_admitted": reason,
            }
        )
    return {
        "schema_version": "OBZIO-PO03-WA003-SOURCE-CLAIMS-v1",
        "task_id": "PO03-WA-003",
        "repository": "github.com/asibrahim336-hash/obzio-ai-coordination-temp",
        "read_at_commit": commit,
        "source_claim_count": len(claims),
        "unresolved_count": len([claim for claim in claims if not claim["resolved"]]),
        "external_source_claims": [],
        "external_source_claim_status": "NOT_SUPPORTED",
        "external_source_claim_boundary": (
            "This runner read no external URL. No web fetch, search or documentation "
            "retrieval was performed, so no external source claim is recorded and none is "
            "invented. Every claim below is an immutable repository read."
        ),
        "source_claims": claims,
    }


def build_manifest(repo: Path, unit_root: str, commit: str | None) -> dict[str, Any]:
    base = repo / unit_root
    artifacts: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(repo).as_posix()
        payload = path.read_bytes()
        entry = {
            "artifact_id": "art-po03-wa-003-"
            + path.relative_to(base).as_posix().replace("/", "-").replace(".", "-"),
            "logical_name": path.relative_to(base).as_posix(),
            "content_uri": relative,
            "sha256": sha256_bytes(payload),
            "bytes": len(payload),
            "media_type": media_type(path),
        }
        if path.name in DEFERRED:
            deferred.append(entry)
        else:
            artifacts.append(entry)
    for name in DEFERRED:
        if not any(item["logical_name"].endswith(name) for item in deferred):
            deferred.append(
                {
                    "artifact_id": f"art-po03-wa-003-deferred-{name.replace('.', '-')}",
                    "logical_name": f"result/{name}",
                    "content_uri": f"{unit_root}result/{name}",
                    "sha256": None,
                    "bytes": None,
                    "media_type": "application/json",
                }
            )
    return {
        "schema_version": "OBZIO-PO03-WA003-ARTIFACT-MANIFEST-v1",
        "task_id": "PO03-WA-003",
        "attempt_id": "PO03-WA-003-A01",
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "owned_subtree": unit_root,
        "result_slot": f"{unit_root}result/",
        "staged_at_commit": commit,
        "hash_algorithm": "sha256",
        "artifact_count": len(artifacts),
        "total_bytes": sum(item["bytes"] for item in artifacts),
        "artifacts": artifacts,
        "deferred_artifacts": deferred,
        "deferred_reason": (
            "artifact-manifest.json cannot contain its own SHA-256, and ready-to-commit.json is "
            "written after it. The manifest hash is carried by ready-to-commit.json, and the "
            "ready-to-commit hash is carried by the producer terminal response. Both are "
            "recomputable from the immutable return commit."
        ),
        "hash_chain": [
            "artifact-manifest.json covers every delivered artifact byte-for-byte",
            "ready-to-commit.json carries manifest_sha256",
            "the producer terminal response carries the ready-to-commit.json SHA-256 and byte count",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_result_ledgers")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--commit", required=True, help="commit the sources were read at")
    parser.add_argument("--unit-root", default="workstreams/po03/wave-a/units/wa-003/")
    parser.add_argument("--staged-at-commit", default=None)
    parser.add_argument("--emit", choices=("source-claims", "manifest", "both"), default="both")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    result_dir = repo / args.unit_root / "result"
    result_dir.mkdir(parents=True, exist_ok=True)

    if args.emit in ("source-claims", "both"):
        claims = build_source_claims(repo, args.commit)
        target = result_dir / "source-claims.json"
        target.write_text(json.dumps(claims, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(
            f"source-claims: {claims['source_claim_count']} claims, "
            f"{claims['unresolved_count']} unresolved -> {target}"
        )

    if args.emit in ("manifest", "both"):
        manifest = build_manifest(repo, args.unit_root, args.staged_at_commit)
        target = result_dir / "artifact-manifest.json"
        target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(
            f"manifest: {manifest['artifact_count']} artifacts, "
            f"{manifest['total_bytes']} bytes -> {target}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
