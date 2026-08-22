"""
Pack 09 - runnable proof.

Two injected failures, both real rather than simulated:

  A. THE KILL. A child process is hard-killed with os._exit(9) at each of four
     points inside apply(), and at two points inside consolidate(). The parent
     then retries to completion and asserts the effect happened EXACTLY once.
     No mocks: real subprocesses, real SQLite, real WAL recovery.

  B. THE CONSOLIDATION THAT OUTGREW ITS CEILING. Enough state is seeded that a
     whole-state read would exceed the per-request byte ceiling. The pack must
     refuse the unbounded path outright, complete in bounded batches, and then
     show request size tracking NEW work rather than accumulated history.

    python3 test_pack.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

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


def cli(*args, crash_at=None, expect_rc=0):
    env = dict(os.environ)
    env.pop("OBZIO_CRASH_AT", None)
    if crash_at:
        env["OBZIO_CRASH_AT"] = crash_at
    cp = subprocess.run([sys.executable, str(HERE / "state_machine.py"), *args],
                        capture_output=True, text=True, env=env, timeout=120)
    if expect_rc is not None and cp.returncode != expect_rc:
        raise AssertionError(
            f"cli {args[0]} rc={cp.returncode} expected {expect_rc}\n"
            f"stdout={cp.stdout[:400]}\nstderr={cp.stderr[:400]}")
    return cp


def dump(db):
    return json.loads(cli("dump", "--db", str(db)).stdout)


def new_db(tmp, tag=""):
    return Path(tmp) / f"{tag}{uuid.uuid4().hex[:8]}.db"


def new_run(tmp, db, tag="w"):
    root = Path(tmp) / f"{tag}-{uuid.uuid4().hex[:6]}"
    gate = AcceptanceGate.generate_keyfile(root / "key")
    run = sm.InfrastructureOperationRun(root / "work", "operator-09", gate, db)
    return run, gate


def objective_for(run):
    return acceptance.objective_for(run.db_path, run.cursor_name,
                                    getattr(run, "_ops", []))


def acceptor(gate, aid="acceptor-QA"):
    return CommitFirstAcceptor(aid, gate,
                               derive=acceptance.derive_expectation,
                               compare=acceptance.compare_to_expectation)


def accept(run, gate):
    return run.finish(acceptor(gate), objective_for(run))


# ==========================================================================
@case
def t01_happy_path_full_lifecycle(tmp):
    db = new_db(tmp, "happy-")
    cli("seed", "--db", str(db), "--count", "20", "--delta", "3")
    run, gate = new_run(tmp, db)
    run.preflight(); run.recover_state()
    run.admit_ops([sm.Op("op-a", "credit", "treasury", {"cents": 500})])
    run.execute()
    run.artefacts_present()
    rep = run.machine_checks()
    expect(rep.ok, f"checks failed: {rep.failed}")
    accept(run, gate)
    st = dump(db)
    expect(st["balances"]["treasury"] == 500, f"treasury {st['balances']}")
    expect(st["balances"]["acct-1"] == 60, f"acct-1 {st['balances']}")
    expect(run.phase == Phase.COMPLETE, f"phase {run.phase}")
    return (f"COMPLETE; balances {st['balances']}, cursor {st['cursors']}, "
            f"{len(rep.checks)} checks green")


@case
def t02_replay_is_a_noop(tmp):
    db = new_db(tmp, "replay-")
    r1 = json.loads(cli("apply", "--db", str(db), "--op-id", "x1",
                        "--account", "a", "--cents", "250").stdout)
    r2 = json.loads(cli("apply", "--db", str(db), "--op-id", "x1",
                        "--account", "a", "--cents", "250").stdout)
    r3 = json.loads(cli("apply", "--db", str(db), "--op-id", "x1",
                        "--account", "a", "--cents", "250").stdout)
    expect(r1["applied"] and not r1["replayed"], "first should apply")
    expect(r2["replayed"] and not r2["applied"], "second should replay")
    expect(r3["replayed"], "third should replay")
    st = dump(db)
    expect(st["balances"]["a"] == 250, f"balance doubled: {st['balances']}")
    expect(st["applied_ops"] == 1, f"applied_ops {st['applied_ops']}")
    return "3 identical applies -> balance 250, applied_ops 1"


@case
def t03_INJECTED_kill_at_every_point_cannot_double(tmp):
    """INJECTED FAILURE A: hard kill inside apply(), at four points."""
    points = ["before_begin", "after_insert_before_effect",
              "after_effect_before_commit", "after_commit_before_return"]
    detail = []
    for pt in points:
        db = new_db(tmp, f"kill-{pt}-")
        cli("apply", "--db", str(db), "--op-id", "k1", "--account", "a",
            "--cents", "100", crash_at=pt, expect_rc=9)
        mid = dump(db)
        # the effect is either fully absent or fully present - never half
        expect(mid["balances"].get("a", 0) in (0, 100),
               f"{pt}: torn state {mid['balances']}")
        expect(mid["applied_ops"] in (0, 1),
               f"{pt}: torn key state {mid['applied_ops']}")
        expect((mid["balances"].get("a", 0) == 100) ==
               (mid["applied_ops"] == 1),
               f"{pt}: effect and key disagree: {mid}")

        # retry twice, as a real supervisor would
        cli("apply", "--db", str(db), "--op-id", "k1", "--account", "a",
            "--cents", "100")
        cli("apply", "--db", str(db), "--op-id", "k1", "--account", "a",
            "--cents", "100")
        end = dump(db)
        expect(end["balances"]["a"] == 100,
               f"{pt}: DOUBLE EFFECT, balance {end['balances']}")
        expect(end["applied_ops"] == 1, f"{pt}: {end['applied_ops']} keys")
        detail.append(f"{pt}->{mid['applied_ops']}")
    return ("killed at " + ", ".join(detail)
            + "; after retries every case is balance=100, keys=1 (exactly once)")


@case
def t04_INJECTED_kill_during_consolidation(tmp):
    """INJECTED FAILURE A, second half: kill inside the consolidation
    transaction, either side of COMMIT."""
    out = []
    for pt, expect_moved in (("consolidate_before_commit", False),
                             ("consolidate_after_commit", True)):
        db = new_db(tmp, f"ckill-{pt}-")
        cli("seed", "--db", str(db), "--count", "10", "--delta", "2")
        cli("consolidate", "--db", str(db), crash_at=pt, expect_rc=9)
        mid = dump(db)
        moved = mid["cursors"].get("main", 0) > 0
        expect(moved == expect_moved,
               f"{pt}: cursor moved={moved}, expected {expect_moved}")
        expect((mid["balances"].get("acct-1", 0) == 20) == expect_moved,
               f"{pt}: effect/cursor disagree: {mid}")
        cli("consolidate", "--db", str(db))
        cli("consolidate", "--db", str(db))
        end = dump(db)
        expect(end["balances"]["acct-1"] == 20,
               f"{pt}: wrong total {end['balances']}")
        expect(end["cursors"]["main"] == 10, f"{pt}: cursor {end['cursors']}")
        out.append(f"{pt}: cursor_moved={moved} -> final 20")
    return "; ".join(out)


@case
def t05_INJECTED_state_outgrew_the_ceiling(tmp):
    """INJECTED FAILURE B: the observed consolidation defect."""
    db = new_db(tmp, "grow-")
    cli("seed", "--db", str(db), "--count", "2000", "--note-size", "100",
        "--delta", "1")

    conn = sm.connect(db); sm.ensure_schema(conn)
    reader = sm.BoundedStateReader(conn)

    # the historical condition really is present
    full = reader.measure_full_state_bytes()
    expect(full > sm.MAX_REQUEST_BYTES,
           f"whole state is only {full}B, ceiling {sm.MAX_REQUEST_BYTES}B - "
           "the defect condition is not reproduced")

    # the defect path does not exist
    err = raises(sm.UnboundedReadRefused, reader.read_all)

    # the bounded path completes
    run, gate = new_run(tmp, db, "grow")
    run.preflight()
    rec = run.recover_state()
    expect(rec["growth_guard"]["whole_state_read_would_exceed_ceiling"] is True,
           f"guard did not flag it: {rec['growth_guard']}")
    run.admit_ops([])
    run.execute()
    c = run.consolidation
    expect(c.rows_consolidated == 2000, f"rows {c.rows_consolidated}")
    expect(len(c.batches) > 1, f"expected batching, got {len(c.batches)}")
    expect(c.max_request_bytes_seen <= sm.MAX_REQUEST_BYTES,
           f"batch over ceiling: {c.max_request_bytes_seen}")
    expect(all(b["rows"] <= sm.MAX_ROWS_PER_REQUEST for b in c.batches),
           "row ceiling breached")
    st = dump(db)
    expect(st["balances"]["acct-1"] == 2000, f"totals wrong: {st['balances']}")

    # ---- the point of the whole control: growth is FLAT ------------------
    run2, gate2 = new_run(tmp, db, "grow2")
    run2.preflight(); run2.recover_state(); run2.admit_ops([]); run2.execute()
    c2 = run2.consolidation
    expect(c2.rows_consolidated == 0, f"re-read old state: {c2.rows_consolidated}")
    expect(c2.max_request_bytes_seen == 0, f"bytes {c2.max_request_bytes_seen}")

    cli("seed", "--db", str(db), "--count", "10", "--note-size", "100")
    run3, gate3 = new_run(tmp, db, "grow3")
    run3.preflight(); run3.recover_state(); run3.admit_ops([]); run3.execute()
    c3 = run3.consolidation
    expect(c3.rows_consolidated == 10, f"rows {c3.rows_consolidated}")
    expect(c3.max_request_bytes_seen < 3000,
           f"request grew with history: {c3.max_request_bytes_seen}B")

    run3.artefacts_present()
    rep = run3.machine_checks()
    expect(rep.ok, f"checks failed: {rep.failed}")
    accept(run3, gate3)
    return (f"whole state {full}B > {sm.MAX_REQUEST_BYTES}B ceiling; read_all "
            f"refused; 2000 rows in {len(c.batches)} batches "
            f"(max {c.max_request_bytes_seen}B); run2 read 0 rows/0B; "
            f"run3 read 10 rows/{c3.max_request_bytes_seen}B - flat, not cumulative")


@case
def t06_row_that_can_never_fit_is_named_not_stalled(tmp):
    db = new_db(tmp, "big-")
    cli("seed", "--db", str(db), "--count", "1", "--note-size", "70000")
    conn = sm.connect(db); sm.ensure_schema(conn)
    reader = sm.BoundedStateReader(conn)
    err = raises(sm.RowTooLarge, reader.read_window, 0)
    expect("stall" in str(err), f"diagnostic missing: {err}")
    return f"RowTooLarge: {str(err)[:88]}"


@case
def t07_same_key_different_payload_refused(tmp):
    db = new_db(tmp, "conflict-")
    cli("apply", "--db", str(db), "--op-id", "c1", "--account", "a",
        "--cents", "100")
    cp = cli("apply", "--db", str(db), "--op-id", "c1", "--account", "a",
             "--cents", "999", expect_rc=1)
    expect("IdempotencyKeyConflict" in cp.stderr, f"stderr: {cp.stderr[-300:]}")
    st = dump(db)
    expect(st["balances"]["a"] == 100, f"balance changed: {st['balances']}")
    return "reused op_id with a different body refused; balance untouched at 100"


@case
def t08_duplicate_op_ids_in_one_batch_refused(tmp):
    db = new_db(tmp, "dupe-")
    run, gate = new_run(tmp, db, "dupe")
    run.preflight(); run.recover_state()
    err = raises(sm.InfraError, run.admit_ops, [
        sm.Op("d1", "credit", "a", {"cents": 1}),
        sm.Op("d1", "credit", "a", {"cents": 1})])
    return f"{str(err)[:70]}"


@case
def t09_producer_cannot_self_advance(tmp):
    db = new_db(tmp, "self-")
    cli("seed", "--db", str(db), "--count", "3")
    run, gate = new_run(tmp, db, "self")
    run.preflight(); run.recover_state(); run.admit_ops([]); run.execute()
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
def t10_checks_are_not_vacuous(tmp):
    db = new_db(tmp, "vac-")
    cli("seed", "--db", str(db), "--count", "5")
    run, gate = new_run(tmp, db, "vac")
    run.preflight(); run.recover_state(); run.admit_ops([]); run.execute()
    run.artefacts_present()
    wd = run.workdir
    expect(checks.run_checks(wd).ok, "clean run should pass")

    t1 = Path(tmp) / f"t1-{uuid.uuid4().hex[:6]}"
    shutil.copytree(wd, t1)
    c = json.loads((t1 / "consolidation_report.json").read_text())
    c["batches"][0]["request_bytes"] = 999_999
    (t1 / "consolidation_report.json").write_text(json.dumps(c))
    r1 = checks.run_checks(t1)
    expect("no_request_exceeded_byte_ceiling" in r1.failed,
           f"ceiling check silent: {r1.failed}")

    t2 = Path(tmp) / f"t2-{uuid.uuid4().hex[:6]}"
    shutil.copytree(wd, t2)
    with open(t2 / "op_log.jsonl", "a") as fh:
        fh.write(json.dumps({"ts": 1, "kind": "APPLY", "idem_key": "dup",
                             "applied": True}) + "\n")
        fh.write(json.dumps({"ts": 2, "kind": "APPLY", "idem_key": "dup",
                             "applied": True}) + "\n")
    r2 = checks.run_checks(t2)
    expect("no_idem_key_applied_twice" in r2.failed,
           f"double-apply check silent: {r2.failed}")

    t3 = Path(tmp) / f"t3-{uuid.uuid4().hex[:6]}"
    shutil.copytree(wd, t3)
    c3 = json.loads((t3 / "consolidation_report.json").read_text())
    c3["batches"][0]["from"] = 99
    (t3 / "consolidation_report.json").write_text(json.dumps(c3))
    r3 = checks.run_checks(t3)
    expect("watermark_contiguous_and_monotonic" in r3.failed,
           f"watermark check silent: {r3.failed}")
    return ("forged over-ceiling batch, duplicate apply and watermark gap all "
            "caught independently")


@case
def t11_acceptor_refuses_post_check_edit(tmp):
    db = new_db(tmp, "acc-")
    cli("seed", "--db", str(db), "--count", "4")
    run, gate = new_run(tmp, db, "acc")
    run.preflight(); run.recover_state(); run.admit_ops([]); run.execute()
    run.artefacts_present(); run.machine_checks()
    c = json.loads((run.workdir / "consolidation_report.json").read_text())
    c["rows_consolidated"] = 4242
    (run.workdir / "consolidation_report.json").write_text(json.dumps(c))
    acc = acceptor(gate)
    acc.precommit(run, objective_for(run))
    err = raises(RejectedByAcceptor, acc.decide, run)
    expect(str(err) == "REJECT", f"channel leaked: {str(err)!r}")
    raises(SelfAcceptanceRefused, run.advance, Phase.INDEPENDENT_ACCEPTANCE)
    return f"single-bit REJECT on post-check edit ({str(err)!r})"



@case
def t12_COMMITFIRST_anchored_acceptor_is_refused(tmp):
    db = new_db(tmp, "anch-")
    cli("seed", "--db", str(db), "--count", "4")
    run, gate = new_run(tmp, db, "anch")
    run.preflight(); run.recover_state(); run.admit_ops([]); run.execute()
    run.artefacts_present(); run.machine_checks()
    anchored = AnchoredAcceptor("acceptor-QA", gate, checks.run_checks)
    token = anchored.review(run)
    err = raises(NoPrecommitment, run.advance, Phase.INDEPENDENT_ACCEPTANCE,
                 token=token)
    expect(run.phase == Phase.MACHINE_CHECKS_PASSED, f"advanced: {run.phase}")
    return f"anchored token refused: {str(err)[:74]}"


@case
def t13_COMMITFIRST_peek_before_commit_is_refused(tmp):
    db = new_db(tmp, "peek-")
    cli("seed", "--db", str(db), "--count", "4")
    run, gate = new_run(tmp, db, "peek")
    run.preflight(); run.recover_state(); run.admit_ops([]); run.execute()
    run.artefacts_present(); run.machine_checks()
    acc = acceptor(gate)
    ArtefactWindow(run, "acceptor-QA").open()
    err = raises(PeekedBeforeCommit, acc.precommit, run, objective_for(run))
    return f"commitment after peeking refused: {str(err)[:70]}"


@case
def t14_COMMITFIRST_acceptor_recomputes_exactly_once_itself(tmp):
    """A double effect applied out of band is caught by arithmetic the acceptor
    did before it read anything the producer wrote."""
    db = new_db(tmp, "arith-")
    cli("seed", "--db", str(db), "--count", "10", "--delta", "2")
    run, gate = new_run(tmp, db, "arith")
    run.preflight(); run.recover_state()
    run.admit_ops([sm.Op("op-x", "credit", "treasury", {"cents": 500})])
    run.execute(); run.artefacts_present(); run.machine_checks()

    # something outside the pack doubles an effect
    conn = sm.connect(db)
    conn.execute("UPDATE balances SET cents = cents + 500 "
                 "WHERE account = 'treasury'")
    conn.close()

    acc = acceptor(gate)
    pre = acc.precommit(run, objective_for(run))
    own = acc._reveal.expected
    expect(own["verdict"] is False, "acceptor missed the double effect")
    expect(own["expected_balances"]["treasury"] == 500,
           f"expected {own['expected_balances']}")
    expect(own["actual_balances"]["treasury"] == 1000,
           f"actual {own['actual_balances']}")
    err = raises(RejectedByAcceptor, acc.decide, run)
    expect(err.outcome.reveal.digest() == pre.expected_digest,
           "reveal does not open the commitment")
    return (f"acceptor computed treasury=500 from the event log, observed 1000, "
            f"and committed REJECT before opening the report")


@case
def t15_COMMITFIRST_channel_carries_one_bit(tmp):
    db = new_db(tmp, "bit-")
    cli("seed", "--db", str(db), "--count", "6")
    run, gate = new_run(tmp, db, "bit")
    run.preflight(); run.recover_state(); run.admit_ops([]); run.execute()
    run.artefacts_present(); run.machine_checks()
    acc = acceptor(gate)
    acc.precommit(run, objective_for(run))
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
    db = new_db(tmp, "cons-")
    cli("seed", "--db", str(db), "--count", "5")
    run, gate = new_run(tmp, db, "cons")
    run.preflight(); run.recover_state(); run.admit_ops([]); run.execute()
    run.artefacts_present(); run.machine_checks()
    good = json.loads((run.workdir / "consolidation_report.json").read_text())
    (run.workdir / "consolidation_report.json").write_text(
        json.dumps({**good, "rows_consolidated": 4242}))

    acc = acceptor(gate)
    pre1 = acc.precommit(run, objective_for(run))
    raises(RejectedByAcceptor, acc.decide, run)

    (run.workdir / "consolidation_report.json").write_text(json.dumps(good))
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
    print("PACK 09  infrastructure-operation  -  test_pack.py")
    print("=" * 74)
    tmp = tempfile.mkdtemp(prefix="p09-")
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
