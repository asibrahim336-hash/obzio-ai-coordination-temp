#!/usr/bin/env python3
"""Lane D — DEF-SCP-01, routed to lane D by the coordinator.

`workstreams/so02/control-plane/operating-environment/scp-si-01/
DEFECT-SCP-01-SUPERSESSION-READS-AS-TAMPERING.json` (published on the
integration branch at commit f0fb3f51, `routing.owning_lane: "D"`):
`currentctl.check_reproducibility`'s `COMMITTED_ARTIFACT_HASH` branch emits
`EVIDENCE_HASH_MISMATCH` whenever a recorded sha256 does not match the
CURRENT bytes of the named path, with no way to tell "this evidence was
altered" (an integrity incident) apart from "this evidence moved on since it
was recorded" (routine and expected — e.g. the EC-13 purge at `3b97d6ff`
legitimately rewrote `scctl.py` after the ledger recorded its earlier hash).
This is the packet's DEF-05/DEF-16 diagnosis reproducing live: "verify each
artifact at its own commit, then compare against branch tip to flag
supersession; neither root alone is correct."

## The defect, DIRECTLY_REPRODUCED

`test_case_2_and_case_3_are_indistinguishable_in_the_unmodified_checker` (in
the extended `l4-currentness-recovery/tests/test_currentctl.py`) builds a
real git repository and shows the shipped `currentctl.check_reproducibility`
emitting the IDENTICAL finding code, `EVIDENCE_HASH_MISMATCH`, for two
situations the finding document says demand opposite responses:

  * Case 2 — SUPERSESSION: the recorded hash was correct at the commit the
    ledger entry was taken at; the file has since legitimately changed.
  * Case 3 — TAMPERING: the recorded hash was never correct, even at its own
    recorded commit.

## The mechanism change

`check_artifact_hash_with_supersession` reimplements just the
`COMMITTED_ARTIFACT_HASH` / `REMOTE_READBACK_HASH`-style artifact branch of
`check_reproducibility`, requiring a THIRD field per the finding's own
specification — `artifact_commit`, the commit the recorded sha256 was taken
at — and produces the three-way split the finding requires:

  * no (or malformed) `artifact_commit`         -> EVIDENCE_ANCHOR_MISSING (ERROR)
  * hash wrong even at its own recorded commit  -> EVIDENCE_HASH_MISMATCH (ERROR)
  * hash right at its commit, changed by tip    -> EVIDENCE_SUPERSEDED (INFO)
  * hash right at its commit, unchanged at tip  -> no finding

This reuses `evidence_gate_wiring.verify_artifact_at_commit` (built for
Defect 2 / DEF-05-DEF-16) rather than reimplementing commit-scoped hashing a
second time in this same lane.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any


def _load(name: str, relative: str):
    repo_root = Path(__file__).resolve().parents[7]
    path = repo_root / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


evidence_gate_wiring = _load(
    "evidence_gate_wiring_reused",
    "workstreams/so02/control-plane/operating-environment/scp-si-01/lane-d/fixes/evidence_gate_wiring.py",
)

OID_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ANCHOR_MISSING = "EVIDENCE_ANCHOR_MISSING"
HASH_MISMATCH = "EVIDENCE_HASH_MISMATCH"
SUPERSEDED = "EVIDENCE_SUPERSEDED"
ERROR = "ERROR"
INFO = "INFO"


def check_artifact_hash_with_supersession(
    entry: dict[str, Any], repo: Path, branch_ref: str = "HEAD"
) -> dict[str, Any] | None:
    """Returns a finding dict, or None when the entry is clean.

    Mirrors `currentctl.Finding`'s shape closely enough to be a drop-in
    replacement for the `EVIDENCE_HASH_MISMATCH`-only branch it patches.
    """
    path = entry.get("artifact_path")
    digest = entry.get("sha256")
    commit = entry.get("artifact_commit")

    if not commit or not OID_RE.fullmatch(str(commit)):
        return {
            "code": ANCHOR_MISSING,
            "severity": ERROR,
            "detail": (
                f"{path} carries a sha256 with no artifact_commit recording where it was "
                "taken; supersession and tampering cannot be distinguished without one"
            ),
        }

    at_commit = evidence_gate_wiring.verify_artifact_at_commit(repo, path, commit)
    if not at_commit.get("present_at_commit"):
        return {
            "code": HASH_MISMATCH,
            "severity": ERROR,
            "detail": f"{path} is not present at its own recorded commit {commit}: {at_commit.get('detail')}",
        }
    if at_commit.get("sha256") != digest:
        return {
            "code": HASH_MISMATCH,
            "severity": ERROR,
            "detail": (
                f"{path} hashes to {at_commit.get('sha256')} at its own recorded commit "
                f"{commit}, evidence claims {digest}; the hash was wrong even at its own "
                "anchor, which a later change cannot explain"
            ),
        }

    comparison = evidence_gate_wiring.compare_to_branch_tip(repo, path, commit, branch_ref)
    if comparison["verdict"] == "SUPERSEDED_AT_TIP":
        return {
            "code": SUPERSEDED,
            "severity": INFO,
            "detail": (
                f"{path} was correctly hashed at {commit} and has legitimately changed by "
                f"{branch_ref}; re-anchor the ledger entry to the new commit rather than "
                "treating this as an integrity incident"
            ),
        }
    if comparison["verdict"] == "PATH_ABSENT_AT_TIP":
        return {
            "code": SUPERSEDED,
            "severity": INFO,
            "detail": f"{path} was correctly hashed at {commit} and has since been removed by {branch_ref}",
        }
    return None


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("path")
    parser.add_argument("sha256")
    parser.add_argument("artifact_commit")
    parser.add_argument("--branch-ref", default="HEAD")
    args = parser.parse_args()

    finding = check_artifact_hash_with_supersession(
        {"artifact_path": args.path, "sha256": args.sha256, "artifact_commit": args.artifact_commit},
        Path(args.repo), args.branch_ref,
    )
    print(json.dumps(finding or {"code": "CLEAN"}, indent=2))
    sys.exit(0 if not finding or finding["severity"] != ERROR else 1)
