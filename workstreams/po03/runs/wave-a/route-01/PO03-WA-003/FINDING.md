# PO03-WA-003 — duplicate callbacks are idempotent

- **Task:** `PO03-WA-003`
- **Route:** `route-01` (transactional-custody), fence token 1, lease `lease-PO03-WA-003-1`
- **Immutable base:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Frozen hypothesis:** Duplicate callbacks are idempotent and create one result transaction.
- **Disposition:** **PASS**
- **Producer terminal report:** `READY_TO_COMMIT` — `obzio_state = RESULT_STAGED`, `independent_acceptance = NOT_TESTED`.

## What was built

`idempotent_callback.py` is a durable callback receiver that collapses
at-least-once delivery onto exactly-once effect. Reservations are keyed by
idempotency key and content-addressed by a canonical digest of the request body:

| Arrival | Outcome |
| --- | --- |
| First for a key | `CREATED`, a new `result_txn_id` is reserved |
| Repeat, same body digest | `DUPLICATE_IGNORED`, the original id is returned unchanged |
| Repeat, different body digest | `IdempotencyConflict` raised, nothing overwritten |

The third row matters: a same-key-different-body arrival is not a duplicate,
and silently picking either payload would discard a real result. The receiver
refuses instead of choosing.

Lookup, conflict check and allocation all happen inside a single `flock` hold.
That is the load-bearing property — a receiver that checks "have I seen this
key" and then allocates outside the lock mints two transactions under the
concurrent retry pattern a real HTTP client produces.

## How it is falsifiable, with a negative control

The concurrency assertion would be worthless if the race simply never fired.
The suite therefore includes `NaiveReceiver`, a deliberately defective
check-then-act receiver with the same interface, driven through the identical
two-thread race with a barrier that widens the window deterministically rather
than hoping the scheduler loses. The control **must** allocate two transactions
for the test to be meaningful; the guarded receiver must allocate one under the
same race. Both are asserted.

## Commands and observed results

```
$ python3 idempotent_callback.py --demo            # exit 0
$ python3 -m unittest -v test_idempotent_callback  # exit 0
```

Full transcript: `evidence/observed-output.txt`.

- 14 tests, **14 passed, 0 failed**, exit 0.
- Duplicate storm, 32 concurrent deliveries across 16 threads synchronised on a
  barrier: `created = 1`, `duplicates_ignored = 31`, exactly one distinct
  `result_txn_id` (`rtxn-1d1237b44e4fe2b1`), one transaction in the store, one
  `CREATED` ledger event, `allocations = 1`.
- Conflicting body under the same key raised `IdempotencyConflict` reporting
  both digests, and the stored body was unchanged.
- Negative control allocated **2** transactions under the same race, confirming
  the assertion detects the defect it claims to detect.
- Dedupe survives receiver restart: a fresh receiver object over the same
  directory returned the original id with `allocations = 0`.
- The ledger retains all 10 deliveries in the restart test while recording only
  one creation, so at-least-once delivery stays observable without becoming a
  duplicate effect.

## Limitations

- Exactly-once is reconstructed at the receiver. Nothing here makes the network
  deliver once; that is not achievable and is not claimed.
- The reservation table is a single JSON document under `flock`, adequate for
  one host. A multi-host deployment would need the same logic expressed as a
  conditional insert in a shared store.
- Conflict resolution is refusal. Deciding *which* of two conflicting bodies is
  authoritative is a coordinator policy question and is deliberately out of scope.
- The negative control demonstrates one defect shape (check-then-act). It does
  not enumerate all possible incorrect receivers.
- `decision_changed: []`.
