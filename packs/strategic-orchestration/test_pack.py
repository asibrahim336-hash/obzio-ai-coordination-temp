#!/usr/bin/env python3
"""strategic-orchestration pack tests.

Includes an INJECTED FAILURE (a commission whose return never arrives) and
proves the pack detects it, refuses to advance, and recovers cleanly once the
return is supplied.
"""

import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
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
from checks import run_checks
from state_machine import build_machine, make_acceptor, PACK
import oracle

S = Suite(PACK)
TMP = tempfile.mkdtemp(prefix="so-")

OBJECTIVE = {
    "id": "OBJ-2026-Q3-01",
    "statement": "Stand up the operator pack programme end to end",
    "budget_units": 100,
    "deadline_iso": "2026-09-30",
    "non_goals": ["hiring"],
    "orchestrator_max_authority": "WRITE_BRANCH_ONLY",
}

SPEC = [
    {"id": "C-RESEARCH", "title": "Survey existing operator contracts",
     "owner_capability": "research", "budget_units": 20,
     "acceptance_criteria": ["sources cited", "gaps listed"]},
    {"id": "C-BUILD", "title": "Implement the pack spine",
     "owner_capability": "build", "budget_units": 40, "depends_on": ["C-RESEARCH"],
     "acceptance_criteria": ["tests run", "manifest written"]},
    {"id": "C-REVIEW", "title": "Adversarially review the spine",
     "owner_capability": "review", "budget_units": 15, "depends_on": ["C-BUILD"],
     "acceptance_criteria": ["verdict issued"]},
]

GOOD_RETURNS = [
    {"commission_id": "C-RESEARCH", "units_spent": 18,
     "criteria_met": ["sources cited", "gaps listed"]},
    {"commission_id": "C-BUILD", "units_spent": 37,
     "criteria_met": ["tests run", "manifest written"]},
    {"commission_id": "C-REVIEW", "units_spent": 12, "criteria_met": ["verdict issued"]},
]


def fresh(name):
    d = os.path.join(TMP, name)
    os.makedirs(d, exist_ok=True)
    return d


def reviewer():
    return acc.ReviewerKeypair.generate("reviewer-independent-01")


def drive_to_gate(run_dir, returns=GOOD_RETURNS, producer="orchestrator-01"):
    """Commit-first: the acceptor derives and commits its expectation from the
    declared inputs BEFORE the machine is built and before work runs."""
    kp = reviewer()
    ac = make_acceptor("reviewer-independent-01", OBJECTIVE, SPEC, returns)
    m = build_machine(run_dir, producer, kp.commitments(), OBJECTIVE, SPEC,
                      returns, acceptor=ac)
    for _ in range(6):
        m.advance()
    return m, kp, ac


def accept_bit(m, kp, ac, bit=True):
    """The whole channel back to the producer: one bit plus the reveals."""
    return exp.AcceptanceReturn(
        accept=bit,
        acceptance_reveal=kp.issue(m.current_run_digest(),
                                   acc.ACCEPT if bit else acc.REJECT),
        expectation_reveal=ac.reveal())


# ------------------------------------------------------------------ happy path

@S.test
def test_full_lifecycle_reaches_complete():
    """Nominal run: 3 commissions, all returns present, reviewer ACCEPTs."""
    m, kp, ac = drive_to_gate(fresh("happy"))
    assert_eq(m.state, State.INDEPENDENT_ACCEPTANCE, "should stop at the gate")
    m.advance(acceptance=accept_bit(m, kp, ac))
    assert_eq(m.state, State.RETURN_STATE_WRITTEN)
    m.advance()
    assert_eq(m.state, State.COMPLETE)
    rs = read_json(os.path.join(m.run_dir, "return_state.json"))
    assert_eq(rs["verdict"], "ACCEPT")
    assert_eq(rs["final_state"], "COMPLETE",
              "the durable record must report the terminal state, not a stale one")
    assert_true(rs["accepted_run_digest"], "accepted digest must be recorded")


@S.test
def test_artefacts_are_real_files_with_content():
    """The four artefacts exist on disk and parse."""
    m, kp, ac = drive_to_gate(fresh("artefacts"))
    for name in ("objective.json", "commissions.json",
                 "routing_table.json", "reconciliation.json"):
        p = os.path.join(m.run_dir, name)
        assert_true(os.path.exists(p), f"{name} missing")
        assert_true(os.path.getsize(p) > 0, f"{name} empty")
    comms = read_json(os.path.join(m.run_dir, "commissions.json"))
    assert_eq(len(comms), 3)
    routing = read_json(os.path.join(m.run_dir, "routing_table.json"))
    assert_eq(routing["waves"], [["C-RESEARCH"], ["C-BUILD"], ["C-REVIEW"]],
              "dependency chain must serialise into three waves")


# ------------------------------------------------- INJECTED FAILURE + RECOVERY

@S.test
def test_injected_missing_return_blocks_progress():
    """INJECTED FAILURE: C-BUILD's return is withheld. Pack must refuse."""
    broken = [r for r in GOOD_RETURNS if r["commission_id"] != "C-BUILD"]
    kp = reviewer()
    d = fresh("injected")
    ac = make_acceptor("reviewer-independent-01", OBJECTIVE, SPEC, broken)
    m = build_machine(d, "orchestrator-01", kp.commitments(), OBJECTIVE, SPEC,
                      broken, acceptor=ac)
    for _ in range(4):
        m.advance()                       # -> REQUIRED_ARTEFACTS_PRESENT
    assert_eq(m.state, State.REQUIRED_ARTEFACTS_PRESENT)

    # The checks guard must REFUSE, not warn-and-continue.
    err = expect_raises(GuardFailure, m.advance)
    assert_in("MACHINE_CHECKS_PASSED", str(err))
    assert_eq(m.state, State.REQUIRED_ARTEFACTS_PRESENT,
              "a refused transition must not move the machine")

    rep = m.check_report
    assert_true(not rep.passed, "check report must record failure")
    msgs = " ".join(f.message for f in rep.failures)
    assert_in("missing_returns", msgs)
    assert_in("C-BUILD", msgs)

    # And the failure is durable on disk, not just in memory.
    disk = read_json(os.path.join(d, "check_report.json"))
    assert_eq(disk["passed"], False)
    assert_true(disk["failure_count"] >= 1)


@S.test
def test_recovery_after_injected_failure():
    """RECOVERY: supply the missing return; a fresh run now completes."""
    d = fresh("recovered")
    m, kp, ac = drive_to_gate(d, GOOD_RETURNS)      # complete return set
    assert_eq(m.state, State.INDEPENDENT_ACCEPTANCE)
    assert_true(m.check_report.passed, "checks must pass once the return exists")
    recon = read_json(os.path.join(d, "reconciliation.json"))
    assert_eq(recon["missing_returns"], [])
    assert_eq(recon["reconciled"], True)
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    assert_eq(m.state, State.COMPLETE, "recovered run must reach COMPLETE")


# --------------------------------------------------------------- the hard gate

@S.test
def test_producer_cannot_self_advance():
    """P1: the producing process cannot cross INDEPENDENT_ACCEPTANCE alone."""
    m, kp, ac = drive_to_gate(fresh("gate"))
    err = expect_raises(acc.AcceptanceError, m.advance)
    assert_in("cannot advance itself", str(err))
    assert_eq(m.state, State.INDEPENDENT_ACCEPTANCE, "must not have moved")


@S.test
def test_self_review_machine_refused():
    """P2: a machine whose reviewer is its own producer cannot be constructed."""
    kp = acc.ReviewerKeypair.generate("same-principal")
    expect_raises(acc.SelfAcceptanceError, OperatorMachine,
                  PACK, fresh("selfrev"), "same-principal", kp.commitments())


@S.test
def test_forged_acceptance_refused():
    """P3: forging a reveal requires inverting SHA-256."""
    m, kp, ac = drive_to_gate(fresh("forge"))
    dg = m.current_run_digest()
    forged = acc.Reveal(reviewer_id="reviewer-independent-01", verdict=acc.ACCEPT,
                        run_digest=dg, secret="not-the-real-secret",
                        token=acc.bind("not-the-real-secret", dg, acc.ACCEPT))
    ret = exp.AcceptanceReturn(True, forged, ac.reveal())
    err = expect_raises(acc.AcceptanceError, m.advance, acceptance=ret)
    assert_in("does not open", str(err))
    assert_eq(m.state, State.INDEPENDENT_ACCEPTANCE)


@S.test
def test_verdict_upgrade_refused():
    """P4: knowing the REJECT secret must not yield an ACCEPT."""
    m, kp, ac = drive_to_gate(fresh("upgrade"))
    dg = m.current_run_digest()
    rej = kp.issue(dg, acc.REJECT)
    upgraded = acc.Reveal(reviewer_id=rej.reviewer_id, verdict=acc.ACCEPT,
                          run_digest=dg, secret=rej.secret,
                          token=acc.bind(rej.secret, dg, acc.ACCEPT))
    expect_raises(acc.AcceptanceError, m.advance,
                  acceptance=exp.AcceptanceReturn(True, upgraded, ac.reveal()))
    assert_eq(m.state, State.INDEPENDENT_ACCEPTANCE)


@S.test
def test_honest_reject_returns_one_bit_and_no_rationale():
    """A REJECT stops the run, is journalled, and leaks NO rubric.

    The old design carried a free-text `note` back to the producer. That is a
    rubric leak: a producer told WHY it failed learns what to change to pass
    without becoming correct. The channel is now one bit."""
    m, kp, ac = drive_to_gate(fresh("reject"))
    err = expect_raises(acc.AcceptanceError, m.advance,
                        acceptance=accept_bit(m, kp, ac, bit=False))
    assert_in("REJECT", str(err))
    assert_in("bit=0", str(err))
    assert_eq(m.verdict, "REJECT")
    # Nothing resembling guidance may reach the producer.
    for leak in ("budget", "criteria", "commission", "unmet", "fix", "should"):
        assert_true(leak not in str(err).lower(),
                    f"rejection message leaked the rubric term {leak!r}")
    ev = [e for e in m.journal if e["event"] == "ACCEPTANCE_REJECTED"][0]
    assert_eq(ev["detail"]["bit"], 0)
    assert_true("note" not in ev["detail"], "journal must not carry a rationale")
    import dataclasses
    fields = {f.name for f in dataclasses.fields(acc.Reveal)}
    assert_true("note" not in fields, "Reveal must not carry free text")


@S.test
def test_replayed_reveal_refused():
    """P5: a reveal valid for run A must not unlock run B."""
    m1, kp, ac1 = drive_to_gate(fresh("replay-a"))
    good = kp.issue(m1.current_run_digest(), acc.ACCEPT)
    # A second run with a different budget => different artefacts => different digest.
    obj2 = dict(OBJECTIVE, budget_units=99)
    ac2 = make_acceptor("reviewer-independent-01", obj2, SPEC, GOOD_RETURNS)
    m2 = build_machine(fresh("replay-b"), "orchestrator-01", kp.commitments(),
                       obj2, SPEC, GOOD_RETURNS, acceptor=ac2)
    for _ in range(6):
        m2.advance()
    assert_true(m2.current_run_digest() != m1.current_run_digest(),
                "runs must have distinct digests for this test to mean anything")
    err = expect_raises(acc.AcceptanceError, m2.advance,
                        acceptance=exp.AcceptanceReturn(True, good, ac2.reveal()))
    assert_in("different run", str(err))


@S.test
def test_post_acceptance_tamper_detected():
    """P6: editing an artefact after ACCEPT invalidates the accepted digest."""
    m, kp, ac = drive_to_gate(fresh("tamper"))
    m.advance(acceptance=accept_bit(m, kp, ac))
    assert_eq(m.state, State.RETURN_STATE_WRITTEN)
    # Quietly inflate the budget after sign-off.
    p = os.path.join(m.run_dir, "objective.json")
    doc = read_json(p)
    doc["budget_units"] = 10 ** 6
    write_json(p, doc)
    err = expect_raises(TransitionError, m.advance)
    assert_in("changed after acceptance", str(err))


@S.test
def test_reveal_on_ungated_transition_refused():
    """Supplying reviewer material at the wrong state is an error, not a no-op."""
    kp = reviewer()
    ac = make_acceptor("reviewer-independent-01", OBJECTIVE, SPEC, GOOD_RETURNS)
    m = build_machine(fresh("wrongstate"), "orchestrator-01", kp.commitments(),
                      OBJECTIVE, SPEC, GOOD_RETURNS, acceptor=ac)
    ret = exp.AcceptanceReturn(True, kp.issue("whatever", acc.ACCEPT), ac.reveal())
    err = expect_raises(TransitionError, m.advance, acceptance=ret)
    assert_in("ungated transition", str(err))


# ------------------------------------------------------------ lifecycle safety

@S.test
def test_no_state_skipping():
    """P11: states advance by exactly one; there is no skip API."""
    m, kp, ac = drive_to_gate(fresh("skip"))
    seq = [e["detail"]["to"] for e in m.journal if e["event"] == "TRANSITION"]
    assert_eq(seq, ["CURRENT_STATE_RECOVERED", "INPUT_ADMITTED", "ACTION_EXECUTED",
                    "REQUIRED_ARTEFACTS_PRESENT", "MACHINE_CHECKS_PASSED",
                    "INDEPENDENT_ACCEPTANCE"])
    assert_true(not hasattr(m, "set_state"), "no setter may exist")
    assert_true(not hasattr(m, "goto"), "no goto may exist")


@S.test
def test_machine_not_reusable():
    """P12: a finalised machine refuses further transitions."""
    m, kp, ac = drive_to_gate(fresh("reuse"))
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    assert_eq(m.state, State.COMPLETE)
    err = expect_raises(TransitionError, m.advance)
    assert_in("finalised", str(err))


# -------------------------------------------------------------- engine + checks

@S.test
def test_overcommit_refused():
    """P7: a decomposition exceeding the objective budget is refused."""
    obj = engine.Objective("O", "s", 10, "2026-01-01")
    err = expect_raises(engine.DecompositionError, engine.decompose, obj, [
        {"id": "A", "title": "a", "owner_capability": "research",
         "budget_units": 99, "acceptance_criteria": ["x"]}])
    assert_in("refusing to over-commit", str(err))


@S.test
def test_cycle_refused():
    """P8: a dependency cycle is refused at decomposition time."""
    obj = engine.Objective("O", "s", 100, "2026-01-01")
    err = expect_raises(engine.DecompositionError, engine.decompose, obj, [
        {"id": "A", "title": "a", "owner_capability": "research", "budget_units": 5,
         "depends_on": ["B"], "acceptance_criteria": ["x"]},
        {"id": "B", "title": "b", "owner_capability": "build", "budget_units": 5,
         "depends_on": ["A"], "acceptance_criteria": ["y"]}])
    assert_in("cycle", str(err))


@S.test
def test_unbounded_commission_refused():
    """P9: a commission with no acceptance criteria cannot be created."""
    obj = engine.Objective("O", "s", 100, "2026-01-01")
    expect_raises(engine.DecompositionError, engine.decompose, obj, [
        {"id": "A", "title": "a", "owner_capability": "research",
         "budget_units": 5, "acceptance_criteria": []}])


@S.test
def test_unroutable_capability_refused():
    """A capability with no route cannot be commissioned."""
    obj = engine.Objective("O", "s", 100, "2026-01-01")
    err = expect_raises(engine.DecompositionError, engine.decompose, obj, [
        {"id": "A", "title": "a", "owner_capability": "telepathy",
         "budget_units": 5, "acceptance_criteria": ["x"]}])
    assert_in("no route", str(err))


@S.test
def test_authority_escalation_caught():
    """P10: CHK-SO-03 catches delegating above the orchestrator's ceiling."""
    d = fresh("escalate")
    m, kp, ac = drive_to_gate(d)
    obj_p = os.path.join(d, "objective.json")
    doc = read_json(obj_p)
    doc["orchestrator_max_authority"] = "VERDICT_ONLY"   # lower the ceiling
    write_json(obj_p, doc)
    rep = run_checks(d)
    assert_true(not rep.passed, "lowered ceiling must trip the ladder check")
    assert_in("CHK-SO-03", " ".join(f.check for f in rep.failures))


@S.test
def test_checks_detect_orphan_return():
    """A return for a commission that was never issued is caught."""
    d = fresh("orphan")
    kp = reviewer()
    rets = GOOD_RETURNS + [{"commission_id": "C-GHOST", "units_spent": 5,
                            "criteria_met": []}]
    m = build_machine(d, "orchestrator-01", kp.commitments(), OBJECTIVE, SPEC,
                      rets, acceptor=make_acceptor("reviewer-independent-01",
                                                   OBJECTIVE, SPEC, rets))
    for _ in range(4):
        m.advance()
    expect_raises(GuardFailure, m.advance)
    assert_in("orphan_returns", " ".join(f.message for f in m.check_report.failures))


@S.test
def test_checks_detect_unmet_criteria():
    """A return that omits a stated acceptance criterion is caught."""
    d = fresh("unmet")
    kp = reviewer()
    rets = [dict(r) for r in GOOD_RETURNS]
    rets[1]["criteria_met"] = ["tests run"]          # drops "manifest written"
    m = build_machine(d, "orchestrator-01", kp.commitments(), OBJECTIVE, SPEC,
                      rets, acceptor=make_acceptor("reviewer-independent-01",
                                                   OBJECTIVE, SPEC, rets))
    for _ in range(4):
        m.advance()
    expect_raises(GuardFailure, m.advance)
    assert_in("unmet acceptance criteria",
              " ".join(f.message for f in m.check_report.failures))


@S.test
def test_checks_report_missing_artefacts():
    """checks.py on an empty directory fails loudly rather than passing vacuously."""
    rep = run_checks(fresh("empty"))
    assert_true(not rep.passed)
    assert_in("missing artefacts", rep.failures[0].message)


@S.test
def test_routing_is_deterministic():
    """Same input twice => byte-identical routing. Required for digest stability."""
    obj = engine.Objective(**{k: OBJECTIVE[k] for k in
                              ("id", "statement", "budget_units", "deadline_iso")})
    a = engine.route(engine.decompose(obj, SPEC))
    b = engine.route(engine.decompose(obj, SPEC))
    assert_eq(a, b, "routing must be deterministic")


# ------------------------------------------------------ commit-first (NEW)

@S.test
def test_anchored_acceptor_is_refused():
    """REQUIRED: an acceptor that has SEEN the artefacts cannot commit.

    This is the defect the commit-first redesign closes. Identity separation
    proved the acceptor was a different principal; it did nothing to stop that
    principal reading the work first and then forming an opinion anchored to
    it. The machine now refuses the commitment outright if any declared
    artefact is already on disk."""
    d = fresh("anchored")
    # Produce a complete run first, so the artefacts exist.
    m0, kp0, ac0 = drive_to_gate(d)
    assert_true(os.path.exists(os.path.join(d, "reconciliation.json")))

    # Now a second acceptor tries to commit AFTER reading the workdir.
    kp = reviewer()
    m = OperatorMachine(PACK, d, "orchestrator-02", kp.commitments(),
                        artefact_names=["objective.json", "commissions.json",
                                        "routing_table.json", "reconciliation.json"])
    late = make_acceptor("reviewer-independent-01", OBJECTIVE, SPEC, GOOD_RETURNS)
    err = expect_raises(exp.AnchoringError, m.register_expectation, late.commitment())
    assert_in("already", str(err))
    assert_in("anchored", str(err))


@S.test
def test_commit_first_is_mandatory():
    """A machine with no committed expectation cannot leave PREFLIGHT."""
    kp = reviewer()
    m = build_machine(fresh("nocommit"), "orchestrator-01", kp.commitments(),
                      OBJECTIVE, SPEC, GOOD_RETURNS)      # no acceptor=
    err = expect_raises(exp.AnchoringError, m.advance)
    assert_in("commit-first is mandatory", str(err))
    assert_eq(m.acceptance_independence, "UNCOMMITTED")


@S.test
def test_expectation_cannot_be_retrofitted():
    """An acceptor cannot swap in an expectation matching what it later saw."""
    m, kp, ac = drive_to_gate(fresh("retrofit"))
    tampered = exp.Expectation(
        fields=dict(oracle.extract_actual(m.run_dir), reconciled=False),
        derivation=exp.Derivation.INDEPENDENT_ORACLE)
    fake = exp.ExpectationReveal(ac.reviewer_id, ac._salt, tampered,
                                 ac.inputs_digest)
    ret = exp.AcceptanceReturn(True, kp.issue(m.current_run_digest(), acc.ACCEPT),
                               fake)
    err = expect_raises(exp.ExpectationError, m.advance, acceptance=ret)
    assert_in("does not open the commitment", str(err))


@S.test
def test_divergence_forces_reject_over_acceptor_bit():
    """Machine overrides an ACCEPT bit when artefacts diverge from expectation.

    The acceptor here says ACCEPT with a valid token. The artefacts have been
    altered so they no longer match what it pre-committed. Divergence defaults
    to REJECT and the machine enforces it -- it does not depend on the
    acceptor choosing to be strict."""
    d = fresh("diverge")
    m, kp, ac = drive_to_gate(d)
    p = os.path.join(d, "reconciliation.json")
    recon = read_json(p)
    recon["reconciled"] = False
    recon["missing_returns"] = ["C-PHANTOM"]
    write_json(p, recon)
    err = expect_raises(exp.DivergenceError, m.advance,
                        acceptance=accept_bit(m, kp, ac, bit=True))
    assert_in("diverge", str(err))
    assert_eq(m.verdict, "REJECT")
    ev = [e for e in m.journal if e["event"] == "DIVERGENCE_FORCED_REJECT"][0]
    assert_eq(ev["detail"]["acceptor_said"], "ACCEPT")
    assert_in("reconciled", ev["detail"]["divergent_fields"])
    # And the producer still learns only that it failed, not the field values.
    assert_true("C-PHANTOM" not in str(err),
                "divergence detail must not leak to the producer")


@S.test
def test_oracle_does_not_import_engine():
    """The independence claim rests on the oracle being separate code."""
    assert_no_import(os.path.join(_HERE, "oracle.py"), ["engine"],
                     "sharing the producer's engine would make the expectation "
                     "a reproducibility check, not an independent one")
    # And it must genuinely reach the same answer by its own route.
    e = oracle.derive_expectation(OBJECTIVE, SPEC, GOOD_RETURNS)
    m, kp, ac = drive_to_gate(fresh("oracle-agree"))
    agrees, div = exp.compare(e, oracle.extract_actual(m.run_dir))
    assert_true(agrees, f"independent oracle disagreed with engine: {div}")
    assert_eq(e.derivation, exp.Derivation.INDEPENDENT_ORACLE)
    assert_true(len(e.uncovered) >= 1, "the oracle must state what it does NOT cover")


@S.test
def test_return_state_records_independence_claim():
    """The durable record states HOW independent the acceptance was."""
    m, kp, ac = drive_to_gate(fresh("claim"))
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    rs = read_json(os.path.join(m.run_dir, "return_state.json"))
    assert_eq(rs["acceptance_independence"], "INDEPENDENT_ORACLE")
    assert_true(rs["expectation_digest"], "the accepted expectation is recorded")
    assert_true(rs["expectation_uncovered"],
                "what the expectation does not cover must be on the record")


@S.test
def test_manifest_verifies_and_detects_tamper():
    """MANIFEST.json detects a modified pack file."""
    ok, problems = manifest.verify(_HERE)
    assert_true(ok, f"manifest should verify clean: {problems}")
    victim = os.path.join(_HERE, "engine.py")
    original = open(victim, "rb").read()
    try:
        with open(victim, "ab") as f:
            f.write(b"\n# tamper\n")
        ok2, problems2 = manifest.verify(_HERE)
        assert_true(not ok2, "tampered file must fail manifest verification")
        assert_in("engine.py", " ".join(problems2))
    finally:
        with open(victim, "wb") as f:
            f.write(original)
    ok3, _ = manifest.verify(_HERE)
    assert_true(ok3, "manifest must verify clean again after restore")


if __name__ == "__main__":
    rc = S.run()
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(rc)
