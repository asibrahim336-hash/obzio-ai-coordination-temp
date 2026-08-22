#!/usr/bin/env python3
"""founder-intent-processing pack tests.

INJECTED FAILURE: an implication that reaches zero surfaces (the registry has
no `clarification` surface), so an ambiguous correction would be silently
dropped. The pack must refuse to advance, and must complete once the registry
gains the missing surface.
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
TMP = tempfile.mkdtemp(prefix="fip-")

CORRECTION = (
    "Stop sending client drafts before I have reviewed them. "
    "Actually the launch date is March, not April. "
    "For this one, use the short template."
)

# Registry WITHOUT a clarification surface -> the injected failure.
REGISTRY_BROKEN = {
    "ops-policy":   {"kind": "doc",    "path": "docs/ops.md",     "tags": ["policy"]},
    "draft-prompt": {"kind": "prompt", "path": "prompts/dr.txt",  "tags": ["prompt"]},
    "site-copy":    {"kind": "page",   "path": "web/index.html",  "tags": ["published", "reference"]},
    "run-notes":    {"kind": "note",   "path": "runs/notes.md",   "tags": ["instance"]},
}
# Registry WITH one -> the recovery.
REGISTRY_GOOD = dict(REGISTRY_BROKEN,
                     **{"open-questions": {"kind": "doc", "path": "docs/q.md",
                                           "tags": ["clarification"]}})


def fresh(n):
    d = os.path.join(TMP, n)
    os.makedirs(d, exist_ok=True)
    return d


def reviewer():
    return acc.ReviewerKeypair.generate("reviewer-intent-01")


def drive(run_dir, registry=REGISTRY_GOOD, text=CORRECTION, producer="intent-op-01",
          steps=6):
    """Commit-first: expectation derived and committed before work runs."""
    kp = reviewer()
    ac = make_acceptor("reviewer-intent-01", text, registry)
    m = build_machine(run_dir, producer, kp.commitments(), text, registry,
                      acceptor=ac)
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
def test_full_lifecycle_reaches_complete():
    """Nominal run over a 3-sentence correction with a complete registry."""
    m, kp, ac = drive(fresh("happy"))
    assert_eq(m.state, State.INDEPENDENT_ACCEPTANCE)
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    assert_eq(m.state, State.COMPLETE)
    rs = read_json(os.path.join(m.run_dir, "return_state.json"))
    assert_eq(rs["verdict"], "ACCEPT")
    assert_eq(rs["final_state"], "COMPLETE")


@S.test
def test_literal_and_inferred_are_separated():
    """The core deliverable: claims and implications are distinct records."""
    m, kp, ac = drive(fresh("sep"))
    interp = read_json(os.path.join(m.run_dir, "interpretation.json"))
    claims = interp["literal_claims"]
    imps = interp["system_implications"]
    assert_eq(len(claims), 3, "three sentences, three claims")
    assert_true(len(imps) >= 3, "at least one implication per claim")
    for im in imps:
        assert_eq(im["inferred"], True, f"{im['id']} must be marked inferred")
        assert_true(im["derived_from"].startswith("CL-"))
    # No implication statement may be attributed to the founder.
    src = read_json(os.path.join(m.run_dir, "correction.json"))["source_text"]
    for im in imps:
        assert_true(im["statement"] not in src,
                    f"{im['id']} statement must be the operator's own words")


@S.test
def test_claims_are_verbatim_against_source():
    """Every claim span reproduces the source byte-for-byte."""
    m, kp, ac = drive(fresh("verbatim"))
    src = read_json(os.path.join(m.run_dir, "correction.json"))["source_text"]
    for c in read_json(os.path.join(m.run_dir, "interpretation.json"))["literal_claims"]:
        assert_eq(src[c["start"]:c["end"]], c["text"], f"{c['id']} span mismatch")


@S.test
def test_scope_classification():
    """STANDING / ONE_OFF are distinguished; unmarked text stays AMBIGUOUS."""
    claims = engine.extract_claims(CORRECTION)
    by_scope = {c.id: (c.scope, c.polarity) for c in claims}
    assert_eq(by_scope["CL-01"], ("STANDING", "PROHIBITION"))
    assert_eq(by_scope["CL-03"][0], "ONE_OFF")
    assert_eq(by_scope["CL-02"][1], "CORRECTION_OF_FACT")


# ------------------------------------------------- INJECTED FAILURE + RECOVERY

@S.test
def test_classifier_blind_spot_is_demonstrated():
    """KNOWN-WEAK: marker-free phrasing misclassifies. Demonstrated, not asserted.

    This test documents a real limit rather than hiding it. `_scope_of` and
    `_polarity_of` are substring matching over fixed marker lists. Text that
    carries intent without carrying a marker is classified wrongly.

    Writing this test found a second gap I had not accounted for: "did not"
    was absent from PROHIBITION_MARKERS, so a prohibition read as a DIRECTIVE.
    That gap is now fixed; the residual gap below is not fixable by adding
    markers, which is the point."""
    # Fixed gap: an explicit negation is now caught.
    c1 = engine.extract_claims("I would rather you did not make a habit of that.")[0]
    assert_eq(c1.polarity, "PROHIBITION", "explicit negation must be caught")
    assert_eq(c1.scope, "AMBIGUOUS", "but scope still cannot be determined")

    # Residual gap: intent with no lexical marker at all.
    c2 = engine.extract_claims("That approach tends to create rework downstream.")[0]
    assert_eq(c2.polarity, "DIRECTIVE",
              "reads as a directive though the founder means 'stop doing it'")
    assert_eq(c2.scope, "AMBIGUOUS")

    # The mitigation is that misclassification fails toward clarification,
    # never toward silently rewriting policy.
    reg = {"q": {"kind": "doc", "path": "q.md", "tags": ["clarification"]},
           "pol": {"kind": "doc", "path": "p.md", "tags": ["policy"]}}
    imps = engine.derive_implications([c2], reg)
    rules = {i.rule_id for i in imps}
    assert_in("R-AMBIGUOUS-SCOPE", rules)
    assert_true("R-STANDING-DIRECTIVE" not in rules,
                "an undetermined scope must NOT reach a standing-policy rule")
    for i in imps:
        assert_eq(i.confidence, "LOW")


@S.test
def test_orphan_implication_blocks_progress():
    """INJECTED FAILURE: no clarification surface, so an implication evaporates."""
    d = fresh("injected")
    kp = reviewer()
    m = build_machine(d, "intent-op-01", kp.commitments(), CORRECTION,
                      REGISTRY_BROKEN,
                      acceptor=make_acceptor("reviewer-intent-01", CORRECTION,
                                             REGISTRY_BROKEN))
    for _ in range(4):
        m.advance()
    assert_eq(m.state, State.REQUIRED_ARTEFACTS_PRESENT)
    err = expect_raises(GuardFailure, m.advance)
    assert_in("MACHINE_CHECKS_PASSED", str(err))
    assert_eq(m.state, State.REQUIRED_ARTEFACTS_PRESENT, "must not have moved")

    msgs = " ".join(f.message for f in m.check_report.failures)
    assert_in("reaches no surface", msgs)
    assert_in("R-AMBIGUOUS-SCOPE", msgs)
    assert_in("CHK-FI-06", " ".join(f.check for f in m.check_report.failures))
    disk = read_json(os.path.join(d, "check_report.json"))
    assert_eq(disk["passed"], False)


@S.test
def test_recovery_after_registering_clarification_surface():
    """RECOVERY: add the clarification surface; the run now completes."""
    d = fresh("recovered")
    m, kp, ac = drive(d, REGISTRY_GOOD)
    assert_true(m.check_report.passed, "checks must pass with a complete registry")
    impact = read_json(os.path.join(d, "surface_impact.json"))
    names = [e["surface"] for e in impact["affected_surfaces"]]
    assert_in("open-questions", names)
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    assert_eq(m.state, State.COMPLETE)


# --------------------------------------------------------- anti-paraphrase set

@S.test
def test_injected_paraphrase_detected():
    """P3: a tidied-up 'quote' no longer matches its span and is caught."""
    d = fresh("paraphrase")
    m, kp, ac = drive(d)
    p = os.path.join(d, "interpretation.json")
    interp = read_json(p)
    interp["literal_claims"][0]["text"] = \
        "Never send client drafts without my review."      # plausible. not said.
    write_json(p, interp)
    rep = run_checks(d)
    assert_true(not rep.passed)
    assert_in("CHK-FI-01", " ".join(f.check for f in rep.failures))
    assert_in("not verbatim", " ".join(f.message for f in rep.failures))


@S.test
def test_unmarked_inference_caught():
    """P4: stripping inferred=true is refused."""
    d = fresh("unmarked")
    m, kp, ac = drive(d)
    p = os.path.join(d, "interpretation.json")
    interp = read_json(p)
    interp["system_implications"][0]["inferred"] = False
    write_json(p, interp)
    rep = run_checks(d)
    assert_in("CHK-FI-02", " ".join(f.check for f in rep.failures))


@S.test
def test_untraceable_implication_caught():
    """P5: an implication pointing at a non-existent claim is refused."""
    d = fresh("untraceable")
    m, kp, ac = drive(d)
    p = os.path.join(d, "interpretation.json")
    interp = read_json(p)
    interp["system_implications"][0]["derived_from"] = "CL-99"
    write_json(p, interp)
    rep = run_checks(d)
    assert_in("CHK-FI-03", " ".join(f.check for f in rep.failures))


@S.test
def test_surface_without_order_caught():
    """P6: an affected surface with its order deleted is caught."""
    d = fresh("noorder")
    m, kp, ac = drive(d)
    p = os.path.join(d, "change_orders.json")
    orders = read_json(p)
    victim = orders[0]["surface"]
    write_json(p, [o for o in orders if o["surface"] != victim])
    rep = run_checks(d)
    assert_in("CHK-FI-04", " ".join(f.check for f in rep.failures))
    assert_in(victim, " ".join(f.message for f in rep.failures))


@S.test
def test_phantom_surface_order_caught():
    """P7: an order aimed at a surface not in the impact map is caught."""
    d = fresh("phantom")
    m, kp, ac = drive(d)
    p = os.path.join(d, "change_orders.json")
    orders = read_json(p)
    orders.append({"id": "CO-999", "surface": "secret-backdoor", "action": "AMEND",
                   "detail": "x", "implication_id": orders[0]["implication_id"],
                   "requires_founder_confirmation": False})
    write_json(p, orders)
    rep = run_checks(d)
    assert_in("CHK-FI-05", " ".join(f.check for f in rep.failures))


@S.test
def test_low_confidence_requires_confirmation():
    """P9: LOW-confidence orders must carry a founder-confirmation flag."""
    d = fresh("lowconf")
    m, kp, ac = drive(d)
    orders = read_json(os.path.join(d, "change_orders.json"))
    imps = {i["id"]: i for i in
            read_json(os.path.join(d, "interpretation.json"))["system_implications"]}
    low = [o for o in orders if imps[o["implication_id"]]["confidence"] == "LOW"]
    assert_true(low, "the ambiguous claim should yield a LOW-confidence order")
    for o in low:
        assert_eq(o["requires_founder_confirmation"], True)
    # Now clear the flag and prove the check fires.
    for o in orders:
        o["requires_founder_confirmation"] = False
    write_json(os.path.join(d, "change_orders.json"), orders)
    rep = run_checks(d)
    assert_in("CHK-FI-07", " ".join(f.check for f in rep.failures))


@S.test
def test_oneoff_promotion_caught():
    """P10: applying a ONE_OFF claim to a policy surface is refused."""
    d = fresh("promote")
    m, kp, ac = drive(d)
    interp = read_json(os.path.join(d, "interpretation.json"))
    oneoff = [i for i in interp["system_implications"] if i["rule_id"] == "R-ONEOFF"][0]
    orders = read_json(os.path.join(d, "change_orders.json"))
    orders.append({"id": "CO-888", "surface": "ops-policy", "action": "AMEND",
                   "detail": "promote the one-off", "implication_id": oneoff["id"],
                   "requires_founder_confirmation": False})
    write_json(os.path.join(d, "change_orders.json"), orders)
    rep = run_checks(d)
    assert_in("CHK-FI-08", " ".join(f.check for f in rep.failures))


@S.test
def test_normalisation_would_break_spans():
    """P11: collapsing whitespace invalidates every span downstream of it."""
    d = fresh("normalise")
    m, kp, ac = drive(d, text="  Stop  doing that always.   Use the short template here.  ")
    p = os.path.join(d, "correction.json")
    corr = read_json(p)
    corr["source_text"] = " ".join(corr["source_text"].split())   # "tidy up"
    write_json(p, corr)
    rep = run_checks(d)
    assert_true(not rep.passed, "normalised source must break verbatim checks")
    assert_in("CHK-FI-01", " ".join(f.check for f in rep.failures))


@S.test
def test_empty_correction_refused():
    """An empty correction never reaches extraction."""
    kp = reviewer()
    m = build_machine(fresh("empty"), "intent-op-01", kp.commitments(),
                      "   ", REGISTRY_GOOD,
                      acceptor=make_acceptor("reviewer-intent-01", "   ",
                                             REGISTRY_GOOD))
    m.advance()
    err = expect_raises(GuardFailure, m.advance)
    assert_in("empty correction", str(err))


@S.test
def test_registry_without_tags_refused():
    """A surface with no tags cannot be routed, so recovery refuses it."""
    kp = reviewer()
    reg = {"x": {"kind": "doc", "path": "p"}}
    m = build_machine(fresh("notags"), "intent-op-01", kp.commitments(),
                      CORRECTION, reg,
                      acceptor=make_acceptor("reviewer-intent-01", CORRECTION, reg))
    err = expect_raises(GuardFailure, m.advance)
    assert_in("no tags", str(err))


# ------------------------------------------------------------------- the gate

@S.test
def test_producer_cannot_self_advance():
    """P1: the interpreting process cannot accept its own interpretation."""
    m, kp, ac = drive(fresh("gate"))
    err = expect_raises(acc.AcceptanceError, m.advance)
    assert_in("cannot advance itself", str(err))
    assert_eq(m.state, State.INDEPENDENT_ACCEPTANCE)


@S.test
def test_self_review_machine_refused():
    """P2: producer and reviewer may not be the same principal."""
    kp = acc.ReviewerKeypair.generate("intent-op-01")
    expect_raises(acc.SelfAcceptanceError, OperatorMachine,
                  PACK, fresh("selfrev"), "intent-op-01", kp.commitments())


@S.test
def test_forged_acceptance_refused():
    """Forging a reveal requires a SHA-256 preimage."""
    m, kp, ac = drive(fresh("forge"))
    dg = m.current_run_digest()
    forged = acc.Reveal("reviewer-intent-01", acc.ACCEPT, dg, "guess",
                        acc.bind("guess", dg, acc.ACCEPT))
    expect_raises(acc.AcceptanceError, m.advance,
                  acceptance=exp.AcceptanceReturn(True, forged, ac.reveal()))
    assert_eq(m.state, State.INDEPENDENT_ACCEPTANCE)


@S.test
def test_post_acceptance_tamper_detected():
    """Rewriting an interpretation after sign-off is caught before COMPLETE."""
    d = fresh("tamper")
    m, kp, ac = drive(d)
    m.advance(acceptance=accept_bit(m, kp, ac))
    p = os.path.join(d, "interpretation.json")
    interp = read_json(p)
    interp["literal_claims"][0]["text"] = "whatever I want it to say"
    write_json(p, interp)
    err = expect_raises(TransitionError, m.advance)
    assert_in("changed after acceptance", str(err))
    # And the durable record must NOT have been upgraded to COMPLETE.
    rs = read_json(os.path.join(d, "return_state.json"))
    assert_eq(rs["final_state"], "RETURN_STATE_WRITTEN",
              "a tampered run must not leave a record claiming COMPLETE")


@S.test
def test_determinism():
    """Same correction + registry twice => identical artefact digests."""
    a, _, _ = drive(fresh("det-a"))
    b, _, _ = drive(fresh("det-b"))
    assert_eq(a.current_run_digest(), b.current_run_digest(),
              "interpretation must be deterministic")


@S.test
def test_checks_report_missing_artefacts():
    """checks.py on an empty dir fails rather than passing vacuously."""
    rep = run_checks(fresh("emptydir"))
    assert_true(not rep.passed)
    assert_in("missing artefacts", rep.failures[0].message)


# ------------------------------------------------------ commit-first (NEW)

@S.test
def test_anchored_acceptor_is_refused():
    """REQUIRED: an acceptor that has SEEN the interpretation cannot commit."""
    d = fresh("anchored")
    m0, kp0, ac0 = drive(d)
    assert_true(os.path.exists(os.path.join(d, "interpretation.json")))
    kp = reviewer()
    m = OperatorMachine(PACK, d, "intent-op-02", kp.commitments(),
                        artefact_names=["correction.json", "interpretation.json",
                                        "surface_impact.json", "change_orders.json"])
    late = make_acceptor("reviewer-intent-01", CORRECTION, REGISTRY_GOOD)
    err = expect_raises(exp.AnchoringError, m.register_expectation, late.commitment())
    assert_in("anchored", str(err))


@S.test
def test_commit_first_is_mandatory():
    """No committed expectation means the run cannot leave PREFLIGHT."""
    kp = reviewer()
    m = build_machine(fresh("nocommit"), "intent-op-01", kp.commitments(),
                      CORRECTION, REGISTRY_GOOD)
    err = expect_raises(exp.AnchoringError, m.advance)
    assert_in("commit-first is mandatory", str(err))


@S.test
def test_independent_segmenter_agrees_with_engine():
    """Two separately-written segmenters must recover the same founder words.

    oracle.independent_segment is a character scan; engine.segment is a regex.
    Agreement here is meaningful precisely because the implementations differ.
    Disagreement would diverge the run, which is the right outcome: two
    implementations disputing what the founder SAID needs a human."""
    mine = [t for _, _, t in oracle.independent_segment(CORRECTION)]
    theirs = [t for _, _, t in engine.segment(CORRECTION)]
    assert_eq(mine, theirs)
    assert_no_import(os.path.join(_HERE, "oracle.py"), ["engine"])


@S.test
def test_divergence_on_paraphrase_forces_reject():
    """A paraphrased claim diverges from the pre-committed literal claims.

    This is the commit-first version of the anti-paraphrase control: the
    acceptor already knew what the founder said before the producer spoke."""
    d = fresh("diverge-para")
    m, kp, ac = drive(d)
    p = os.path.join(d, "interpretation.json")
    interp = read_json(p)
    interp["literal_claims"][0]["text"] = "Never send drafts without review."
    write_json(p, interp)
    err = expect_raises(exp.DivergenceError, m.advance,
                        acceptance=accept_bit(m, kp, ac, bit=True))
    assert_eq(m.verdict, "REJECT")
    ev = [e for e in m.journal if e["event"] == "DIVERGENCE_FORCED_REJECT"][0]
    assert_in("claim_texts", ev["detail"]["divergent_fields"])
    assert_true("Never send drafts" not in str(err),
                "the divergent value must not leak back to the producer")


@S.test
def test_partial_oracle_declares_what_it_cannot_cover():
    """This pack CANNOT independently derive the implications. It says so."""
    e = oracle.derive_expectation(CORRECTION, REGISTRY_GOOD)
    assert_eq(e.derivation, exp.Derivation.PARTIAL_ORACLE)
    joined = " ".join(e.uncovered).lower()
    assert_in("judgement", joined)
    assert_true(any("implication" in u.lower() for u in e.uncovered),
                "the uncovered list must name the implications explicitly")
    # And the committed fields must NOT pretend to cover them.
    assert_true(not any("implication_statements" in k for k in e.fields),
                "the oracle must not commit to values it cannot derive")


@S.test
def test_return_state_records_partial_independence():
    """The record says PARTIAL_ORACLE, not INDEPENDENT_ORACLE."""
    m, kp, ac = drive(fresh("claim"))
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    rs = read_json(os.path.join(m.run_dir, "return_state.json"))
    assert_eq(rs["acceptance_independence"], "PARTIAL_ORACLE")
    assert_true(rs["expectation_uncovered"])


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
        assert_true(not ok2, "tampered file must fail verification")
    finally:
        with open(victim, "wb") as f:
            f.write(original)
    assert_true(manifest.verify(_HERE)[0], "clean again after restore")


if __name__ == "__main__":
    rc = S.run()
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(rc)
