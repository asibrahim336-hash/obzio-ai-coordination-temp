#!/usr/bin/env python3
"""Reconstruct G0 from immutable Git objects and prove the copy is byte-exact.

G0 is not described here, it is read.  The reconstruction names a commit, reads
the blob that commit's tree points at, and compares those bytes against the copy
committed into this unit's subtree.  A single differing byte is a hard failure:
a baseline that is not the real pre-amendment source cannot support a lift claim.

The provenance record also names the ancestor commits that carry the same blob,
so the reader can see how far back the baseline reaches, and lists the callable
surface G0 has against the surface the current factory has.  That surface delta
is what the suite later scores as UNSUPPORTED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROVENANCE_VERSION = "PO03-G0-PROVENANCE-v1"
FACTORY_PATH = "workstreams/po03/tools/transactional_factory.py"
# 2b48869 froze the transactional activation state; 5cfebfd is the commit that
# added fencing, ingestion, completion gating and the recovery scanner.  The
# ancestors are recorded so the baseline's reach is visible, not asserted.
BASELINE_COMMIT = "2b48869"
ANCESTOR_COMMITS = ("f64ff69", "7b9ee3e")
AMENDMENT_COMMIT = "5cfebfd"
DEF_PATTERN = re.compile(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", re.MULTILINE)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_bytes(repo: Path, *arguments: str) -> bytes:
    completed = subprocess.run(("git", *arguments), cwd=repo, check=True, capture_output=True)
    return completed.stdout


def git_text(repo: Path, *arguments: str) -> str:
    return git_bytes(repo, *arguments).decode("utf-8", "replace").strip()


def public_surface(source: str) -> list[str]:
    return sorted(name for name in DEF_PATTERN.findall(source) if not name.startswith("_"))


def blob_at(repo: Path, commit: str) -> dict[str, Any]:
    return {
        "commit": commit,
        "commit_id": git_text(repo, "rev-parse", commit),
        "blob_id": git_text(repo, "rev-parse", f"{commit}:{FACTORY_PATH}"),
        "committed_at": git_text(repo, "show", "-s", "--format=%cI", commit),
        "subject": git_text(repo, "show", "-s", "--format=%s", commit),
    }


def reconstruct(repo: Path, destination: Path) -> dict[str, Any]:
    baseline = blob_at(repo, BASELINE_COMMIT)
    payload = git_bytes(repo, "cat-file", "blob", f"{BASELINE_COMMIT}:{FACTORY_PATH}")
    reconstructed = {
        "source_bytes": len(payload),
        "source_sha256": sha256_bytes(payload),
        "git_blob_id": baseline["blob_id"],
        "retrieved_with": f"git cat-file blob {BASELINE_COMMIT}:{FACTORY_PATH}",
    }

    committed_copy: dict[str, Any] = {"path": destination.as_posix(), "present": destination.is_file()}
    if committed_copy["present"]:
        copied = destination.read_bytes()
        committed_copy.update(
            {
                "bytes": len(copied),
                "sha256": sha256_bytes(copied),
                "byte_exact": copied == payload,
                # A checkout can normalise line endings; naming the first
                # differing offset makes a mismatch diagnosable rather than
                # merely reported.
                "first_difference_offset": next(
                    (index for index, (left, right) in enumerate(zip(copied, payload)) if left != right),
                    None if copied == payload else min(len(copied), len(payload)),
                ),
            }
        )
    else:
        committed_copy["byte_exact"] = False

    current = repo / FACTORY_PATH
    current_payload = current.read_bytes()
    g0_surface = public_surface(payload.decode("utf-8"))
    g1_surface = public_surface(current_payload.decode("utf-8"))

    return {
        "provenance_version": PROVENANCE_VERSION,
        "recorded_at": utc_now(),
        "generation": "G0",
        "definition": "the pre-amendment controller, read from immutable Git objects rather than reconstructed from memory",
        "baseline_commit": baseline,
        "ancestors_carrying_the_same_blob": [
            record for record in (blob_at(repo, commit) for commit in ANCESTOR_COMMITS)
            if record["blob_id"] == baseline["blob_id"]
        ],
        "ancestors_carrying_an_earlier_blob": [
            record for record in (blob_at(repo, commit) for commit in ANCESTOR_COMMITS)
            if record["blob_id"] != baseline["blob_id"]
        ],
        "amendment_commit": blob_at(repo, AMENDMENT_COMMIT),
        "reconstructed": reconstructed,
        "committed_copy": committed_copy,
        "current_factory": {
            "path": FACTORY_PATH,
            "commit": git_text(repo, "rev-parse", "HEAD"),
            "blob_id": git_text(repo, "rev-parse", f"HEAD:{FACTORY_PATH}"),
            "sha256": sha256_bytes(current_payload),
            "bytes": len(current_payload),
        },
        "surface": {
            "g0_public_callables": g0_surface,
            "g1_public_callables": g1_surface,
            "added_after_g0": sorted(set(g1_surface) - set(g0_surface)),
            "removed_after_g0": sorted(set(g0_surface) - set(g1_surface)),
        },
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--destination", required=True, help="the committed G0 copy to verify")
    parser.add_argument("--write", action="store_true", help="write the blob to --destination before verifying")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    destination = Path(args.destination).resolve()
    if args.write:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(git_bytes(repo, "cat-file", "blob", f"{BASELINE_COMMIT}:{FACTORY_PATH}"))

    record = reconstruct(repo, destination)
    Path(args.out).write_bytes(canonical(record))
    print(json.dumps(record, indent=2, sort_keys=True))
    if not record["committed_copy"]["byte_exact"]:
        print("RECONSTRUCTION FAILED: the committed copy is not byte-exact with the immutable blob", file=sys.stderr)
        return 1
    print("RECONSTRUCTION VERIFIED: byte-exact with blob " + record["reconstructed"]["git_blob_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
