#!/usr/bin/env python3
"""Run cohort a6's read-back audit against this cohort's own result records.

    python3 -I workstreams/po03/successor/audit_own_records.py --write
    python3 -I workstreams/po03/successor/audit_own_records.py --verify-invariant

Why audit ourselves
-------------------
Lesson L-08 says a result record has to be readable at the immutable locator it
declares, and G2's change C-09 enforces it.  a6 found five records across three
other cohorts that failed that test.  The obvious question is whether this
cohort's own records pass, and the honest way to answer it is to run the same
check rather than to assume the answer.

They do not.  ``make_result.py`` resolves ``result_commit_id`` to HEAD at the
moment it writes the record, which is necessarily before the record itself is
committed, so the declared commit can never contain it.  That is a defect in
coordinator-owned tooling this cohort must not modify, and it is exactly the
failure mode C-09 refuses - reproduced from the inside, on our own records, by
following the protocol as instructed rather than by attacking anything.

Two distinct outcomes are separated below, because they are not equally bad:

ABSENT_AT_DECLARED_COMMIT   the record does not exist at the commit it names.
                            Recoverable: the artifacts verify, and the record is
                            at a later commit on the same branch.
STALE_AT_DECLARED_COMMIT    a record does exist at the declared commit, but its
                            bytes differ from the current record. Worse, because
                            the locator resolves and returns the wrong answer, so
                            a verifier that checks existence and stops is misled.

Artifact verification is reported separately, since that is the part the protocol
does get right: every artifact is expected to read back byte-exact at the commit
its own content_uri names.

Why the written document is a snapshot and not a checkable digest
-----------------------------------------------------------------
This audit describes result records, and result records cite this audit.  Pinning
the document by re-deriving it and demanding byte-equality would therefore be a
check on a cycle: re-recording any unit moves that unit's declared commit, and a
unit re-recorded a second time moves from ABSENT to STALE, because by then a
record does exist at the commit it names.  So the document is written once as an
observation at a stated commit, and ``--verify-invariant`` checks the two claims
that do not depend on when it was written:

  every artifact claim reads back byte-exact at the commit its content_uri names
  no record of this cohort resolves to its own bytes at its declared commit

The second reads backwards - it asserts the defect is still present.  That is
deliberate.  If ``make_result.py`` is ever repaired, this exits non-zero and says
so, which is the signal to refresh the snapshot and revisit L-08 rather than to
leave a stale claim standing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PO03 = Path(__file__).resolve().parents[1]
REPO_ROOT = PO03.parents[1]
UNITS_DIR = PO03 / "control" / "units" / "a8"
TARGET = PO03 / "successor" / "self-readback-audit.json"
RECORD_PREFIX = "workstreams/po03/control/units/a8"


def head_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def git_bytes(revision: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "cat-file", "blob", f"{revision}:{path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def parse_locator(uri: str) -> tuple[str, str]:
    """``git:<branch>@<commit>:<path>`` -> (commit, path)."""
    if not uri.startswith("git:"):
        raise ValueError(f"unrecognised locator: {uri}")
    locator, _, path = uri[len("git:") :].partition(":")
    return locator.split("@", 1)[1], path


def classify(at_declared: bytes | None, current: bytes) -> str:
    """Decide what a locator did when it was resolved.

    Kept separate from the git plumbing so all three outcomes are reachable in a
    test. Only two of them occur in this cohort's records today, and the third is
    the one that would mean the defect was fixed.
    """
    if at_declared is None:
        return "ABSENT_AT_DECLARED_COMMIT"
    if at_declared == current:
        return "RESOLVES_TO_THIS_RECORD"
    return "STALE_AT_DECLARED_COMMIT"


def audit_unit(unit_id: str) -> dict:
    record_path = f"{RECORD_PREFIX}/{unit_id}.json"
    current = (UNITS_DIR / f"{unit_id}.json").read_bytes()
    document = json.loads(current)
    declared_commit = document["result_transaction"]["result_commit_id"]

    artifacts = []
    for artifact in document["artifacts"]:
        commit, path = parse_locator(artifact["content_uri"])
        data = git_bytes(commit, path)
        artifacts.append(
            {
                "path": path,
                "declared_commit": commit,
                "present": data is not None,
                "sha256_matches": data is not None and hashlib.sha256(data).hexdigest() == artifact["sha256"],
                "bytes_match": data is not None and len(data) == artifact["bytes"],
            }
        )

    at_declared = git_bytes(declared_commit, record_path) if declared_commit else None
    finding = classify(at_declared, current)

    return {
        "unit_id": unit_id,
        "obzio_state": document["obzio_state"],
        "declared_result_commit_id": declared_commit,
        "record_path": record_path,
        "record_finding": finding,
        "artifact_count": len(artifacts),
        "artifacts_verified": sum(
            1 for entry in artifacts if entry["present"] and entry["sha256_matches"] and entry["bytes_match"]
        ),
        "artifacts": artifacts,
    }


def build_document() -> dict:
    unit_ids = sorted(path.stem for path in UNITS_DIR.glob("a8-u*.json"))
    units = [audit_unit(unit_id) for unit_id in unit_ids]

    findings: dict[str, list[str]] = {}
    for unit in units:
        findings.setdefault(unit["record_finding"], []).append(unit["unit_id"])

    artifact_total = sum(unit["artifact_count"] for unit in units)
    artifact_verified = sum(unit["artifacts_verified"] for unit in units)

    return {
        "document_id": "po03-a8-self-readback-audit-v001",
        "unit_id": "a8-u06",
        "owner": "po03-worker-a8",
        "generated_by": "workstreams/po03/successor/audit_own_records.py",
        "method": (
            "For each of this cohort's result records: resolve every artifact at the commit its own "
            "content_uri names and compare digest and byte count, then test whether the record itself "
            "is readable at its declared result_commit_id and whether the bytes there are the current "
            "record. This is the check cohort a6 applied to other cohorts, turned inward."
        ),
        "lesson": "L-08",
        "mechanism_that_would_refuse_this": "C-09",
        "observed_at_commit": head_commit(),
        "snapshot_semantics": (
            "An observation of the records as they stood at observed_at_commit, not a digest to be "
            "re-derived. Records cite this audit and this audit describes records, so re-recording a "
            "unit necessarily moves it: its declared commit changes, and a unit recorded a second time "
            "moves from ABSENT to STALE because by then a record does exist at the commit it names. "
            "The claims that hold regardless of when this was written are checked by "
            "`audit_own_records.py --verify-invariant` and pinned by "
            "test_a8_lessons.SelfReadbackTests."
        ),
        "aggregate": {
            "records_audited": len(units),
            "artifact_claims_audited": artifact_total,
            "artifacts_verified": artifact_verified,
            "artifact_verification_failures": artifact_total - artifact_verified,
            "records_absent_at_declared_commit": len(findings.get("ABSENT_AT_DECLARED_COMMIT", [])),
            "records_stale_at_declared_commit": len(findings.get("STALE_AT_DECLARED_COMMIT", [])),
            "records_resolving_to_themselves": len(findings.get("RESOLVES_TO_THIS_RECORD", [])),
            "result": "DISCREPANCY_FOUND"
            if findings.get("ABSENT_AT_DECLARED_COMMIT") or findings.get("STALE_AT_DECLARED_COMMIT")
            else "CLEAN",
        },
        "findings_by_class": {key: sorted(value) for key, value in sorted(findings.items())},
        "root_cause": (
            "workstreams/po03/tools/make_result.py resolves result_commit_id to HEAD at the moment it "
            "writes the record (line 127, `commit if committed else None`), which is necessarily before "
            "that record is committed. No sequence of correct operator behaviour can make the declared "
            "commit contain the record, so this is a property of the tool and not of how it was used."
        ),
        "why_not_fixed_here": (
            "workstreams/po03/tools/make_result.py is coordinator-owned and strictly read-only for this "
            "cohort. The defect is reported with a reproducer rather than patched."
        ),
        "proposed_repair": (
            "Either declare the locator after committing the record - write the record, commit, then "
            "rewrite result_commit_id to the new HEAD and amend, which is a two-phase commit - or "
            "declare the locator as branch-relative and require the parent to resolve the record at the "
            "branch head rather than at a fixed commit. C-09 in G2 takes the second form: the locator is "
            "a name that must resolve to the submitted bytes, and admission fails if it does not."
        ),
        "impact": (
            "Artifact bytes are independently recoverable at the declared commits, so no evidence is "
            "lost. What is not true is the stronger claim the protocol appears to make: that a result "
            "record is self-locating from its own declared commit. A parent ingesting these records must "
            "resolve them at the branch head."
        ),
        "units": units,
    }


def verify_invariant() -> int:
    """Check the two claims that do not depend on when the snapshot was written."""
    document = build_document()
    units = document["units"]
    aggregate = document["aggregate"]

    unverified = [
        f"{unit['unit_id']}:{entry['path']}"
        for unit in units
        for entry in unit["artifacts"]
        if not (entry["present"] and entry["sha256_matches"] and entry["bytes_match"])
    ]
    for name in unverified:
        print(f"FAIL artifact does not read back at its declared commit: {name}")

    resolving = [unit["unit_id"] for unit in units if unit["record_finding"] == "RESOLVES_TO_THIS_RECORD"]
    for unit_id in resolving:
        print(
            f"REVISIT {unit_id}: this record now resolves to its own bytes at its declared commit, "
            "so make_result.py was repaired. Refresh self-readback-audit.json and revisit L-08."
        )

    if unverified:
        print(f"INVARIANT BROKEN: {len(unverified)} of {aggregate['artifact_claims_audited']} artifact claims")
        return 1
    if resolving:
        return 2
    print(
        f"INVARIANT HOLDS: {aggregate['artifacts_verified']}/{aggregate['artifact_claims_audited']} "
        f"artifact claims read back byte-exact, and {aggregate['records_audited']}/"
        f"{aggregate['records_audited']} records still fail to resolve at their declared commit "
        f"({aggregate['records_absent_at_declared_commit']} absent, "
        f"{aggregate['records_stale_at_declared_commit']} stale)"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--verify-invariant", dest="verify", action="store_true")
    args = parser.parse_args()

    if args.verify:
        return verify_invariant()

    document = build_document()
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    TARGET.write_text(text, encoding="utf-8")
    aggregate = document["aggregate"]
    print(f"WROTE {TARGET}")
    print(
        f"{aggregate['records_audited']} records, "
        f"{aggregate['artifacts_verified']}/{aggregate['artifact_claims_audited']} artifact claims verified, "
        f"{aggregate['records_absent_at_declared_commit']} absent and "
        f"{aggregate['records_stale_at_declared_commit']} stale at their declared commit: "
        f"{aggregate['result']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
