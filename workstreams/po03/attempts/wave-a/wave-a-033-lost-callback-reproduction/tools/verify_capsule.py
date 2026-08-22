#!/usr/bin/env python3
"""Verify this attempt's frozen task capsule against immutable Git bytes.

Every declared source hash is recomputed from Git object bytes rather than from
the working tree, at both the capsule's historical controller head and the
immutable dispatch base. Divergence is reported, not smoothed over.

Usage:
    python3 tools/verify_capsule.py --out capsule-verification.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ATTEMPT_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = ATTEMPT_ROOT.parents[4]

TASK_ID = "wave-a-033-lost-callback-reproduction"
CAPSULE_HEAD = "1bb843b2a81fd8d73617caf2f1db81909266bb6e"
DISPATCH_BASE = "e63fbae079774b151fd24a4132e4a5e571f75298"
CONTROLLER_BRANCH = "po03/repository-engineering-portable-runtime-20260822-v001"

TASK_DIRECTORY = f"workstreams/po03/control/tasks/{TASK_ID}"

# Declared hash -> the path the capsule names, as written in input.json.
DECLARED = (
    (
        "immutable_input_manifest_sha256",
        f"{TASK_DIRECTORY}/input.json",
        "4e8bfb1bf06815bbd687d8955b751520d8110c3e8fbdd12a36fde844d722bfed",
    ),
    (
        "acceptance_contract_sha256",
        f"{TASK_DIRECTORY}/acceptance.json",
        "40738956bf0feb02e711455c08fedf32e4757530606c626d414ad512218ebe65",
    ),
    (
        "commission_sha256",
        "workstreams/po03/COMMISSION.md",
        "b6dff810facb443c7f081b98a3b578f6ad8521a1e79f13c3b862f527504b968d",
    ),
    (
        "transaction_schema_sha256",
        "workstreams/po03/contracts/transactional-result.schema.json",
        "bca86858131cf1644f88fcbe615f4ca7a4ef44b7464eebc086c84e39b77301f1",
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git(*arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments), cwd=REPOSITORY, check=True, capture_output=True, text=True
    ).stdout.strip()


def blob_at(commit: str, path: str) -> tuple[bytes, str] | None:
    """Return committed bytes and blob SHA, or None when the path is absent."""
    probe = subprocess.run(
        ("git", "rev-parse", "--verify", f"{commit}:{path}"),
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        return None
    payload = subprocess.run(
        ("git", "cat-file", "blob", f"{commit}:{path}"),
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
    ).stdout
    return payload, probe.stdout.strip()


def schema_lineage() -> list[dict[str, object]]:
    """Every committed revision of the transactional schema, oldest last."""
    path = "workstreams/po03/contracts/transactional-result.schema.json"
    commits = git("log", "--format=%H", DISPATCH_BASE, "--", path).splitlines()
    lineage = []
    for commit in commits:
        found = blob_at(commit, path)
        if found is None:
            continue
        payload, blob_sha = found
        lineage.append(
            {
                "commit": commit,
                "subject": git("log", "-1", "--format=%s", commit),
                "blob_sha": blob_sha,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return lineage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ATTEMPT_ROOT / "capsule-verification.json"))
    arguments = parser.parse_args()

    checks = []
    for field, path, declared in DECLARED:
        entry: dict[str, object] = {
            "declared_field": field,
            "declared_sha256": declared,
            "capsule_named_path": path,
            "revisions": {},
        }
        for label, commit in (("capsule_head", CAPSULE_HEAD), ("dispatch_base", DISPATCH_BASE)):
            found = blob_at(commit, path)
            if found is None:
                entry["revisions"][label] = {"commit": commit, "present": False}
                continue
            payload, blob_sha = found
            digest = hashlib.sha256(payload).hexdigest()
            entry["revisions"][label] = {
                "commit": commit,
                "present": True,
                "blob_sha": blob_sha,
                "bytes": len(payload),
                "sha256": digest,
                "matches_declared": digest == declared,
            }
        base = entry["revisions"]["dispatch_base"]
        entry["verdict"] = (
            "MATCH_AT_DISPATCH_BASE"
            if base.get("matches_declared")
            else "MISMATCH_AT_DISPATCH_BASE"
        )
        checks.append(entry)

    lineage = schema_lineage()
    declared_schema = "bca86858131cf1644f88fcbe615f4ca7a4ef44b7464eebc086c84e39b77301f1"
    declared_revision = next(
        (item for item in lineage if item["sha256"] == declared_schema), None
    )

    document = {
        "verification_version": "PO03-WAVE-A-033-CAPSULE-VERIFICATION-v1",
        "task_id": TASK_ID,
        "recorded_at": utc_now(),
        "decision_changed": [],
        "identifiers": {
            "capsule_declared_controller_head_sha": CAPSULE_HEAD,
            "immutable_dispatch_base_sha": DISPATCH_BASE,
            "controller_branch": CONTROLLER_BRANCH,
            "capsule_head_is_ancestor_of_dispatch_base": subprocess.run(
                (
                    "git",
                    "merge-base",
                    "--is-ancestor",
                    CAPSULE_HEAD,
                    DISPATCH_BASE,
                ),
                cwd=REPOSITORY,
                capture_output=True,
            ).returncode
            == 0,
            "commits_between_capsule_head_and_dispatch_base": int(
                git("rev-list", "--count", f"{CAPSULE_HEAD}..{DISPATCH_BASE}")
            ),
        },
        "checks": checks,
        "additive_hardening_disclosure": {
            "statement": (
                "The capsule declares controller head "
                f"{CAPSULE_HEAD}, but this attempt was dispatched from {DISPATCH_BASE}, "
                "which carries additive controller hardening committed after the capsule's "
                "historical head. The current controller branch tip has advanced further "
                "still. No capsule byte was rewritten; the hardening is additive."
            ),
            "capsule_files_absent_at_capsule_head": [
                check["capsule_named_path"]
                for check in checks
                if not check["revisions"]["capsule_head"].get("present")
            ],
            "schema_lineage_oldest_last": list(reversed(lineage)),
            "declared_schema_revision": declared_revision,
            # ``lineage`` is newest-first, so revisions committed after the
            # declared one are exactly those preceding it in the list.
            "declared_schema_superseded_times": (
                lineage.index(declared_revision) if declared_revision is not None else None
            ),
            "dispatch_base_schema_sha256": lineage[0]["sha256"] if lineage else None,
        },
    }

    destination = Path(arguments.out)
    destination.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {destination} ({destination.stat().st_size} bytes)")
    for check in checks:
        print(f"  {check['declared_field']}: {check['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
