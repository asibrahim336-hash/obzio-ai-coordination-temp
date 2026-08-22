#!/usr/bin/env python3
"""Emit, seal and verify the transactional result document for one work unit.

A subordinate never hand-writes custody metadata.  It names the artifacts it
actually produced and this tool derives the hashes, byte counts and locators
from the committed tree, so a result can only describe bytes that exist.  The
strongest state a subordinate may emit is RESULT_COMMITTED; COMPLETED belongs
to the coordinator and ACCEPTED belongs to an independent reviewer.

Why the locator scheme changed
------------------------------
The previous emitter stamped the commit that existed at emission time and then
the record was committed afterwards, so every result declared a commit that did
not contain it.  Cohort a6 found five such records independently.  A record
simply cannot name the commit that contains it: that commit's tree covers the
record, so the record would have to contain the id of a commit whose id depends
on the record.  The self-reference is removed rather than repaired.

Three locators do the work instead, and each one resolves:

``result_commit_id``
    The commit that contains every declared artifact.  The emitter proves it by
    reading each artifact back out of that commit and comparing bytes before
    writing anything.

``manifest_uri`` = ``obzio-manifest-sha256:<hash>``
    A derivation rather than a path.  A reader recomputes it from the artifacts
    at ``result_commit_id`` and compares, which needs no guessing and no
    out-of-band knowledge.

the sealed sidecar ``<unit>.locator.json``
    Written by a second ``--seal`` pass once the record itself is committed, it
    names the commit that contains the record.  A sidecar may name the record
    because nothing needs to name the sidecar.

``--verify`` resolves all three end to end and fails loudly if any of them has
stopped describing the bytes it claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESULT_PROTOCOL = "OBZIO-TRANSACTIONAL-RESULT-v1"
LOCATOR_PROTOCOL = "OBZIO-RESULT-LOCATOR-v1"
MANIFEST_SCHEME = "obzio-manifest-sha256"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def git_ok(root: Path, *args: str) -> bool:
    return subprocess.run(["git", *args], cwd=root, capture_output=True).returncode == 0


def read_blob(root: Path, commit: str, relative: str) -> bytes | None:
    """Return the exact bytes of ``relative`` as committed in ``commit``."""
    proc = subprocess.run(
        ["git", "cat-file", "blob", f"{commit}:{relative}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def introducing_commit(root: Path, relative: str) -> str | None:
    """The most recent commit reachable from HEAD that touched ``relative``."""
    proc = subprocess.run(
        ["git", "rev-list", "-1", "HEAD", "--", relative],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    commit = proc.stdout.strip()
    return commit or None


def load_dispatch(root: Path, unit_id: str) -> dict[str, Any]:
    path = root / "workstreams/po03/control/dispatch" / f"{unit_id}.json"
    if not path.is_file():
        raise SystemExit(f"no immutable dispatch record for {unit_id} at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def record_path(root: Path, dispatch: dict[str, Any], override: str | None) -> Path:
    return Path(override) if override else root / dispatch["result_slot"]["unit_record"]


def seal_path(record: Path) -> Path:
    return record.with_suffix(".locator.json")


def manifest_of(unit_id: str, commit: str | None, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    """The derivation a reader reproduces from the artifacts at ``commit``.

    Deliberately excludes the branch: a branch is a moving name, and a manifest
    that changes when a branch is renamed is not a content address.
    """
    return {
        "unit_id": unit_id,
        "commit": commit,
        "artifacts": [
            {"logical_name": item["logical_name"], "sha256": item["sha256"], "bytes": item["bytes"]}
            for item in sorted(artifacts, key=lambda item: item["artifact_id"])
        ],
    }


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------


def build_artifacts(root: Path, unit_id: str, relatives: list[str], *, committed: bool,
                    branch: str, commit: str) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for index, relative in enumerate(relatives, start=1):
        target = root / relative
        if not target.is_file():
            raise SystemExit(f"artifact does not exist in the worktree: {relative}")
        blob = read_blob(root, commit, relative)
        working_sha = sha256_file(target)
        if blob is None:
            if committed:
                raise SystemExit(
                    f"artifact is not committed at {commit}: {relative}; "
                    "RESULT_COMMITTED may only describe committed bytes"
                )
            content_uri = f"file:{relative}"
            sha, size = working_sha, target.stat().st_size
        else:
            committed_sha = sha256_bytes(blob)
            if committed and committed_sha != working_sha:
                raise SystemExit(
                    f"artifact {relative} does not match the committed bytes at {commit}: "
                    f"worktree {working_sha}, commit {committed_sha}. Commit the change "
                    "before declaring it durable."
                )
            if committed_sha == working_sha:
                content_uri = f"git:{branch}@{commit}:{relative}"
                sha, size = committed_sha, len(blob)
            else:
                content_uri = f"file:{relative}"
                sha, size = working_sha, target.stat().st_size
        media, _ = mimetypes.guess_type(relative)
        artifacts.append(
            {
                "artifact_id": f"{unit_id}-art-{index:02d}",
                "logical_name": relative.rsplit("/", 1)[-1],
                "content_uri": content_uri,
                "sha256": sha,
                "bytes": size,
                "media_type": media or "application/octet-stream",
                "readback_verified_at": utc_now() if committed else None,
            }
        )
    return artifacts


def emit(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    dispatch = load_dispatch(root, args.unit_id)
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    commit = git(root, "rev-parse", "HEAD")
    worker_id = dispatch["owner"]
    committed = args.state == "RESULT_COMMITTED"

    artifacts = build_artifacts(
        root,
        args.unit_id,
        sorted(set(args.artifact)),
        committed=committed,
        branch=branch,
        commit=commit,
    )
    if committed and not artifacts:
        raise SystemExit("RESULT_COMMITTED requires at least one committed artifact")

    manifest_sha = sha256_bytes(canonical(manifest_of(args.unit_id, commit, artifacts)).encode("utf-8"))
    now = utc_now()
    document = {
        "protocol_version": RESULT_PROTOCOL,
        "task_id": args.unit_id,
        "commission_id": dispatch["commission_id"],
        "immutable_input_manifest_sha256": dispatch["immutable_input_manifest_sha256"],
        "acceptance_contract_sha256": dispatch["acceptance_contract_sha256"],
        "provider_state": "COMPLETED" if committed else "UNKNOWN",
        "obzio_state": args.state,
        "attempt": {
            "attempt_id": f"{args.unit_id}-attempt-{args.fence_token}",
            "idempotency_key": dispatch["idempotency_key"],
            "lease_id": f"lease-{args.unit_id}-{args.fence_token}",
            "fence_token": args.fence_token,
            "provider_run_id": args.provider_run_id,
            "worker_id": worker_id,
            "heartbeat_at": now,
            "checkpoint_seq": len(artifacts),
        },
        "result_transaction": {
            "result_txn_id": f"{args.unit_id}-txn-{args.fence_token}",
            "state": "COMMITTED" if committed else "RESERVED",
            # No self-reference: a derivation the reader can reproduce from the
            # artifacts at result_commit_id, not a path that never existed.
            "manifest_uri": f"{MANIFEST_SCHEME}:{manifest_sha}" if committed else None,
            "manifest_sha256": manifest_sha if committed else None,
            "artifact_count": len(artifacts),
            "total_bytes": sum(item["bytes"] for item in artifacts),
            "committed_at": now if committed else None,
            "verified_at": now if committed else None,
            "parent_ingested_at": None,
            "result_commit_id": commit if committed else None,
        },
        "artifacts": artifacts,
        "completion_actor": None,
        "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
    }

    out = record_path(root, dispatch, args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"wrote {out} ({len(artifacts)} artifacts, "
        f"{document['result_transaction']['total_bytes']} bytes)"
    )
    if committed:
        print(f"  result_commit_id {commit}")
        print(f"  manifest_uri     {MANIFEST_SCHEME}:{manifest_sha}")
        print("  seal the record locator with --seal after committing this file")
    return 0


# ---------------------------------------------------------------------------
# seal
# ---------------------------------------------------------------------------


def seal(args: argparse.Namespace) -> int:
    """Publish an immutable locator for the record, once the record is committed."""
    root = Path(args.root).resolve()
    dispatch = load_dispatch(root, args.unit_id)
    record = record_path(root, dispatch, args.out)
    if not record.is_file():
        raise SystemExit(f"no result record to seal at {record}; emit it first")
    relative = record.resolve().relative_to(root).as_posix()
    if not git_ok(root, "ls-files", "--error-unmatch", relative):
        raise SystemExit(f"result record {relative} is not committed; commit it before sealing")

    body = record.read_bytes()
    commit = introducing_commit(root, relative)
    if commit is None:
        raise SystemExit(f"result record {relative} is not committed on this branch")
    blob = read_blob(root, commit, relative)
    if blob is None:
        raise SystemExit(f"result record {relative} is not present at {commit}")
    if blob != body:
        raise SystemExit(
            f"result record {relative} has uncommitted edits; commit them before sealing "
            f"(worktree {sha256_bytes(body)}, commit {sha256_bytes(blob)})"
        )

    document = json.loads(body.decode("utf-8"))
    payload = {
        "protocol_version": LOCATOR_PROTOCOL,
        "unit_id": args.unit_id,
        "branch": git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "record_path": relative,
        "record_commit_id": commit,
        "record_sha256": sha256_bytes(body),
        "record_bytes": len(body),
        "artifact_commit_id": document["result_transaction"]["result_commit_id"],
        "manifest_uri": document["result_transaction"]["manifest_uri"],
        "sealed_at": utc_now(),
        "resolve_with": f"git cat-file blob {commit}:{relative}",
    }
    target = seal_path(record)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"sealed {target}")
    print(f"  {payload['resolve_with']}")
    return 0


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def verify(args: argparse.Namespace) -> int:
    """Resolve every declared locator and report, rather than assert, the result."""
    root = Path(args.root).resolve()
    dispatch = load_dispatch(root, args.unit_id)
    record = record_path(root, dispatch, args.out)
    if not record.is_file():
        raise SystemExit(f"no result record at {record}")
    document = json.loads(record.read_text(encoding="utf-8"))
    txn = document["result_transaction"]
    commit = txn["result_commit_id"]
    failures: list[str] = []

    resolves = bool(commit) and git_ok(root, "cat-file", "-e", f"{commit}^{{commit}}")
    if commit and not resolves:
        failures.append(f"result_commit_id {commit} does not resolve to a commit")

    artifact_report = []
    for artifact in document["artifacts"]:
        uri = artifact["content_uri"]
        if uri.startswith("git:") and "@" in uri:
            declared_commit = uri.split("@", 1)[1].split(":", 1)[0]
            relative = uri.split(":", 2)[2]
            blob = read_blob(root, declared_commit, relative)
        else:
            declared_commit = None
            relative = uri.split(":", 1)[-1]
            target = root / relative
            blob = target.read_bytes() if target.is_file() else None
        if blob is None:
            failures.append(f"{uri} does not resolve to bytes")
            artifact_report.append({"content_uri": uri, "resolved": False})
            continue
        actual = sha256_bytes(blob)
        ok = actual == artifact["sha256"] and len(blob) == artifact["bytes"]
        if not ok:
            failures.append(
                f"{uri} sha256 mismatch: declared {artifact['sha256']}/{artifact['bytes']}B, "
                f"read {actual}/{len(blob)}B"
            )
        artifact_report.append(
            {
                "content_uri": uri,
                "resolved": True,
                "commit": declared_commit,
                "sha256_matches": actual == artifact["sha256"],
                "bytes_match": len(blob) == artifact["bytes"],
            }
        )

    manifest_reproduced = None
    if txn["manifest_uri"] and str(txn["manifest_uri"]).startswith(f"{MANIFEST_SCHEME}:"):
        expected = canonical(manifest_of(document["task_id"], commit, document["artifacts"]))
        manifest_reproduced = sha256_bytes(expected.encode("utf-8")) == txn["manifest_sha256"]
        if not manifest_reproduced:
            failures.append("manifest_sha256 could not be reproduced from the declared artifacts")
        if txn["manifest_uri"] != f"{MANIFEST_SCHEME}:{txn['manifest_sha256']}":
            failures.append("manifest_uri does not agree with manifest_sha256")

    sealed = seal_path(record)
    record_resolves = None
    if sealed.is_file():
        payload = json.loads(sealed.read_text(encoding="utf-8"))
        blob = read_blob(root, payload["record_commit_id"], payload["record_path"])
        record_resolves = blob is not None and sha256_bytes(blob) == payload["record_sha256"]
        if not record_resolves:
            failures.append(
                f"sealed locator {payload['record_commit_id']}:{payload['record_path']} "
                "does not resolve to the recorded bytes"
            )

    report = {
        "unit_id": args.unit_id,
        "record": str(record.relative_to(root)) if record.is_relative_to(root) else str(record),
        "result_commit_id": commit,
        "result_commit_resolves": resolves,
        "manifest_sha256_reproduced": manifest_reproduced,
        "record_resolves_from_seal": record_resolves,
        "sealed": sealed.is_file(),
        "artifacts": artifact_report,
        "failures": failures,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("unit_id")
    parser.add_argument("--root", default=".", help="worktree root")
    parser.add_argument("--artifact", action="append", default=[], help="repo-relative artifact path")
    parser.add_argument("--fence-token", type=int, default=1)
    parser.add_argument("--provider-run-id", help="required when emitting a result")
    parser.add_argument(
        "--state",
        default="RESULT_COMMITTED",
        choices=["RESULT_COMMITTED", "PROVIDER_COMPLETED_UNCOMMITTED", "FAILED_TERMINAL"],
    )
    parser.add_argument("--out", help="output path (defaults to the unit record slot)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--seal", action="store_true", help="publish the record's immutable locator")
    mode.add_argument("--verify", action="store_true", help="resolve every declared locator")
    args = parser.parse_args(argv)

    if args.seal:
        return seal(args)
    if args.verify:
        return verify(args)
    if not args.provider_run_id:
        parser.error("--provider-run-id is required when emitting a result")
    return emit(args)


if __name__ == "__main__":
    raise SystemExit(main())
