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
    }
    git("fetch", "origin", branch, check=False)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ingest a wave of subordinate results")
    parser.add_argument("--cohort", action="append", help="restrict to one or more cohorts")
    parser.add_argument("--complete", action="store_true", help="set COMPLETED for verified units")
    args = parser.parse_args(argv)

    branches = cohort_branches()
    selected = args.cohort or sorted(branches, key=lambda c: (len(c), c))
    report = []
    for cohort in selected:
        branch = branches.get(cohort)
        if branch is None:
            print(f"unknown cohort: {cohort}", file=sys.stderr)
            return 2
        report.append(ingest_cohort(cohort, branch, complete=args.complete))

    CP.materialize()
    state = CP.scan_recovery()
    summary = {
        "cohorts": report,
        "totals": {
            "results_found": sum(int(r["results_found"]) for r in report),
            "ingested": sum(len(r["ingested"]) for r in report),
            "duplicates": sum(len(r["duplicates"]) for r in report),
            "rejected": sum(len(r["rejected"]) for r in report),
            "completed": sum(len(r["completed"]) for r in report),
            "not_pushed": [r["cohort"] for r in report if r["state"] == "NOT_PUSHED"],
        },
        "recovery": {
            "ledger_rows": state["ledger_rows"],
            "ledger_chain_valid": state["ledger_chain_valid"],
            "false_completions": state["false_completions"],
            "provider_completed_uncommitted": state["provider_completed_uncommitted"],
            "expired_leases": state["expired_leases"],
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if state["false_completions"] or not state["ledger_chain_valid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
