#!/usr/bin/env python3
"""Pre-integration guard for the CUR-ENV-01 lane group.

The root controller is the sole writer of shared projection state. A lane may
return only READY_TO_COMMIT. This tool decides, from the remote bytes alone,
whether a lane candidate may be integrated. It never merges and it never asks
a human to compare anything.

Written after a live SHARED_WORKTREE_COLLISION reproduction: lanes dispatched
into one shared working directory can commit onto the wrong branch or capture
another lane's files. Instruction did not prevent that, so containment is
enforced here as an executable check instead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "GROUP-MANIFEST-OE-20260822-v001.json"
REPO = Path(__file__).resolve().parents[5]

PROTECTED_REFS = {
    "main",
    "so02/strategic-control-plane-migration-20260822-v001",
    "po03/repository-engineering-portable-runtime-20260822-v001",
    "cursor/setup-dev-environment-b5ce",
    "soo/v003-currentness-repair-20260820",
    "soo/v003-controlling-pointer-and-part-manifest-repair-20260820",
    "cursor/so02-cur-orch-qual-01",
    "cursor/operating-environment-return-20260822-v001",
}
PROTECTED_PREFIXES = ("cursor/po03-", "po03/", "soo/", "packs/")


def run(args: list[str], cwd: Path = REPO) -> tuple[int, str, str]:
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return done.returncode, done.stdout, done.stderr


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def namespace_matches(path: str, owned: list[str]) -> bool:
    for pattern in owned:
        prefix = pattern[:-3] if pattern.endswith("/**") else pattern
        if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
            return True
    return False


def evaluate_lane(parent: dict[str, Any], base_sha: str) -> dict[str, Any]:
    """Decide a single lane candidate from remote evidence only."""
    lane_id = parent["parent_id"]
    branch = parent["isolated_branch"]
    owned = parent["owned_namespace"]
    findings: list[str] = []

    code, out, _ = run(["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"])
    if code != 0 or not out.strip():
        return {
            "parent_id": lane_id,
            "branch": branch,
            "state": "NOT_RETURNED",
            "detail": "no remote branch; a lane that did not push is not assumed successful",
            "integrable": False,
        }

    head = out.split()[0]
    code, _, err = run(["git", "fetch", "--no-tags", "--quiet", "origin", branch])
    if code != 0:
        return {"parent_id": lane_id, "branch": branch, "state": "FETCH_FAILED",
                "detail": err.strip(), "integrable": False}

    code, _, _ = run(["git", "merge-base", "--is-ancestor", base_sha, head])
    if code != 0:
        findings.append(f"branch head {head} does not descend from the declared base {base_sha}")

    code, listing, _ = run(["git", "diff", "--name-only", f"{base_sha}..{head}"])
    changed = [line for line in listing.splitlines() if line.strip()]
    if not changed:
        # An empty branch means the lane has not delivered yet. That is not the
        # same as a lane that delivered something disallowed, and conflating the
        # two is the state-confusion this estate is trying to eliminate.
        return {
            "parent_id": lane_id,
            "branch": branch,
            "immutable_head": head,
            "base_sha": base_sha,
            "changed_file_count": 0,
            "changed_files": [],
            "state": "IN_FLIGHT_NO_CONTENT_YET",
            "detail": "branch exists but carries no changes against the declared base; not delivered and not rejected",
            "integrable": False,
        }

    outside = [path for path in changed if not namespace_matches(path, owned)]
    for path in outside:
        findings.append(f"cross-contamination: {path} is outside this lane's owned namespace")

    return {
        "parent_id": lane_id,
        "branch": branch,
        "immutable_head": head,
        "base_sha": base_sha,
        "changed_file_count": len(changed),
        "changed_files": changed,
        "files_outside_namespace": outside,
        "state": "READY_FOR_INTEGRATION" if not findings else "REJECTED_FAIL_CLOSED",
        "findings": findings,
        "integrable": not findings,
    }


def verify_reported_head(branch: str, reported_sha: str) -> dict[str, Any]:
    """Check a lane's reported commit against what the remote actually serves.

    A lane sharing a detached HEAD can commit, then `git push` a branch ref that
    never moved. Git prints "Everything up-to-date" and exits 0, so a zero exit
    is not evidence of publication. Only the remote ref is evidence.
    """
    code, out, _ = run(["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"])
    if code != 0 or not out.strip():
        return {
            "branch": branch,
            "reported_sha": reported_sha,
            "remote_sha": None,
            "state": "REPORTED_BUT_ABSENT",
            "matches": False,
            "detail": "the lane reported a commit but the remote holds no such branch",
        }
    remote = out.split()[0]
    matches = remote == reported_sha
    return {
        "branch": branch,
        "reported_sha": reported_sha,
        "remote_sha": remote,
        "state": "CONFIRMED_PUBLISHED" if matches else "SILENT_PUSH_DIVERGENCE",
        "matches": matches,
        "detail": None if matches else (
            "the remote head differs from the commit the lane reported; a push may have "
            "silently no-opped against a stale ref"
        ),
    }


def detect_path_collisions(results: list[dict[str, Any]]) -> list[str]:
    """Two lanes claiming one path is an automatic fail-closed rejection of both."""
    owners: dict[str, list[str]] = {}
    for result in results:
        for path in result.get("changed_files", []):
            owners.setdefault(path, []).append(result["parent_id"])
    return [
        f"path {path} claimed by {sorted(set(lanes))}"
        for path, lanes in sorted(owners.items())
        if len(set(lanes)) > 1
    ]


def verify_protected_refs(expected: dict[str, str]) -> list[str]:
    drift: list[str] = []
    for ref, sha in expected.items():
        code, out, _ = run(["git", "ls-remote", "--heads", "origin", f"refs/heads/{ref}"])
        if code != 0 or not out.strip():
            drift.append(f"{ref}: could not resolve")
            continue
        observed = out.split()[0]
        if observed != sha:
            drift.append(f"{ref}: expected {sha} observed {observed}")
    return drift


def guard_ref_is_protected(branch: str) -> bool:
    return branch in PROTECTED_REFS or branch.startswith(PROTECTED_PREFIXES)


def evaluate() -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    base_sha = manifest["immutable_source"]["immutable_sha"]
    parents = manifest["parents"]

    results = [evaluate_lane(parent, base_sha) for parent in parents]
    collisions = detect_path_collisions(results)
    if collisions:
        for result in results:
            claimed = set(result.get("changed_files", []))
            for collision in collisions:
                path = collision.split()[1]
                if path in claimed:
                    result["state"] = "REJECTED_FAIL_CLOSED"
                    result["integrable"] = False
                    result.setdefault("findings", []).append(f"contested path: {path}")

    expected = manifest["protected_surfaces_declared_untouchable"]
    drift = verify_protected_refs({
        "main": "37943ec2ff9f6702d72e127a3c8e56c81b0c3812",
        "so02/strategic-control-plane-migration-20260822-v001": base_sha,
        "cursor/so02-cur-orch-qual-01": "11a60dcf6dbc2eac4e6d975efab5d985ebbabd62",
    })

    declared = manifest["declared_parent_denominator"]
    undelivered = {"NOT_RETURNED", "IN_FLIGHT_NO_CONTENT_YET"}
    returned = sum(1 for r in results if r["state"] not in undelivered)
    integrable = sum(1 for r in results if r["integrable"])
    rejected = sum(1 for r in results if r["state"] == "REJECTED_FAIL_CLOSED")

    return {
        "guard_id": "CUR-ENV-01-LANE-GUARD",
        "decision_changed": [],
        "base_sha": base_sha,
        "declared_parent_denominator": declared,
        "delivered_lane_count": returned,
        "integrable_lane_count": integrable,
        "rejected_lane_count": rejected,
        "undelivered_lane_count": len(results) - returned,
        "denominator_reconciles": len(results) == declared,
        "path_collisions": collisions,
        "protected_ref_drift": drift,
        "lanes": results,
        "verdict": (
            "PROTECTED_REF_DRIFT_FAIL" if drift
            else "ALL_RETURNED_LANES_INTEGRABLE" if returned and integrable == returned
            else "PARTIAL" if returned
            else "NO_LANE_RETURNED"
        ),
        "founder_is_comparison_retrieval_or_merge_layer": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CUR-ENV-01 pre-integration lane guard")
    parser.add_argument("--json", action="store_true", help="emit the full report as JSON")
    args = parser.parse_args(argv)

    report = evaluate()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"base {report['base_sha']}")
        print(f"declared {report['declared_parent_denominator']} | "
              f"delivered {report['delivered_lane_count']} | "
              f"integrable {report['integrable_lane_count']} | "
              f"rejected {report['rejected_lane_count']} | "
              f"undelivered {report['undelivered_lane_count']}")
        for lane in report["lanes"]:
            print(f"  {lane['parent_id']:<32} {lane['state']}")
            for finding in lane.get("findings", []):
                print(f"      - {finding}")
        for collision in report["path_collisions"]:
            print(f"  COLLISION: {collision}")
        for item in report["protected_ref_drift"]:
            print(f"  PROTECTED REF DRIFT: {item}")
        print(f"verdict: {report['verdict']}")

    if report["protected_ref_drift"]:
        return 2
    return 0 if report["verdict"] in {"ALL_RETURNED_LANES_INTEGRABLE", "NO_LANE_RETURNED"} else 1


if __name__ == "__main__":
    sys.exit(main())
