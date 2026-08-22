"""
Pack 06 - runnable proof.

Includes the injected failure this pack exists for: the browser surface
silently switches conversation BETWEEN route verification and the send click.
The test first demonstrates the failure is real (naive verify-then-send puts
the message in the wrong conversation), then proves the guard refuses it and
that the run recovers and delivers to the correct conversation.

    python3 test_pack.py
"""
from __future__ import annotations

import json
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
    AcceptanceBudgetExhausted, AcceptanceGate, AnchoredAcceptor, ArtefactWindow,
    CommitFirstAcceptor, NoPrecommitment, PeekedBeforeCommit, Phase,
    RejectedByAcceptor, SelfAcceptanceRefused, TokenInvalid,
)

# --------------------------------------------------------------------------
# tiny harness
# --------------------------------------------------------------------------
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
# simulated browser surface (adversarial by design)
# --------------------------------------------------------------------------
class SimSurface(sm.Surface):
    def __init__(self, current="conv-alpha"):
        self.conv = {
            "conv-alpha": {"recipient": "@ops-alpha", "title": "Deploy window",
                           "inbox": []},
            "conv-beta": {"recipient": "@client-beta", "title": "Contract review",
                          "inbox": []},
        }
        self.current = current
        self.mutation_seq = 0
        self.compose_open_count = 1
        self.focused = "compose-1"
        self.hijack_to = None
        self.hijack_at_observe = None
        self._observes = 0
        self.sent = 0

    def observe(self):
        self._observes += 1
        if self.hijack_to and self._observes == self.hijack_at_observe:
            # silent SPA re-render: conversation swaps, mutation counter NOT
            # bumped (the pessimistic case - we cannot rely on the app telling
            # us it changed)
            self.current = self.hijack_to
        c = self.conv[self.current]
        return sm.Observation(
            conversation_id=self.current,
            recipient_handle=c["recipient"],
            thread_title=c["title"],
            compose_open_count=self.compose_open_count,
            focused_compose_id=self.focused,
            mutation_seq=self.mutation_seq,
            observed_at=time.time(),
            obs_id=uuid.uuid4().hex,
        )

    def do_send(self, text):
        self.sent += 1
        mid = f"msg-{self.sent:03d}"
        self.conv[self.current]["inbox"].append({"id": mid, "text": text})
        return mid

    def navigate(self, cid):
        self.current = cid
        self.mutation_seq += 1

    # -- read side used by the commit-first acceptor ---------------------
    def conversation_ids(self):
        return sorted(self.conv)

    def inbox_digests(self, conversation_id):
        import hashlib
        return [hashlib.sha256(m["text"].encode()).hexdigest()
                for m in self.conv[conversation_id]["inbox"]]


ALPHA = sm.Target("conv-alpha", "@ops-alpha", "Deploy window")
BETA = sm.Target("conv-beta", "@client-beta", "Contract review")
ALLOW = ["@ops-alpha", "@client-beta"]


def new_env(tmp, producer="operator-06"):
    wd = Path(tmp) / f"run-{uuid.uuid4().hex[:8]}"
    gate = AcceptanceGate.generate_keyfile(Path(tmp) / f"key-{uuid.uuid4().hex[:6]}")
    run = sm.BrowserExecutionRun(wd, producer, gate, ALLOW, max_sends=2,
                                 task_id="T-1")
    return wd, gate, run


def objective_for(targets, messages):
    return acceptance.objective_for(targets, messages, ALLOW, 2, "T-1")


def acceptor(gate, surface, aid="acceptor-QA"):
    return CommitFirstAcceptor(
        aid, gate,
        derive=lambda obj: acceptance.derive_expectation(obj, surface),
        compare=acceptance.compare_to_expectation)


def accept(run, gate, surface, targets, messages):
    return run.finish(acceptor(gate, surface), objective_for(targets, messages))


# ==========================================================================
@case
def t01_happy_path_full_lifecycle(tmp):
    wd, gate, run = new_env(tmp)
    surf = SimSurface("conv-alpha")
    run.preflight(surf)
    run.recover_state()
    run.admit_input([ALPHA], ["deploy approved"])
    ids = run.execute([ALPHA], ["deploy approved"])
    run.artefacts_present()
    rep = run.machine_checks()
    expect(rep.ok, f"checks failed: {rep.failed}")
    accept(run, gate, surf, [ALPHA], ["deploy approved"])
    expect(run.phase == Phase.COMPLETE, f"phase {run.phase}")
    expect(len(surf.conv["conv-alpha"]["inbox"]) == 1, "alpha should have 1")
    expect(len(surf.conv["conv-beta"]["inbox"]) == 0, "beta must be empty")
    return f"COMPLETE, 1 send {ids}, {len(rep.checks)} checks green"


@case
def t02_the_trap_is_real_naive_send_misroutes(tmp):
    """Proof the injected failure is not hypothetical: verify, then send
    without re-deriving the surface, and the message lands in conv-beta."""
    surf = SimSurface("conv-alpha")
    surf.hijack_to, surf.hijack_at_observe = "conv-beta", 2
    obs = surf.observe()                       # observe #1 - looks correct
    expect(obs.conversation_id == "conv-alpha", "first observe should be alpha")
    surf.observe()                             # observe #2 - hijack fires
    surf.do_send("deploy approved")            # naive: no re-check
    expect(len(surf.conv["conv-beta"]["inbox"]) == 1,
           "trap did not fire; test is not proving anything")
    expect(len(surf.conv["conv-alpha"]["inbox"]) == 0, "alpha wrongly got it")
    return "naive verify-then-send delivered into conv-beta (the live failure)"


@case
def t03_INJECTED_hijack_refused_then_recovered(tmp):
    """THE INJECTED FAILURE + RECOVERY."""
    wd, gate, run = new_env(tmp)
    surf = SimSurface("conv-alpha")
    guard = run.preflight(surf)
    run.recover_state()
    run.admit_input([ALPHA], ["deploy approved"])

    # arm the hijack so it fires on the send-time re-observation
    surf.hijack_to, surf.hijack_at_observe = "conv-beta", 2

    def recover(target):
        """surface-specific re-navigation, handed to the pack's bounded retry"""
        surf.hijack_to = None
        surf.navigate(target.conversation_id)

    # the pack's own execute() must refuse, recover, and land it correctly
    ids = run.execute([ALPHA], ["deploy approved"], recover=recover)
    mid = ids[0]

    expect(surf.sent == 1, f"expected exactly 1 delivery, got {surf.sent}")
    expect([m["id"] for m in surf.conv["conv-alpha"]["inbox"]] == [mid],
           "alpha did not receive exactly the recovered message")
    expect(surf.conv["conv-beta"]["inbox"] == [],
           "WRONG CONVERSATION RECEIVED A MESSAGE")

    rows = json.loads("[" + ",".join(
        (wd / "route_ledger.jsonl").read_text().strip().splitlines()) + "]")
    verdicts = [(r["kind"], r["verdict"]) for r in rows]
    expect(("SEND", "ROUTE_CHANGED") in verdicts, f"refusal not logged: {verdicts}")
    expect(("SEND", "OK") in verdicts, f"recovery not logged: {verdicts}")

    # run still completes cleanly through independent acceptance
    run.artefacts_present()
    rep = run.machine_checks()
    expect(rep.ok, f"checks failed after recovery: {rep.failed}")
    accept(run, gate, surf, [ALPHA], ["deploy approved"])
    return (f"ROUTE_CHANGED refused mid-send, beta clean, "
            f"alpha got {mid} after bounded recovery, run COMPLETE")


@case
def t04_misroute_detected_at_verify(tmp):
    wd, gate, run = new_env(tmp)
    surf = SimSurface("conv-beta")               # already on the wrong thread
    guard = run.preflight(surf)
    err = raises(sm.Misroute, guard.verify, ALPHA)
    expect(surf.sent == 0, "sent despite misroute")
    return f"{err.__class__.__name__}: {str(err)[:60]}"


@case
def t05_ambiguous_surface_refused(tmp):
    wd, gate, run = new_env(tmp)
    surf = SimSurface("conv-alpha")
    surf.compose_open_count = 2
    guard = run.preflight(surf)
    raises(sm.AmbiguousSurface, guard.verify, ALPHA)
    surf.compose_open_count, surf.focused = 1, None
    raises(sm.AmbiguousSurface, guard.verify, ALPHA)
    return "2-compose and unfocused-compose both refused"


@case
def t06_offallowlist_and_mandate_cap(tmp):
    wd, gate, run = new_env(tmp)
    surf = SimSurface("conv-alpha")
    guard = run.preflight(surf)
    stranger = sm.Target("conv-alpha", "@not-on-list", "Deploy window")
    raises(sm.RecipientNotAllowed, guard.verify, stranger)
    guard.verified_send(ALPHA, "one")
    guard.verified_send(ALPHA, "two")
    raises(sm.MandateExceeded, guard.verified_send, ALPHA, "three")
    expect(surf.sent == 2, f"cap leaked: {surf.sent} sends")
    return "off-allowlist refused; cap of 2 held at 2"


@case
def t07_forged_and_replayed_tokens(tmp):
    wd, gate, run = new_env(tmp)
    surf = SimSurface("conv-alpha")
    guard = run.preflight(surf)
    good = guard.verify(ALPHA)
    forged = sm.SendToken(**{**good.to_dict(), "mac": "0" * 64})
    raises(sm.TokenForged, guard.send, forged, "x")
    guard.send(good, "one")
    raises(sm.TokenReplay, guard.send, good, "one again")
    expect(surf.sent == 1, f"expected 1 send, got {surf.sent}")
    return "forged MAC refused; spent token refused; exactly 1 delivery"


@case
def t08_producer_cannot_self_advance(tmp):
    wd, gate, run = new_env(tmp)
    surf = SimSurface("conv-alpha")
    run.preflight(surf); run.recover_state()
    run.admit_input([ALPHA], ["hi"]); run.execute([ALPHA], ["hi"])
    run.artefacts_present(); run.machine_checks()
    expect(run.phase == Phase.MACHINE_CHECKS_PASSED, "wrong ceiling")
    raises(SelfAcceptanceRefused, run.advance, Phase.INDEPENDENT_ACCEPTANCE)
    self_tok = gate.mint(run.run_id, run.ledger.head(), run.producer_id, "PASS", "x")
    raises(SelfAcceptanceRefused, run.advance, Phase.INDEPENDENT_ACCEPTANCE,
           token=self_tok)
    acc = acceptor(gate, surf)
    acc.precommit(run, objective_for([ALPHA], ["hi"]))
    stale = acc.decide(run)
    run.note("PRODUCER_SNEAKS_A_WRITE", {"why": "moves the ledger head"})
    raises(TokenInvalid, run.advance, Phase.INDEPENDENT_ACCEPTANCE,
           token=stale.token)
    acc2 = acceptor(gate, surf)
    acc2.precommit(run, objective_for([ALPHA], ["hi"]))
    run.accept_with(acc2.decide(run))
    return ("self-advance, self-token and head-stale token all refused; "
            "commit-first token accepted")


@case
def t09_checks_are_not_vacuous(tmp):
    """Fabricate a misrouted send row in a completed run; checks must fail."""
    wd, gate, run = new_env(tmp)
    surf = SimSurface("conv-alpha")
    run.preflight(surf); run.recover_state()
    run.admit_input([ALPHA], ["hi"]); run.execute([ALPHA], ["hi"])
    run.artefacts_present()
    expect(checks.run_checks(wd).ok, "clean run should pass")

    tampered = Path(tmp) / "tampered"
    shutil.copytree(wd, tampered)
    with open(tampered / "route_ledger.jsonl", "a") as fh:
        fh.write(json.dumps({
            "ts": time.time(), "kind": "SEND", "verdict": "OK",
            "nonce": "fabricated", "message_id": "msg-999",
            "intended_digest": "a" * 64, "surface_digest_at_send": "b" * 64,
        }) + "\n")
    rep = checks.run_checks(tampered)
    expect(not rep.ok, "tampered run passed checks")
    for name in ("every_send_has_verified_route", "no_send_to_unintended_route",
                 "transcript_matches_route_ledger"):
        expect(name in rep.failed, f"{name} did not fire; failed={rep.failed}")
    return f"fabricated send caught by: {sorted(rep.failed)}"


@case
def t10_acceptor_refuses_a_bad_run(tmp):
    wd, gate, run = new_env(tmp)
    surf = SimSurface("conv-alpha")
    run.preflight(surf); run.recover_state()
    run.admit_input([ALPHA], ["hi"]); run.execute([ALPHA], ["hi"])
    run.artefacts_present(); run.machine_checks()
    (wd / "transcript.json").write_text('{"sent": ["msg-forged"]}')
    acc = acceptor(gate, surf)
    acc.precommit(run, objective_for([ALPHA], ["hi"]))
    err = raises(RejectedByAcceptor, acc.decide, run)
    expect(str(err) == "REJECT", f"channel leaked: {str(err)!r}")
    raises(SelfAcceptanceRefused, run.advance, Phase.INDEPENDENT_ACCEPTANCE)
    return f"single-bit REJECT on post-check tampering ({str(err)!r})"



@case
def t11_COMMITFIRST_anchored_acceptor_is_refused(tmp):
    wd, gate, run = new_env(tmp)
    surf = SimSurface("conv-alpha")
    run.preflight(surf); run.recover_state()
    run.admit_input([ALPHA], ["hi"]); run.execute([ALPHA], ["hi"])
    run.artefacts_present(); run.machine_checks()
    anchored = AnchoredAcceptor("acceptor-QA", gate, checks.run_checks)
    token = anchored.review(run)
    err = raises(NoPrecommitment, run.advance, Phase.INDEPENDENT_ACCEPTANCE,
                 token=token)
    expect(run.phase == Phase.MACHINE_CHECKS_PASSED, f"advanced: {run.phase}")
    return f"anchored token refused: {str(err)[:74]}"


@case
def t12_COMMITFIRST_peek_before_commit_is_refused(tmp):
    wd, gate, run = new_env(tmp)
    surf = SimSurface("conv-alpha")
    run.preflight(surf); run.recover_state()
    run.admit_input([ALPHA], ["hi"]); run.execute([ALPHA], ["hi"])
    run.artefacts_present(); run.machine_checks()
    acc = acceptor(gate, surf)
    ArtefactWindow(run, "acceptor-QA").open()
    err = raises(PeekedBeforeCommit, acc.precommit, run,
                 objective_for([ALPHA], ["hi"]))
    return f"commitment after peeking refused: {str(err)[:70]}"


@case
def t13_COMMITFIRST_acceptor_sees_the_misroute_itself(tmp):
    """A transcript that claims delivery to alpha cannot survive an acceptor
    that already looked in beta."""
    wd, gate, run = new_env(tmp)
    surf = SimSurface("conv-alpha")
    guard = run.preflight(surf); run.recover_state()
    run.admit_input([ALPHA], ["deploy approved"])
    run.execute([ALPHA], ["deploy approved"])
    run.artefacts_present(); run.machine_checks()

    # the message is moved into the wrong conversation after the fact, and the
    # producer's artefacts still say it went to alpha
    moved = surf.conv["conv-alpha"]["inbox"].pop()
    surf.conv["conv-beta"]["inbox"].append(moved)

    acc = acceptor(gate, surf)
    pre = acc.precommit(run, objective_for([ALPHA], ["deploy approved"]))
    committed = acc._reveal.expected
    expect(committed["verdict"] is False, "acceptor should have seen the misroute")
    expect(committed["foreign_deliveries"], "foreign delivery not recorded")
    err = raises(RejectedByAcceptor, acc.decide, run)
    expect(err.outcome.reveal.digest() == pre.expected_digest,
           "reveal does not open the commitment")
    return (f"acceptor independently recorded foreign delivery in "
            f"{sorted(committed['foreign_deliveries'])} before reading the "
            f"transcript; REJECT")


@case
def t14_COMMITFIRST_channel_carries_one_bit(tmp):
    wd, gate, run = new_env(tmp)
    surf = SimSurface("conv-alpha")
    run.preflight(surf); run.recover_state()
    run.admit_input([ALPHA], ["hi"]); run.execute([ALPHA], ["hi"])
    run.artefacts_present(); run.machine_checks()
    acc = acceptor(gate, surf)
    acc.precommit(run, objective_for([ALPHA], ["hi"]))
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
    wd, gate, run = new_env(tmp)
    surf = SimSurface("conv-alpha")
    run.preflight(surf); run.recover_state()
    run.admit_input([ALPHA], ["hi"]); run.execute([ALPHA], ["hi"])
    run.artefacts_present(); run.machine_checks()
    good = json.loads((wd / "transcript.json").read_text())
    (wd / "transcript.json").write_text('{"sent": ["msg-forged"]}')

    acc = acceptor(gate, surf)
    pre1 = acc.precommit(run, objective_for([ALPHA], ["hi"]))
    raises(RejectedByAcceptor, acc.decide, run)

    (wd / "transcript.json").write_text(json.dumps(good))
    acc2 = acceptor(gate, surf)
    pre2 = acc2.precommit(run, objective_for([ALPHA], ["hi"]))
    expect(pre2.ledger_seq > pre1.ledger_seq, "commitment not fresh")
    run.accept_with(acc2.decide(run))

    acc3 = acceptor(gate, surf)
    raises(AcceptanceBudgetExhausted, acc3.precommit, run,
           objective_for([ALPHA], ["hi"]))
    return (f"REJECT at seq {pre1.ledger_seq}; fresh commitment at "
            f"{pre2.ledger_seq} accepted; third attempt refused on budget")


# ==========================================================================
def main() -> int:
    print("=" * 74)
    print("PACK 06  browser-execution  -  test_pack.py")
    print("=" * 74)
    tmp = tempfile.mkdtemp(prefix="p06-")
    failures = 0
    for fn in _RESULTS:
        name = fn.__name__
        try:
            detail = fn(tmp)
            print(f"  PASS  {name}\n          {detail}")
        except Exception:  # noqa: BLE001
            failures += 1
            print(f"  FAIL  {name}")
            print("        " + traceback.format_exc().replace("\n", "\n        "))
    print("-" * 74)
    print(f"  {len(_RESULTS) - failures}/{len(_RESULTS)} passed")
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
