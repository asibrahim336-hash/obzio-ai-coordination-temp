#!/usr/bin/env python3
"""Check lane C's write declaration against the bytes on disk.

Stdlib only. Runs under `python3 -I`.

    python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/verify_declaration_evidence.py \
        --repo-root .

Exits 0 when the declaration's evidence is true of this working tree.

## Why this is not redundant with the admission gate

`write_admission`'s evidence gate delegates to
`evidence_integrity.verify_manifest_closure`, which asks two questions:

* is every `present_paths` entry covered by some entry in the record?
* does `bundle_sha256` bind the entry list?

Both are answerable without opening a single declared file. So a declaration
whose recorded hashes are stale — or invented — passes the gate. That is the
shape of `verify_readback_truth`'s original defect: a record naming commit
000...0 verified because the verifier checked the record's shape and never its
truth. This tool asks the question the gate cannot: **do these hashes describe
the files that are actually there.**

It also checks the exclusions. `target.paths` names more paths than
`evidence.present_paths` covers, which is legitimate only while every gap is a
declared exclusion; an undeclared gap is indistinguishable from an omission, so
it is reported as a failure rather than a note.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import authorship_sidecar as A  # noqa: E402
import build_receipts as R  # noqa: E402
from build_declaration import (ADMISSION_REL, DECLARATION_REL, MANIFEST_REL,  # noqa: E402
                              OBSERVATION_REL, READ_BACK_REL)

#: The only paths that may appear in target.paths without a hash in the record.
#: Each is excluded because it hashes or evaluates the declaration itself; the
#: reasons are stated in the declaration's closure_note and here so that a
#: reader of either finds the same three.
DECLARED_EXCLUSIONS = frozenset({DECLARATION_REL, ADMISSION_REL, MANIFEST_REL})


def verify(repo_root: str, declaration: dict | None = None) -> list[str]:
    """Check one declaration against disk. Reads the lane's own when not supplied.

    The parameter exists so `reproduce_gate_blindness.py` can put a deliberately
    stale record through the same code the real declaration goes through, rather
    than through a second implementation that might disagree with it.
    """
    errors: list[str] = []
    if declaration is None:
        path = os.path.join(repo_root, DECLARATION_REL)
        declaration, problems = A.read_back_and_parse(path)
        if declaration is None:
            return [f"UNPARSABLE {DECLARATION_REL}: {problems}"]

    record = ((declaration.get("evidence") or {}).get("record")) or {}
    entries = record.get("entries") or []
    if not entries:
        return [f"EVIDENCE_EMPTY {DECLARATION_REL} carries no entries to recompute"]

    # 1. Every recorded hash must describe the file that is actually there.
    for e in entries:
        rel = e.get("path")
        try:
            fresh = R.entry(repo_root, rel)
        except OSError:
            errors.append(f"MISSING {rel} is hashed by the declaration but absent from disk")
            continue
        if fresh["sha256"] != e.get("sha256"):
            errors.append(f"HASH_MISMATCH {rel}: on disk {fresh['sha256']}, "
                          f"declared {e.get('sha256')}")
        if fresh["size_bytes"] != e.get("size_bytes"):
            errors.append(f"SIZE_MISMATCH {rel}: on disk {fresh['size_bytes']}, "
                          f"declared {e.get('size_bytes')}")

    # 2. bundle_sha256 must bind the entry list as constructed.
    recomputed = A.bundle_sha256(entries)
    if recomputed != record.get("bundle_sha256"):
        errors.append(f"BUNDLE_MISMATCH recomputed {recomputed}, "
                      f"declared {record.get('bundle_sha256')}")
    if len(entries) != record.get("entry_count"):
        errors.append(f"ENTRY_COUNT_MISMATCH {len(entries)} entries, "
                      f"declared {record.get('entry_count')}")

    # 3. Coverage must be complete over what is on disk now, not merely over
    #    what the declaration chose to list.
    covered = {e.get("path") for e in entries}
    present = set(R.walk(repo_root, R.LANE_REL))
    if os.path.exists(os.path.join(repo_root, READ_BACK_REL)):
        present.add(READ_BACK_REL)
    for rel in sorted(present - covered):
        errors.append(f"UNCOVERED_FILE_PRESENT {rel} exists but no entry hashes it")
    for rel in sorted(covered - present):
        errors.append(f"COVERS_ABSENT_FILE {rel} is hashed but is not in the covered scope")

    # 4. present_paths must be stated, and must be what is covered.
    stated = (declaration.get("evidence") or {}).get("present_paths")
    if stated is None:
        errors.append("PRESENT_PATHS_DEFAULTED evidence.present_paths is absent, so the gate "
                      "would default it from the entry list and the closure check becomes "
                      "trivially true")
    elif set(stated) != covered:
        errors.append(f"PRESENT_PATHS_DISAGREE stated {len(set(stated))} paths, "
                      f"entries cover {len(covered)}")

    # 5. Any gap between the write's footprint and its evidence must be declared.
    touched = set((declaration.get("target") or {}).get("paths") or [])
    for rel in sorted(touched - covered - DECLARED_EXCLUSIONS):
        errors.append(f"UNDECLARED_EXCLUSION {rel} is in target.paths, is not hashed, and is "
                      "not one of the three declared exclusions")
    for rel in sorted(DECLARED_EXCLUSIONS - touched):
        errors.append(f"EXCLUSION_NOT_DECLARED_AS_TOUCHED {rel} is excluded from the evidence "
                      "but is not listed in target.paths either, so the write does not admit "
                      "to writing it")

    # 6. The concurrency observation must be a parsable artifact, not a claim.
    obs_pin = (declaration.get("concurrency") or {}).get("observation_artifact") or {}
    observation, obs_problems = A.read_back_and_parse(
        os.path.join(repo_root, OBSERVATION_REL))
    if observation is None:
        errors.append(f"OBSERVATION_UNPARSABLE {OBSERVATION_REL}: {obs_problems}")
    else:
        try:
            fresh = R.entry(repo_root, OBSERVATION_REL)
        except OSError:
            errors.append(f"OBSERVATION_MISSING {OBSERVATION_REL}")
        else:
            if obs_pin.get("sha256") != fresh["sha256"]:
                errors.append("OBSERVATION_HASH_MISMATCH the declaration pins a different "
                              "concurrency observation than the one on disk")
        declared_agents = (declaration.get("concurrency") or {}).get("agents") or []
        if declared_agents != (observation.get("agents") or []):
            errors.append("OBSERVATION_AGENTS_DISAGREE the agent list in the declaration is "
                          "not the one in the pinned observation artifact")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    repo_root = os.path.abspath(args.repo_root)

    errors = verify(repo_root)
    for err in errors:
        print(f"FAIL {err}")
    print("declaration_evidence = "
          + ("TRUE_OF_DISK" if not errors else f"FAILED ({len(errors)} findings)"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
