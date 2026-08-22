#!/usr/bin/env python3
"""Coordinator-side ingestion driver for a wave of subordinate results.

Ingestion is deliberately paranoid.  For each cohort the driver fetches the
subordinate branch, materialises it as a detached worktree at an immutable SHA,
and re-reads every declared artifact from that tree by hash and byte count.
The subordinate's own worktree is never trusted and never consulted: the only
thing that counts is what the remote actually holds.

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
    ownership = json.loads((CP.CONTROL_ROOT / "control" / "path-ownership.json").read_text(encoding="utf-8"))
    branches: dict[str, str] = {}
    for owner, entry in ownership["owners"].items():
        if owner == "coordinator":
            continue
        cohort = owner.rsplit("-", 1)[-1]
        branches[cohort] = entry["branch"]
    return branches


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
    }
    git("fetch", "origin", branch, check=False)
    # --verify --quiet is required: plain rev-parse echoes an unresolvable ref
    # back on stdout, which would make an unpushed cohort look resolvable.
    sha = git("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}", check=False)
    if not CP.SHA256_RE.fullmatch(sha) and not (len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)):
        return outcome
    outcome["remote_sha"] = sha
    outcome["state"] = "PUSHED"

    scratch = Path(tempfile.mkdtemp(prefix=f"po03-ingest-{cohort}-"))
    tree = scratch / "tree"
    try:
        git("worktree", "add", "--detach", "--quiet", str(tree), sha)
        unit_dir = tree / "workstreams" / "po03" / "control" / "units" / cohort
        if not unit_dir.is_dir():
            return outcome
        for record in sorted(unit_dir.glob("*.json")):
            try:
                doc = json.loads(record.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                outcome["rejected"].append({"file": record.name, "reason": f"unparseable: {exc}"})
                continue
            if not isinstance(doc, dict) or doc.get("protocol_version") != RESULT_PROTOCOL:
                continue  # canaries and scratch files are not results
            outcome["results_found"] += 1
            unit_id = doc.get("task_id", record.stem)
            try:
                admitted = CP.ingest_result(doc, artifact_root=tree)
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
        git("worktree", "remove", "--force", str(tree), check=False)
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
