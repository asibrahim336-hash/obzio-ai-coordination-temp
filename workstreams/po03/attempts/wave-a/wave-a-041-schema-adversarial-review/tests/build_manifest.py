#!/usr/bin/env python3
"""Build `manifest.json` covering every artifact this unit owns.

The manifest excludes itself, because a digest cannot cover the file that
carries it.  Read-back is verified separately against the pushed commit and the
remote ref by `readback.py`, which recomputes these digests from git objects
rather than from the working tree.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ATTEMPT_ROOT = HERE.parent
MANIFEST = ATTEMPT_ROOT / "manifest.json"
REPO_RELATIVE_ROOT = "workstreams/po03/attempts/wave-a/wave-a-041-schema-adversarial-review"

EXCLUDED_NAMES = {"manifest.json"}
EXCLUDED_DIRS = {"__pycache__"}


def iter_artifacts():
    for path in sorted(ATTEMPT_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if path.name in EXCLUDED_NAMES:
            continue
        if EXCLUDED_DIRS & set(path.relative_to(ATTEMPT_ROOT).parts):
            continue
        if path.suffix == ".pyc":
            continue
        yield path


def main() -> int:
    artifacts = []
    total = 0
    for path in iter_artifacts():
        data = path.read_bytes()
        total += len(data)
        artifacts.append(
            {
                "logical_name": path.relative_to(ATTEMPT_ROOT).as_posix(),
                "repository_path": f"{REPO_RELATIVE_ROOT}/{path.relative_to(ATTEMPT_ROOT).as_posix()}",
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        )

    document = {
        "manifest_version": "PO03-WAVE-A-041-MANIFEST-v1",
        "task_id": "wave-a-041-schema-adversarial-review",
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "result_slot": REPO_RELATIVE_ROOT,
        "result_branch": "po03/wave-a-041-schema-adversarial-review",
        "base_commit": "f5b758f373e8d0cb14660c167f4b0b3673251862",
        "algorithm": "sha256",
        "self_exclusion": "manifest.json is excluded because it cannot contain its own digest. Its digest is reported in the return and verified by read-back from the commit.",
        "artifact_count": len(artifacts),
        "total_bytes": total,
        "artifacts": artifacts,
        "reviewed_sources": [
            {
                "repository_path": "workstreams/po03/control/tasks/wave-a-041-schema-adversarial-review/input.json",
                "sha256": "a7e38fbecb72bcbdf463739179ac6eda5f6bde3b33a1bf5cb7db3b1d6397e1b3",
                "bytes": 1831,
                "disposition": "READ_ONLY_UNMODIFIED",
            },
            {
                "repository_path": "workstreams/po03/control/tasks/wave-a-041-schema-adversarial-review/acceptance.json",
                "sha256": "94068ea1a40afc15be626ec89a06906c463d7af687f02da1c28c8cd00b383f15",
                "bytes": 628,
                "disposition": "READ_ONLY_UNMODIFIED",
            },
            {
                "repository_path": "workstreams/po03/control/tasks/wave-a-041-schema-adversarial-review/transaction-created.json",
                "sha256": "f673959bad0e409fd8fa987c7cb27486161377d1fa56537a4cbb75b3b9b51507",
                "bytes": 1233,
                "disposition": "READ_ONLY_UNMODIFIED",
            },
            {
                "repository_path": "workstreams/po03/contracts/transactional-result.schema.json",
                "sha256": "bca86858131cf1644f88fcbe615f4ca7a4ef44b7464eebc086c84e39b77301f1",
                "bytes": 4618,
                "disposition": "READ_ONLY_UNMODIFIED",
            },
            {
                "repository_path": "workstreams/po03/tools/validate_contracts.py",
                "sha256": "3c2ebd7f06b0230c35355ae0b569283e8dbf90ed87127dedddb7d389b1c62bc7",
                "bytes": 12390,
                "disposition": "READ_ONLY_UNMODIFIED",
            },
            {
                "repository_path": "workstreams/po03/COMMISSION.md",
                "sha256": "b6dff810facb443c7f081b98a3b578f6ad8521a1e79f13c3b862f527504b968d",
                "bytes": 16030,
                "disposition": "READ_ONLY_UNMODIFIED",
            },
        ],
        "decision_changed": [],
    }
    MANIFEST.write_text(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"manifest: {len(artifacts)} artifacts, {total} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
