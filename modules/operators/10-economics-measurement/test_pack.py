"""
Pack 10 - runnable proof.

Injected failure: a cost campaign in which 500 000 micro-USD of harness cost
is booked under a basis the pack does not recognise. Left out of the report,
config `weak-in-strong` looks like the cheapest thing anyone has ever run.
The pack refuses to publish at all, and the recovery - reclassifying that
spend as HARNESS - is what makes the weak model stop looking strong.

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
    AnchoredAcceptor, ArtefactWindow, AttestedAcceptance, CommitFirstAcceptor,
    NoIndependentExpectation, NoPrecommitment, PeekedBeforeCommit, Phase,
    RejectedByAcceptor, SelfAcceptanceRefused,
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
# the campaign
#
#   weak-in-strong : cheap model, heavy scaffold. 300 attempts for 90 units.
#   strong-light   : expensive model, thin scaffold. 100 attempts for 95 units.
#
# On MODEL cost per accepted unit, weak-in-strong wins by ~6x.
# On TOTAL cost per accepted unit, it loses.
# --------------------------------------------------------------------------
E = sm.CostEvent
U = sm.WorkUnit

WEAK = "weak-in-strong"
STRONG = "strong-light"
WEAK_TOTAL = 660_000
STRONG_TOTAL = 440_000


def weak_events(misc_basis="orchestration_tokens"):
    return [
        E("w-e1", WEAK, "input_tokens", 40_000),
        E("w-e2", WEAK, "output_tokens", 20_000),
        E("w-e3", WEAK, "tool_invocation", 100_000),
        # the 500k that decides the whole comparison
        E("w-e4", WEAK, misc_basis, 500_000, detail="scaffold driver loop"),
    ]


def strong_events():
    return [
        E("s-e1", STRONG, "input_tokens", 250_000),
        E("s-e2", STRONG, "output_tokens", 150_000),
        E("s-e3", STRONG, "verification_pass", 30_000),
        E("s-e4", STRONG, "acceptance_review", 10_000),
    ]


def units(config_id, n_units, n_accepted, n_first_pass, attempts_each):
    out = []
    for i in range(n_units):
        acc = i < n_accepted
        fp = i < n_first_pass
        out.append(U(f"{config_id}-u{i:03d}", config_id,
                     attempts=1 if fp else attempts_each,
                     accepted=acc, produced_by=f"producer-{config_id}",
                     accepted_by="acceptor-QA" if acc else None,
                     first_pass=fp))
    return out


def weak_units():
    # 100 units, 90 accepted, 20 first pass; 300 total attempts
    return units(WEAK, 100, 90, 20, 4)


def strong_units():
    # 100 units, 95 accepted, 90 first pass; 110 total attempts
    return units(STRONG, 100, 95, 90, 2)


def new_run(tmp, tag="econ"):
    root = Path(tmp) / f"{tag}-{uuid.uuid4().hex[:8]}"
    gate = AcceptanceGate.generate_keyfile(root / "key")
    run = sm.EconomicsMeasurementRun(root / "work", "operator-10", gate, "CAMP-1")
    return run, gate


def write_meter(tmp, weak_model=60_000, weak_harness=600_000,
                weak_accepted=90, strong_accepted=95):
    """An independent meter: a billing export the producer does not write."""
    path = Path(tmp) / f"meter-{uuid.uuid4().hex[:8]}.json"
    path.write_text(json.dumps({"configs": {
        WEAK: {"model_micro": weak_model, "harness_micro": weak_harness,
               "accepted_units": weak_accepted, "attempted_units": 100},
        STRONG: {"model_micro": 400_000, "harness_micro": 40_000,
                 "accepted_units": strong_accepted, "attempted_units": 100},
    }}, indent=2))
    return path


def objective_for(meter=None):
    return acceptance.objective_for(
        "CAMP-1", {WEAK: WEAK_TOTAL, STRONG: STRONG_TOTAL},
        meter_path=str(meter) if meter else None)


def acceptor(gate, aid="acceptor-QA"):
    return CommitFirstAcceptor(aid, gate,
                               derive=acceptance.derive_expectation,
                               compare=acceptance.compare_to_expectation)


def accept(run, gate, meter):
    return run.finish(acceptor(gate), objective_for(meter))


def drive(run, misc_basis="orchestration_tokens"):
    run.preflight({WEAK: WEAK_TOTAL, STRONG: STRONG_TOTAL})
    run.recover_state()
    run.admit(weak_events(misc_basis) + strong_events(),
              weak_units() + strong_units())
    run.measure()
    return run.publish()


# ==========================================================================
@case
def t01_happy_path_full_lifecycle(tmp):
    run, gate = new_run(tmp, "happy")
    r = drive(run)
    rep = run.machine_checks()
    expect(rep.ok, f"checks failed: {rep.failed}")
    accept(run, gate, write_meter(tmp))
    expect(run.phase == Phase.COMPLETE, f"phase {run.phase}")
    return (f"PUBLISHED, {len(r['configs'])} configs, "
            f"{len(r['comparisons'])} comparison(s), {len(rep.checks)} checks green")


@case
def t02_INJECTED_unattributed_cost_refused_then_reclassified(tmp):
    """THE INJECTED FAILURE + RECOVERY."""
    run, gate = new_run(tmp, "unattrib")
    run.preflight({WEAK: WEAK_TOTAL, STRONG: STRONG_TOTAL})
    run.recover_state()

    err = raises(sm.UnattributedCost, run.admit,
                 weak_events("misc_overhead") + strong_events(),
                 weak_units() + strong_units())
    expect("misc_overhead" in str(err), f"reason: {err}")
    expect("neither MODEL nor HARNESS" in str(err), f"reason: {err}")
    expect(run.phase == Phase.CURRENT_STATE_RECOVERED,
           f"advanced despite refusal: {run.phase}")

    # the second guard: dropping the inconvenient event does not help either
    run2, gate2 = new_run(tmp, "dropped")
    run2.preflight({WEAK: WEAK_TOTAL, STRONG: STRONG_TOTAL})
    run2.recover_state()
    err2 = raises(sm.UnreconciledSpend, run2.admit,
                  weak_events()[:3] + strong_events(),
                  weak_units() + strong_units())
    expect("500000" in str(err2), f"gap not named: {err2}")

    # ---- recovery: reclassify as HARNESS and publish ---------------------
    run3, gate3 = new_run(tmp, "recov")
    r = drive(run3, "orchestration_tokens")
    w = r["configs"][WEAK]
    expect(w["harness_micro"] == 600_000, f"harness {w['harness_micro']}")
    expect(w["model_micro"] == 60_000, f"model {w['model_micro']}")
    expect(w["harness_amplification"] == 10.0, f"amp {w['harness_amplification']}")
    rep = run3.machine_checks()
    expect(rep.ok, f"recovery checks failed: {rep.failed}")
    accept(run3, gate3, write_meter(tmp))
    return (f"UnattributedCost refused admission; dropping the event hit "
            f"UnreconciledSpend naming the 500000 gap; after reclassification "
            f"{WEAK} shows amplification {w['harness_amplification']}x and "
            f"harness share {w['harness_share']}")


@case
def t03_weak_model_in_strong_harness_is_not_mistaken_for_strong(tmp):
    """The measurement this pack exists to get right."""
    run, gate = new_run(tmp, "trap")
    r = drive(run)
    w = r["configs"][WEAK]
    s = r["configs"][STRONG]
    c = r["comparisons"][0]

    # 1. on model cost alone, the weak config looks far cheaper
    mw, ms = w["model_per_accepted_micro"], s["model_per_accepted_micro"]
    expect(mw < ms, f"model-only trap absent: {mw} vs {ms}")
    ratio = round(ms / mw, 2)
    expect(ratio > 3, f"model-only advantage only {ratio}x - trap too weak")

    # 2. on total cost it loses
    tw, ts = w["cost_per_accepted_micro"], s["cost_per_accepted_micro"]
    expect(tw > ts, f"total-cost reversal absent: {tw} vs {ts}")

    # 3. the pack says so explicitly
    expect(c["model_only_is_misleading"] is True,
           "pack did not flag the model-only view as misleading")
    expect(c["model_only_ranking"][0] == WEAK, f"{c['model_only_ranking']}")
    expect(c["raw_ranking"][0] == STRONG, f"{c['raw_ranking']}")

    # 4. and refuses the raw comparison outright
    expect(c["verdict"] == "NOT_COMPARABLE", f"verdict {c['verdict']}")
    expect(c["amplification_ratio"] > sm.AMPLIFICATION_RATIO_THRESHOLD,
           f"ratio {c['amplification_ratio']}")

    # 5. equal-harness re-scoring keeps the honest ranking
    expect(c["normalised_ranking"][0] == STRONG,
           f"normalised {c['normalised_cost_per_accepted']}")

    # 6. the yield metric tells the same story independently of money
    expect(w["first_pass_yield"] < s["first_pass_yield"],
           f"yield {w['first_pass_yield']} vs {s['first_pass_yield']}")
    return (f"model-only says {WEAK} is {ratio}x cheaper ({mw} vs {ms}); total "
            f"cost says {STRONG} wins ({tw} vs {ts}); verdict NOT_COMPARABLE at "
            f"{c['amplification_ratio']}x amplification; equal-harness ranking "
            f"{c['normalised_ranking']}; first-pass yield "
            f"{w['first_pass_yield']} vs {s['first_pass_yield']}")


@case
def t04_zero_accepted_units_is_undefined_not_cheap(tmp):
    run, gate = new_run(tmp, "zero")
    cid = "never-shipped"
    run.preflight({cid: 100_000})
    run.recover_state()
    run.admit([E("z1", cid, "input_tokens", 60_000),
               E("z2", cid, "retry_overhead", 40_000)],
              [U(f"{cid}-u{i}", cid, attempts=5, accepted=False,
                 produced_by="p") for i in range(20)])
    m = run.measure()[cid]
    expect(m.units_accepted == 0, "setup")
    expect(m.cost_per_accepted_micro is None,
           f"computed a cost per accepted unit: {m.cost_per_accepted_micro}")
    expect(m.status == "NO_ACCEPTED_UNITS", f"status {m.status}")
    expect(m.attempts_per_accepted is None, "attempts_per_accepted should be None")
    per_attempt = round(m.total_micro / m.units_attempted, 6)
    expect(m.cost_per_accepted_micro != per_attempt,
           "fell back to cost per attempt")
    r = run.publish()
    expect(r["configs_with_no_accepted_units"] == [cid], f"{r}")
    rep = run.machine_checks()
    expect(rep.ok, f"checks failed: {rep.failed}")
    return (f"20 attempted, 0 accepted, {m.total_micro} micro-USD spent -> "
            f"cost_per_accepted=None, status NO_ACCEPTED_UNITS "
            f"(cost per ATTEMPT would have been {per_attempt})")


@case
def t05_self_accepted_unit_refused(tmp):
    run, gate = new_run(tmp, "selfacc")
    run.preflight({"c": 1000}); run.recover_state()
    err = raises(sm.SelfAcceptedUnit, run.admit,
                 [E("e1", "c", "input_tokens", 1000)],
                 [U("u1", "c", attempts=1, accepted=True,
                    produced_by="agent-7", accepted_by="agent-7", first_pass=True)])
    return f"{str(err)[:88]}"


@case
def t06_comparable_configs_are_not_refused(tmp):
    """The threshold must not refuse everything - a control that always says
    NOT_COMPARABLE is not a control."""
    run, gate = new_run(tmp, "comparable")
    a, b = "cfg-a", "cfg-b"
    run.preflight({a: 120_000, b: 110_000})
    run.recover_state()
    run.admit(
        [E("a1", a, "input_tokens", 100_000), E("a2", a, "tool_invocation", 20_000),
         E("b1", b, "input_tokens", 90_000), E("b2", b, "tool_invocation", 20_000)],
        units(a, 10, 9, 8, 2) + units(b, 10, 8, 7, 2))
    run.measure()
    r = run.publish()
    c = r["comparisons"][0]
    expect(c["verdict"] == "COMPARABLE",
           f"refused a fair comparison: {c['verdict']} / {c['reason']}")
    expect(c["amplification_ratio"] <= sm.AMPLIFICATION_RATIO_THRESHOLD,
           f"ratio {c['amplification_ratio']}")
    rep = run.machine_checks()
    expect(rep.ok, f"checks failed: {rep.failed}")
    return (f"amplification {c['amplification']} -> ratio "
            f"{c['amplification_ratio']}x -> COMPARABLE; ranking {c['raw_ranking']}")


@case
def t07_bad_unit_shapes_refused(tmp):
    run, gate = new_run(tmp, "shapes")
    run.preflight({"c": 1000}); run.recover_state()
    led = sm.CostLedger("c", 1000)
    raises(sm.EconomicsError, led.add_unit,
           U("u1", "c", attempts=0, accepted=False, produced_by="p"))
    raises(sm.EconomicsError, led.add_unit,
           U("u2", "c", attempts=1, accepted=True, produced_by="p"))
    raises(sm.EconomicsError, led.add_unit,
           U("u3", "c", attempts=3, accepted=True, produced_by="p",
             accepted_by="q", first_pass=True))
    raises(sm.EconomicsError, led.add_unit,
           U("u4", "c", attempts=1, accepted=False, produced_by="p",
             first_pass=True))
    raises(sm.EconomicsError, led.add_event,
           E("neg", "c", "input_tokens", -5))
    return ("zero attempts, acceptor-less acceptance, first_pass with 3 "
            "attempts, first_pass without acceptance, negative cost - all refused")


@case
def t08_producer_cannot_self_advance(tmp):
    run, gate = new_run(tmp, "self")
    drive(run)
    run.machine_checks()
    expect(run.phase == Phase.MACHINE_CHECKS_PASSED, f"phase {run.phase}")
    raises(SelfAcceptanceRefused, run.advance, Phase.INDEPENDENT_ACCEPTANCE)
    self_tok = gate.mint(run.run_id, run.ledger.head(), run.producer_id, "PASS", "x")
    raises(SelfAcceptanceRefused, run.advance, Phase.INDEPENDENT_ACCEPTANCE,
           token=self_tok)
    acc = acceptor(gate)
    acc.precommit(run, objective_for(write_meter(tmp)))
    run.accept_with(acc.decide(run))
    return "self-advance and self-token refused; commit-first token accepted"


@case
def t09_checks_are_not_vacuous(tmp):
    run, gate = new_run(tmp, "vac")
    drive(run)
    wd = run.workdir
    expect(checks.run_checks(wd).ok, "clean run should pass")

    # (a) inflate the model share to make the weak config look good
    t1 = Path(tmp) / f"t1-{uuid.uuid4().hex[:6]}"
    shutil.copytree(wd, t1)
    r = json.loads((t1 / "economics_report.json").read_text())
    r["configs"][WEAK]["harness_micro"] = 1
    r["configs"][WEAK]["cost_per_accepted_micro"] = 667.0
    (t1 / "economics_report.json").write_text(json.dumps(r, indent=2))
    r1 = checks.run_checks(t1)
    expect("totals_rederived_from_events" in r1.failed,
           f"totals check silent: {r1.failed}")
    expect("ratios_rederived_from_events" in r1.failed,
           f"ratio check silent: {r1.failed}")

    # (b) flip a comparison verdict to hide the refusal
    t2 = Path(tmp) / f"t2-{uuid.uuid4().hex[:6]}"
    shutil.copytree(wd, t2)
    r2j = json.loads((t2 / "economics_report.json").read_text())
    r2j["comparisons"][0]["verdict"] = "COMPARABLE"
    (t2 / "economics_report.json").write_text(json.dumps(r2j, indent=2))
    r2 = checks.run_checks(t2)
    expect("comparability_verdicts_consistent" in r2.failed,
           f"comparability check silent: {r2.failed}")

    # (c) sneak a self-accepted unit into the evidence
    t3 = Path(tmp) / f"t3-{uuid.uuid4().hex[:6]}"
    shutil.copytree(wd, t3)
    with open(t3 / "work_units.jsonl", "a") as fh:
        fh.write(json.dumps({"unit_id": "sneak", "config_id": WEAK, "attempts": 1,
                             "accepted": True, "produced_by": "p",
                             "accepted_by": "p", "first_pass": True}) + "\n")
    r3 = checks.run_checks(t3)
    expect("no_self_accepted_units" in r3.failed,
           f"self-acceptance check silent: {r3.failed}")
    return ("forged harness total, flipped comparability verdict and injected "
            "self-accepted unit all caught independently")


@case
def t10_acceptor_refuses_post_check_edit(tmp):
    run, gate = new_run(tmp, "acc")
    drive(run)
    run.machine_checks()
    r = json.loads((run.workdir / "economics_report.json").read_text())
    r["configs"][WEAK]["cost_per_accepted_micro"] = 1.0
    (run.workdir / "economics_report.json").write_text(json.dumps(r))
    acc = acceptor(gate)
    acc.precommit(run, objective_for(write_meter(tmp)))
    err = raises(RejectedByAcceptor, acc.decide, run)
    expect(str(err) == "REJECT", f"channel leaked: {str(err)!r}")
    raises(SelfAcceptanceRefused, run.advance, Phase.INDEPENDENT_ACCEPTANCE)
    return f"single-bit REJECT against the meter ({str(err)!r})"



@case
def t11_COMMITFIRST_anchored_acceptor_is_refused(tmp):
    run, gate = new_run(tmp, "anch")
    drive(run)
    run.machine_checks()
    anchored = AnchoredAcceptor("acceptor-QA", gate, checks.run_checks)
    token = anchored.review(run)
    err = raises(NoPrecommitment, run.advance, Phase.INDEPENDENT_ACCEPTANCE,
                 token=token)
    expect(run.phase == Phase.MACHINE_CHECKS_PASSED, f"advanced: {run.phase}")
    return f"anchored token refused: {str(err)[:74]}"


@case
def t12_COMMITFIRST_peek_before_commit_is_refused(tmp):
    run, gate = new_run(tmp, "peek")
    drive(run)
    run.machine_checks()
    acc = acceptor(gate)
    ArtefactWindow(run, "acceptor-QA").open()
    err = raises(PeekedBeforeCommit, acc.precommit, run,
                 objective_for(write_meter(tmp)))
    return f"commitment after peeking refused: {str(err)[:70]}"


@case
def t13_COMMITFIRST_NO_METER_refuses_to_fabricate(tmp):
    """THE HONEST LIMIT. With no independent meter the acceptor cannot derive
    a cost figure it never observed, so it makes no commitment at all."""
    run, gate = new_run(tmp, "nometer")
    drive(run)
    run.machine_checks()
    obj = objective_for(None)
    expect(obj.derivable is False, "objective should be non-derivable")
    expect(obj.independence_basis == "NONE", obj.independence_basis)

    acc = acceptor(gate)
    err = raises(NoIndependentExpectation, acc.precommit, run, obj)
    expect("fabricate" in str(err), f"reason: {err}")
    expect(run.phase == Phase.MACHINE_CHECKS_PASSED, "advanced anyway")

    # the only sanctioned route: attested, and labelled as such
    att = AttestedAcceptance("cfo-human", gate)
    run.finish_attested(att, obj, "reviewed the invoice by hand, 2026-08-20")
    expect(run.phase == Phase.COMPLETE, f"phase {run.phase}")
    rs = json.loads((run.workdir / "return_state.json").read_text())
    expect(rs["acceptance_machine_enforced"] is False,
           f"artefact claims machine enforcement: {rs}")
    expect(rs["magnitude_acceptance"] == "BEHAVIOURAL_ONLY", rs)
    expect(rs["independence_basis"] == "NONE", rs)
    return ("no meter -> NoIndependentExpectation, no commitment fabricated; "
            "attested route completes with acceptance_machine_enforced=false "
            "and magnitude_acceptance=BEHAVIOURAL_ONLY in the artefact")


@case
def t14_COMMITFIRST_meter_catches_fabricated_events(tmp):
    """With a meter, commit-first reaches the failure the old design could not:
    events that reconcile perfectly to a declared total that is itself a lie."""
    run, gate = new_run(tmp, "fab")
    drive(run)
    run.machine_checks()
    rep = checks.run_checks(run.workdir)
    expect(rep.ok, f"producer's own checks pass: {rep.failed}")

    # the meter says the weak config really burned 1.2M of harness, not 600k
    meter = write_meter(tmp, weak_harness=1_200_000)
    acc = acceptor(gate)
    pre = acc.precommit(run, objective_for(meter))
    own = acc._reveal.expected["configs"][WEAK]
    expect(own["harness_micro"] == 1_200_000, own)
    err = raises(RejectedByAcceptor, acc.decide, run)
    expect(err.outcome.reveal.digest() == pre.expected_digest,
           "reveal does not open the commitment")
    return (f"producer's internally-consistent report passed every machine "
            f"check; meter-derived commitment said harness=1200000 vs "
            f"reported 600000; REJECT")


@case
def t15_COMMITFIRST_channel_carries_one_bit(tmp):
    run, gate = new_run(tmp, "bit")
    drive(run)
    run.machine_checks()
    acc = acceptor(gate)
    acc.precommit(run, objective_for(write_meter(tmp)))
    out = acc.decide(run)
    fields = sorted(out.to_dict())
    expect(fields == ["accept", "precommitment", "reveal", "run_id", "token"],
           f"channel fields: {fields}")
    run.accept_with(out)
    rep = checks.run_checks(run.workdir)
    expect("acceptance_channel_is_one_bit" not in rep.failed, f"{rep.failed}")
    return f"outcome fields {fields}; accept={out.accept}"


@case
def t16_COMMITFIRST_conservative_update_on_reject(tmp):
    run, gate = new_run(tmp, "cons")
    drive(run)
    run.machine_checks()
    acc = acceptor(gate)
    pre1 = acc.precommit(run, objective_for(write_meter(tmp, weak_harness=999)))
    raises(RejectedByAcceptor, acc.decide, run)

    acc2 = acceptor(gate)
    pre2 = acc2.precommit(run, objective_for(write_meter(tmp)))
    expect(pre2.ledger_seq > pre1.ledger_seq, "commitment not fresh")
    run.accept_with(acc2.decide(run))

    acc3 = acceptor(gate)
    raises(AcceptanceBudgetExhausted, acc3.precommit, run,
           objective_for(write_meter(tmp)))
    return (f"REJECT at seq {pre1.ledger_seq}; fresh commitment at "
            f"{pre2.ledger_seq} accepted; third attempt refused on budget")


# ==========================================================================
def main() -> int:
    print("=" * 74)
    print("PACK 10  economics-measurement  -  test_pack.py")
    print("=" * 74)
    tmp = tempfile.mkdtemp(prefix="p10-")
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
