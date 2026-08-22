#!/usr/bin/env python3
"""Coordinator-side ingestion driver for a wave of subordinate results.

Ingestion is deliberately paranoid.  For each cohort the driver fetches the
subordinate branch and re-reads every declared artifact by hash and byte count.
The subordinate's own worktree is never trusted and never consulted: the only
thing that counts is what the remote actually holds.

Read-back is anchored to the commit each artifact names, not to the branch tip.
Materialising the branch at its HEAD and hashing files out of that tree looks
equivalent but is not: as soon as a later commit touches an artifact, an honest
earlier result stops verifying even though its bytes are still durable at the
commit it declared.  That is not a hypothetical -- it is why cohort a2's unit
a2-u01 was really rejected for a fault_lab.py hash mismatch.

A working tree is therefore materialised only when a result does *not* claim
durability, because an uncommitted artifact has no object to read.

A cohort branch that has not been pushed yields no ingestion at all, which is
the correct outcome.  Provider completion is not result custody.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parents[2]

_spec = importlib.util.spec_from_file_location("control_plane", TOOLS / "control_plane.py")
CP = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(CP)

RESULT_PROTOCOL = "OBZIO-TRANSACTIONAL-RESULT-v1"


def git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd or REPO_ROOT, capture_output=True, text=True, check=False
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def cohort_branches() -> dict[str, str]:
    """Read the committed cohort roster.

    The roster is read through ``CP.PATH_OWNERSHIP_PATH`` rather than by
    rebuilding the path, so a fresh clone or a relocated control root resolves
    the same way the rest of the control plane does.
    """
    ownership = json.loads(Path(CP.PATH_OWNERSHIP_PATH).read_text(encoding="utf-8"))
    branches: dict[str, str] = {}
    for owner, entry in ownership["owners"].items():
        if owner == "coordinator" or "branch" not in entry:
            continue
        cohort = owner.rsplit("-", 1)[-1]
        branches[cohort] = entry["branch"]
    return branches


def is_sha(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
#
# After total runtime loss the coordinator has a clone and nothing else.  A
# clone does carry the remote's refs, so the bytes are not the missing part:
# what is missing is any local record of which refs carry subordinate results.
# That has to come from committed configuration -- the ownership roster and the
# immutable dispatch records -- and be confirmed against the remote.
#
# Configuration is the authority and the remote is only the confirmation.  A
# driver that ingested whatever branch it found pushed would treat push access
# as custody authority, so an undeclared branch is reported and never read.


def remote_heads(remote: str = "origin") -> dict[str, str]:
    """Every branch the remote is offering, as ``{branch: sha}``."""
    listing = git("ls-remote", "--heads", remote, check=False)
    heads: dict[str, str] = {}
    for line in listing.splitlines():
        sha, _, ref = line.partition("\t")
        if is_sha(sha.strip()) and ref.startswith("refs/heads/"):
            heads[ref[len("refs/heads/") :]] = sha.strip()
    return heads


def _declare(declared: dict[str, dict], branch: str, *, cohort: str | None, source: str, owner: str | None) -> None:
    entry = declared.setdefault(branch, {"cohorts": [], "sources": [], "owners": []})
    for key, value in (("cohorts", cohort), ("sources", source), ("owners", owner)):
        if value and value not in entry[key]:
            entry[key].append(value)


def declared_result_branches() -> dict[str, dict]:
    """Result branches named by committed configuration, with their provenance.

    Two independent sources are read, because either can be incomplete: the
    ownership roster names one branch per subordinate, and each immutable
    dispatch record names the branch of the result slot it reserved.
    """
    declared: dict[str, dict] = {}
    ownership_path = Path(CP.PATH_OWNERSHIP_PATH)
    if ownership_path.exists():
        ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
        for owner, entry in (ownership.get("owners") or {}).items():
            branch = entry.get("branch")
            if owner == "coordinator" or not branch:
                continue
            _declare(
                declared,
                branch,
                cohort=owner.rsplit("-", 1)[-1],
                source="path-ownership",
                owner=owner,
            )
    dispatch_dir = Path(CP.DISPATCH_DIR)
    if dispatch_dir.exists():
        for path in sorted(dispatch_dir.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            branch = ((record.get("result_slot") or {}).get("branch")) or None
            if not branch:
                continue
            unit_id = str(record.get("unit_id") or path.stem)
            _declare(
                declared,
                branch,
                cohort=record.get("cohort_id") or unit_id.split("-", 1)[0],
                source="dispatch-result-slot",
                owner=record.get("owner"),
            )
    return declared


def discover_result_branches(remote: str = "origin") -> dict[str, object]:
    """Enumerate result branches from configuration and confirm them remotely.

    Pure: it reads the remote and the committed configuration, and writes
    nothing.  Discovery has to be safe to run from a read-only clone before any
    decision to ingest has been taken.
    """
    declared = declared_result_branches()
    heads = remote_heads(remote)
    for branch, entry in declared.items():
        entry["on_remote"] = branch in heads
        entry["remote_sha"] = heads.get(branch)
    return {
        "remote": remote,
        "remote_branches": len(heads),
        "branches": declared,
        "cohorts": sorted({cohort for entry in declared.values() for cohort in entry["cohorts"]}),
        "declared_but_absent": sorted(b for b, e in declared.items() if not e["on_remote"]),
        "undeclared_on_remote": sorted(set(heads) - set(declared)),
    }


def unit_record_paths(sha: str, cohort: str) -> list[str]:
    """List the unit-record blobs a cohort published, straight from the tree."""
    prefix = f"workstreams/po03/control/units/{cohort}/"
    listing = git("ls-tree", "-r", "--name-only", sha, "--", prefix, check=False)
    return sorted(line for line in listing.splitlines() if line.endswith(".json"))


def read_record(sha: str, path: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "cat-file", "blob", f"{sha}:{path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def ingest_cohort(cohort: str, branch: str, *, complete: bool) -> dict[str, object]:
    outcome: dict[str, object] = {
        "cohort": cohort,
        "branch": branch,
        "remote_sha": None,
        "results_found": 0,
        "ingested": [],
        "duplicates": [],
        "rejected": [],
        "completed": [],
        "state": "NOT_PUSHED",
        "worktree_materialised": False,
        "fetched_branches": [],
    }
    git("fetch", "origin", f"+{branch}:refs/remotes/origin/{branch}", check=False)
    outcome["fetched_branches"].append(branch)
    # --verify --quiet is required: plain rev-parse echoes an unresolvable ref
    # back on stdout, which would make an unpushed cohort look resolvable.
    sha = git("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}", check=False)
    if not is_sha(sha):
        return outcome
    outcome["remote_sha"] = sha
    outcome["state"] = "PUSHED"

    records: list[tuple[str, dict]] = []
    for path in unit_record_paths(sha, cohort):
        raw = read_record(sha, path)
        if raw is None:
            outcome["rejected"].append({"file": path, "reason": "record blob could not be read"})
            continue
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            outcome["rejected"].append({"file": path, "reason": f"unparseable: {exc}"})
            continue
        if not isinstance(doc, dict) or doc.get("protocol_version") != RESULT_PROTOCOL:
            continue  # canaries and scratch files are not results
        records.append((path, doc))

    outcome["results_found"] = len(records)
    if not records:
        return outcome

    # An artifact locator carries the branch it was committed on, and it need
    # not be this cohort's branch.  A fresh clone has to fetch that branch
    # before it can resolve the commit, or an honest cross-branch result is
    # rejected for nothing more than an unfetched object.
    for _path, doc in records:
        for artifact in doc.get("artifacts") or []:
            artifact_branch, _commit, _relative = CP.parse_content_uri(str(artifact.get("content_uri") or ""))
            if not artifact_branch or artifact_branch in outcome["fetched_branches"]:
                continue
            git("fetch", "origin", f"+{artifact_branch}:refs/remotes/origin/{artifact_branch}", check=False)
            outcome["fetched_branches"].append(artifact_branch)

    # Only an uncommitted result needs a checkout; a durable one is read out of
    # the object database at the commit it declared.
    needs_tree = any(doc.get("obzio_state") != "RESULT_COMMITTED" for _path, doc in records)
    scratch: Path | None = None
    tree: Path | None = None
    try:
        if needs_tree:
            scratch = Path(tempfile.mkdtemp(prefix=f"po03-ingest-{cohort}-"))
            tree = scratch / "tree"
            git("worktree", "add", "--detach", "--quiet", str(tree), sha)
            outcome["worktree_materialised"] = True
        for path, doc in records:
            unit_id = doc.get("task_id", Path(path).stem)
            try:
                admitted = CP.ingest_result(
                    doc,
                    artifact_root=tree if tree is not None else Path(REPO_ROOT),
                    repo=Path(REPO_ROOT),
                )
            except CP.ControlPlaneError as exc:
                outcome["rejected"].append({"unit_id": unit_id, "reason": str(exc)})
                continue
            if admitted["duplicate"]:
                outcome["duplicates"].append(unit_id)
            else:
                outcome["ingested"].append(unit_id)
            if complete and doc.get("obzio_state") == "RESULT_COMMITTED":
                try:
                    CP.cmd_complete(argparse.Namespace(unit_id=unit_id))
                    outcome["completed"].append(unit_id)
                except CP.ControlPlaneError as exc:
                    outcome["rejected"].append({"unit_id": unit_id, "reason": f"completion refused: {exc}"})
    finally:
        if tree is not None:
            git("worktree", "remove", "--force", str(tree), check=False)
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
    return outcome


def _summarise(report: list[dict[str, object]], extra: dict[str, object] | None = None) -> dict[str, object]:
    CP.materialize()
    state = CP.scan_recovery()
    summary: dict[str, object] = {
        "cohorts": report,
        "totals": {
            "results_found": sum(int(r["results_found"]) for r in report),
            "ingested": sum(len(r["ingested"]) for r in report),
            "recovered": sum(len(r["ingested"]) for r in report),
            "duplicates": sum(len(r["duplicates"]) for r in report),
            "rejected": sum(len(r["rejected"]) for r in report),
            "completed": sum(len(r["completed"]) for r in report),
            "not_pushed": [r["cohort"] for r in report if r["state"] == "NOT_PUSHED"],
        },
        "fetched_branches": sorted({b for r in report for b in r.get("fetched_branches", [])}),
        "recovery": {
            "ledger_rows": state["ledger_rows"],
            "ledger_chain_valid": state["ledger_chain_valid"],
            "false_completions": state["false_completions"],
            "provider_completed_uncommitted": state["provider_completed_uncommitted"],
            "expired_leases": state["expired_leases"],
        },
    }
    if extra:
        summary.update(extra)
    return summary


def recover_from_remote(
    *,
    cohorts: list[str] | None = None,
    complete: bool = False,
    remote: str = "origin",
) -> dict[str, object]:
    """Discover result branches, then recover every committed result they hold.

    This is the fresh-clone path: nothing here consults local state beyond
    committed configuration, so a coordinator that lost its runtime entirely
    recovers custody from the remote's bytes.  Verification is unchanged and
    non-negotiable -- every artifact is re-read at the commit it declared and
    re-hashed -- so a corrupt result is refused while its neighbours recover.
    """
    discovery = discover_result_branches(remote)
    report: list[dict[str, object]] = []
    for branch in sorted(discovery["branches"]):
        entry = discovery["branches"][branch]
        for cohort in entry["cohorts"]:
            if cohorts is not None and cohort not in cohorts:
                continue
            report.append(ingest_cohort(cohort, branch, complete=complete))
    return _summarise(report, {"discovery": discovery})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ingest a wave of subordinate results")
    parser.add_argument("--cohort", action="append", help="restrict to one or more cohorts")
    parser.add_argument("--complete", action="store_true", help="set COMPLETED for verified units")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="enumerate result branches from committed configuration and the remote, and stop",
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        help="recover every committed result from the discovered branches (fresh-clone path)",
    )
    args = parser.parse_args(argv)

    if args.discover:
        print(json.dumps(discover_result_branches(), indent=2, sort_keys=True))
        return 0
    if args.recover:
        summary = recover_from_remote(cohorts=args.cohort, complete=args.complete)
        print(json.dumps(summary, indent=2, sort_keys=True))
        recovery = summary["recovery"]
        return 1 if recovery["false_completions"] or not recovery["ledger_chain_valid"] else 0

    branches = cohort_branches()
    selected = args.cohort or sorted(branches, key=lambda c: (len(c), c))
    report = []
    for cohort in selected:
        branch = branches.get(cohort)
        if branch is None:
            print(f"unknown cohort: {cohort}", file=sys.stderr)
            return 2
        report.append(ingest_cohort(cohort, branch, complete=args.complete))

    summary = _summarise(report)
    print(json.dumps(summary, indent=2, sort_keys=True))
    recovery = summary["recovery"]
    return 1 if recovery["false_completions"] or not recovery["ledger_chain_valid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
