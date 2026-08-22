#!/usr/bin/env python3
"""independent-acceptance pack tests.

The subject under review is REAL: each test first runs the actual
strategic-orchestration pack to produce a genuine run directory, then reviews
it. Reviewing a hand-written fixture would prove only that the fixture parses.

INJECTED FAILURE: the subject's check_report.json is forged to claim PASS
while its artefacts actually fail. The reviewer must catch it by recomputation
and REJECT.
"""

import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_PACKS = os.path.dirname(_HERE)
sys.path.insert(0, _PACKS)
sys.path.insert(0, _HERE)

from obzio_spine import acceptance as acc
from obzio_spine import expectation as exp
from obzio_spine.machine import OperatorMachine, GuardFailure, TransitionError
from obzio_spine.states import State
from obzio_spine.tinytest import (Suite, expect_raises, assert_eq,
                                  assert_true, assert_in, assert_no_import)
from obzio_spine.artefacts import read_json, write_json
from obzio_spine import manifest

import engine
import fence as F
from checks import run_checks
from state_machine import build_machine, make_acceptor, PACK
import oracle

S = Suite(PACK)
TMP = tempfile.mkdtemp(prefix="ia-")

SUBJECT_PACK = os.path.join(_PACKS, "strategic-orchestration")
SUBJECT_REQUIRED = ["objective.json", "commissions.json",
                    "routing_table.json", "reconciliation.json"]


def fresh(n):
    d = os.path.join(TMP, n)
    os.makedirs(d, exist_ok=True)
    return d


def make_subject(name, complete=True):
    """Run the REAL strategic-orchestration pack to produce a subject."""
    saved = list(sys.path)
    sys.path.insert(0, SUBJECT_PACK)
    for mod in ("state_machine", "checks", "engine", "oracle"):
        sys.modules.pop(mod, None)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "so_state_machine", os.path.join(SUBJECT_PACK, "state_machine.py"))
        sm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sm)

        objective = {"id": "OBJ-SUBJ", "statement": "produce a reviewable run",
                     "budget_units": 100, "deadline_iso": "2026-09-30",
                     "orchestrator_max_authority": "WRITE_BRANCH_ONLY"}
        spec_rows = [
            {"id": "C-A", "title": "alpha", "owner_capability": "research",
             "budget_units": 20, "acceptance_criteria": ["done"]},
            {"id": "C-B", "title": "beta", "owner_capability": "build",
             "budget_units": 30, "depends_on": ["C-A"],
             "acceptance_criteria": ["shipped"]},
        ]
        returns = [{"commission_id": "C-A", "units_spent": 19, "criteria_met": ["done"]},
                   {"commission_id": "C-B", "units_spent": 28, "criteria_met": ["shipped"]}]

        d = fresh(name)
        kp = acc.ReviewerKeypair.generate("subject-reviewer")
        sac = sm.make_acceptor("subject-reviewer", objective, spec_rows, returns)
        m = sm.build_machine(d, "subject-producer-01", kp.commitments(),
                             objective, spec_rows, returns, acceptor=sac)
        for _ in range(6):
            m.advance()
        if complete:
            m.advance(acceptance=exp.AcceptanceReturn(
                True, kp.issue(m.current_run_digest(), acc.ACCEPT), sac.reveal()))
            m.advance()
        return d, m
    finally:
        sys.path[:] = saved
        for mod in ("state_machine", "checks", "engine", "oracle"):
            sys.modules.pop(mod, None)


def reviewer_kp():
    return acc.ReviewerKeypair.generate("review-acceptor-01")


def review(subject_dir, name, reviewer_id="reviewer-01", steps=6,
           pack_dir=SUBJECT_PACK, required=None):
    """Commit-first: the review's acceptor commits its structural expectation
    before the review produces anything."""
    kp = reviewer_kp()
    req = required if required is not None else SUBJECT_REQUIRED
    ac = make_acceptor("review-acceptor-01", subject_dir, req, reviewer_id)
    m = build_machine(fresh(name), reviewer_id, kp.commitments(), subject_dir,
                      req, pack_dir, acceptor=ac)
    for _ in range(steps):
        m.advance()
    return m, kp, ac


def accept_bit(m, kp, ac, bit=True):
    return exp.AcceptanceReturn(
        accept=bit,
        acceptance_reveal=kp.issue(m.current_run_digest(),
                                   acc.ACCEPT if bit else acc.REJECT),
        expectation_reveal=ac.reveal())


# ------------------------------------------------------------------ happy path

@S.test
def test_reviews_a_real_subject_and_accepts():
    """A genuine, clean subject run is reviewed and accepted."""
    subj, _ = make_subject("subject-clean")
    m, kp, ac = review(subj, "review-clean")
    assert_eq(m.state, State.INDEPENDENT_ACCEPTANCE)
    v = read_json(os.path.join(m.run_dir, "verdict.json"))
    assert_eq(v["verdict"], "ACCEPT", "a clean subject must be accepted")
    assert_eq(v["blocking_count"], 0)
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    assert_eq(m.state, State.COMPLETE)


@S.test
def test_all_mandatory_probes_actually_ran():
    """P8: the review is not a rubber stamp."""
    subj, _ = make_subject("subject-probes")
    m, kp, ac = review(subj, "review-probes")
    scope = read_json(os.path.join(m.run_dir, "review_scope.json"))
    for p in ["P-01_required_artefacts", "P-02_return_state", "P-03_check_report",
              "P-04_recomputed_checks", "P-05_manifest", "P-06_journal",
              "P-07_digest_binding"]:
        assert_in(p, scope["probes_run"])
    assert_eq(scope["recomputed_subject_checks"], True,
              "the reviewer must have re-run the subject's checks itself")


@S.test
def test_independence_proof_records_unchanged_subject():
    """P3: the subject is digest-snapshotted and re-verified."""
    subj, _ = make_subject("subject-proof")
    m, kp, ac = review(subj, "review-proof")
    proof = read_json(os.path.join(m.run_dir, "independence_proof.json"))
    assert_eq(proof["unchanged"], True)
    assert_true(proof["files_snapshotted"] >= 6,
                f"expected a real subject, got {proof['files_snapshotted']} files")
    assert_eq(proof["before"], proof["after"])


# ------------------------------------------------- INJECTED FAILURE + RECOVERY

@S.test
def test_forged_subject_check_report_detected():
    """INJECTED FAILURE: subject forges a PASS report over failing artefacts.

    This is the attack the pack exists to defeat: the subject breaks its own
    reconciliation, then edits check_report.json to say everything passed.
    A reviewer that reads the report is fooled. A reviewer that recomputes
    is not."""
    subj, _ = make_subject("subject-forged")

    # Break the artefacts: introduce a missing return.
    recon_p = os.path.join(subj, "reconciliation.json")
    recon = read_json(recon_p)
    recon["missing_returns"] = ["C-B"]
    recon["reconciled"] = False
    write_json(recon_p, recon)

    # Forge the report so the subject's own claim is spotless.
    write_json(os.path.join(subj, "check_report.json"), {
        "pack": "strategic-orchestration", "passed": True,
        "failure_count": 0, "warning_count": 0, "findings": []})

    m, kp, ac = review(subj, "review-forged", steps=6)
    v = read_json(os.path.join(m.run_dir, "verdict.json"))
    assert_eq(v["verdict"], "REJECT", "recomputation must expose the forgery")
    assert_true(v["blocking_count"] >= 1)

    findings = read_json(os.path.join(m.run_dir, "findings.json"))
    summaries = " ".join(f["summary"] for f in findings)
    assert_in("recomputed check failed", summaries)
    assert_in("CHK-SO-06", summaries)
    assert_in("claims PASS but recomputation", summaries)
    # Every finding must be reproducible by a third party.
    for f in findings:
        assert_true(f["evidence"], f"{f['id']} has no evidence")


@S.test
def test_recovery_review_of_repaired_subject():
    """RECOVERY: a subject with real artefacts and an honest report is accepted."""
    subj, _ = make_subject("subject-repaired")
    m, kp, ac = review(subj, "review-repaired")
    v = read_json(os.path.join(m.run_dir, "verdict.json"))
    assert_eq(v["verdict"], "ACCEPT")
    assert_true(m.check_report.passed, "the review's own checks must pass")
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    assert_eq(m.state, State.COMPLETE)


@S.test
def test_detects_subject_that_self_reviewed():
    """A subject whose producer and reviewer are the same is rejected."""
    subj, _ = make_subject("subject-selfrev")
    p = os.path.join(subj, "return_state.json")
    rs = read_json(p)
    rs["reviewer_id"] = rs["producer_id"]
    write_json(p, rs)
    m, kp, ac = review(subj, "review-selfrev")
    v = read_json(os.path.join(m.run_dir, "verdict.json"))
    assert_eq(v["verdict"], "REJECT")
    assert_in("self-reviewed",
              " ".join(f["summary"] for f in
                       read_json(os.path.join(m.run_dir, "findings.json"))))


@S.test
def test_detects_incomplete_subject():
    """A subject that never crossed its own gate is rejected."""
    subj, _ = make_subject("subject-incomplete", complete=False)
    m, kp, ac = review(subj, "review-incomplete")
    v = read_json(os.path.join(m.run_dir, "verdict.json"))
    assert_eq(v["verdict"], "REJECT")
    sm = " ".join(f["summary"] for f in
                  read_json(os.path.join(m.run_dir, "findings.json")))
    assert_in("no return_state.json", sm)


@S.test
def test_detects_broken_digest_binding():
    """P-07: artefacts edited after acceptance break the accepted digest."""
    subj, _ = make_subject("subject-digest")
    p = os.path.join(subj, "objective.json")
    doc = read_json(p)
    doc["budget_units"] = 999999
    write_json(p, doc)
    m, kp, ac = review(subj, "review-digest")
    v = read_json(os.path.join(m.run_dir, "verdict.json"))
    assert_eq(v["verdict"], "REJECT")
    assert_in("does not match the artefacts present",
              " ".join(f["summary"] for f in
                       read_json(os.path.join(m.run_dir, "findings.json"))))


@S.test
def test_detects_tampered_journal():
    """P-06: removing journal entries breaks sequence contiguity."""
    subj, _ = make_subject("subject-journal")
    p = os.path.join(subj, "journal.json")
    j = read_json(p)
    write_json(p, [e for e in j if e.get("event") != "ACCEPTANCE_VERIFIED"])
    m, kp, ac = review(subj, "review-journal")
    sm = " ".join(f["summary"] for f in
                  read_json(os.path.join(m.run_dir, "findings.json")))
    assert_in("not contiguous", sm)
    assert_in("no ACCEPTANCE_VERIFIED event", sm)


@S.test
def test_detects_self_contradictory_check_report():
    """P-03: passed=true alongside failures is caught without recomputation."""
    subj, _ = make_subject("subject-contradict")
    write_json(os.path.join(subj, "check_report.json"), {
        "pack": "x", "passed": True, "failure_count": 3, "warning_count": 0,
        "findings": [{"check": "c", "severity": "FAIL", "message": "m",
                      "evidence": {}}]})
    m, kp, ac = review(subj, "review-contradict")
    sm = " ".join(f["summary"] for f in
                  read_json(os.path.join(m.run_dir, "findings.json")))
    assert_in("claims passed=true while reporting failures", sm)


# ------------------------------------------------------- CANNOT PRODUCE (core)

@S.test
def test_fence_refuses_write_into_subject():
    """P1: the defining control. The reviewer cannot write into the subject."""
    subj, _ = make_subject("subject-fence")
    rdir = fresh("review-fence")
    wf = F.WriteFence(subj, rdir)
    err = expect_raises(F.ProductionAttemptError, wf.write_json,
                        os.path.join(subj, "helpful_fix.json"), {"fixed": True})
    assert_in("cannot produce it", str(err))
    # Nested paths too.
    expect_raises(F.ProductionAttemptError, wf.write_json,
                  os.path.join(subj, "sub", "deep", "x.json"), {})
    # And traversal out of the review dir back into the subject.
    expect_raises(F.ProductionAttemptError, wf.write_json,
                  os.path.join(rdir, "..", os.path.basename(subj), "x.json"), {})
    assert_true(not os.path.exists(os.path.join(subj, "helpful_fix.json")),
                "no file may have been created")
    assert_eq(len(wf.refused), 3, "every refusal must be recorded")


@S.test
def test_subject_handle_exposes_no_write_method():
    """P1: there is no write method on the handle to call by accident."""
    subj, _ = make_subject("subject-handle")
    h = F.SubjectHandle(subj)
    for banned in ("write", "write_json", "write_bytes", "put", "delete",
                   "remove", "open_for_write"):
        assert_true(not hasattr(h, banned),
                    f"SubjectHandle must not expose {banned!r}")
    assert_true(hasattr(h, "read_json") and hasattr(h, "digest"))


@S.test
def test_review_dir_inside_subject_refused():
    """P2: the review cannot output into the thing it is reviewing."""
    subj, _ = make_subject("subject-nested")
    inner = os.path.join(subj, "review_here")
    os.makedirs(inner, exist_ok=True)
    err = expect_raises(F.ProductionAttemptError, F.WriteFence, subj, inner)
    assert_in("contaminate", str(err))


@S.test
def test_out_of_band_subject_edit_voids_review():
    """P3: an edit that BYPASSES the fence still voids the review.

    This is the control that does not depend on the reviewer cooperating.
    The write here uses plain open() -- the fence never sees it."""
    subj, _ = make_subject("subject-oob")
    kp = reviewer_kp()
    m = build_machine(fresh("review-oob"), "reviewer-01", kp.commitments(),
                      subj, SUBJECT_REQUIRED, SUBJECT_PACK,
                      acceptor=make_acceptor("review-acceptor-01", subj,
                                             SUBJECT_REQUIRED, "reviewer-01"))
    m.advance()          # CURRENT_STATE_RECOVERED -> snapshot taken
    m.advance()          # INPUT_ADMITTED

    # Bypass every layer: raw filesystem write into the subject.
    with open(os.path.join(subj, "sneaky.txt"), "w") as f:
        f.write("the reviewer fixed something")

    err = expect_raises(GuardFailure, m.advance)
    assert_in("IndependenceViolation", str(err))
    assert_in("sneaky.txt", str(err))
    assert_eq(m.state, State.INPUT_ADMITTED, "the review must not proceed")


@S.test
def test_cannot_review_own_work():
    """P4: a reviewer may not review a subject it produced."""
    subj, _ = make_subject("subject-own")
    kp = reviewer_kp()
    m = build_machine(fresh("review-own"), "subject-producer-01",
                      kp.commitments(), subj, SUBJECT_REQUIRED, SUBJECT_PACK,
                      acceptor=make_acceptor("review-acceptor-01", subj,
                                             SUBJECT_REQUIRED,
                                             "subject-producer-01"))
    m.advance()
    err = expect_raises(GuardFailure, m.advance)
    assert_in("cannot review own work", str(err))


@S.test
def test_no_review_output_landed_in_subject():
    """After a full review, the subject directory is byte-identical."""
    subj, _ = make_subject("subject-clean2")
    h = F.SubjectHandle(subj)
    before = h.snapshot()
    m, kp, ac = review(subj, "review-clean2")
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    assert_eq(F.SubjectHandle(subj).snapshot(), before,
              "the subject must be byte-identical after a completed review")


# ------------------------------------------------------------ verdict discipline

@S.test
def test_verdict_is_derived_not_chosen():
    """P5: verdict() is a function of findings; there is no setter."""
    subj, _ = make_subject("subject-derive")
    h = F.SubjectHandle(subj)
    rv = engine.Review(h, SUBJECT_PACK)
    rv.run_all(SUBJECT_REQUIRED)
    assert_eq(rv.verdict(), "ACCEPT")
    rv._add("manual", "BLOCKING", "injected blocking finding",
            [engine.Evidence("a", "b", "c")])
    assert_eq(rv.verdict(), "REJECT", "a blocking finding must force REJECT")
    assert_true(not hasattr(rv, "set_verdict"))


@S.test
def test_accept_with_blocking_finding_caught():
    """P5: an ACCEPT recorded alongside a blocking finding is refused."""
    subj, _ = make_subject("subject-badaccept")
    m, kp, ac = review(subj, "review-badaccept")
    fp = os.path.join(m.run_dir, "findings.json")
    fs = read_json(fp)
    fs.append({"id": "F-999", "probe": "x", "severity": "BLOCKING",
               "summary": "a real defect", "evidence": [
                   {"artefact": "a", "locator": "b", "observed": "c"}]})
    write_json(fp, fs)
    rep = run_checks(m.run_dir)
    assert_true(not rep.passed)
    assert_in("CHK-IA-04", " ".join(f.check for f in rep.failures))
    assert_in("ACCEPT issued with", " ".join(f.message for f in rep.failures))


@S.test
def test_unjustified_reject_caught():
    """P6: REJECT with no blocking finding is refused."""
    subj, _ = make_subject("subject-badreject")
    m, kp, ac = review(subj, "review-badreject")
    vp = os.path.join(m.run_dir, "verdict.json")
    v = read_json(vp)
    v["verdict"] = "REJECT"
    write_json(vp, v)
    rep = run_checks(m.run_dir)
    assert_in("CHK-IA-04", " ".join(f.check for f in rep.failures))
    assert_in("no blocking finding", " ".join(f.message for f in rep.failures))


@S.test
def test_evidence_free_finding_caught():
    """P7: a finding without an evidence pointer is refused."""
    subj, _ = make_subject("subject-noevid")
    m, kp, ac = review(subj, "review-noevid")
    fp = os.path.join(m.run_dir, "findings.json")
    write_json(fp, [{"id": "F-001", "probe": "p", "severity": "ADVISORY",
                     "summary": "trust me", "evidence": []}])
    rep = run_checks(m.run_dir)
    assert_in("CHK-IA-05", " ".join(f.check for f in rep.failures))


@S.test
def test_vacuous_review_caught():
    """P8: a review that ran no probes cannot pass its own checks."""
    subj, _ = make_subject("subject-vacuous")
    m, kp, ac = review(subj, "review-vacuous")
    sp = os.path.join(m.run_dir, "review_scope.json")
    scope = read_json(sp)
    scope["probes_run"] = []
    write_json(sp, scope)
    rep = run_checks(m.run_dir)
    assert_in("CHK-IA-06", " ".join(f.check for f in rep.failures))
    assert_in("mandatory probe", " ".join(f.message for f in rep.failures))


@S.test
def test_uncomputed_checks_caught():
    """P9: a review that did not recompute is refused."""
    subj, _ = make_subject("subject-norecompute")
    m, kp, ac = review(subj, "review-norecompute")
    sp = os.path.join(m.run_dir, "review_scope.json")
    scope = read_json(sp)
    scope["recomputed_subject_checks"] = False
    write_json(sp, scope)
    rep = run_checks(m.run_dir)
    assert_in("CHK-IA-07", " ".join(f.check for f in rep.failures))


@S.test
def test_independence_violation_in_artefact_caught():
    """CHK-IA-02 fails if the proof itself records a change."""
    subj, _ = make_subject("subject-ivio")
    m, kp, ac = review(subj, "review-ivio")
    pp = os.path.join(m.run_dir, "independence_proof.json")
    proof = read_json(pp)
    proof["unchanged"] = False
    proof["after"] = dict(proof["after"], **{"injected.txt": "deadbeef"})
    write_json(pp, proof)
    rep = run_checks(m.run_dir)
    assert_in("CHK-IA-02", " ".join(f.check for f in rep.failures))


# ------------------------------------------------------------------- guards

@S.test
def test_empty_subject_refused():
    """P12: an empty subject directory cannot be reviewed."""
    kp = reviewer_kp()
    empty = fresh("subject-empty")
    m = build_machine(fresh("review-empty"), "reviewer-01", kp.commitments(),
                      empty, SUBJECT_REQUIRED, SUBJECT_PACK,
                      acceptor=make_acceptor("review-acceptor-01", empty,
                                             SUBJECT_REQUIRED, "reviewer-01"))
    err = expect_raises(GuardFailure, m.advance)
    assert_in("contains no files", str(err))


@S.test
def test_review_without_expectations_refused():
    """P13: a review with no required-artefact list cannot fail, so is refused."""
    subj, _ = make_subject("subject-noexp")
    kp = reviewer_kp()
    m = build_machine(fresh("review-noexp"), "reviewer-01", kp.commitments(),
                      subj, [], SUBJECT_PACK,
                      acceptor=make_acceptor("review-acceptor-01", subj, [],
                                             "reviewer-01"))
    m.advance()
    err = expect_raises(GuardFailure, m.advance)
    assert_in("no expectations", str(err))


@S.test
def test_reviewer_cannot_self_advance():
    """P10: the gate applies to the reviewer exactly as to everyone else."""
    subj, _ = make_subject("subject-gate")
    m, kp, ac = review(subj, "review-gate")
    err = expect_raises(acc.AcceptanceError, m.advance)
    assert_in("cannot advance itself", str(err))
    assert_eq(m.state, State.INDEPENDENT_ACCEPTANCE)


@S.test
def test_reviewer_self_review_refused():
    """P11: the reviewer may not hold the commitments that accept its review."""
    subj, _ = make_subject("subject-selfacc")
    kp = acc.ReviewerKeypair.generate("reviewer-01")
    expect_raises(acc.SelfAcceptanceError, OperatorMachine,
                  PACK, fresh("review-selfacc"), "reviewer-01", kp.commitments())


@S.test
def test_checks_report_missing_artefacts():
    """checks.py on an empty dir fails rather than passing vacuously."""
    rep = run_checks(fresh("emptydir"))
    assert_true(not rep.passed)
    assert_in("missing artefacts", rep.failures[0].message)


# ------------------------------------------------------ commit-first (NEW)

@S.test
def test_anchored_acceptor_is_refused():
    """REQUIRED: an acceptor that has SEEN the review's output cannot commit.

    Note what is and is not hidden. The review's acceptor MAY read the
    subject -- that is its input. It may not read the verdict or findings
    before committing, and those are the artefacts the check covers."""
    subj, _ = make_subject("subject-anchor")
    m0, kp0, ac0 = review(subj, "review-anchor")
    d = m0.run_dir
    assert_true(os.path.exists(os.path.join(d, "verdict.json")))
    kp = reviewer_kp()
    m = OperatorMachine(PACK, d, "reviewer-02", kp.commitments(),
                        artefact_names=["review_scope.json", "findings.json",
                                        "verdict.json", "independence_proof.json"])
    late = make_acceptor("review-acceptor-01", subj, SUBJECT_REQUIRED, "reviewer-02")
    err = expect_raises(exp.AnchoringError, m.register_expectation, late.commitment())
    assert_in("anchored", str(err))


@S.test
def test_commit_first_is_mandatory():
    """No committed expectation means the review cannot leave PREFLIGHT."""
    subj, _ = make_subject("subject-nocommit")
    kp = reviewer_kp()
    m = build_machine(fresh("review-nocommit"), "reviewer-01", kp.commitments(),
                      subj, SUBJECT_REQUIRED, SUBJECT_PACK)
    err = expect_raises(exp.AnchoringError, m.advance)
    assert_in("commit-first is mandatory", str(err))


@S.test
def test_oracle_does_not_import_review_engine():
    """Independence rests on the oracle not being the reviewer."""
    assert_no_import(os.path.join(_HERE, "oracle.py"), ["engine", "fence"])


@S.test
def test_one_sided_oracle_catches_false_accept():
    """The FPR direction: a review that ACCEPTs a broken subject diverges.

    This is the exact failure the commit-first redesign targets. The acceptor
    independently found a structural defect BEFORE seeing the verdict, so a
    verdict of ACCEPT contradicts a commitment it cannot retract."""
    subj, _ = make_subject("subject-broken", complete=False)   # no return_state
    scan = oracle.independent_structural_scan(subj, SUBJECT_REQUIRED)
    assert_true(not scan["sound"], "the subject must be structurally unsound")
    assert_in("no_return_state", scan["defects"])

    ac = make_acceptor("review-acceptor-01", subj, SUBJECT_REQUIRED, "reviewer-01")
    assert_eq(ac.expectation.fields["subject_structurally_sound"], False)

    # Forge a review that ACCEPTs it anyway.
    d = fresh("review-falseaccept")
    os.makedirs(d, exist_ok=True)
    write_json(os.path.join(d, "review_scope.json"),
               {"reviewer_id": "reviewer-01", "subject_producer_id": "producer-x",
                "probes_run": [], "recomputed_subject_checks": True,
                "required_artefacts": SUBJECT_REQUIRED, "subject_root": subj,
                "review_outputs": []})
    write_json(os.path.join(d, "findings.json"), [])
    write_json(os.path.join(d, "verdict.json"),
               {"verdict": "ACCEPT", "blocking_count": 0, "advisory_count": 0,
                "reviewer_id": "reviewer-01", "subject_root": subj})
    actual = oracle.extract_actual(d, subj, SUBJECT_REQUIRED)
    agrees, div = exp.compare(ac.expectation, actual)
    assert_true(not agrees, "a false ACCEPT must diverge from the commitment")
    assert_in("verdict_at_least_as_strict_as_structure",
              {x["field"] for x in div})


@S.test
def test_one_sided_oracle_admits_it_cannot_catch_false_reject():
    """The limit, demonstrated rather than asserted.

    A review that REJECTs a perfectly sound subject does NOT diverge. This
    oracle bounds strictness from below only. That is a real gap and the
    pack must not claim otherwise."""
    subj, _ = make_subject("subject-sound")
    scan = oracle.independent_structural_scan(subj, SUBJECT_REQUIRED)
    assert_true(scan["sound"], f"subject should be sound: {scan['defects']}")
    ac = make_acceptor("review-acceptor-01", subj, SUBJECT_REQUIRED, "reviewer-01")

    d = fresh("review-falsereject")
    os.makedirs(d, exist_ok=True)
    write_json(os.path.join(d, "review_scope.json"),
               {"reviewer_id": "reviewer-01", "subject_producer_id": "producer-x",
                "probes_run": [], "recomputed_subject_checks": True,
                "required_artefacts": SUBJECT_REQUIRED, "subject_root": subj,
                "review_outputs": []})
    write_json(os.path.join(d, "findings.json"),
               [{"id": "F-1", "probe": "p", "severity": "BLOCKING",
                 "summary": "spurious", "evidence": [
                     {"artefact": "a", "locator": "b", "observed": "c"}]}])
    write_json(os.path.join(d, "verdict.json"),
               {"verdict": "REJECT", "blocking_count": 1, "advisory_count": 0,
                "reviewer_id": "reviewer-01", "subject_root": subj})
    agrees, div = exp.compare(ac.expectation,
                              oracle.extract_actual(d, subj, SUBJECT_REQUIRED))
    assert_true(agrees,
                "a spurious REJECT passes: this oracle is one-sided by design")
    joined = " ".join(ac.expectation.uncovered).lower()
    assert_in("false reject", joined)


@S.test
def test_return_state_records_one_sided_claim():
    """The record must say PARTIAL_ORACLE and name what is uncovered."""
    subj, _ = make_subject("subject-claim")
    m, kp, ac = review(subj, "review-claim")
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    rs = read_json(os.path.join(m.run_dir, "return_state.json"))
    assert_eq(rs["acceptance_independence"], "PARTIAL_ORACLE")
    assert_true(any("false REJECT" in u for u in rs["expectation_uncovered"]))


@S.test
def test_manifest_verifies_and_detects_tamper():
    """MANIFEST.json detects a modified pack file."""
    ok, problems = manifest.verify(_HERE)
    assert_true(ok, f"manifest should verify clean: {problems}")
    victim = os.path.join(_HERE, "fence.py")
    original = open(victim, "rb").read()
    try:
        with open(victim, "ab") as f:
            f.write(b"\n# tamper\n")
        assert_true(not manifest.verify(_HERE)[0], "tamper must be detected")
    finally:
        with open(victim, "wb") as f:
            f.write(original)
    assert_true(manifest.verify(_HERE)[0], "clean again after restore")


if __name__ == "__main__":
    rc = S.run()
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(rc)
