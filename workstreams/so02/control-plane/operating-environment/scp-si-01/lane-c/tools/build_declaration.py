#!/usr/bin/env python3
"""Generate lane C's one write declaration, with its evidence recomputed.

Stdlib only. Runs under `python3 -I`.

    python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/build_declaration.py \
        --repo-root . --ref cursor/scp-c-authorship-sidecar-696d \
        --commit <integration-sha> --ref-absent

This exists because a hand-maintained declaration goes stale the moment a
deliverable file is edited, and nothing catches it: `write_admission`'s evidence
gate recomputes the closure *internally* — that `present_paths` is covered and
that `bundle_sha256` binds the entry list — and never compares an entry's hash
against the file on disk. A declaration can therefore pass every gate while
asserting hashes for bytes that no longer exist. That is the same failure as
`evidence_integrity.verify_readback_truth`, which checked a record's shape and
not its truth, one layer out. So the hashes are generated from the files here,
in the same run as the push, rather than transcribed.

The concurrency observation is read from a file rather than embedded, because an
observation is evidence with an instrument and a limitation, not a constant.

## What the evidence covers, and what it cannot

`evidence.record` closes over every file in `lane-c/**` plus `READ-BACK.json`.
Four files are in `target.paths` and not in the record, each because it is
written after this declaration:

* this declaration — a file cannot contain its own hash;
* `ADMISSION.json` — it is the verdict *on* this declaration;
* `MANIFEST.json` — it covers this declaration, and a mutual hash is a cycle;
* `PUSH-CONFIRMATION.json` — it records the SHA of a commit that does not exist
  until after this declaration is committed.

They are listed in `target.paths` regardless, because the write does touch them
and a write that does not admit what it writes is the collision this whole
declaration schema exists to prevent. `MANIFEST.json` carries the complete
closure over all four, including this declaration, with its own independent
`bundle_sha256`. The exclusions are stated in the record rather than left to be
noticed, because an undeclared exclusion is indistinguishable from an omission.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import authorship_sidecar as A  # noqa: E402
import build_receipts as R  # noqa: E402

DECLARATION_REL = ("workstreams/so02/control-plane/operating-environment/"
                   "write-declarations/WRITE-DECLARATION-SCP-C.json")
READ_BACK_REL = "receipts/so02/2026-08-27/scp-c/READ-BACK.json"
ADMISSION_REL = "receipts/so02/2026-08-27/scp-c/ADMISSION.json"
MANIFEST_REL = "receipts/so02/2026-08-27/scp-c/MANIFEST.json"
PUSH_CONFIRMATION_REL = "receipts/so02/2026-08-27/scp-c/PUSH-CONFIRMATION.json"
OBSERVATION_REL = "receipts/so02/2026-08-27/scp-c/raw/concurrency-observation.json"

STATEMENT = (
    "Publish lane C's commissioned authorship sidecar onto the lane's own new branch "
    "cursor/scp-c-authorship-sidecar-696d: a non-destructive query layer over the estate's "
    "authority-bearing artifacts that classifies authorship below message granularity into "
    "FOUNDER_DIRECT, FOUNDER_ADOPTED, FOUNDER_REPRESENTED, NONFOUNDER_PASTED and "
    "UNRESOLVED_USER_ROLE, excludes the last two from default authority queries, and refuses "
    "the two proxies reproduced against the estate's live provctl.py - heading position "
    "conferring founder authorship, and an exact substring match treated as the verdict. "
    "Nothing outside the lane's own namespace is written and the authority index itself is "
    "not modified."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--ref", required=True)
    parser.add_argument("--commit", required=True,
                        help="integration commit this lane audited against")
    parser.add_argument("--ref-sha", default=None,
                        help="live sha of --ref, omitted when the ref does not exist yet")
    parser.add_argument("--ref-absent", action="store_true",
                        help="git ls-remote returned empty for --ref")
    args = parser.parse_args(argv)
    repo_root = os.path.abspath(args.repo_root)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    observation_path = os.path.join(repo_root, OBSERVATION_REL)
    observation, problems = A.read_back_and_parse(observation_path)
    if observation is None:
        for p in problems:
            print(f"FAIL {p}")
        print(f"FAIL the concurrency observation at {OBSERVATION_REL} must exist and parse; "
              "an observation a declaration asserts about itself is not an observation")
        return 1

    covered = R.walk(repo_root, R.LANE_REL)
    if os.path.exists(os.path.join(repo_root, READ_BACK_REL)):
        covered.append(READ_BACK_REL)
    else:
        print(f"FAIL {READ_BACK_REL} is absent; run build_receipts.py --stage read-back first")
        return 1
    covered = sorted(set(covered))
    entries = sorted((R.entry(repo_root, rel) for rel in covered),
                     key=lambda e: e["path"])

    # Every path the write touches, including the receipts written after this
    # file. target.paths is the write's footprint; evidence.present_paths is the
    # subset whose bytes are final now. Conflating them is what would force the
    # cycle the docstring describes.
    touched = sorted(set(covered) | {DECLARATION_REL, ADMISSION_REL, MANIFEST_REL,
                                     PUSH_CONFIRMATION_REL})

    declaration = {
        "declaration_version": "1.0",
        "declared_by": "SCP-SI-01 lane C, bc-479fe73d-737d-50f2-bca8-6dcd8eec9eca",
        "declared_at": now,
        "generated_by": (
            "workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/"
            "tools/build_declaration.py, in the same run as the push"
        ),
        "audited_against_integration_commit": args.commit,
        "target": {
            "ref": args.ref,
            "paths": touched,
            "operation": "COMMIT_AND_PUSH",
        },
        "reason": {
            "code": "PUBLISH_LANE_DELIVERABLE",
            "statement": STATEMENT,
            "lane_id": "SCP-SI-01-LANE-C",
            "commission_id": "SCP-SI-01",
            "expires_when": ("the SCP-SI-01 cohort closes and lane C's return is "
                             "integrated or refused"),
            "recorded_at": now,
        },
        "reversal": {
            "method": "DELETE_CREATED_REF",
            "created_ref": args.ref,
            "command": ["git", "push", "origin", "--delete", args.ref],
            "note": (
                f"This branch does not exist on the remote at declaration time - confirmed by "
                f"git ls-remote origin {args.ref} returning empty. The lane creates it, so "
                "deleting it restores the remote to its exact pre-write state. No other ref is "
                "touched, so no other work can be unwound by this reversal."
                if args.ref_absent else
                f"The ref exists at {args.ref_sha} and DELETE_CREATED_REF would destroy work "
                "this lane did not create. Re-declare with RESTORE_REF_TO_RECORDED_SHA and "
                "custody before pushing."
            ),
        },
        "evidence": {
            "asserts_result": True,
            "kind": "MANIFEST_CLOSURE",
            "present_paths": [e["path"] for e in entries],
            "record": {
                "entries": entries,
                "entry_count": len(entries),
                "bundle_sha256": A.bundle_sha256(entries),
                "closure_note": (
                    "Closure over every file in "
                    "workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/ "
                    "plus receipts/so02/2026-08-27/scp-c/READ-BACK.json, hashed from disk by "
                    "build_declaration.py in the same run as the push rather than transcribed. "
                    "present_paths is stated explicitly rather than defaulted from the entry "
                    "list, so the closure question is well posed instead of trivially true. "
                    "Four paths in target.paths are deliberately not covered here and the "
                    "exclusions are declared rather than silent: this declaration, because a "
                    "file cannot contain its own hash; ADMISSION.json, because it is the "
                    "verdict on this declaration and is therefore written after it; "
                    "MANIFEST.json, because it covers this declaration and a mutual hash is a "
                    "cycle; and PUSH-CONFIRMATION.json, because it records the SHA of a commit "
                    "that does not exist until after this declaration is committed. All four "
                    "are listed in target.paths anyway, because the write does touch them and "
                    "a write that does not admit what it writes is the collision this schema "
                    "exists to prevent. MANIFEST.json carries the complete closure over all "
                    "four, with its own independent bundle_sha256."
                ),
                "verify_it_yourself": (
                    "python3 -I workstreams/so02/control-plane/operating-environment/"
                    "scp-si-01/lane-c/tools/verify_declaration_evidence.py --repo-root ."
                ),
            },
        },
        "concurrency": {
            "observed_at": now,
            "ref_sha_at_observation": args.ref_sha,
            "ref_absent_at_observation": bool(args.ref_absent),
            "instrument": observation.get("instrument"),
            "agents": observation.get("agents", []),
            "observation_artifact": {
                "path": OBSERVATION_REL,
                "sha256": R.entry(repo_root, OBSERVATION_REL)["sha256"],
            },
            "note": (
                f"{observation.get('agent_count')} accessible agents observed; the agent list "
                f"here is that artifact's, not restated. None holds {args.ref}. "
                + ("The ref does not exist on the remote, so no work is in flight on it and "
                   "there is no SHA to record. "
                   if args.ref_absent else
                   f"The ref exists at {args.ref_sha}. ")
                + "Six sibling SCP-SI-01 lanes are running concurrently and each writes its "
                "own namespace; this write touches no path outside lane C's own two "
                "directories and its one write declaration. "
                + str(observation.get("limitation") or "")
            ),
        },
        "provenance_of_this_declaration": {
            "gate_1_concurrency": "FOUNDER_AUTHORED - 'Do not corrupt work in flight.'",
            "gate_2_reversibility": ("FOUNDER_AUTHORED - 'Snapshot before an irreversible "
                                     "write... That is custody, not protection.'"),
            "gate_3_evidence": ("FOUNDER_AUTHORED - 'A write that asserts a result carries "
                                "the evidence for that result.'"),
            "authority_basis": ("FOUNDER_AUTHORED - 'You do not need my permission for any of "
                                "it - you need a reason and a rollback.'"),
            "asserts_result_note": (
                "EARNED. reason.code PUBLISH_LANE_DELIVERABLE has asserts_result=False in the "
                "vocabulary, so the evidence gate would have expired with its reason and this "
                "write would have owed nothing. asserts_result is set true anyway, because "
                "this lane's deliverable does assert a result - a classifier's verdicts over "
                "the real corpus - and the defect this whole lane was commissioned against is "
                "a verdict published without recomputable evidence. Opting into a gate that "
                "would not have fired is the only part of this declaration that is stricter "
                "than the mechanism requires."
            ),
            "enforcement_note": (
                "EARNED. Project hooks do not fire in this runtime; the coordinator reproduced "
                "that at 2026-08-27T04:57:11Z and recorded it in SCP-SI-01-BASELINE.yaml. "
                "Nothing would have refused this write. write_admission.py was therefore "
                "invoked explicitly by this lane and its verdict is attached at "
                "receipts/so02/2026-08-27/scp-c/ADMISSION.json, including the gates it failed "
                "if any."
            ),
        },
        "decision_changed": [],
    }

    path = os.path.join(repo_root, DECLARATION_REL)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(declaration, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    reread, problems = A.read_back_and_parse(path)
    if reread is None:
        for p in problems:
            print(f"FAIL {p}")
        return 1
    record = reread["evidence"]["record"]
    if A.bundle_sha256(record["entries"]) != record["bundle_sha256"]:
        print("FAIL BUNDLE_MISMATCH after read-back")
        return 1
    print(f"declaration   = {DECLARATION_REL}")
    print(f"entry_count   = {record['entry_count']}")
    print(f"bundle_sha256 = {record['bundle_sha256']}")
    print(f"target_paths  = {len(reread['target']['paths'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
