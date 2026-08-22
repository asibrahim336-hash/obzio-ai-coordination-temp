"""One-sided acceptance oracle for independent-acceptance.

DOES NOT IMPORT engine.py (the review engine) OR fence.py.

WHAT THE ACCEPTOR OF A REVIEW MAY LOOK AT
-----------------------------------------
Note which thing is hidden. The acceptor of a review is REQUIRED to read the
SUBJECT -- that is its input, and it must form its own view of whether the
subject is sound. What it must not see, until it has committed, is the
REVIEW'S OWN OUTPUT: the findings, the verdict, the scope record. Those are
the artefacts under `artefact_names`, and the machine's anchoring check
covers exactly them.

WHY THIS ORACLE IS ONE-SIDED -- the honest limit
------------------------------------------------
A fully independent expectation of a verdict would require re-deriving every
probe: reimplementing the reviewer. Two copies of the same probe list are not
two opinions.

So this oracle derives only a LOWER BOUND on strictness. It independently
detects structural defects in the subject that no competent review could
miss -- absent return_state, a run that never completed, a self-reviewed
subject, an acceptance digest that does not bind the artefacts present. If any
of those exist, the verdict MUST be REJECT, and a review saying ACCEPT
diverges.

  * It CATCHES a false ACCEPT over a structurally broken subject.
  * It CANNOT catch a false REJECT, and it cannot catch a subject that is
    structurally clean but substantively wrong.

The false-ACCEPT direction is the one that matters here: a rubber-stamping
reviewer is the failure mode, and a reviewer that wrongly rejects is merely
annoying. But "one-sided" must be read as one-sided, not as coverage.
"""

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obzio_spine.expectation import Expectation, Derivation, canonical_digest

COVERS = ("subject_structurally_sound", "verdict_at_least_as_strict_as_structure",
          "reviewer_is_not_subject_producer", "all_findings_evidenced",
          "accept_implies_no_blocking", "subject_root")

UNCOVERED = (
    "whether the review found every defect that is really there",
    "whether a structurally clean subject is substantively correct",
    "a false REJECT (this oracle bounds strictness from below only)",
    "the specific findings the review should have raised",
)


def _read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return json.load(f)


def independent_structural_scan(subject_root: str, required_artefacts) -> dict:
    """Detect defects no competent review could miss. Plain json + os only."""
    defects = []
    rs_path = os.path.join(subject_root, "return_state.json")
    if not os.path.exists(rs_path):
        defects.append("no_return_state")
    else:
        rs = _read(subject_root, "return_state.json")
        if rs.get("final_state") != "COMPLETE":
            defects.append("run_not_complete")
        if rs.get("verdict") != "ACCEPT":
            defects.append("subject_verdict_not_accept")
        if not rs.get("accepted_run_digest"):
            defects.append("no_accepted_digest")
        if rs.get("producer_id") and rs.get("producer_id") == rs.get("reviewer_id"):
            defects.append("subject_self_reviewed")

    for rel in required_artefacts:
        p = os.path.join(subject_root, rel)
        if not os.path.exists(p):
            defects.append(f"missing:{rel}")
        elif os.path.getsize(p) == 0:
            defects.append(f"empty:{rel}")

    cr_path = os.path.join(subject_root, "check_report.json")
    if os.path.exists(cr_path):
        cr = _read(subject_root, "check_report.json")
        if cr.get("passed") and cr.get("failure_count", 0) > 0:
            defects.append("check_report_self_contradictory")
    else:
        defects.append("no_check_report")

    return {"sound": not defects, "defects": sorted(defects)}


def inputs_digest(subject_root, required_artefacts, reviewer_id) -> str:
    scan = independent_structural_scan(subject_root, required_artefacts)
    return canonical_digest({"subject_root": os.path.realpath(subject_root),
                             "required": sorted(required_artefacts),
                             "reviewer_id": reviewer_id,
                             "structural_scan": scan})


def derive_expectation(subject_root, required_artefacts, reviewer_id) -> Expectation:
    scan = independent_structural_scan(subject_root, required_artefacts)
    fields = {
        "subject_root": os.path.realpath(subject_root),
        "subject_structurally_sound": scan["sound"],
        # Invariants committed before the review's output is visible.
        "verdict_at_least_as_strict_as_structure": True,
        "reviewer_is_not_subject_producer": True,
        "all_findings_evidenced": True,
        "accept_implies_no_blocking": True,
    }
    return Expectation(fields=fields, derivation=Derivation.PARTIAL_ORACLE,
                       covers=COVERS, uncovered=UNCOVERED)


def extract_actual(run_dir: str, subject_root: str, required_artefacts) -> dict:
    def rd(n):
        return _read(run_dir, n)
    scope = rd("review_scope.json")
    findings = rd("findings.json")
    verdict = rd("verdict.json")

    # Re-scan the subject independently. If it changed since the commitment,
    # this diverges too -- a free tamper check.
    scan = independent_structural_scan(subject_root, required_artefacts)
    v = verdict.get("verdict")
    blocking = [f for f in findings if f.get("severity") == "BLOCKING"]

    return {
        "subject_root": os.path.realpath(subject_root),
        "subject_structurally_sound": scan["sound"],
        # The one-sided rule: an unsound subject MUST have been rejected.
        "verdict_at_least_as_strict_as_structure": (
            True if scan["sound"] else v == "REJECT"),
        "reviewer_is_not_subject_producer": (
            scope.get("reviewer_id") != scope.get("subject_producer_id")),
        "all_findings_evidenced": all(f.get("evidence") for f in findings),
        "accept_implies_no_blocking": (v != "ACCEPT") or (not blocking),
    }
