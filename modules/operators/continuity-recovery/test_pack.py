#!/usr/bin/env python3
"""continuity-recovery pack tests.

The corpus recovered from is REAL: each test first runs the actual
strategic-orchestration and repository-engineering packs to produce genuine
run directories, then recovers state from those artefacts with no other input.

INJECTED FAILURE: two runs record conflicting budget_units for the same
objective id. The recovery must report the contradiction and must NOT
resolve it.
"""

import importlib.util
import os
import shutil
import subprocess
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
from obzio_spine.artefacts import read_json, write_json, canonical, sha256_bytes
from obzio_spine import manifest

import engine
from checks import run_checks
from state_machine import build_machine, make_acceptor, PACK
import oracle

S = Suite(PACK)
TMP = tempfile.mkdtemp(prefix="cr-")
SO_PACK = os.path.join(_PACKS, "strategic-orchestration")


def fresh(n):
    d = os.path.join(TMP, n)
    os.makedirs(d, exist_ok=True)
    return d


def _load_pack(pack_dir, modname):
    saved = list(sys.path)
    sys.path.insert(0, pack_dir)
    for m in ("state_machine", "checks", "engine", "oracle"):
        sys.modules.pop(m, None)
    try:
        spec = importlib.util.spec_from_file_location(
            modname, os.path.join(pack_dir, "state_machine.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path[:] = saved
        for m in ("state_machine", "checks", "engine", "oracle"):
            sys.modules.pop(m, None)


def make_orchestration_run(root, name, complete=True, missing_return=False):
    """Run the REAL orchestration pack into root/name."""
    sm = _load_pack(SO_PACK, "so_sm_" + name)
    objective = {"id": "OBJ-" + name, "statement": "s", "budget_units": 100,
                 "deadline_iso": "2026-09-30",
                 "orchestrator_max_authority": "WRITE_BRANCH_ONLY"}
    spec = [{"id": "C-A", "title": "alpha", "owner_capability": "research",
             "budget_units": 20, "acceptance_criteria": ["done"]},
            {"id": "C-B", "title": "beta", "owner_capability": "build",
             "budget_units": 30, "acceptance_criteria": ["shipped"]}]
    returns = [{"commission_id": "C-A", "units_spent": 19, "criteria_met": ["done"]}]
    if not missing_return:
        returns.append({"commission_id": "C-B", "units_spent": 28,
                        "criteria_met": ["shipped"]})
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    kp = acc.ReviewerKeypair.generate("rev-" + name)
    sac = sm.make_acceptor("rev-" + name, objective, spec, returns)
    m = sm.build_machine(d, "producer-" + name, kp.commitments(),
                         objective, spec, returns, acceptor=sac)
    steps = 6
    try:
        for _ in range(steps):
            m.advance()
    except Exception:
        return d, m          # a deliberately-broken run stops early
    if complete:
        m.advance(acceptance=exp.AcceptanceReturn(
            True, kp.issue(m.current_run_digest(), acc.ACCEPT), sac.reveal()))
        m.advance()
    return d, m


def make_corpus(name, runs=("run-a", "run-b")):
    root = fresh(name + "-corpus")
    for rn in runs:
        make_orchestration_run(root, rn)
    return root


def reviewer():
    return acc.ReviewerKeypair.generate("reviewer-continuity-01")


def drive(corpus, name, steps=6, producer="continuity-op-01"):
    """Commit-first: the acceptor walks the corpus and commits its own
    headline counts before the recovery produces anything."""
    kp = reviewer()
    ac = make_acceptor("reviewer-continuity-01", corpus)
    m = build_machine(fresh(name), producer, kp.commitments(), corpus,
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
def test_recovers_state_from_a_real_corpus():
    """Two real orchestration runs are recovered with full provenance."""
    corpus = make_corpus("happy")
    m, kp, ac = drive(corpus, "happy-run")
    assert_eq(m.state, State.INDEPENDENT_ACCEPTANCE)
    st = read_json(os.path.join(m.run_dir, "recovered_state.json"))
    assert_eq(st["run_count"], 2)
    assert_eq(st["packs_seen"], ["strategic-orchestration"])
    assert_eq(st["conversation_history_used"], False)
    assert_true(st["recovered_field_count"] > 0)
    for r in st["runs"]:
        assert_eq(r["final_state"], "COMPLETE")
        assert_eq(r["verdict"], "ACCEPT")
        assert_true(r["accepted_run_digest"])
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    assert_eq(m.state, State.COMPLETE)


@S.test
def test_every_recovered_fact_reresolves():
    """The defining property: open the cited file, walk the pointer, compare."""
    corpus = make_corpus("resolve")
    m, kp, ac = drive(corpus, "resolve-run")
    prov = read_json(os.path.join(m.run_dir, "provenance.json"))
    assert_true(prov["fact_count"] >= 10, "expected a substantive fact set")
    for f in prov["facts"]:
        doc = read_json(os.path.join(prov["root"], f["source_file"]))
        assert_eq(engine.resolve_pointer(doc, f["pointer"]), f["value"],
                  f"fact {f['key']} did not re-resolve")


@S.test
def test_file_inventory_is_complete():
    """P8: every scanned file is either used or ignored with a stated reason."""
    corpus = make_corpus("inventory")
    m, kp, ac = drive(corpus, "inventory-run")
    prov = read_json(os.path.join(m.run_dir, "provenance.json"))
    scanned = set(prov["files_scanned"])
    used = set(prov["sources_used"])
    ignored = {x["file"] for x in prov["sources_ignored"]}
    assert_eq(scanned - used - ignored, set(), "nothing may be unaccounted for")
    for x in prov["sources_ignored"]:
        assert_true(x["reason"].strip(), f"{x['file']} ignored with no reason")


@S.test
def test_gaps_are_enumerated_not_guessed():
    """An incomplete run produces explicit gaps rather than a tidy story."""
    root = fresh("gappy-corpus")
    make_orchestration_run(root, "good")
    make_orchestration_run(root, "unfinished", complete=False)
    m, kp, ac = drive(root, "gappy-run")
    gaps = read_json(os.path.join(m.run_dir, "gap_report.json"))
    assert_true(gaps["gap_count"] >= 1, "an unfinished run must produce a gap")
    texts = " ".join(g["missing"] + g["reason"] for g in gaps["gaps"])
    # The unfinished run never wrote return_state.json, so it is an ORPHAN
    # directory: real artefacts, no recorded outcome. It must be surfaced,
    # not skipped.
    assert_in("completion record for unfinished", texts)
    assert_in("no return_state.json", texts)
    for g in gaps["gaps"]:
        assert_true(g["missing"].strip() and g["reason"].strip())
    # And the orphan's last known state is still recovered, with provenance.
    prov = read_json(os.path.join(m.run_dir, "provenance.json"))
    keys = {f["key"]: f["value"] for f in prov["facts"]}
    assert_eq(keys.get("orphan.unfinished.last_state"), "INDEPENDENT_ACCEPTANCE",
              "the orphan run's last state must be recoverable from its journal")


# ------------------------------------------------- INJECTED FAILURE + RECOVERY

@S.test
def test_injected_contradiction_is_reported_unresolved():
    """INJECTED FAILURE: two runs record different budgets for one objective.

    The operator must surface the disagreement and must not pick a winner.
    Choosing silently would destroy the only evidence that something is wrong."""
    root = make_corpus("contradiction", runs=("run-x", "run-y"))
    # Make both runs describe the SAME objective, then have them disagree
    # about its budget. Same logical thing, two incompatible values.
    for rn in ("run-x", "run-y"):
        p = os.path.join(root, rn, "objective.json")
        doc = read_json(p)
        doc["id"] = "OBJ-SHARED"
        if rn == "run-y":
            doc["budget_units"] = 55        # run-x recorded 100
        write_json(p, doc)

    out = engine.recover(root)
    gr = out["gap_report"]
    assert_eq(gr["contradiction_count"], 1, "the disagreement must be detected")
    c = gr["contradictions"][0]
    assert_eq(c["key"], "objective[OBJ-SHARED].budget_units")
    assert_eq(c["resolution"], "UNRESOLVED_BY_DESIGN")
    assert_eq(len(c["sources"]), 2, "both sides must be cited")
    # Both values are preserved; neither is discarded or averaged.
    vals = sorted(s["value"] for s in c["sources"])
    assert_eq(vals, [55, 100])

    # And the full machine run over this corpus still passes its own checks:
    # reporting a contradiction is correct behaviour, not a failure.
    m, kp, ac = drive(root, "contradiction-run")
    assert_true(m.check_report.passed,
                "reporting a contradiction is correct, not a check failure")
    st = read_json(os.path.join(m.run_dir, "recovered_state.json"))
    assert_eq(st["contradiction_count"], 1)


@S.test
def test_resolved_contradiction_caught():
    """RECOVERY-SIDE CONTROL: an operator that resolved a contradiction fails."""
    root = make_corpus("resolved", runs=("run-x", "run-y"))
    for rn in ("run-x", "run-y"):
        p = os.path.join(root, rn, "objective.json")
        doc = read_json(p)
        doc["id"] = "OBJ-SHARED"
        if rn == "run-y":
            doc["budget_units"] = 42
        write_json(p, doc)
    m, kp, ac = drive(root, "resolved-run")
    gp = os.path.join(m.run_dir, "gap_report.json")
    gr = read_json(gp)
    gr["contradictions"][0]["resolution"] = "took the newer value"
    write_json(gp, gr)
    rep = run_checks(m.run_dir)
    assert_true(not rep.passed)
    assert_in("CHK-CR-05", " ".join(f.check for f in rep.failures))
    assert_in("must not choose", " ".join(f.message for f in rep.failures))


@S.test
def test_recovery_after_contradiction_is_resolved_upstream():
    """RECOVERY: once the artefacts agree, the contradiction disappears."""
    root = make_corpus("healed", runs=("run-x", "run-y"))
    out = engine.recover(root)
    assert_eq(out["gap_report"]["contradiction_count"], 0,
              "two independent runs of different objectives are NOT a "
              "contradiction; flagging them would be a false positive")
    m, kp, ac = drive(root, "healed-run")
    assert_true(m.check_report.passed)
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    assert_eq(m.state, State.COMPLETE)


# ------------------------------------------------------- anti-confabulation

@S.test
def test_injected_fabricated_fact_detected():
    """P3: a fact whose value was edited no longer matches its source."""
    corpus = make_corpus("fabricate")
    m, kp, ac = drive(corpus, "fabricate-run")
    p = os.path.join(m.run_dir, "provenance.json")
    prov = read_json(p)
    victim = prov["facts"][0]
    victim["value"] = "a value that is nowhere in the corpus"
    write_json(p, prov)
    rep = run_checks(m.run_dir)
    assert_true(not rep.passed)
    assert_in("CHK-CR-01", " ".join(f.check for f in rep.failures))
    assert_in("actually holds", " ".join(f.message for f in rep.failures))


@S.test
def test_ledger_cannot_be_told_a_value():
    """P3: record() reads from the file; the caller names a place, not a value."""
    import inspect
    sig = inspect.signature(engine.Ledger.record)
    assert_true("value" not in sig.parameters,
                "record() must not accept a caller-supplied value")
    assert_in("key", sig.parameters)
    assert_in("pointer", sig.parameters)


@S.test
def test_fact_requires_provenance():
    """P6: a Fact cannot be constructed without source and pointer."""
    expect_raises(TypeError, engine.Fact, "k", "v")
    f = engine.Fact("k", "v", "a.json", "/x")
    assert_eq(f.source_file, "a.json")
    assert_true(hasattr(engine.Fact, "__hash__"), "frozen dataclass expected")
    expect_raises(Exception, setattr, f, "value", "mutated")


@S.test
def test_dangling_source_detected():
    """P4: citing a file that does not exist is refused at record time."""
    corpus = make_corpus("dangling")
    led = engine.Ledger(corpus)
    err = expect_raises(engine.ProvenanceError, led.record,
                        "k", "no/such/file.json", "/x")
    assert_in("does not exist", str(err))


@S.test
def test_pointer_miss_raises_not_none():
    """P5: a missing key raises rather than returning None."""
    doc = {"a": {"b": [1, 2]}}
    assert_eq(engine.resolve_pointer(doc, "/a/b/0"), 1)
    expect_raises(engine.ProvenanceError, engine.resolve_pointer, doc, "/a/zzz")
    expect_raises(engine.ProvenanceError, engine.resolve_pointer, doc, "/a/b/9")
    expect_raises(engine.ProvenanceError, engine.resolve_pointer, doc, "/a/b/x")
    expect_raises(engine.ProvenanceError, engine.resolve_pointer, doc, "no-slash")


@S.test
def test_out_of_root_source_caught():
    """P7: a fact citing a file outside the recovery root is caught."""
    corpus = make_corpus("outroot")
    m, kp, ac = drive(corpus, "outroot-run")
    p = os.path.join(m.run_dir, "provenance.json")
    prov = read_json(p)
    prov["facts"][0]["source_file"] = "../../../etc/hostname"
    write_json(p, prov)
    rep = run_checks(m.run_dir)
    checks = " ".join(f.check for f in rep.failures)
    assert_true("CHK-CR-03" in checks or "CHK-CR-01" in checks,
                f"expected an out-of-root or resolution failure, got {checks}")


@S.test
def test_unaccounted_file_caught():
    """P8: dropping a file from both used and ignored lists is caught."""
    corpus = make_corpus("unaccounted")
    m, kp, ac = drive(corpus, "unaccounted-run")
    p = os.path.join(m.run_dir, "provenance.json")
    prov = read_json(p)
    prov["sources_ignored"] = []
    write_json(p, prov)
    rep = run_checks(m.run_dir)
    assert_in("CHK-CR-04", " ".join(f.check for f in rep.failures))
    assert_in("neither used nor", " ".join(f.message for f in rep.failures))


@S.test
def test_hidden_gap_caught():
    """P10: quietly shrinking the gap list is caught by cross-counting."""
    corpus = fresh("hidden-corpus")
    make_orchestration_run(corpus, "unfinished", complete=False)
    m, kp, ac = drive(corpus, "hidden-run")
    p = os.path.join(m.run_dir, "gap_report.json")
    gr = read_json(p)
    assert_true(gr["gap_count"] >= 1, "test needs at least one real gap")
    gr["gaps"] = []
    write_json(p, gr)
    rep = run_checks(m.run_dir)
    assert_in("CHK-CR-06", " ".join(f.check for f in rep.failures))


@S.test
def test_no_conversation_flag_enforced():
    """P13: the artefact must positively assert no conversation was used."""
    corpus = make_corpus("noconv")
    m, kp, ac = drive(corpus, "noconv-run")
    p = os.path.join(m.run_dir, "recovered_state.json")
    st = read_json(p)
    st["conversation_history_used"] = True
    write_json(p, st)
    rep = run_checks(m.run_dir)
    assert_in("CHK-CR-07", " ".join(f.check for f in rep.failures))


# --------------------------------------------------------------- determinism

@S.test
def test_recovery_is_byte_reproducible():
    """P11: two recoveries over the same corpus are byte-identical."""
    corpus = make_corpus("determinism")
    a = engine.recover(corpus)
    b = engine.recover(corpus)
    for k in ("recovered_state", "provenance", "gap_report"):
        assert_eq(sha256_bytes(canonical(a[k])), sha256_bytes(canonical(b[k])),
                  f"{k} is not byte-reproducible")


@S.test
def test_nondeterminism_would_be_caught():
    """CHK-CR-08 compares a stored state against a fresh recovery."""
    corpus = make_corpus("nondet")
    m, kp, ac = drive(corpus, "nondet-run")
    p = os.path.join(m.run_dir, "recovered_state.json")
    st = read_json(p)
    st["run_count"] = 99            # as if recovery had produced something else
    write_json(p, st)
    rep = run_checks(m.run_dir)
    assert_in("CHK-CR-08", " ".join(f.check for f in rep.failures))
    assert_in("different state", " ".join(f.message for f in rep.failures))


# ------------------------------------------------------------------- guards

@S.test
def test_output_inside_root_refused():
    """P12: recovery may not write into the corpus it reads."""
    corpus = make_corpus("inside")
    kp = reviewer()
    inner = os.path.join(corpus, "my-output")
    os.makedirs(inner, exist_ok=True)
    m = build_machine(inner, "continuity-op-01", kp.commitments(), corpus,
                      acceptor=make_acceptor("reviewer-continuity-01", corpus))
    err = expect_raises(GuardFailure, m.advance)
    assert_in("ingest its own output", str(err))


@S.test
def test_empty_root_refused():
    """P14: an empty corpus cannot yield a recovery."""
    kp = reviewer()
    ec = fresh("empty-corpus")
    m = build_machine(fresh("empty-out"), "continuity-op-01", kp.commitments(),
                      ec, acceptor=make_acceptor("reviewer-continuity-01", ec))
    err = expect_raises(GuardFailure, m.advance)
    assert_in("contains no artefacts", str(err))


@S.test
def test_side_channel_input_refused():
    """P13: there is no parameter through which remembered context can enter."""
    import inspect
    sig = inspect.signature(build_machine)
    assert_eq(sorted(sig.parameters),
              ["acceptor", "commitments", "producer_id", "recovery_root",
               "run_dir"])
    corpus = make_corpus("sidechannel")
    kp = reviewer()
    m = build_machine(fresh("sidechannel-out"), "continuity-op-01",
                      kp.commitments(), corpus,
                      acceptor=make_acceptor("reviewer-continuity-01", corpus))
    m.advance()
    err = expect_raises(GuardFailure, m.advance,
                        remembered_context="the founder said it was fine")
    assert_in("no side-channel input", str(err))


@S.test
def test_missing_root_refused():
    """A non-existent recovery root is refused, not treated as empty."""
    kp = reviewer()
    missing = os.path.join(TMP, "does-not-exist")
    os.makedirs(missing, exist_ok=True)
    ac0 = make_acceptor("reviewer-continuity-01", missing)
    os.rmdir(missing)
    m = build_machine(fresh("missing-out"), "continuity-op-01", kp.commitments(),
                      missing, acceptor=ac0)
    err = expect_raises(GuardFailure, m.advance)
    assert_in("not a directory", str(err))


# ------------------------------------------------------------------- the gate

@S.test
def test_producer_cannot_self_advance():
    """P1: the recovering process cannot accept its own reconstruction."""
    corpus = make_corpus("gate")
    m, kp, ac = drive(corpus, "gate-run")
    err = expect_raises(acc.AcceptanceError, m.advance)
    assert_in("cannot advance itself", str(err))
    assert_eq(m.state, State.INDEPENDENT_ACCEPTANCE)


@S.test
def test_self_review_machine_refused():
    """P2: producer and reviewer may not be the same principal."""
    kp = acc.ReviewerKeypair.generate("continuity-op-01")
    expect_raises(acc.SelfAcceptanceError, OperatorMachine,
                  PACK, fresh("selfrev"), "continuity-op-01", kp.commitments())


@S.test
def test_post_acceptance_tamper_detected():
    """Editing recovered state after sign-off is caught before COMPLETE."""
    corpus = make_corpus("tamper")
    m, kp, ac = drive(corpus, "tamper-run")
    m.advance(acceptance=accept_bit(m, kp, ac))
    p = os.path.join(m.run_dir, "recovered_state.json")
    st = read_json(p)
    st["run_count"] = 0
    write_json(p, st)
    err = expect_raises(TransitionError, m.advance)
    assert_in("changed after acceptance", str(err))


@S.test
def test_checks_report_missing_artefacts():
    """checks.py on an empty dir fails rather than passing vacuously."""
    rep = run_checks(fresh("emptydir"))
    assert_true(not rep.passed)
    assert_in("missing artefacts", rep.failures[0].message)


# ------------------------------------------------------ commit-first (NEW)

@S.test
def test_anchored_acceptor_is_refused():
    """REQUIRED: an acceptor that has SEEN the recovery output cannot commit.

    The corpus is the acceptor's input and stays visible. The recovery's own
    artefacts are what must not be readable before the commitment."""
    corpus = make_corpus("anchored")
    m0, kp0, ac0 = drive(corpus, "anchored-run")
    d = m0.run_dir
    assert_true(os.path.exists(os.path.join(d, "recovered_state.json")))
    kp = reviewer()
    m = OperatorMachine(PACK, d, "continuity-op-02", kp.commitments(),
                        artefact_names=["recovered_state.json", "provenance.json",
                                        "gap_report.json"])
    late = make_acceptor("reviewer-continuity-01", corpus)
    err = expect_raises(exp.AnchoringError, m.register_expectation, late.commitment())
    assert_in("anchored", str(err))


@S.test
def test_commit_first_is_mandatory():
    """No committed expectation means the recovery cannot leave PREFLIGHT."""
    corpus = make_corpus("nocommit")
    kp = reviewer()
    m = build_machine(fresh("nocommit-out"), "continuity-op-01", kp.commitments(),
                      corpus)
    err = expect_raises(exp.AnchoringError, m.advance)
    assert_in("commit-first is mandatory", str(err))


@S.test
def test_oracle_walks_corpus_independently():
    """The oracle re-derives headline counts without importing engine.py."""
    assert_no_import(os.path.join(_HERE, "oracle.py"), ["engine"])
    corpus = make_corpus("indep", runs=("r1", "r2"))
    scan = oracle.scan_corpus(corpus)
    assert_eq(scan["run_count"], 2)
    assert_eq(scan["packs_seen"], ["strategic-orchestration"])
    assert_eq(scan["orphan_dir_count"], 0)
    out = engine.recover(corpus)
    assert_eq(scan["run_count"], out["recovered_state"]["run_count"],
              "two independent walks must agree on the run count")


@S.test
def test_oracle_detects_orphans_and_contradictions_independently():
    """The oracle finds the same structural facts by its own route."""
    root = fresh("indep2-corpus")
    make_orchestration_run(root, "done")
    make_orchestration_run(root, "abandoned", complete=False)
    scan = oracle.scan_corpus(root)
    assert_eq(scan["run_count"], 1, "the abandoned run has no return_state")
    assert_eq(scan["orphan_dir_count"], 1)
    assert_eq(scan["completed_run_count"], 1)

    root2 = make_corpus("indep3", runs=("a", "b"))
    for rn in ("a", "b"):
        p = os.path.join(root2, rn, "objective.json")
        doc = read_json(p)
        doc["id"] = "OBJ-SHARED"
        if rn == "b":
            doc["budget_units"] = 7
        write_json(p, doc)
    assert_eq(oracle.scan_corpus(root2)["objective_contradiction_count"], 1)


@S.test
def test_inflated_recovery_diverges_from_precommitment():
    """A recovery claiming more runs than the corpus holds is rejected.

    Confabulation is this pack's named failure mode. The acceptor counted the
    runs itself before the recovery spoke, so an inflated count contradicts a
    commitment that cannot be retracted."""
    corpus = make_corpus("inflate", runs=("r1", "r2"))
    m, kp, ac = drive(corpus, "inflate-run")
    p = os.path.join(m.run_dir, "recovered_state.json")
    st = read_json(p)
    st["run_count"] = 5
    st["runs"] = st["runs"] + [
        {"run_id": "ghost", "pack": "strategic-orchestration",
         "producer_id": "nobody", "final_state": "COMPLETE", "verdict": "ACCEPT",
         "accepted_run_digest": "0" * 64, "source": "nowhere"}]
    write_json(p, st)
    err = expect_raises(exp.DivergenceError, m.advance,
                        acceptance=accept_bit(m, kp, ac, bit=True))
    assert_eq(m.verdict, "REJECT")
    ev = [e for e in m.journal if e["event"] == "DIVERGENCE_FORCED_REJECT"][0]
    assert_in("run_count", ev["detail"]["divergent_fields"])
    assert_true("ghost" not in str(err), "divergence detail must not leak")


@S.test
def test_return_state_records_independence_claim():
    """The record states the strength of the independence claim."""
    corpus = make_corpus("claim")
    m, kp, ac = drive(corpus, "claim-run")
    m.advance(acceptance=accept_bit(m, kp, ac))
    m.advance()
    rs = read_json(os.path.join(m.run_dir, "return_state.json"))
    assert_eq(rs["acceptance_independence"], "INDEPENDENT_ORACLE")
    assert_true(rs["expectation_uncovered"],
                "the oracle must state what it cannot cover")
    joined = " ".join(rs["expectation_uncovered"]).lower()
    assert_in("no artefact records", joined)


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
        assert_true(not manifest.verify(_HERE)[0], "tamper must be detected")
    finally:
        with open(victim, "wb") as f:
            f.write(original)
    assert_true(manifest.verify(_HERE)[0], "clean again after restore")


if __name__ == "__main__":
    rc = S.run()
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(rc)
