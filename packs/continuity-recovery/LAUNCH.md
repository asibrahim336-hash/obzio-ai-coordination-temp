# LAUNCH — continuity-recovery

## Entry point

```bash
cd /tmp/packs/continuity-recovery
python3 test_pack.py
python3 checks.py <run_dir>
```

```python
from state_machine import build_machine, make_acceptor
from obzio_spine.expectation import AcceptanceReturn

# COMMIT FIRST: the acceptor walks the corpus and commits its own headline
# counts before the recovery produces anything.
acceptor = make_acceptor("reviewer-01", recovery_root)
m = build_machine(run_dir, producer_id, commitments, recovery_root,
                  acceptor=acceptor)
for _ in range(6): m.advance()
m.advance(acceptance=AcceptanceReturn(True, acceptance_reveal, acceptor.reveal()))
m.advance()
```

`recovery_root` is a directory of durable artefacts from prior runs. It is the
**only** input. `run_dir` must be outside it, or recovery would ingest its own
output on the second pass and the determinism check would be self-fulfilling —
the machine refuses that arrangement.

## Acceptance independence: `INDEPENDENT_ORACLE`

Acceptance is **commit-first**. The acceptor derives and hash-commits its own
expected result from the declared inputs *before any artefact exists*; the
machine refuses the commitment if one already does. At the gate the artefacts
are compared against that commitment and **divergence defaults to REJECT**.
The channel back to the producer is **one bit** — no rationale, no diff, no
rubric. See BOUNDARIES.md for exactly what this oracle does and does not
cover.

## Mandate

The conversation is gone. Rebuild operating state from what was written to
disk, and be able to prove which artefact every recovered field came from.

The failure mode is not forgetting — it is **confabulation**: producing a
plausible state where nobody can separate what was read from what was inferred
to make the story cohere.

## Maximum delegated authority

| Act | Authority |
|---|---|
| Scan the recovery root and read any artefact | **GRANTED** |
| Record a fact **with** a resolvable provenance pointer | **GRANTED** |
| Declare a gap for anything the artefacts do not answer | **GRANTED** |
| Report a contradiction between two artefacts | **GRANTED** |
| **Resolve** a contradiction by choosing a value | **DENIED** — `CHK-CR-05` |
| Record a value not literally present at a cited pointer | **DENIED** — `CHK-CR-01` re-resolves every pointer |
| Fill a gap by inference, recency, or plausibility | **DENIED** — gaps are listed, never guessed |
| Accept remembered or conversational context | **DENIED** — no parameter exists to pass it |
| Write into the recovery root | **DENIED** — refused at recovery |
| Accept its own recovery | **DENIED** — machine-enforced at the gate |

## What "recovered" means here

| Recovered | How |
|---|---|
| Which runs exist, their pack, producer, final state, verdict | `return_state.json` per run dir |
| Which acceptances are bound to which digests | `/accepted_run_digest` |
| Outstanding commissions | `reconciliation.json` `/missing_returns` |
| Open pull requests awaiting a decision | `pr_record.json` `/state` |
| Change orders awaiting founder confirmation | `change_orders.json` |
| Everything the artefacts do not say | `gap_report.json` |

## Required artefacts

`recovered_state.json` · `provenance.json` · `gap_report.json` — plus
`check_report.json`, `journal.json`, `return_state.json`.

## Definition of done

Every fact in `provenance.json` re-resolves to its cited file and pointer, the
file inventory is complete, contradictions are unresolved, gaps are enumerated,
recovery is byte-reproducible, and the reviewer returned ACCEPT.
