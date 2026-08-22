#!/usr/bin/env python3
"""Result custody for PO03-WA-008: manifest generation and immutable readback.

Two subcommands, standard library only:

``manifest``
    Hash every artifact in the result slot and write artifact-manifest.json with
    per-artifact SHA-256 and byte counts plus reconciled totals.

``readback``
    Fetch one commit from a remote into a throwaway repository and compare every
    manifested artifact byte-for-byte against that immutable commit, so the
    verification is performed by a different process reading a different object
    store than the one that produced the files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_PROTOCOL_VERSION = "OBZIO-ARTIFACT-MANIFEST-v1"
MANIFEST_NAME = "artifact-manifest.json"
RETURN_NAME = "ready-to-commit.json"
RESULT_SLOT = "workstreams/po03/wave-a/units/wa-008/result"

MEDIA_TYPES = {
    ".json": "application/json",
    ".py": "text/x-python; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git(args, cwd=None, check=True):
    completed = subprocess.run(
        ["git", *args], cwd=str(cwd) if cwd else None, capture_output=True, text=True
    )
    if check and completed.returncode != 0:
        raise RuntimeError("git {} failed: {}".format(" ".join(args), completed.stderr.strip()))
    return completed


def artifact_records(slot: Path, exclude):
    records = []
    for path in sorted(slot.iterdir()):
        if not path.is_file() or path.name in exclude:
            continue
        payload = path.read_bytes()
        records.append(
            {
                "logical_name": path.name,
                "content_uri": "{}/{}".format(RESULT_SLOT, path.name),
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
                "media_type": MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
            }
        )
    return records


def build_manifest(slot: Path, base_commit: str, produced_commit: str) -> dict:
    records = artifact_records(slot, exclude={MANIFEST_NAME, RETURN_NAME})
    return {
        "protocol_version": MANIFEST_PROTOCOL_VERSION,
        "task_id": "PO03-WA-008",
        "attempt_id": "PO03-WA-008-A02",
        "hypothesis_id": "H-PO03-WA-008",
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "result_slot": RESULT_SLOT + "/",
        "immutable_base_commit": base_commit,
        "generated_at": now(),
        "manifest_scope": (
            "Every file in the result slot except this manifest and ready-to-commit.json, which "
            "carries this manifest's own digest and is written in the return commit."
        ),
        "artifact_count": len(records),
        "total_bytes": sum(record["bytes"] for record in records),
        "artifacts": records,
        "produced_at_local_commit": produced_commit,
        "decision_changed": [],
    }


def cmd_manifest(args) -> int:
    slot = Path(args.slot).resolve()
    repo = git(["rev-parse", "--show-toplevel"], cwd=slot).stdout.strip()
    produced_commit = git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()
    manifest = build_manifest(slot, args.base_commit, produced_commit)
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (slot / MANIFEST_NAME).write_text(payload, encoding="utf-8")
    print(
        "manifest artifacts={} total_bytes={} sha256={}".format(
            manifest["artifact_count"],
            manifest["total_bytes"],
            sha256_bytes(payload.encode("utf-8")),
        )
    )
    return 0


def cmd_readback(args) -> int:
    """Verify every manifested artifact against an immutable remote commit."""
    scratch = Path(tempfile.mkdtemp(prefix="po03-wa-008-readback-")).resolve()
    try:
        git(["init", "--quiet", str(scratch)])
        git(
            [
                "fetch",
                "--quiet",
                "--no-tags",
                args.remote,
                "+{}:refs/readback/target".format(args.ref),
            ],
            cwd=scratch,
        )
        remote_tip = git(["rev-parse", "refs/readback/target"], cwd=scratch).stdout.strip()
        if git(["cat-file", "-e", args.commit + "^{commit}"], cwd=scratch, check=False).returncode:
            raise RuntimeError("commit {} not present in the fetched ref".format(args.commit))

        manifest_uri = "{}/{}".format(RESULT_SLOT, MANIFEST_NAME)
        manifest_blob = subprocess.run(
            ["git", "show", "--no-textconv", "{}:{}".format(args.commit, manifest_uri)],
            cwd=str(scratch),
            capture_output=True,
        )
        if manifest_blob.returncode != 0:
            raise RuntimeError("manifest not present at {}".format(args.commit))
        manifest = json.loads(manifest_blob.stdout.decode("utf-8"))

        checks = []
        for record in manifest["artifacts"]:
            blob = subprocess.run(
                ["git", "show", "--no-textconv", "{}:{}".format(args.commit, record["content_uri"])],
                cwd=str(scratch),
                capture_output=True,
            )
            observed_sha = sha256_bytes(blob.stdout) if blob.returncode == 0 else None
            checks.append(
                {
                    "path": record["content_uri"],
                    "sha256": record["sha256"],
                    "bytes": record["bytes"],
                    "observed_sha256": observed_sha,
                    "observed_bytes": len(blob.stdout) if blob.returncode == 0 else None,
                    "matches": blob.returncode == 0
                    and observed_sha == record["sha256"]
                    and len(blob.stdout) == record["bytes"],
                }
            )
        checks.append(
            {
                "path": manifest_uri,
                "sha256": sha256_bytes(manifest_blob.stdout),
                "bytes": len(manifest_blob.stdout),
                "observed_sha256": sha256_bytes(manifest_blob.stdout),
                "observed_bytes": len(manifest_blob.stdout),
                "matches": True,
                "note": "manifest verified as present and hashed at the immutable commit",
            }
        )
        changed = git(
            ["diff", "--name-only", args.base_commit, args.commit], cwd=scratch, check=False
        )
        changed_paths = sorted(line for line in changed.stdout.splitlines() if line)
        out_of_scope = [path for path in changed_paths if not path.startswith(RESULT_SLOT + "/")]
        report = {
            "protocol_version": "OBZIO-WA-008-READBACK-v1",
            "method": (
                "Fresh temporary Git repository, forced ref fetch from the remote, then "
                "git show --no-textconv <immutable-commit>:<path> with SHA-256 and byte comparison."
            ),
            "remote_ref": args.ref,
            "remote_tip_at_readback": remote_tip,
            "commit": args.commit,
            "base_commit": args.base_commit,
            "verified_at": now(),
            "artifact_count": len(checks),
            "all_match": all(check["matches"] for check in checks),
            "changed_path_count": len(changed_paths),
            "out_of_scope_changed_path_count": len(out_of_scope),
            "out_of_scope_changed_paths": out_of_scope,
            "checks": checks,
        }
        payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.json_path:
            Path(args.json_path).write_text(payload, encoding="utf-8")
        else:
            sys.stdout.write(payload)
        return 0 if report["all_match"] and not out_of_scope else 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PO03-WA-008 result custody.")
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="write artifact-manifest.json")
    manifest.add_argument("--slot", default=str(Path(__file__).resolve().parent))
    manifest.add_argument("--base-commit", required=True)
    manifest.set_defaults(func=cmd_manifest)

    readback = sub.add_parser("readback", help="verify artifacts at an immutable remote commit")
    readback.add_argument("--remote", required=True)
    readback.add_argument("--ref", required=True)
    readback.add_argument("--commit", required=True)
    readback.add_argument("--base-commit", required=True)
    readback.add_argument("--json", dest="json_path", default=None)
    readback.set_defaults(func=cmd_readback)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
