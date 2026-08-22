"""
Pack 07 - runnable proof.

Injected failure: an external agent platform returns a polished, confident,
entirely non-functional capability - README, STATUS.md, results.json claiming
twelve passing tests, and a module that parses but does not run. The pack must
call it NARRATIVE_RETURN, refuse to advance, refuse to promote it out of
quarantine, and then recover by re-commissioning against a tightened spec.

    python3 test_pack.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import traceback
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import acceptance
import checks
import state_machine as sm
from _spine import (
    AcceptanceBudgetExhausted, AcceptanceGate, AcceptanceRefused,
    AnchoredAcceptor, ArtefactWindow, CommitFirstAcceptor, NoPrecommitment,
    PeekedBeforeCommit, Phase, RejectedByAcceptor, SelfAcceptanceRefused,
)

_RESULTS = []


def case(fn):
    _RESULTS.append(fn)
    return fn


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"expected {exc.__name__}, nothing raised")


# --------------------------------------------------------------------------
# the commission
# --------------------------------------------------------------------------
def make_spec(cid="C-1", min_probes=1):
    return sm.CommissionSpec(
        commission_id=cid,
        vendor="acme-agent-platform",
        deliverables=(
            sm.Deliverable(
                path="solver.py", kind="python_module",
                must_define=("solve", "main"),
                probe=sm.Probe(argv=("--selftest",), expect_exit=0,
                               expect_stdout_contains=("SELFTEST OK",)),
            ),
            sm.Deliverable(path="cases.jsonl", kind="jsonl", min_bytes=10),
        ),
        min_probes_passed=min_probes,
    )


# --------------------------------------------------------------------------
# vendor returns
# --------------------------------------------------------------------------
NARRATIVE_README = """# Capability: solver

## Overview
We have **successfully implemented** the requested solver capability.
The implementation is complete and production-ready.

## Testing
All tests pass. The solution has been verified working end-to-end across the
full corpus. There are no known issues.

## Architecture
The solver uses a layered approach with a pluggable strategy interface,
a normalisation pre-pass, and a result cache. Extensive care was taken to
ensure the module is idiomatic, well factored and easy to extend. The design
document below describes each layer in detail, along with the rationale for
every trade-off considered during implementation.
""" + ("\nThe pipeline is organised into discrete, independently testable "
       "stages, each of which is documented in full below.\n" * 12)

NARRATIVE_SOLVER = '''"""Solver capability."""
import sys

CACHE = {}

def solve(case):
    """Solve a single case."""
    raise NotImplementedError("solve() pending integration")

def main():
    raise NotImplementedError("wiring pending")

if __name__ == "__main__":
    main()
'''

MATERIAL_SOLVER = '''"""Solver capability."""
import json
import sys

CACHE = {}

def solve(case):
    return sum(int(x) for x in case["xs"])

def main():
    if "--selftest" in sys.argv:
        assert solve({"xs": [1, 2, 3]}) == 6
        assert solve({"xs": []}) == 0
        print("SELFTEST OK")
        return 0
    for line in sys.stdin:
        if line.strip():
            print(solve(json.loads(line)))
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''

CASES = '{"xs": [1, 2, 3]}\n{"xs": [4, 5]}\n{"xs": []}\n'


def vendor_returns_narrative(q: Path):
    q.mkdir(parents=True, exist_ok=True)
    (q / "README.md").write_text(NARRATIVE_README)
    (q / "STATUS.md").write_text(
        "# Status: COMPLETE\n\nAll checks passing. Ready for production.\n")
    (q / "results.json").write_text(json.dumps(
        {"status": "success", "tests_passed": 12, "tests_failed": 0,
         "coverage": "100%"}, indent=2))
    (q / "solver.py").write_text(NARRATIVE_SOLVER)
    (q / "cases.jsonl").write_text(CASES)


def vendor_returns_material(q: Path):
    q.mkdir(parents=True, exist_ok=True)
    (q / "README.md").write_text("# solver\n\nUsage: `python3 solver.py --selftest`\n")
    (q / "solver.py").write_text(MATERIAL_SOLVER)
    (q / "cases.jsonl").write_text(CASES)


def vendor_returns_partial(q: Path):
    q.mkdir(parents=True, exist_ok=True)
    (q / "solver.py").write_text(MATERIAL_SOLVER)
    # cases.jsonl absent


def vendor_returns_nothing(q: Path):
    q.mkdir(parents=True, exist_ok=True)
    (q / "notes.txt").write_text("work not started; blocked on access\n")


def new_env(tmp, spec=None, tag=""):
    root = Path(tmp) / f"{tag}{uuid.uuid4().hex[:8]}"
    wd, q = root / "work", root / "quarantine"
    gate = AcceptanceGate.generate_keyfile(root / "key")
    spec = spec or make_spec()
    run = sm.CapabilityManufactureRun(wd, "operator-07", gate, spec, q)
    return wd, q, gate, run


def objective_for(run):
    return acceptance.objective_for(run.spec, run.quarantine)


def acceptor(gate, aid="acceptor-QA"):
    return CommitFirstAcceptor(aid, gate,
                               derive=acceptance.derive_expectation,
                               compare=acceptance.compare_to_expectation)


def accept(run, gate):
    return run.finish(acceptor(gate), objective_for(run))


def drive(run, q, vendor_fn):
    run.dispatch()
    run.recover_state()
    vendor_fn(q)
    run.admit_return()
    return run.validate_return()


# ==========================================================================
@case
def t01_material_return_accepted_and_promoted(tmp):
    wd, q, gate, run = new_env(tmp, tag="mat-")
    a = drive(run, q, vendor_returns_material)
    expect(a.verdict == sm.Verdict.MATERIAL.value, f"verdict {a.verdict}")
    run.artefacts_present()
    rep = run.machine_checks()
    expect(rep.ok, f"checks failed: {rep.failed}")
    accept(run, gate)
    moved = run.promote(Path(tmp) / "prod")
    expect(run.phase == Phase.COMPLETE, f"phase {run.phase}")
    return (f"MATERIAL, {a.probes_passed}/{a.probes_defined} probes passed "
            f"under our execution, promoted {moved}")


@case
def t02_INJECTED_narrative_return_refused_then_recovered(tmp):
    """THE INJECTED FAILURE + RECOVERY."""
    wd, q, gate, run = new_env(tmp, tag="narr-")
    a = drive(run, q, vendor_returns_narrative)

    expect(a.verdict == sm.Verdict.NARRATIVE_RETURN.value,
           f"expected NARRATIVE_RETURN, got {a.verdict}: {a.reasoning}")
    expect(a.probes_passed == 0, f"probes should all fail, got {a.probes_passed}")
    expect(a.claims_found, "no completion claims detected")
    expect(any(x["file"] == "results.json" for x in a.self_attestation_ignored),
           f"results.json not excluded: {a.self_attestation_ignored}")

    # solver.py PARSES and defines both symbols - surface conformance is not
    # evidence, and the pack must not be fooled by it
    solver_row = [d for d in a.deliverables if d["path"] == "solver.py"][0]
    expect(solver_row["type_ok"], "solver.py should type-check (that's the trap)")
    expect(solver_row["probe_passed"] is False, "probe should have failed")

    # refuse to advance
    err = raises(sm.ReturnRejected, run.artefacts_present)
    expect(run.phase == Phase.ACTION_EXECUTED, f"advanced anyway: {run.phase}")
    # refuse to promote
    raises(sm.PromotionRefused, run.promote, Path(tmp) / "prod-should-not-exist")
    expect(not (Path(tmp) / "prod-should-not-exist").exists()
           or not any((Path(tmp) / "prod-should-not-exist").iterdir()),
           "narrative return escaped quarantine")

    # ---- recovery: re-commission, tightened, and re-validate -------------
    wd2, q2, gate2, run2 = new_env(tmp, spec=make_spec("C-1-r2", min_probes=1),
                                   tag="recov-")
    a2 = drive(run2, q2, vendor_returns_material)
    expect(a2.verdict == sm.Verdict.MATERIAL.value, f"recovery verdict {a2.verdict}")
    run2.artefacts_present()
    rep = run2.machine_checks()
    expect(rep.ok, f"recovery checks failed: {rep.failed}")
    accept(run2, gate2)
    expect(run2.phase == Phase.COMPLETE, "recovery run did not complete")

    labels = sorted({c["label"] for c in a.claims_found})
    return (f"NARRATIVE_RETURN on {len(a.claims_found)} claim(s) {labels}; "
            f"results.json excluded; {err.__class__.__name__} blocked advance; "
            f"re-commission returned MATERIAL and completed")


@case
def t03_empty_return(tmp):
    wd, q, gate, run = new_env(tmp, tag="empty-")
    a = drive(run, q, vendor_returns_nothing)
    expect(a.verdict == sm.Verdict.EMPTY.value, f"verdict {a.verdict}")
    expect(a.material_bytes == 0, f"material_bytes {a.material_bytes}")
    raises(sm.ReturnRejected, run.artefacts_present)
    return f"EMPTY, 0 material bytes, advance refused"


@case
def t04_partial_return(tmp):
    wd, q, gate, run = new_env(tmp, tag="part-")
    a = drive(run, q, vendor_returns_partial)
    expect(a.verdict == sm.Verdict.PARTIAL.value,
           f"verdict {a.verdict}: {a.reasoning}")
    expect(a.missing == ["cases.jsonl"], f"missing {a.missing}")
    expect(a.probes_passed == 1, f"probes {a.probes_passed}")
    raises(sm.ReturnRejected, run.artefacts_present)
    return f"PARTIAL (1 probe passed, cases.jsonl missing), advance refused"


@case
def t05_spec_cannot_move_after_the_return(tmp):
    wd, q, gate, run = new_env(tmp, tag="spec-")
    run.dispatch(); run.recover_state()
    vendor_returns_partial(q)
    run.admit_return()
    # operator tries to drop the inconvenient deliverable
    run.spec = sm.CommissionSpec(
        commission_id="C-1", vendor="acme-agent-platform",
        deliverables=(run.spec.deliverables[0],), min_probes_passed=1)
    err = raises(sm.SpecMutated, run.validate_return)
    return f"SpecMutated: {str(err)[:78]}"


@case
def t06_quarantine_escape_refused(tmp):
    wd, q, gate, run = new_env(tmp, spec=sm.CommissionSpec(
        commission_id="C-esc", vendor="acme",
        deliverables=(sm.Deliverable(path="../../etc/passwd", kind="text"),),
        min_probes_passed=0), tag="esc-")
    a = drive(run, q, vendor_returns_material)
    expect(a.type_failures and "outside quarantine" in a.type_failures[0],
           f"escape not caught: {a.type_failures}")
    return f"path traversal refused: {a.type_failures[0][:70]}"


@case
def t07_promotion_requires_acceptance_not_just_material(tmp):
    wd, q, gate, run = new_env(tmp, tag="prom-")
    a = drive(run, q, vendor_returns_material)
    expect(a.verdict == sm.Verdict.MATERIAL.value, "setup")
    run.artefacts_present(); run.machine_checks()
    raises(sm.PromotionRefused, run.promote, Path(tmp) / "prod2")
    accept(run, gate)
    run.promote(Path(tmp) / "prod2")
    return "MATERIAL alone refused; promotion allowed only after acceptance"


@case
def t08_producer_cannot_self_advance(tmp):
    wd, q, gate, run = new_env(tmp, tag="self-")
    drive(run, q, vendor_returns_material)
    run.artefacts_present(); run.machine_checks()
    expect(run.phase == Phase.MACHINE_CHECKS_PASSED, f"phase {run.phase}")
    raises(SelfAcceptanceRefused, run.advance, Phase.INDEPENDENT_ACCEPTANCE)
    self_tok = gate.mint(run.run_id, run.ledger.head(), run.producer_id, "PASS", "x")
    raises(SelfAcceptanceRefused, run.advance, Phase.INDEPENDENT_ACCEPTANCE,
           token=self_tok)
    acc = acceptor(gate)
    acc.precommit(run, objective_for(run))
    run.accept_with(acc.decide(run))
    return "self-advance and self-token refused; commit-first token accepted"


@case
def t09_checks_are_not_vacuous(tmp):
    """Forge a MATERIAL verdict with no execution behind it."""
    wd, q, gate, run = new_env(tmp, tag="forge-")
    drive(run, q, vendor_returns_narrative)
    tampered = Path(tmp) / f"tampered-{uuid.uuid4().hex[:6]}"
    shutil.copytree(wd, tampered)
    a = json.loads((tampered / "assessment.json").read_text())
    a["verdict"] = "MATERIAL"
    a["probes_passed"] = 2
    (tampered / "assessment.json").write_text(json.dumps(a, indent=2))
    rep = checks.run_checks(tampered)
    expect(not rep.ok, "forged MATERIAL passed checks")
    expect("probe_count_matches_log" in rep.failed,
           f"probe log cross-check did not fire: {rep.failed}")
    expect("material_backed_by_execution" in rep.failed,
           f"execution-evidence check did not fire: {rep.failed}")
    return f"forged MATERIAL caught by {sorted(rep.failed)}"


@case
def t10_acceptor_refuses_after_the_fact_edits(tmp):
    wd, q, gate, run = new_env(tmp, tag="acc-")
    drive(run, q, vendor_returns_material)
    run.artefacts_present(); run.machine_checks()
    a = json.loads((wd / "assessment.json").read_text())
    a["probes_passed"] = 99
    (wd / "assessment.json").write_text(json.dumps(a))
    acc = acceptor(gate)
    acc.precommit(run, objective_for(run))
    err = raises(RejectedByAcceptor, acc.decide, run)
    expect(str(err) == "REJECT", f"channel leaked: {str(err)!r}")
    raises(SelfAcceptanceRefused, run.advance, Phase.INDEPENDENT_ACCEPTANCE)
    return f"single-bit REJECT on post-check edit ({str(err)!r})"



@case
def t11_COMMITFIRST_anchored_acceptor_is_refused(tmp):
    wd, q, gate, run = new_env(tmp, tag="anch-")
    drive(run, q, vendor_returns_material)
    run.artefacts_present(); run.machine_checks()
    anchored = AnchoredAcceptor("acceptor-QA", gate, checks.run_checks)
    token = anchored.review(run)
    err = raises(NoPrecommitment, run.advance, Phase.INDEPENDENT_ACCEPTANCE,
                 token=token)
    expect(run.phase == Phase.MACHINE_CHECKS_PASSED, f"advanced: {run.phase}")
    return f"anchored token refused: {str(err)[:74]}"


@case
def t12_COMMITFIRST_peek_before_commit_is_refused(tmp):
    wd, q, gate, run = new_env(tmp, tag="peek-")
    drive(run, q, vendor_returns_material)
    run.artefacts_present(); run.machine_checks()
    acc = acceptor(gate)
    ArtefactWindow(run, "acceptor-QA").open()
    err = raises(PeekedBeforeCommit, acc.precommit, run, objective_for(run))
    return f"commitment after peeking refused: {str(err)[:70]}"


@case
def t13_COMMITFIRST_acceptor_runs_the_probes_itself(tmp):
    """A forged MATERIAL assessment cannot survive an acceptor that already ran
    the code and wrote down NARRATIVE_RETURN."""
    wd, q, gate, run = new_env(tmp, tag="own-")
    drive(run, q, vendor_returns_narrative)
    a = json.loads((wd / "assessment.json").read_text())
    a["verdict"] = "MATERIAL"
    a["probes_passed"] = a["probes_defined"]
    (wd / "assessment.json").write_text(json.dumps(a))

    acc = acceptor(gate)
    pre = acc.precommit(run, objective_for(run))
    own = acc._reveal.expected
    expect(own["verdict"] == sm.Verdict.NARRATIVE_RETURN.value,
           f"acceptor committed {own['verdict']}")
    expect(own["probes_passed"] == 0, f"probes {own['probes_passed']}")
    err = raises(RejectedByAcceptor, acc.decide, run)
    expect(err.outcome.reveal.digest() == pre.expected_digest,
           "reveal does not open the commitment")
    return (f"acceptor ran the probes itself and committed "
            f"{own['verdict']} ({own['probes_passed']}/{own['probes_defined']}) "
            f"before reading a forged MATERIAL assessment; REJECT")


@case
def t14_COMMITFIRST_channel_carries_one_bit(tmp):
    wd, q, gate, run = new_env(tmp, tag="bit-")
    drive(run, q, vendor_returns_material)
    run.artefacts_present(); run.machine_checks()
    acc = acceptor(gate)
    acc.precommit(run, objective_for(run))
    out = acc.decide(run)
    fields = sorted(out.to_dict())
    expect(fields == ["accept", "precommitment", "reveal", "run_id", "token"],
           f"channel fields: {fields}")
    run.accept_with(out)
    rep = checks.run_checks(wd)
    expect("acceptance_channel_is_one_bit" not in rep.failed, f"{rep.failed}")
    return f"outcome fields {fields}; accept={out.accept}"


@case
def t15_COMMITFIRST_conservative_update_on_reject(tmp):
    wd, q, gate, run = new_env(tmp, tag="cons-")
    drive(run, q, vendor_returns_material)
    run.artefacts_present(); run.machine_checks()
    good = json.loads((wd / "assessment.json").read_text())
    bad = {**good, "probes_passed": 99}
    (wd / "assessment.json").write_text(json.dumps(bad))

    acc = acceptor(gate)
    pre1 = acc.precommit(run, objective_for(run))
    raises(RejectedByAcceptor, acc.decide, run)

    (wd / "assessment.json").write_text(json.dumps(good))
    acc2 = acceptor(gate)
    pre2 = acc2.precommit(run, objective_for(run))
    expect(pre2.ledger_seq > pre1.ledger_seq, "commitment not fresh")
    run.accept_with(acc2.decide(run))

    acc3 = acceptor(gate)
    raises(AcceptanceBudgetExhausted, acc3.precommit, run, objective_for(run))
    return (f"REJECT at seq {pre1.ledger_seq}; fresh commitment at "
            f"{pre2.ledger_seq} accepted; third attempt refused on budget")


# ==========================================================================
def main() -> int:
    print("=" * 74)
    print("PACK 07  capability-manufacture  -  test_pack.py")
    print("=" * 74)
    tmp = tempfile.mkdtemp(prefix="p07-")
    failures = 0
    for fn in _RESULTS:
        try:
            detail = fn(tmp)
            print(f"  PASS  {fn.__name__}\n          {detail}")
        except Exception:  # noqa: BLE001
            failures += 1
            print(f"  FAIL  {fn.__name__}")
            print("        " + traceback.format_exc().replace("\n", "\n        "))
    print("-" * 74)
    print(f"  {len(_RESULTS) - failures}/{len(_RESULTS)} passed")
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
