"""Deterministic checks for independent-acceptance artefacts.

These check the REVIEW, not the subject. The question they answer is: is this
a real review, or a rubber stamp with a signature on it?"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from obzio_spine.artefacts import read_json
from obzio_spine.checkkit import CheckReport

REQUIRED_ARTEFACTS = [
    "review_scope.json",
    "findings.json",
    "verdict.json",
    "independence_proof.json",
]

MANDATORY_PROBES = [
    "P-01_required_artefacts",
    "P-02_return_state",
    "P-03_check_report",
    "P-04_recomputed_checks",
    "P-06_journal",
    "P-07_digest_binding",
]


def run_checks(run_dir: str) -> CheckReport:
    r = CheckReport("independent-acceptance")

    missing = [a for a in REQUIRED_ARTEFACTS
               if not os.path.exists(os.path.join(run_dir, a))]
    if missing:
        r.fail("artefacts_present", f"missing artefacts: {missing}", missing=missing)
        return r

    scope = read_json(os.path.join(run_dir, "review_scope.json"))
    findings = read_json(os.path.join(run_dir, "findings.json"))
    verdict = read_json(os.path.join(run_dir, "verdict.json"))
    proof = read_json(os.path.join(run_dir, "independence_proof.json"))

    # --- CHK-IA-01 reviewer is not the subject's producer ---------------
    if scope.get("reviewer_id") == scope.get("subject_producer_id"):
        r.fail("CHK-IA-01_reviewer_independent",
               f"reviewer {scope.get('reviewer_id')!r} is the subject's own "
               f"producer", reviewer=scope.get("reviewer_id"))
    if not scope.get("reviewer_id"):
        r.fail("CHK-IA-01_reviewer_independent", "no reviewer_id recorded")

    # --- CHK-IA-02 the subject did not change during review -------------
    # This is the pack's defining control: a reviewer that edited the work is
    # not a reviewer, and this detects it even if the fence was bypassed.
    if not proof.get("unchanged"):
        before, after = proof.get("before", {}), proof.get("after") or {}
        changed = sorted(set(before) ^ set(after)) + sorted(
            k for k in set(before) & set(after) if before[k] != after[k])
        r.fail("CHK-IA-02_subject_unmodified",
               f"the subject changed while under review: {changed[:10]}",
               changed=changed[:10])
    if proof.get("after") is None:
        r.fail("CHK-IA-02_subject_unmodified",
               "independence proof was never re-verified at verdict time")
    if not proof.get("files_snapshotted"):
        r.fail("CHK-IA-02_subject_unmodified",
               "independence proof snapshotted zero files")

    # --- CHK-IA-03 no review output was written into the subject --------
    sroot = os.path.realpath(scope.get("subject_root", "/nonexistent"))
    rroot = os.path.realpath(run_dir)
    if rroot == sroot or rroot.startswith(sroot + os.sep):
        r.fail("CHK-IA-03_no_production_in_subject",
               f"review output {rroot} sits inside the subject {sroot}")
    for rel in scope.get("review_outputs", []):
        p = os.path.realpath(os.path.join(run_dir, rel))
        if p == sroot or p.startswith(sroot + os.sep):
            r.fail("CHK-IA-03_no_production_in_subject",
                   f"review output {rel} resolves inside the subject", output=rel)

    # --- CHK-IA-04 verdict follows from findings ------------------------
    v = verdict.get("verdict")
    if v not in ("ACCEPT", "REJECT"):
        r.fail("CHK-IA-04_verdict_follows_findings",
               f"verdict {v!r} is neither ACCEPT nor REJECT")
    blocking = [f for f in findings if f.get("severity") == "BLOCKING"]
    if v == "ACCEPT" and blocking:
        r.fail("CHK-IA-04_verdict_follows_findings",
               f"ACCEPT issued with {len(blocking)} blocking findings: "
               f"{[f['id'] for f in blocking][:5]}",
               blocking=[f["id"] for f in blocking])
    if v == "REJECT" and not blocking:
        r.fail("CHK-IA-04_verdict_follows_findings",
               "REJECT issued with no blocking finding to justify it")
    if verdict.get("blocking_count") != len(blocking):
        r.fail("CHK-IA-04_verdict_follows_findings",
               f"verdict records {verdict.get('blocking_count')} blocking "
               f"findings but findings.json contains {len(blocking)}")

    # --- CHK-IA-05 every finding carries reproducible evidence ----------
    for f in findings:
        if not f.get("evidence"):
            r.fail("CHK-IA-05_findings_evidenced",
                   f"finding {f.get('id')} has no evidence pointer",
                   finding=f.get("id"))
            continue
        for e in f["evidence"]:
            for k in ("artefact", "locator", "observed"):
                if not str(e.get(k, "")).strip():
                    r.fail("CHK-IA-05_findings_evidenced",
                           f"finding {f.get('id')} has an evidence entry missing "
                           f"{k!r}", finding=f.get("id"))
        if f.get("severity") not in ("BLOCKING", "ADVISORY"):
            r.fail("CHK-IA-05_findings_evidenced",
                   f"finding {f.get('id')} has invalid severity "
                   f"{f.get('severity')!r}", finding=f.get("id"))

    # --- CHK-IA-06 the review was not vacuous ---------------------------
    # A "review" that ran no probes and found nothing is a rubber stamp.
    ran = set(scope.get("probes_run", []))
    for p in MANDATORY_PROBES:
        if p not in ran:
            r.fail("CHK-IA-06_review_not_vacuous",
                   f"mandatory probe {p} was not run", probe=p)

    # --- CHK-IA-07 the review recomputed rather than copied -------------
    if not scope.get("recomputed_subject_checks"):
        r.fail("CHK-IA-07_checks_recomputed",
               "the review did not independently recompute the subject's "
               "checks; it can only have copied the subject's own claim")

    # --- CHK-IA-08 scope covers the subject's required artefacts --------
    if not scope.get("required_artefacts"):
        r.fail("CHK-IA-08_scope_complete",
               "review scope names no required artefacts: the review could "
               "not have known what the subject owed")

    return r


if __name__ == "__main__":
    rep = run_checks(sys.argv[1])
    print(rep.summary())
    for f in rep.findings:
        print(f"  [{f.severity}] {f.check}: {f.message}")
    sys.exit(0 if rep.passed else 1)
