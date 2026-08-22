"""
Pack 08 - runnable proof.

Injected failure, reproducing the defect observed in this operation:
a drift row that read MATCH while the underlying file had changed.

Reproduced exactly:
  1. run A compares a pin and legitimately gets MATCH
  2. the file's CONTENT changes while its MTIME is restored to the old value
  3. run B is handed run A's MATCH row (the carried-forward verdict)
  4. the pack refuses it, re-derives, and reports DRIFT

t02 first proves the trap is real by showing an mtime-based comparator
still answers MATCH after the content has changed.

    python3 test_pack.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import traceback
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import acceptance
import checks
import state_machine as sm
from _spine import (
    AcceptanceGate, AcceptanceRefused, AnchoredAcceptor, ArtefactWindow,
    CommitFirstAcceptor, NoPrecommitment, PeekedBeforeCommit, Phase,
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


ORIGINAL = b"schema_version: 4\nfields: [id, name, created_at]\n"
CHANGED = b"schema_version: 5\nfields: [id, name, created_at, deleted_at]\n"


def new_world(tmp, tag="", max_staleness_s=sm.DEFAULT_MAX_STALENESS_S):
    root = Path(tmp) / f"{tag}{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True)
    live = root / "live"; live.mkdir()
    target = live / "schema.yaml"
    target.write_bytes(ORIGINAL)
    gate = AcceptanceGate.generate_keyfile(root / "key")
    pinboard = root / "pins.json"
    board = sm.Pinboard(pinboard)
    board.pin("schema", target, "operator-08")
    mtime = os.stat(target).st_mtime
    return root, target, gate, pinboard, mtime


def new_run(root, gate, pinboard, tag="run", max_staleness_s=sm.DEFAULT_MAX_STALENESS_S):
    return sm.KnowledgeCurrentnessRun(
        root / f"work-{tag}-{uuid.uuid4().hex[:6]}", "operator-08", gate,
        pinboard, max_staleness_s=max_staleness_s)


def objective_for(run, keys=None):
    return acceptance.objective_for(run.mandate["pinboard"],
                                    keys if keys is not None else run._to_audit,
                                    run.mandate["max_staleness_s"])


def acceptor(gate, aid="acceptor-QA", audit=None):
    return CommitFirstAcceptor(aid, gate,
                               derive=acceptance.derive_expectation,
                               compare=acceptance.compare_to_expectation,
                               audit_path=audit)


def accept(run, gate, aid="acceptor-QA"):
    return run.finish(acceptor(gate, aid), objective_for(run))


def drive(run, mtimes=None):
    run.preflight(); run.recover_state(); run.admit_pins()
    run.audit(mtimes or {})
    return run.publish()


def change_content_preserving_mtime(target: Path, mtime: float):
    """The exact condition that made an mtime comparator lie."""
    st = os.stat(target)
    target.write_bytes(CHANGED)
    os.utime(target, (st.st_atime, mtime))
    return os.stat(target).st_mtime


# ==========================================================================
@case
def t01_unchanged_reports_current(tmp):
    root, target, gate, pinboard, mtime = new_world(tmp, "cur-")
    run = new_run(root, gate, pinboard)
    r = drive(run, {"schema": mtime})
    expect(r["status"] == sm.ReportStatus.CURRENT.value, f"status {r['status']}")
    expect(r["exit_code"] == 0, "exit code")
    expect(r["counts"]["MATCH"] == 1, f"counts {r['counts']}")
    rep = run.machine_checks()
    expect(rep.ok, f"checks failed: {rep.failed}")
    accept(run, gate)
    expect(run.phase == Phase.COMPLETE, f"phase {run.phase}")
    return (f"CURRENT, 1 MATCH backed by {r['reads_performed']} full read, "
            f"{len(rep.checks)} checks green, COMPLETE")


@case
def t02_the_trap_is_real_mtime_comparator_lies(tmp):
    root, target, gate, pinboard, mtime = new_world(tmp, "trap-")
    board = sm.Pinboard(pinboard)
    exp = board.pins["schema"]
    after = change_content_preserving_mtime(target, mtime)
    expect(after == mtime, f"mtime not preserved: {after} != {mtime}")
    expect(target.read_bytes() != ORIGINAL, "content did not change")
    said = sm.mtime_shortcut_verdict(exp, mtime)
    expect(said == sm.Verdict.MATCH.value,
           f"trap did not fire; mtime comparator said {said}")
    return ("content changed, mtime restored: the mtime comparator still "
            "answers MATCH (this is the live defect)")


@case
def t03_INJECTED_carried_forward_match_refused_then_recovered(tmp):
    """THE INJECTED FAILURE + RECOVERY."""
    root, target, gate, pinboard, mtime = new_world(tmp, "carry-")

    # ---- run A: legitimate MATCH ----------------------------------------
    runA = new_run(root, gate, pinboard, "A")
    rA = drive(runA, {"schema": mtime})
    expect(rA["status"] == sm.ReportStatus.CURRENT.value, f"A status {rA['status']}")
    rowA = runA.auditor.rows[0]
    expect(rowA.verdict == sm.Verdict.MATCH.value, "A should MATCH")

    # ---- the world changes, invisibly to mtime --------------------------
    change_content_preserving_mtime(target, mtime)

    # ---- run B: an orchestrator tries to reuse run A's verdict -----------
    runB = new_run(root, gate, pinboard, "B")
    runB.preflight(); runB.recover_state(); runB.admit_pins()
    err = raises(sm.UnbackedVerdictRefused, runB.auditor.admit_row, rowA)

    # and separately: even a row this auditor DID mint is refused if it
    # carries a foreign run_nonce - the two guards are independent
    coreA = rowA.core()
    relabelled = sm.DriftRow(**coreA, pinned_bytes=rowA.pinned_bytes,
                             live_bytes=rowA.live_bytes,
                             compared_mono=rowA.compared_mono,
                             auth=runB.auditor._auth(coreA))
    err2 = raises(sm.UnbackedVerdictRefused, runB.auditor.admit_row, relabelled)
    expect("run_nonce" in str(err2), f"nonce guard did not fire: {err2}")

    # ---- run B does it properly ------------------------------------------
    runB.audit({"schema": mtime})
    rB = runB.publish()
    expect(rB["status"] == sm.ReportStatus.DRIFT.value, f"B status {rB['status']}")
    expect(rB["exit_code"] == 1, "drift must not exit 0")
    rowB = rB["rows"][0]
    expect(rowB["verdict"] == sm.Verdict.DRIFT.value, f"B verdict {rowB['verdict']}")
    expect(rowB["live_digest"] != rowB["pinned_digest"], "digests should differ")
    expect(rB["mtime_shortcut_disagreements"] == ["schema"],
           f"tripwire silent: {rB['mtime_shortcut_disagreements']}")

    rep = runB.machine_checks()
    expect(rep.ok, f"B checks failed: {rep.failed}")
    accept(runB, gate)
    expect(runB.phase == Phase.COMPLETE, "B did not complete")
    return (f"carried-forward MATCH refused on MAC and independently on "
            f"run_nonce; "
            f"fresh comparison returned DRIFT, exit 1, mtime tripwire fired; "
            f"audit run COMPLETE")


@case
def t04_handmade_match_row_refused(tmp):
    """A MATCH constructed by code that never read anything."""
    root, target, gate, pinboard, mtime = new_world(tmp, "hand-")
    run = new_run(root, gate, pinboard)
    run.preflight(); run.recover_state(); run.admit_pins()
    exp = run.pinboard.pins["schema"]
    forged = sm.DriftRow(
        key="schema", path=str(target), verdict=sm.Verdict.MATCH.value,
        pinned_digest=exp.pinned_digest, live_digest=exp.pinned_digest,
        pinned_bytes=exp.pinned_bytes, live_bytes=exp.pinned_bytes,
        evidence_id=None, run_nonce=run.reader.run_nonce,
        compared_at=time.time(), compared_mono=time.monotonic(),
        auth="0" * 64)
    err = raises(sm.UnbackedVerdictRefused, run.auditor.admit_row, forged)
    return f"unminted MATCH refused: {str(err)[:76]}"


@case
def t05_match_citing_foreign_evidence_refused(tmp):
    root, target, gate, pinboard, mtime = new_world(tmp, "foreign-")
    runA = new_run(root, gate, pinboard, "A")
    runA.preflight(); runA.recover_state(); runA.admit_pins(); runA.audit()
    evA = list(runA.reader.registry.values())[0]

    runB = new_run(root, gate, pinboard, "B")
    runB.preflight(); runB.recover_state(); runB.admit_pins()
    exp = runB.pinboard.pins["schema"]
    core = {"key": "schema", "path": str(target), "verdict": "MATCH",
            "pinned_digest": exp.pinned_digest, "live_digest": evA.digest,
            "evidence_id": evA.evidence_id, "run_nonce": runB.reader.run_nonce,
            "compared_at": time.time()}
    row = sm.DriftRow(**core, pinned_bytes=exp.pinned_bytes,
                      live_bytes=evA.byte_len, compared_mono=time.monotonic(),
                      auth=runB.auditor._auth(core))
    err = raises(sm.UnbackedVerdictRefused, runB.auditor.admit_row, row)
    expect("never read" in str(err), f"wrong reason: {err}")
    return f"MATCH citing another run's evidence refused: {str(err)[:70]}"


@case
def t06_stale_evidence_downgrades_match(tmp):
    root, target, gate, pinboard, mtime = new_world(tmp, "stale-")
    run = new_run(root, gate, pinboard, "S", max_staleness_s=0.0)
    r = drive(run, {"schema": mtime})
    expect(r["status"] == sm.ReportStatus.DEGRADED.value, f"status {r['status']}")
    expect(r["exit_code"] == 1, "degraded must not exit 0")
    row = r["rows"][0]
    expect(row["verdict"] == sm.Verdict.UNKNOWN.value, f"verdict {row['verdict']}")
    expect(row["downgraded_from"] == "MATCH", "downgrade not recorded")
    rep = run.machine_checks()
    expect(rep.ok, f"checks failed: {rep.failed}")
    return (f"MATCH downgraded to UNKNOWN at publication "
            f"({row['staleness_s_at_publication']}s > 0.0s), status DEGRADED, exit 1")


@case
def t07_partial_coverage_is_incomplete_not_current(tmp):
    root, target, gate, pinboard, mtime = new_world(tmp, "cov-")
    second = root / "live" / "policy.yaml"
    second.write_bytes(b"retention_days: 30\n")
    board = sm.Pinboard(pinboard)
    board.pin("policy", second, "operator-08")

    run = new_run(root, gate, pinboard, "C")
    run.preflight(); run.recover_state()
    run.admit_pins(["schema"])            # deliberately audit only one of two
    run.audit()
    r = run.publish()
    expect(r["status"] == sm.ReportStatus.INCOMPLETE.value, f"status {r['status']}")
    expect(r["uncompared_pins"] == ["policy"], f"uncompared {r['uncompared_pins']}")
    expect(r["exit_code"] == 1, "incomplete must not exit 0")
    return "1 of 2 pins audited -> INCOMPLETE, exit 1 (not CURRENT)"


@case
def t08_missing_target(tmp):
    root, target, gate, pinboard, mtime = new_world(tmp, "miss-")
    target.unlink()
    run = new_run(root, gate, pinboard, "M")
    r = drive(run)
    expect(r["counts"]["MISSING"] == 1, f"counts {r['counts']}")
    expect(r["status"] == sm.ReportStatus.DRIFT.value, f"status {r['status']}")
    return "deleted target -> MISSING, status DRIFT, exit 1"


@case
def t09_zero_comparisons_refused(tmp):
    root, target, gate, pinboard, mtime = new_world(tmp, "zero-")
    run = new_run(root, gate, pinboard, "Z")
    run.preflight(); run.recover_state(); run.admit_pins([])
    err = raises(sm.NoComparisonPerformed, run.publish)
    return f"empty audit refused publication: {str(err)[:70]}"


@case
def t10_checks_are_not_vacuous(tmp):
    root, target, gate, pinboard, mtime = new_world(tmp, "vac-")
    run = new_run(root, gate, pinboard, "V")
    drive(run, {"schema": mtime})
    wd = run.workdir
    expect(checks.run_checks(wd).ok, "clean run should pass")

    tampered = Path(tmp) / f"tamp-{uuid.uuid4().hex[:6]}"
    shutil.copytree(wd, tampered)
    r = json.loads((tampered / "drift_report.json").read_text())
    r["rows"][0]["evidence_id"] = "deadbeefdeadbeefdeadbeef"
    (tampered / "drift_report.json").write_text(json.dumps(r, indent=2))
    rep = checks.run_checks(tampered)
    expect(not rep.ok, "tampered report passed")
    expect("every_match_row_has_this_run_evidence" in rep.failed,
           f"central check did not fire: {rep.failed}")

    tampered2 = Path(tmp) / f"tamp2-{uuid.uuid4().hex[:6]}"
    shutil.copytree(wd, tampered2)
    r2 = json.loads((tampered2 / "drift_report.json").read_text())
    r2["rows"][0]["verdict"] = "MATCH"
    r2["rows"][0]["live_digest"] = "f" * 64      # MATCH that disagrees with pin
    (tampered2 / "drift_report.json").write_text(json.dumps(r2, indent=2))
    rep2 = checks.run_checks(tampered2)
    expect("every_match_row_has_this_run_evidence" in rep2.failed,
           f"digest cross-check did not fire: {rep2.failed}")
    return (f"forged evidence_id caught by {sorted(rep.failed)}; "
            f"forged live_digest caught too")


@case
def t11_producer_cannot_self_advance(tmp):
    root, target, gate, pinboard, mtime = new_world(tmp, "self-")
    run = new_run(root, gate, pinboard, "P")
    drive(run, {"schema": mtime})
    run.machine_checks()
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
def t12_acceptor_refuses_post_check_edit(tmp):
    root, target, gate, pinboard, mtime = new_world(tmp, "acc-")
    run = new_run(root, gate, pinboard, "A2")
    drive(run, {"schema": mtime})
    run.machine_checks()
    r = json.loads((run.workdir / "drift_report.json").read_text())
    r["rows"][0]["live_digest"] = "f" * 64      # the ANSWER now diverges
    (run.workdir / "drift_report.json").write_text(json.dumps(r))
    acc = acceptor(gate)
    acc.precommit(run, objective_for(run))
    err = raises(RejectedByAcceptor, acc.decide, run)
    expect(str(err) == "REJECT", f"channel leaked: {str(err)!r}")
    raises(SelfAcceptanceRefused, run.advance, Phase.INDEPENDENT_ACCEPTANCE)
    # DIVISION OF LABOUR: commit-first acceptance judges the ANSWER. A forged
    # evidence_id that leaves the answer intact is a process defect and is
    # caught upstream by machine checks (t10), not by the acceptor.
    return f"single-bit REJECT (channel carried {str(err)!r} and nothing else)"



@case
def t13_COMMITFIRST_anchored_acceptor_is_refused(tmp):
    """The refuted design: read the candidate, then judge. Its token no longer
    opens the gate."""
    root, target, gate, pinboard, mtime = new_world(tmp, "anch-")
    run = new_run(root, gate, pinboard, "AN")
    drive(run, {"schema": mtime})
    run.machine_checks()
    anchored = AnchoredAcceptor("acceptor-QA", gate, checks.run_checks)
    token = anchored.review(run)          # reads workdir first, then decides
    err = raises(NoPrecommitment, run.advance, Phase.INDEPENDENT_ACCEPTANCE,
                 token=token)
    expect("anchored" in str(err), f"reason: {err}")
    expect(run.phase == Phase.MACHINE_CHECKS_PASSED, f"advanced: {run.phase}")
    return f"anchored token refused: {str(err)[:74]}"


@case
def t14_COMMITFIRST_peek_before_commit_is_refused(tmp):
    root, target, gate, pinboard, mtime = new_world(tmp, "peek-")
    run = new_run(root, gate, pinboard, "PK")
    drive(run, {"schema": mtime})
    run.machine_checks()
    acc = acceptor(gate)
    ArtefactWindow(run, "acceptor-QA").open()     # the acceptor peeks
    err = raises(PeekedBeforeCommit, acc.precommit, run, objective_for(run))
    expect("anchored" in str(err), f"reason: {err}")
    return f"commitment after peeking refused: {str(err)[:70]}"


@case
def t15_COMMITFIRST_kills_carried_forward_match_structurally(tmp):
    """The acceptor writes DRIFT from its own read before it sees the producer
    claim MATCH. No rule is consulted - the answers simply differ."""
    root, target, gate, pinboard, mtime = new_world(tmp, "struct-")
    run = new_run(root, gate, pinboard, "ST")
    drive(run, {"schema": mtime})
    run.machine_checks()
    r = json.loads((run.workdir / "drift_report.json").read_text())
    expect(r["rows"][0]["verdict"] == "MATCH", "setup: producer said MATCH")

    change_content_preserving_mtime(target, mtime)   # world moves under it

    acc = acceptor(gate)
    pre = acc.precommit(run, objective_for(run))
    committed = acc._reveal.expected["verdicts"]["schema"]
    expect(committed == sm.Verdict.DRIFT.value,
           f"acceptor committed {committed}, expected DRIFT")
    err = raises(RejectedByAcceptor, acc.decide, run)
    expect(str(err) == "REJECT", f"channel leaked: {str(err)!r}")
    expect(err.outcome.reveal.digest() == pre.expected_digest,
           "reveal does not open the commitment")
    return ("acceptor committed DRIFT from its own read before opening the "
            "report that claimed MATCH; REJECT, commitment opened and verified")


@case
def t16_COMMITFIRST_channel_carries_one_bit(tmp):
    root, target, gate, pinboard, mtime = new_world(tmp, "bit-")
    run = new_run(root, gate, pinboard, "BT")
    drive(run, {"schema": mtime})
    run.machine_checks()
    acc = acceptor(gate)
    acc.precommit(run, objective_for(run))
    out = acc.decide(run)
    fields = sorted(out.to_dict())
    expect(fields == ["accept", "precommitment", "reveal", "run_id", "token"],
           f"channel fields: {fields}")
    for banned in ("reason", "failed", "report", "diff", "guidance", "message"):
        expect(not hasattr(out, banned), f"channel exposes {banned}")
    run.accept_with(out)
    rep = checks.run_checks(run.workdir)
    expect("acceptance_channel_is_one_bit" not in rep.failed,
           f"one-bit check failed: {rep.failed}")
    return f"outcome fields {fields}; accept={out.accept}; no rubric channel"


@case
def t17_COMMITFIRST_conservative_update_on_reject(tmp):
    root, target, gate, pinboard, mtime = new_world(tmp, "cons-")
    run = new_run(root, gate, pinboard, "CN")
    drive(run, {"schema": mtime})
    run.machine_checks()
    r = json.loads((run.workdir / "drift_report.json").read_text())
    r["rows"][0]["verdict"] = "DRIFT"          # producer contradicts the world
    (run.workdir / "drift_report.json").write_text(json.dumps(r))

    from _spine import AcceptanceBudgetExhausted
    acc = acceptor(gate)
    pre1 = acc.precommit(run, objective_for(run))
    raises(RejectedByAcceptor, acc.decide, run)

    # round 2 requires a FRESH commitment; the stale one may not be reused
    r["rows"][0]["verdict"] = "MATCH"           # producer corrects itself
    (run.workdir / "drift_report.json").write_text(json.dumps(r))
    acc2 = acceptor(gate)
    pre2 = acc2.precommit(run, objective_for(run))
    expect(pre2.ledger_seq > pre1.ledger_seq, "second commitment not fresh")
    out = acc2.decide(run)
    run.accept_with(out)
    expect(run.phase == Phase.INDEPENDENT_ACCEPTANCE, f"phase {run.phase}")

    # round 3 is refused outright rather than re-graded
    acc3 = acceptor(gate)
    err = raises(AcceptanceBudgetExhausted, acc3.precommit, run,
                 objective_for(run))
    return (f"REJECT at seq {pre1.ledger_seq}; fresh commitment at seq "
            f"{pre2.ledger_seq} accepted; third attempt refused on budget")


# ==========================================================================
def main() -> int:
    print("=" * 74)
    print("PACK 08  knowledge-currentness  -  test_pack.py")
    print("=" * 74)
    tmp = tempfile.mkdtemp(prefix="p08-")
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
