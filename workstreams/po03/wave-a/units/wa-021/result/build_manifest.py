#!/usr/bin/env python3
"""Build or verify the deterministic WA-021 artifact manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[6]
UNIT_PREFIX = "workstreams/po03/wave-a/units/wa-021"
UNIT_ROOT = REPO_ROOT / UNIT_PREFIX
MANIFEST = UNIT_ROOT / "result" / "artifact-manifest.json"
EXCLUDED = {
    f"{UNIT_PREFIX}/result/artifact-manifest.json",
    f"{UNIT_PREFIX}/result/ready-to-commit.json",
}


def role_for(relative: str) -> str:
    if relative == "README.md":
        return "documentation"
    if relative.startswith("scanner/"):
        return "scoring_fixture" if relative.endswith(".json") else "executable_scanner"
    if relative.startswith("tests/"):
        return "test"
    if relative.startswith("sources/"):
        return "source_claim"
    if relative.startswith("hypotheses/"):
        return "frozen_hypothesis"
    if relative.startswith("reproductions/"):
        return "reproduction"
    if relative == "proposals/mechanism-changes.json":
        return "mechanism_change_proposal"
    if relative == "proposals/strategy-proposals.json":
        return "strategy_proposal"
    return "result"


def media_type(path: Path) -> str:
    if path.suffix == ".json":
        return "application/json"
    if path.suffix == ".py":
        return "text/x-python; charset=utf-8"
    guessed, _ = mimetypes.guess_type(path.name)
    return f"{guessed}; charset=utf-8" if guessed and guessed.startswith("text/") else (
        guessed or "application/octet-stream"
    )


def artifact_id(relative: str) -> str:
    normalized = "".join(character if character.isalnum() else "-" for character in relative)
    return f"art-po03-wa-021-{normalized.strip('-').lower()}"


def build() -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    for path in sorted(UNIT_ROOT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        content_uri = path.relative_to(REPO_ROOT).as_posix()
        if content_uri in EXCLUDED:
            continue
        data = path.read_bytes()
        relative = path.relative_to(UNIT_ROOT).as_posix()
        artifacts.append(
            {
                "artifact_id": artifact_id(relative),
                "logical_name": relative,
                "content_uri": content_uri,
                "role": role_for(relative),
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "media_type": media_type(path),
            }
        )
    by_role: dict[str, dict[str, int]] = {}
    for artifact in artifacts:
        totals = by_role.setdefault(artifact["role"], {"count": 0, "bytes": 0})
        totals["count"] += 1
        totals["bytes"] += artifact["bytes"]
    return {
        "protocol_version": "PO03-WAVE-A-MATERIAL-MANIFEST-v1",
        "task_id": "PO03-WA-021",
        "attempt_id": "PO03-WA-021-A02",
        "state": "ARTIFACT_MANIFEST",
        "source_base": "22af3833bd25e2fa1b4e91111c045907e9534119",
        "owned_subtree": f"{UNIT_PREFIX}/",
        "digest_algorithm": "sha256",
        "generated_by": f"{UNIT_PREFIX}/result/build_manifest.py",
        "regenerate": (
            f"python3 -B {UNIT_PREFIX}/result/build_manifest.py --write"
        ),
        "verify": f"python3 -B {UNIT_PREFIX}/result/build_manifest.py --verify",
        "result_commit_id": None,
        "result_commit_id_note": (
            "The immutable result commit is reported by ready-to-commit.json, which is "
            "added in a distinct return commit. Embedding the containing commit here "
            "would be self-referential."
        ),
        "excluded_self_referential": sorted(EXCLUDED),
        "artifact_count": len(artifacts),
        "total_bytes": sum(item["bytes"] for item in artifacts),
        "by_role": dict(sorted(by_role.items())),
        "artifacts": artifacts,
        "decision_changed": [],
    }


def encoded(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    expected = encoded(build())
    if args.write:
        MANIFEST.write_bytes(expected)
        document = json.loads(expected)
        print(
            f"MANIFEST: {document['artifact_count']} artifacts, "
            f"{document['total_bytes']} bytes, WRITTEN"
        )
        return 0
    actual = MANIFEST.read_bytes()
    if actual != expected:
        print("MANIFEST: STALE")
        return 1
    document = json.loads(actual)
    print(
        f"MANIFEST: {document['artifact_count']} artifacts, "
        f"{document['total_bytes']} bytes, CURRENT"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
