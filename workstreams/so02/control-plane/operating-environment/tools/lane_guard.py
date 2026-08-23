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

## Retired 2026-08-23 — the protected-ref machinery

Ahmed Sadek, standing amendment 2026-08-23:

    "'Protected surfaces' is not a founder-established category. I never
    designated main, PO-03, PR #9, any cursor/po03-* branch, PO-01, PR #6, PR #7
    or any SO-02 source branch as protected. [...] It is void as a category."

    "Never report 'protected surfaces verified unchanged.' [...] Untouched is not
    a virtue. Correct is."

So `PROTECTED_REFS`, `PROTECTED_PREFIXES`, `guard_ref_is_protected`,
`verify_protected_refs` and the `PROTECTED_REF_DRIFT_FAIL` verdict are gone, and
`protected_ref_drift` no longer appears in the report. They are not replaced by a
shorter list. Write admissibility now lives in `write_admission.py`, which asks
whether a write was declared and reasoned.

Two things worth recording about what was removed, because they show the
category was decorative as well as unfounded:

- `verify_protected_refs` was called with a HARDCODED dict of three refs. The
  manifest key `protected_surfaces_declared_untouchable` was read into a local
  named `expected` and then never used. The file that appeared to declare the
  boundary was not the file the check consulted.
- The check compared refs this lane group never wrote to, so it could only ever
  report "unchanged". That is the inaction-as-success the founder struck out.

What is kept here is kept as EARNED mechanism, each citing the defect it caught:
namespace containment, the reported-head check, path-collision detection, and
the distinction between a lane that has not delivered and one that was refused.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


concurrency_observer = _load("concurrency_observer")

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "GROUP-MANIFEST-OE-20260822-v001.json"
REPO = Path(__file__).resolve().parents[5]

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


def lanes_in_flight(results: list[dict[str, Any]], observation: dict[str, Any] | None) -> list[str]:
    """Which candidate lanes are still being written, per the founder's first gate.

    This replaces the retired drift check, and it is a different question. The
    old one asked whether refs on a list had moved, which this group never wrote
    and so could only answer "unchanged". This one asks whether a lane branch is
    held by a live run right now — the only concurrency fact that bears on
    integrating it. It gates on the world, not on a name, and it expires when
    the run does.

    An absent observation yields no findings and says so: this function is not
    the place that decides admissibility, `write_admission` is, and inventing a
    refusal here from missing data would be the assistant-authored class.
    """
    if not observation:
        return []
    agents = observation.get("agents") or []
    in_flight: list[str] = []
    for result in results:
        branch = result.get("branch")
        if not branch:
            continue
        holders = concurrency_observer.live_agents_holding(branch, agents)
        for holder in holders:
            in_flight.append(
                f"{result['parent_id']} branch {branch} is held by run {holder.get('bcId')} "
                f"in state {holder.get('status')}; integrating it now would disturb work in flight"
            )
    return in_flight


def evaluate(observation: dict[str, Any] | None = None) -> dict[str, Any]:
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

    in_flight = lanes_in_flight(results, observation)
    for result in results:
        for note in in_flight:
            if note.startswith(f"{result['parent_id']} "):
                result["state"] = "IN_FLIGHT_LIVE_RUN_HOLDS_BRANCH"
                result["integrable"] = False
                result.setdefault("findings", []).append(note)

    declared = manifest["declared_parent_denominator"]
    undelivered = {"NOT_RETURNED", "IN_FLIGHT_NO_CONTENT_YET", "IN_FLIGHT_LIVE_RUN_HOLDS_BRANCH"}
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
        "lanes_in_flight": in_flight,
        "concurrency_observed": observation is not None,
        "lanes": results,
        "verdict": (
            "ALL_RETURNED_LANES_INTEGRABLE" if returned and integrable == returned
            else "PARTIAL" if returned
            else "NO_LANE_RETURNED"
        ),
        "write_admissibility_is_decided_by": (
            "write_admission.py — declared and reasoned, not target avoidance. The "
            "protected-surface category was voided by the founder on 2026-08-23."
        ),
        "founder_is_comparison_retrieval_or_merge_layer": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CUR-ENV-01 pre-integration lane guard")
    parser.add_argument("--json", action="store_true", help="emit the full report as JSON")
    parser.add_argument("--observation", default=None,
                        help="JSON from list-cloud-agents, to check whether a lane branch is still live")
    args = parser.parse_args(argv)

    observation = None
    if args.observation:
        try:
            observation = concurrency_observer.normalise_observation(
                json.loads(Path(args.observation).read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"could not read observation: {exc}", file=sys.stderr)
            return 2

    report = evaluate(observation)
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
        for item in report["lanes_in_flight"]:
            print(f"  IN FLIGHT: {item}")
        if not report["concurrency_observed"]:
            print("  note: no agent observation supplied, so lane concurrency was not checked")
        print(f"verdict: {report['verdict']}")

    return 0 if report["verdict"] in {"ALL_RETURNED_LANES_INTEGRABLE", "NO_LANE_RETURNED"} else 1


if __name__ == "__main__":
    sys.exit(main())
