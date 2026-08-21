# LAUNCH — pack 07 · capability-manufacture

## Entry point

```bash
cd 07-capability-manufacture
python3 test_pack.py
python3 checks.py <workdir>
```

```python
import checks, state_machine as sm
from _spine import AcceptanceGate, IndependentAcceptor

spec = sm.CommissionSpec(
    commission_id="C-1",
    vendor="acme-agent-platform",
    deliverables=(
        sm.Deliverable(path="solver.py", kind="python_module",
                       must_define=("solve", "main"),
                       probe=sm.Probe(argv=("--selftest",), expect_exit=0,
                                      expect_stdout_contains=("SELFTEST OK",))),
        sm.Deliverable(path="cases.jsonl", kind="jsonl", min_bytes=10),
    ),
    min_probes_passed=1,
)

run = sm.CapabilityManufactureRun(workdir, "operator-07", gate, spec, quarantine)
run.dispatch()          # PREFLIGHT   - spec pinned + hashed BEFORE anything returns
run.recover_state()     # CURRENT_STATE_RECOVERED
#   ... the vendor drops its return into `quarantine` ...
run.admit_return()      # INPUT_ADMITTED - byte inventory of what arrived
run.validate_return()   # ACTION_EXECUTED - typecheck + execute their code
run.artefacts_present() # REQUIRED_ARTEFACTS_PRESENT - refuses unless MATERIAL
run.machine_checks()    # MACHINE_CHECKS_PASSED  <-- producer stops here
# COMMIT-FIRST ACCEPTANCE
import acceptance
from _spine import CommitFirstAcceptor
objective = acceptance.objective_for(spec, quarantine)
acc = CommitFirstAcceptor("acceptor-QA", gate,
                          derive=acceptance.derive_expectation,
                          compare=acceptance.compare_to_expectation)
run.finish(acc, objective)   # the acceptor runs the probes itself, first
run.promote("/opt/capabilities/solver")   # only reachable after acceptance
```

## Writing a commission that can actually be graded

A deliverable with no `probe` can only ever be checked for *shape*. Shape is
what a narrative return is best at faking. **At least one deliverable must
carry a probe, and `min_probes_passed` must be ≥ 1**, or this pack degrades
into a file-existence checker.

A good probe:
- runs the artefact as a subprocess and asserts on **stdout we captured**
- has a deterministic expected string, not "no exception"
- is cheap enough to run on every return, including re-commissions

## Mandate

Commission an external agent platform for a named capability, take delivery
into quarantine, and decide — from execution, not from documentation — whether
a capability actually arrived.

## Maximum delegated authority

| | |
|---|---|
| May write to | `workdir`, and read `quarantine` |
| May execute | vendor artefacts, as subprocesses, inside `quarantine`, under a wall-clock timeout |
| May promote out of quarantine | only after `INDEPENDENT_ACCEPTANCE`, only declared deliverables |
| May not | alter the spec after dispatch; count vendor self-reports as evidence; grant MATERIAL without a passing probe |
| Phase reachable alone | `MACHINE_CHECKS_PASSED` |
| Money / contracts | **out of scope.** This pack decides *accept or reject*. It never signs, pays, renews, or negotiates. Route those to a human. |

## Verdict meanings and what to do next

| Verdict | Meaning | Next action |
|---|---|---|
| `MATERIAL` | Every deliverable conforms and every probe passed **under our execution**. | Accept, promote. |
| `PARTIAL` | Some of it works. | Re-commission the gap. Do not promote the working half into a system that expects the whole. |
| `NARRATIVE_RETURN` | Confident prose, no working artefact. | Re-commission with the same spec. Send the claim list back with it. Escalate if it recurs — this is a vendor-capability signal, not a bug. |
| `EMPTY` | Nothing arrived. | Chase delivery. Different problem from the above. |

## Escalate, do not improvise

- `SpecMutated` — someone tried to move the acceptance criteria after seeing
  the return. That is a governance event, not a merge conflict.
- `QuarantineEscape` — a declared path resolved outside quarantine. Treat as
  hostile until proven otherwise.
- A second consecutive `NARRATIVE_RETURN` from the same vendor.
