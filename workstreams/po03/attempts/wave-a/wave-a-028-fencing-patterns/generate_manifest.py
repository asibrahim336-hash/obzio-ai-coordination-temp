#!/usr/bin/env python3
"""Generate the complete attempt manifest, excluding the manifest itself."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from pathlib import Path


UNIT_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = UNIT_ROOT / "manifest.json"


def git_blob_sha(payload: bytes) -> str:
    framed = f"blob {len(payload)}\0".encode("ascii") + payload
    return hashlib.sha1(framed).hexdigest()


def artifact_record(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return {
        "bytes": len(payload),
        "git_blob_sha": git_blob_sha(payload),
        "media_type": media_type,
        "path": path.relative_to(UNIT_ROOT).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def main() -> int:
    custody = json.loads((UNIT_ROOT / "evidence" / "custody.json").read_text())
    limitations = json.loads((UNIT_ROOT / "limitations.json").read_text())
    paths = sorted(
        (
            path
            for path in UNIT_ROOT.rglob("*")
            if path.is_file()
            and path != MANIFEST_PATH
            and "__pycache__" not in path.parts
        ),
        key=lambda path: path.relative_to(UNIT_ROOT).as_posix(),
    )
    records = [artifact_record(path) for path in paths]
    manifest = {
        "artifact_count": len(records),
        "artifacts": records,
        "base_and_heads": custody["base_and_heads"],
        "branch": "po03/wave-a-028-fencing-patterns",
        "capsule_verification": custody["capsule_verification"],
        "commands": custody["commands"],
        "commission_id": (
            "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
        ),
        "decision_changed": [],
        "event_chain": custody["event_chain"],
        "limitations": limitations["limitations"],
        "manifest_version": "PO03-ATTEMPT-MANIFEST-v1",
        "repository": "github.com/asibrahim336-hash/obzio-ai-coordination-temp",
        "runtime": custody["runtime"],
        "self_excluded": {
            "path": "manifest.json",
            "reason": "A file cannot contain its own final digest without a circular definition."
        },
        "task_id": "wave-a-028-fencing-patterns",
        "topology": custody["topology"],
        "total_artifact_bytes_excluding_manifest": sum(
            int(record["bytes"]) for record in records
        ),
        "unit_root": (
            "workstreams/po03/attempts/wave-a/"
            "wave-a-028-fencing-patterns"
        ),
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
