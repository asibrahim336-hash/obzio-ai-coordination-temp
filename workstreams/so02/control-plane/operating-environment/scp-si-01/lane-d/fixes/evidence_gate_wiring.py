#!/usr/bin/env python3
"""Lane D / Defect 2 — a hash-valid artifact that does not parse still passes closure.

## The defect, DIRECTLY_REPRODUCED

`evidence_integrity.verify_artifact_validity` already exists and does exactly
what its docstring claims: it loads every `.json` path and reports a finding
if the bytes do not parse. It is DIRECTLY_REPRODUCED to work correctly in
isolation (see `evidence/DEFECT-2-TRANSCRIPT.txt`).

The gap is one level up. `write_admission.check_evidence_gate`'s
`MANIFEST_CLOSURE` branch calls only `evidence_integrity.verify_manifest_closure`:

    if kind == "MANIFEST_CLOSURE":
        present = evidence.get("present_paths") or [...]
        errors = evidence_integrity.verify_manifest_closure(record, present)
        return _gate(GATE_EVIDENCE, not errors, ...)

`verify_artifact_validity` is imported into `write_admission`'s namespace
(`evidence_integrity = _load("evidence_integrity")`) but that specific
function is never called from anywhere in the gate. `verify_manifest_closure`
itself only checks (a) that every present path is a key in the manifest's
`entries` list and (b) that `bundle_sha256` is the hash of the entries list
AS WRITTEN — it never reads the referenced files from disk at all. So a
truncated JSON artifact, correctly hashed and correctly listed, passes the
evidence gate exactly as described: "a lane published truncated JSON whose
digest matched its manifest exactly and passed closure."

`test_the_unpatched_gate_wrongly_admits_a_truncated_artifact` in the extended
`test_write_admission.py` reproduces this against the real, unmodified
`write_admission.admit`.

## The mechanism change

`check_evidence_gate_with_artifact_validity` below is `write_admission
.check_evidence_gate`'s exact MANIFEST_CLOSURE branch, plus one additional
call this lane adds:

    errors += evidence_integrity.verify_artifact_validity(present, repo)

Nothing else changes: the READBACK branch, the "no result asserted" early
return, and the unknown-kind refusal are untouched. This is proposed as
`patches/write_admission.py.patch`.

## DEF-05 / DEF-16, applied here

"Verify each artifact at its own commit, then compare against branch tip to
flag supersession. Neither root alone is correct." `verify_artifact_at_commit`
recomputes an artifact's bytes AT THE COMMIT the evidence claims (never trusts
the working tree), and separately fetches the SAME path at the branch tip; a
difference is reported as `SUPERSEDED_AT_TIP` rather than silently ignored or
treated as failure. This is additive — `write_admission` has no commit-scoped
verification today, so this is new capability honouring the structural
finding rather than a patch to an existing function.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


def _load(name: str, relative: str):
    repo_root = Path(__file__).resolve().parents[7]
    path = repo_root / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


evidence_integrity = _load(
    "evidence_integrity_canonical",
    "workstreams/so02/control-plane/operating-environment/tools/evidence_integrity.py",
)
write_declaration = _load(
    "write_declaration_canonical",
    "workstreams/so02/control-plane/operating-environment/tools/write_declaration.py",
)


def _gate(name: str, passed: bool, verdict: str, findings: list[str], **extra) -> dict[str, Any]:
    return {"gate": name, "passed": passed, "verdict": verdict, "findings": findings, **extra}


def check_evidence_gate_with_artifact_validity(
    declaration: dict[str, Any], repo: Path | None, remote_url: str | None = None
) -> dict[str, Any]:
    """`write_admission.check_evidence_gate`, plus the missing validity call.

    Byte-for-byte the same control flow for every branch except
    MANIFEST_CLOSURE, where `verify_artifact_validity` is now run over the
    same `present` paths `verify_manifest_closure` was already given.
    """
    reason = declaration.get("reason") or {}
    spec = write_declaration.REASON_VOCABULARY.get(reason.get("code"))
    evidence = declaration.get("evidence") or {}
    asserts = bool(evidence.get("asserts_result")) or bool(spec and spec.asserts_result)

    if not asserts:
        return _gate("evidence", True, "NO_RESULT_ASSERTED", [],
                     note="the gate expires with its reason; a write asserting no result owes no evidence")

    kind, record = evidence.get("kind"), evidence.get("record")
    if not isinstance(record, dict) or not record:
        return _gate("evidence", False, "EVIDENCE_ABSENT",
                     [f"reason {reason.get('code')} asserts a result but carries no record to recompute"])

    if kind == "MANIFEST_CLOSURE":
        present = evidence.get("present_paths") or [e.get("path") for e in record.get("entries", [])]
        errors = list(evidence_integrity.verify_manifest_closure(record, present))
        # The mechanism change: DEF-SCP-D-02. A hash-bound artifact that is
        # not parseable JSON was never checked here before this lane.
        errors += evidence_integrity.verify_artifact_validity(present, repo or Path("."))
        return _gate("evidence", not errors,
                     "EVIDENCE_RECOMPUTED" if not errors else "EVIDENCE_FAILED_RECOMPUTATION",
                     errors,
                     verified_by="evidence_integrity.verify_manifest_closure "
                                 "+ evidence_integrity.verify_artifact_validity (SCP-D DEF-SCP-D-02)")

    if kind == "READBACK":
        if not remote_url:
            return _gate("evidence", False, "EVIDENCE_UNVERIFIABLE_HERE",
                         ["a READBACK record can only be recomputed against a remote; none was supplied, "
                          "so the claim is unverified and an unverified assertion is refused"],
                         verified_by="evidence_integrity.verify_readback_truth (not run)")
        errors = evidence_integrity.verify_readback_truth(record, remote_url, repo or Path("."))
        return _gate("evidence", not errors,
                     "EVIDENCE_RECOMPUTED" if not errors else "EVIDENCE_FAILED_RECOMPUTATION",
                     errors, verified_by="evidence_integrity.verify_readback_truth")

    return _gate("evidence", False, "EVIDENCE_KIND_UNKNOWN",
                 [f"evidence.kind {kind!r} has no recomputation route, so it cannot be verified"])


# ---------------------------------------------------------------------------
# DEF-05 / DEF-16 — verify at commit, then compare to branch tip
# ---------------------------------------------------------------------------

def _run(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return done.returncode, done.stdout, done.stderr


def verify_artifact_at_commit(repo: Path, path: str, commit: str) -> dict[str, Any]:
    """Read `path` as git stored it at `commit`, never the working tree.

    DEF-05 half: an artifact is evidence for the commit it was produced at,
    not for whatever the working tree or branch tip happens to hold now.
    """
    code, blob, err = _run(["git", "cat-file", "-p", f"{commit}:{path}"], cwd=repo)
    if code != 0:
        return {
            "path": path, "commit": commit, "present_at_commit": False,
            "detail": err.strip(),
        }
    return {
        "path": path, "commit": commit, "present_at_commit": True,
        "sha256": evidence_integrity.sha256_bytes(blob.encode("utf-8")),
        "bytes": len(blob.encode("utf-8")),
    }


def compare_to_branch_tip(repo: Path, path: str, commit: str, branch_ref: str) -> dict[str, Any]:
    """DEF-16 half: the same path, compared at the commit versus the branch tip.

    Chain validity at `commit` says nothing about whether `branch_ref` has
    since carried a different version of the same evidence path. A
    difference is reported as supersession, not silently accepted and not
    treated as a failure of the commit-scoped verification, which remains
    correct for the commit it verified.
    """
    at_commit = verify_artifact_at_commit(repo, path, commit)
    code, tip_sha, _ = _run(["git", "rev-parse", branch_ref], cwd=repo)
    tip_sha = tip_sha.strip() if code == 0 else None
    at_tip = verify_artifact_at_commit(repo, path, branch_ref) if tip_sha else {
        "path": path, "commit": branch_ref, "present_at_commit": False,
        "detail": "branch_ref did not resolve",
    }

    if tip_sha == commit:
        verdict = "COMMIT_IS_TIP_NO_SUPERSESSION_POSSIBLE"
    elif not at_tip.get("present_at_commit"):
        verdict = "PATH_ABSENT_AT_TIP"
    elif not at_commit.get("present_at_commit"):
        verdict = "PATH_ABSENT_AT_VERIFIED_COMMIT"
    elif at_commit.get("sha256") == at_tip.get("sha256"):
        verdict = "UNCHANGED_AT_TIP"
    else:
        verdict = "SUPERSEDED_AT_TIP"

    return {
        "path": path,
        "verified_commit": commit,
        "branch_ref": branch_ref,
        "branch_tip_sha": tip_sha,
        "at_commit": at_commit,
        "at_tip": at_tip,
        "verdict": verdict,
        "note": (
            "Neither root alone is correct (DEF-05/DEF-16): at_commit is the only "
            "thing the evidence gate may rely on for THIS write's admission; "
            "verdict is a disclosure about drift since, not a re-litigation of it."
        ),
    }


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("supersession")
    s.add_argument("repo")
    s.add_argument("path")
    s.add_argument("commit")
    s.add_argument("--branch-ref", default="HEAD")

    args = parser.parse_args()
    if args.cmd == "supersession":
        result = compare_to_branch_tip(Path(args.repo), args.path, args.commit, args.branch_ref)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
