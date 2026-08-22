#!/usr/bin/env python3
"""Build or verify the PO03-WA-024 artifact manifest.

The manifest accounts for every file this unit wrote, with a SHA-256 and a byte
count for each.  It is generated rather than hand-written so that a reader can
re-derive it and get the same bytes, and so that a drifting entry is a test
failure rather than a discrepancy nobody notices.

Two files are deliberately excluded, because neither can contain its own digest:
``artifact-manifest.json`` and ``ready-to-commit.json``.  Their digests are
reported in the producer terminal report and are recomputable from the immutable
commit tree.

    python3 -B build_manifest.py --write      # regenerate the manifest
    python3 -B build_manifest.py --verify     # exit 1 if it is stale
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[6]
UNIT_REL = "workstreams/po03/wave-a/units/wa-024"

MANIFEST_PATH = UNIT_ROOT / "result" / "artifact-manifest.json"

SELF_REFERENTIAL = {
    f"{UNIT_REL}/result/artifact-manifest.json",
    f"{UNIT_REL}/result/ready-to-commit.json",
}

MEDIA_TYPES = {
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".py": "text/x-python; charset=utf-8",
    ".sh": "text/x-shellscript; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".diff": "text/x-diff; charset=utf-8",
}

# The role each directory plays, so the manifest carries meaning and not only
# digests.  These are the states the acceptance contract requires to stay apart.
ROLES = (
    (f"{UNIT_REL}/sources/", "source_claim"),
    (f"{UNIT_REL}/hypotheses/", "frozen_hypothesis"),
    (f"{UNIT_REL}/harness/", "executable_mechanism"),
    (f"{UNIT_REL}/tests/", "test"),
    (f"{UNIT_REL}/proposals/patches/", "mechanism_change"),
    (f"{UNIT_REL}/proposals/", "proposal"),
    (f"{UNIT_REL}/result/", "result"),
    (f"{UNIT_REL}/README.md", "documentation"),
)


def role_of(relative: str) -> str:
    for prefix, role in ROLES:
        if relative.startswith(prefix):
            return role
    return "other"


def artifact_id(relative: str) -> str:
    stem = relative[len(UNIT_REL) + 1 :]
    slug = stem.replace("/", "-").replace(".", "-").replace("_", "-").lower()
    return f"art-po03-wa-024-{slug}"


def collect() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(UNIT_ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(REPO_ROOT).as_posix()
        if "__pycache__" in relative or relative in SELF_REFERENTIAL:
            continue
        payload = path.read_bytes()
        rows.append(
            {
                "artifact_id": artifact_id(relative),
                "logical_name": relative[len(UNIT_REL) + 1 :],
                "content_uri": relative,
                "role": role_of(relative),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "media_type": MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
            }
        )
    return rows


def build(result_commit_id: str | None, remote_branch: str | None) -> dict[str, object]:
    rows = collect()
    by_role: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_role.setdefault(str(row["role"]), {"count": 0, "bytes": 0})
        bucket["count"] += 1
        bucket["bytes"] += int(row["bytes"])
    return {
        "protocol_version": "PO03-WAVE-A-MATERIAL-MANIFEST-v1",
        "task_id": "PO03-WA-024",
        "attempt_id": "PO03-WA-024-A01",
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "state": "ARTIFACT_MANIFEST",
        "owned_subtree": f"{UNIT_REL}/",
        "generated_by": f"{UNIT_REL}/result/build_manifest.py",
        "regenerate": f"python3 -B {UNIT_REL}/result/build_manifest.py --write",
        "verify": f"python3 -B {UNIT_REL}/result/build_manifest.py --verify",
        "digest_algorithm": "sha256",
        "remote_branch": remote_branch,
        "result_commit_id": result_commit_id,
        "excluded_self_referential": sorted(SELF_REFERENTIAL),
        "excluded_self_referential_note": (
            "A file cannot contain its own digest. These two are accounted for in the producer "
            "terminal report instead, and both are recomputable from the immutable commit tree."
        ),
        "artifact_count": len(rows),
        "total_bytes": sum(int(row["bytes"]) for row in rows),
        "by_role": dict(sorted(by_role.items())),
        "artifacts": rows,
        "decision_changed": [],
    }


def render(document: dict[str, object]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate the manifest")
    mode.add_argument("--verify", action="store_true", help="exit 1 if the manifest is stale")
    parser.add_argument("--result-commit-id", default=None)
    parser.add_argument("--remote-branch", default=None)
    args = parser.parse_args(argv)

    if args.write:
        document = build(args.result_commit_id, args.remote_branch)
        MANIFEST_PATH.write_text(render(document), encoding="utf-8")
        print(
            f"wrote {MANIFEST_PATH.relative_to(REPO_ROOT)}: "
            f"{document['artifact_count']} artifacts, {document['total_bytes']} bytes"
        )
        return 0

    if not MANIFEST_PATH.is_file():
        print("artifact-manifest.json is missing", file=sys.stderr)
        return 1
    recorded = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    expected = {row["content_uri"]: row for row in collect()}
    actual = {row["content_uri"]: row for row in recorded["artifacts"]}

    problems: list[str] = []
    for uri in sorted(set(expected) - set(actual)):
        problems.append(f"missing from the manifest: {uri}")
    for uri in sorted(set(actual) - set(expected)):
        problems.append(f"recorded but no longer present: {uri}")
    for uri in sorted(set(expected) & set(actual)):
        for field in ("sha256", "bytes"):
            if expected[uri][field] != actual[uri][field]:
                problems.append(
                    f"{uri}: recorded {field} {actual[uri][field]} but measured {expected[uri][field]}"
                )
    if recorded["artifact_count"] != len(actual):
        problems.append(f"artifact_count {recorded['artifact_count']} does not match {len(actual)} entries")
    byte_sum = sum(int(row["bytes"]) for row in recorded["artifacts"])
    if recorded["total_bytes"] != byte_sum:
        problems.append(f"total_bytes {recorded['total_bytes']} does not match the sum {byte_sum}")

    for problem in problems:
        print(problem, file=sys.stderr)
    print(
        f"MANIFEST: {len(actual)} artifacts, {byte_sum} bytes, "
        f"{'STALE' if problems else 'CURRENT'}",
        file=sys.stderr,
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
