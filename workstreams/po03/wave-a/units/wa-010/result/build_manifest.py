#!/usr/bin/env python3
"""Build the WA-010 artifact manifest with complete SHA-256 and byte accounting.

Every committed file in the owned subtree is hashed except the manifest itself and
``ready-to-commit.json``.  Excluding those two is what keeps the accounting
non-circular: the manifest cannot contain its own digest, and the producer return
is written afterwards so it can carry the manifest's digest.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

RESULT_DIR = Path(__file__).resolve().parent
UNIT_DIR = RESULT_DIR.parent
REPO_ROOT = UNIT_DIR.parents[4]
UNIT_PREFIX = "workstreams/po03/wave-a/units/wa-010"

SELF_EXCLUDED = ("result/artifact-manifest.json", "result/ready-to-commit.json")

MEDIA_TYPES = {
    ".json": "application/json",
    ".py": "text/x-python; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}

ARTIFACT_ID_PREFIX = "art-po03-wa-010"


def tracked_unit_files() -> list[str]:
    """List the unit's files from git rather than the filesystem.

    Reading the index means an untracked scratch file cannot silently enter the
    manifest, and a file the manifest claims is always a file the commit carries.
    """
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", UNIT_PREFIX],
        check=True,
        capture_output=True,
    )
    entries = [
        item.decode("utf-8")
        for item in completed.stdout.split(b"\x00")
        if item and not item.endswith(b".pyc")
    ]
    return sorted(entries)


def artifact_id(relative: str) -> str:
    stem = relative.rsplit("/", 1)[-1]
    for suffix in (".json", ".py", ".txt", ".md"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    slug = stem.replace("_", "-").replace(".", "-").lower()
    group = relative.split("/")[0] if "/" in relative else "root"
    return f"{ARTIFACT_ID_PREFIX}-{group}-{slug}"


def build() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    total = 0
    seen_ids: set[str] = set()
    for path in tracked_unit_files():
        relative = path[len(UNIT_PREFIX) + 1 :]
        if relative in SELF_EXCLUDED:
            continue
        data = (REPO_ROOT / path).read_bytes()
        suffix = "." + relative.rsplit(".", 1)[-1] if "." in relative else ""
        identifier = artifact_id(relative)
        if identifier in seen_ids:
            raise SystemExit(f"duplicate artifact id {identifier} for {relative}")
        seen_ids.add(identifier)
        entries.append(
            {
                "artifact_id": identifier,
                "logical_name": relative,
                "content_uri": path,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "media_type": MEDIA_TYPES.get(suffix, "application/octet-stream"),
            }
        )
        total += len(data)

    required = (
        "result/result.json",
        "result/tests.json",
        "result/limitations.json",
    )
    present = {entry["logical_name"] for entry in entries}
    missing = [name for name in required if name not in present]
    if missing:
        raise SystemExit(f"manifest is missing required artifacts: {missing}")

    return {
        "protocol_version": "OBZIO-ARTIFACT-MANIFEST-v1",
        "task_id": "PO03-WA-010",
        "attempt_id": "PO03-WA-010-A02",
        "hypothesis_id": "H-PO03-WA-010",
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "owned_subtree": f"{UNIT_PREFIX}/**",
        "result_slot": f"{UNIT_PREFIX}/result/",
        "hash_algorithm": "sha256",
        "source_of_truth": "git ls-files over the owned subtree, so the manifest cannot list an untracked file",
        "self_excluded": [f"{UNIT_PREFIX}/{name}" for name in SELF_EXCLUDED],
        "self_excluded_reason": (
            "The manifest cannot carry its own digest. ready-to-commit.json is written after the "
            "manifest so that it can carry the manifest digest and the immutable read-back."
        ),
        "artifact_count": len(entries),
        "total_bytes": total,
        "artifacts": entries,
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    payload = build()
    out = RESULT_DIR / "artifact-manifest.json"
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    out.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    print(
        json.dumps(
            {
                "manifest_path": f"{UNIT_PREFIX}/result/artifact-manifest.json",
                "manifest_sha256": digest,
                "manifest_bytes": len(text.encode("utf-8")),
                "artifact_count": payload["artifact_count"],
                "total_bytes": payload["total_bytes"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
