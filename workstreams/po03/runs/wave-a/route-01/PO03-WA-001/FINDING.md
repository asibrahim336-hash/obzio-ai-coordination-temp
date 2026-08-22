# PO03-WA-001 — custody transitions reject skipped or reversed states

- **Task:** `PO03-WA-001`
- **Route:** `route-01` (transactional-custody), fence token 1, lease `lease-PO03-WA-001-1`
- **Immutable base:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Frozen hypothesis:** State transitions reject skipped or reversed custody states.
- **Disposition:** **PASS**
- **Producer terminal report:** `READY_TO_COMMIT` — `obzio_state = RESULT_STAGED`, `independent_acceptance = NOT_TESTED`.

## What was built

`custody_fsm.py` is an executable custody state machine for the ten-rung Obzio
ladder plus five off-ladder states. Legal movement is an **explicitly declared
edge set**, not a computed ordinal comparison, so the machine cannot be widened
by accident. It enforces four separable invariants:

| Invariant | Rejection reason |
| --- | --- |
| Forward movement advances exactly one rung | `SKIPPED_STATE` |
| A ladder state never moves to a lower rung | `REVERSED_STATE` |
| Terminal states have no outgoing edges | `TERMINAL_STATE_RESURRECTION` |
| Off-ladder states re-enter only at `LEASED` | `ILLEGAL_LADDER_REENTRY` |

It additionally refuses a worker-actor transition above the producer ceiling
`RESULT_STAGED` (`PRODUCER_CEILING_EXCEEDED`), refuses `PARENT_INGESTED` and
`COMPLETED` from any non-coordinator actor (`ACTOR_NOT_PERMITTED`), and refuses
ladder re-entry on a non-increasing fence (`STALE_FENCE_ON_REENTRY`).

## How it is falsifiable

`test_custody_fsm.py` is exhaustive rather than example-driven. It enumerates
**all 90 ordered pairs** of the ten ladder states and asserts that the set of
accepted pairs equals exactly the nine single-rung forward edges. If any skip or
reversal were accepted, `test_every_ladder_pair_is_classified` fails on the set
comparison, so the hypothesis is falsified by construction rather than by a
hand-picked case. Every rejection must also carry the correct machine-readable
reason, so a rejection for the wrong cause is a failure too.

## Commands and observed results

```
$ python3 custody_fsm.py --demo
$ python3 custody_fsm.py --from CREATED --to COMPLETED    # exit 1
$ python3 -m unittest -v test_custody_fsm                 # exit 0
```

Full transcript: `evidence/observed-output.txt`.

- 17 tests, **17 passed, 0 failed**, exit 0.
- `CREATED -> COMPLETED` (the shape of the recorded PO-02 Code-2 false
  completion) is rejected as `SKIPPED_STATE`, detail `COMPLETED is 9 rungs above
  CREATED; only 1 is legal`, and the record's state and history are unchanged.
- `RUNNING -> RESULT_COMMITTED` is rejected as `SKIPPED_STATE` (5 rungs).
- `RESULT_COMMITTED -> RUNNING` is rejected as `REVERSED_STATE`.
- `COMPLETED -> RUNNING` is rejected as `TERMINAL_STATE_RESURRECTION`.
- A worker attempting `RESULT_STAGED -> RESULT_VERIFIED` is rejected as
  `PRODUCER_CEILING_EXCEEDED`.

Two assertions failed on the first execution. Both were incorrect expectations
in the test file (a rung count of 4 where the ladder distance is 5, and
`UNDECLARED_EDGE` where the component returns the more precise
`ILLEGAL_LADDER_REENTRY`). The component was not changed to make the tests pass;
the assertions were corrected to the observed, more specific classifications.

## Limitations

- The machine validates transition *legality* only. It does not verify that the
  artifacts implied by a rung actually exist on disk; that obligation is
  discharged separately by `PO03-WA-005`.
- Rejection is in-process. Nothing here prevents a caller from writing a state
  field directly without consulting the machine; enforcement at the durable
  boundary is `PO03-WA-002`'s concern.
- Exhaustiveness covers ordered *pairs*. Longer illegal paths are covered only
  by the pairwise property plus the named walk tests, not by full path
  enumeration.
- `decision_changed: []` — no strategy binding is proposed or changed.
