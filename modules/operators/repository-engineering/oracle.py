"""Independent acceptance oracle for repository-engineering.

DOES NOT IMPORT engine.py OR transport.py.

This is the strongest of the five oracles, because the expected result is not
a matter of judgement at all. If you intend to write bytes B to path P, then
the remote must afterwards return bytes whose SHA-256 is sha256(B). The
acceptor can compute that from the inputs alone, with hashlib, before any
branch exists -- and it is the same number no matter who computes it or how.

That makes the comparison meaningful in a way the other packs' cannot quite
match: the acceptor is not re-running the producer's logic and agreeing with
itself, it is checking an externally-fixed arithmetic fact.
"""

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obzio_spine.expectation import Expectation, Derivation, canonical_digest

COVERS = ("paths", "expected_digests", "branch", "base", "branch_differs_from_base",
          "pr_head", "pr_base", "pr_merged", "pr_state", "all_readback_verified",
          "file_count")

UNCOVERED = (
    "whether the file CONTENT is correct, useful, or safe",
    "whether the change should be made at all",
    "server-side branch protection or required status checks",
    "whether a human should approve the PR",
)


def inputs_digest(branch, files, base, pr_title) -> str:
    return canonical_digest({
        "branch": branch, "base": base, "pr_title": pr_title,
        "files": {p: hashlib.sha256(bytes(c)).hexdigest()
                  for p, c in sorted(files.items())}})


def derive_expectation(branch, files, base, pr_title,
                       protected=("main", "master", "release", "production")
                       ) -> Expectation:
    """Computed from the intended bytes. No repository is contacted."""
    digests = {p: hashlib.sha256(bytes(c)).hexdigest()
               for p, c in sorted(files.items())}
    fields = {
        "paths": sorted(files),
        "file_count": len(files),
        "expected_digests": digests,
        "branch": branch,
        "base": base,
        "branch_differs_from_base": branch != base,
        "pr_head": branch,
        "pr_base": base,
        "pr_merged": False,          # this pack proposes; it never merges
        "pr_state": "open",
        "all_readback_verified": True,
    }
    return Expectation(fields=fields, derivation=Derivation.INDEPENDENT_ORACLE,
                       covers=COVERS, uncovered=UNCOVERED)


def extract_actual(run_dir: str) -> dict:
    def rd(n):
        with open(os.path.join(run_dir, n), encoding="utf-8") as f:
            return json.load(f)
    br = rd("branch_record.json")
    cr = rd("commit_record.json")
    pr = rd("pr_record.json")
    rb = rd("readback_verification.json")

    # OBSERVED digests -- what the remote actually returned, not what we hoped.
    observed = {r["path"]: r["observed_sha256"] for r in rb.get("results", [])}
    return {
        "paths": sorted(f["path"] for f in cr.get("files", [])),
        "file_count": len(cr.get("files", [])),
        "expected_digests": observed,
        "branch": br.get("branch"),
        "base": br.get("base"),
        "branch_differs_from_base": br.get("branch") != br.get("base"),
        "pr_head": pr.get("head"),
        "pr_base": pr.get("base"),
        "pr_merged": bool(pr.get("merged", False)),
        "pr_state": pr.get("state"),
        "all_readback_verified": bool(rb.get("all_verified")),
    }
