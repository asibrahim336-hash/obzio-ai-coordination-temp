"""The forced-interruption test W18 named as the proof obligation.

A clean runner, given only canonical artefacts and no chat history, must resume
at the correct point, must not repeat a committed side effect, and must not skip
unfinished work - for a kill at EVERY position, not one convenient position.
"""
import os
import tempfile
from contract import WorkUnit
from ledger import Ledger
from runner import Runner, ForcedInterruption

STEPS = ["extract", "verify", "publish", "receipt"]

UNIT = WorkUnit(
    unit_id="WU-001",
    objective="reconcile one estate delta end to end",
    inputs={"source": "estate-delta-001"},
    acceptance=STEPS,
    authority_scope=["read:estate", "write:ledger"],
    forbidden=["external:send", "delete:depended-upon"],
    side_effects=[f"did:{s}" for s in STEPS],
)


def fresh():
    d = tempfile.mkdtemp()
    return os.path.join(d, "run.jsonl")


def run_with_kill(path, kill_before=None, kill_after=None):
    """Each call is a NEW process-equivalent: new Runner, new sink read from
    ledger. Nothing carries over in memory."""
    sink = []
    led = Ledger(path)
    # rebuild the outside world from the ledger alone - cold start
    for ev in led.read():
        if ev["kind"] == "effect":
            sink.append(ev["payload"]["effect"])
    r = Runner(UNIT, led, sink)
    try:
        r.run(STEPS, kill_before=kill_before, kill_after=kill_after)
        return sink, False
    except ForcedInterruption:
        return sink, True


def test_kill_at_every_position():
    failures = []
    positions = [("before", s) for s in STEPS] + [("after", s) for s in STEPS]
    for mode, step in positions:
        path = fresh()
        kb = step if mode == "before" else None
        ka = step if mode == "after" else None
        sink, interrupted = run_with_kill(path, kill_before=kb, kill_after=ka)
        assert interrupted, f"{mode}/{step}: kill did not fire"
        # cold resume, no history
        sink2, interrupted2 = run_with_kill(path)
        led = Ledger(path)
        r = Runner(UNIT, led, sink2)
        problems = []
        if interrupted2:
            problems.append("resume did not complete")
        if not r.accepts():
            problems.append(f"acceptance failed: {led.committed_steps()}")
        if len(sink2) != len(set(sink2)):
            problems.append(f"DUPLICATE side effect: {sink2}")
        if sorted(set(sink2)) != sorted(UNIT.side_effects):
            problems.append(f"wrong effect set: {sink2}")
        if not led.verify():
            problems.append("ledger chain failed verification")
        if problems:
            failures.append((mode, step, problems))
    return failures


def test_tamper_is_detected():
    path = fresh()
    run_with_kill(path)
    assert Ledger(path).verify(), "clean ledger should verify"
    lines = open(path).read().splitlines()
    # locate a real earlier event and alter it; assert the edit actually landed
    target = next(i for i, l in enumerate(lines) if '"did:verify"' in l)
    assert target < len(lines) - 1, "tamper target must not be the last event"
    before = lines[target]
    lines[target] = before.replace('"did:verify"', '"did:tampered"')
    assert lines[target] != before, "tamper edit did not apply - test would be vacuous"
    open(path, "w").write("\n".join(lines) + "\n")
    return not Ledger(path).verify()


def test_contract_cannot_be_edited_silently():
    j = UNIT.to_json()
    tampered = j.replace('"reconcile one estate delta end to end"', '"something else"')
    try:
        WorkUnit.from_json(tampered)
        return False
    except ValueError:
        return True


if __name__ == "__main__":
    fails = test_kill_at_every_position()
    print(f"forced interruption, {len(STEPS)*2} kill positions: "
          f"{'PASS' if not fails else 'FAIL'}")
    for f in fails:
        print("   ", f)
    print("tamper-evident ledger:      ", "PASS" if test_tamper_is_detected() else "FAIL")
    print("contract seal enforced:     ", "PASS" if test_contract_cannot_be_edited_silently() else "FAIL")
