# LAUNCH — pack 09 · infrastructure-operation

## Entry point

```bash
cd 09-infrastructure-operation
python3 test_pack.py
python3 checks.py <workdir>

# operational CLI (also the crash-test subject)
python3 state_machine.py apply       --db D --op-id ID --account A --cents N
python3 state_machine.py consolidate --db D [--cursor main]
python3 state_machine.py seed        --db D --count N [--note-size B]
python3 state_machine.py dump        --db D
```

```python
import checks, state_machine as sm
from _spine import AcceptanceGate, IndependentAcceptor

run = sm.InfrastructureOperationRun(
    workdir="/var/obzio/infra/<run_id>",
    producer_id="operator-09",
    gate=gate,
    db_path="/var/obzio/state.db",
    cursor_name="main",
)

run.preflight()        # PREFLIGHT
run.recover_state()    # CURRENT_STATE_RECOVERED - watermark + applied keys + growth guard
run.admit_ops([sm.Op("invoice-8842-credit", "credit", "treasury", {"cents": 500})])
run.execute()          # ACTION_EXECUTED - exactly-once apply, then bounded consolidation
run.artefacts_present()
run.machine_checks()   # MACHINE_CHECKS_PASSED  <-- producer stops here
# COMMIT-FIRST ACCEPTANCE
import acceptance
from _spine import CommitFirstAcceptor
objective = acceptance.objective_for(db_path, "main", ops)
acc = CommitFirstAcceptor("acceptor-QA", gate,
                          derive=acceptance.derive_expectation,
                          compare=acceptance.compare_to_expectation)
run.finish(acc, objective)   # the acceptor redoes the arithmetic, first
```

## The one thing you must get right: `op_id`

`Op.op_id` **is** the idempotency key. Everything in this pack depends on the
caller choosing it correctly.

- It must be derived from the **business fact**, not from the attempt.
  `invoice-8842-credit` is right. `uuid4()` is wrong — a retry generates a new
  one and the effect happens twice, and no control here can catch that, because
  from the database's point of view it is a different operation.
- The same `op_id` with a different payload is refused
  (`IdempotencyKeyConflict`), so a key collision fails loudly rather than
  silently reinterpreting one operation as another.

That is the pack's real boundary: it guarantees exactly-once **per key**. It
cannot guarantee that you named the key after the right thing.

## Retry policy

Retry freely. A retry is a no-op that returns the stored result. The supervisor
does not need to know whether the previous attempt got as far as committing —
that is the entire point. `t03` kills the process at four points inside
`apply()` and retries twice from each; every path lands on balance=100,
keys=1.

## Mandate

Execute operations against the database with exactly-once effects, and
consolidate accumulated events without any request growing past the
per-request ceiling.

## Maximum delegated authority

| | |
|---|---|
| May write | `balances`, `applied_ops`, `cursors`, `run_stats`, and `events` via `seed` |
| Per-request ceilings | `MAX_ROWS_PER_REQUEST = 500`, `MAX_REQUEST_BYTES = 65_536` — set **below** any platform limit so we fail with our own diagnostic |
| May never | perform a whole-state read; move a cursor outside the transaction that applies its batch; delete rows from `applied_ops`; raise a ceiling to make a batch fit |
| Phase reachable alone | `MACHINE_CHECKS_PASSED` |
| Schema changes | out of scope. Migrations are not idempotent in the sense this pack enforces. |

Raising `MAX_REQUEST_BYTES` because a batch did not fit is the exact reasoning
that produced the original incident. The correct response to a batch that will
not fit is a smaller batch, and to a **row** that will never fit,
`RowTooLarge` — which names the row instead of stalling the cursor on it
forever.

## Escalate, do not improvise

- `RowTooLarge` — one row cannot ever be batched. The cursor is stuck behind it.
  Fix the row; do not raise the ceiling.
- `IdempotencyKeyConflict` — two different operations were given the same key.
  Someone's key derivation is wrong. Stop and find it.
- `UnboundedReadRefused` — code somewhere wants the whole state. It should want
  a window and a watermark instead.
