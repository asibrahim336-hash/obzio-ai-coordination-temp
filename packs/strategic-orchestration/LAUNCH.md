# LAUNCH — strategic-orchestration

## Entry point

```bash
cd /tmp/packs/strategic-orchestration
python3 test_pack.py                      # full lifecycle + injected failure
python3 checks.py <run_dir>               # checks alone, exit 0 = pass
```

Programmatic:

```python
from state_machine import build_machine, make_acceptor
from obzio_spine.expectation import AcceptanceReturn

# 1. COMMIT FIRST -- the acceptor derives its own expected reconciliation from
#    the declared inputs, before any artefact exists.
acceptor = make_acceptor("reviewer-01", objective_doc, spec, returns)

m = build_machine(run_dir, producer_id, commitments, objective_doc, spec,
                  returns, acceptor=acceptor)   # registers at PREFLIGHT
for _ in range(6):   m.advance()          # PREFLIGHT -> INDEPENDENT_ACCEPTANCE

# 2. SINGLE BIT back to the producer, plus both reveals. No rationale.
m.advance(acceptance=AcceptanceReturn(
    accept=True,
    acceptance_reveal=kp.issue(m.current_run_digest(), ACCEPT),
    expectation_reveal=acceptor.reveal()))
m.advance()                               # -> COMPLETE
```

`commitments` MUST come from a reviewer principal that is not `producer_id`.
The constructor refuses the machine outright if they match.

## Acceptance independence: `INDEPENDENT_ORACLE`

Acceptance is **commit-first**. The acceptor derives and hash-commits its own
expected result from the declared inputs *before any artefact exists*; the
machine refuses the commitment if one already does. At the gate the artefacts
are compared against that commitment and **divergence defaults to REJECT**.
The channel back to the producer is **one bit** — no rationale, no diff, no
rubric. See BOUNDARIES.md for exactly what this oracle does and does not
cover.

## Mandate

Take one founder objective with a finite budget and a deadline. Decompose it
into bounded commissions, route each to a capability pool, and reconcile every
return against what was commissioned. Emit the four artefacts and a return
state that a later operator can resume from with no conversation history.

## Maximum delegated authority

| Act | Authority |
|---|---|
| Decompose an objective into commissions | **GRANTED** |
| Assign a commission to a capability pool | **GRANTED** |
| Set an authority ceiling on a commission | **GRANTED, bounded** — never above this orchestrator's own ceiling (`CHK-SO-03`) |
| Reconcile returns and report gaps | **GRANTED** |
| Execute the work inside any commission | **DENIED** — orchestration routes, it does not perform |
| Manufacture a return for a commission | **DENIED** — returns are inputs, never generated here |
| Raise the objective budget to fit the decomposition | **DENIED** — over-commitment is refused, not absorbed |
| Accept its own orchestration | **DENIED** — machine-enforced at the gate |

Default ceiling is `PROPOSE_ONLY`. Anything above that must be granted
explicitly in `objective_doc["orchestrator_max_authority"]` and is still
capped by the authority ladder in `checks.py`.

## Required artefacts

`objective.json` · `commissions.json` · `routing_table.json` ·
`reconciliation.json` — plus `check_report.json`, `journal.json`,
`return_state.json` written by the spine.

## Definition of done

`return_state.json` exists, `final_state` is `COMPLETE`, `verdict` is
`ACCEPT`, and `accepted_run_digest` matches a recomputed digest of the
artefact set. Any of those absent means not done, whatever the transcript says.
