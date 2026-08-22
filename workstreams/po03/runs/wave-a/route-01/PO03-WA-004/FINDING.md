# PO03-WA-004 — a lost callback is recovered from the durable outbox

- **Task:** `PO03-WA-004`
- **Route:** `route-01` (transactional-custody), fence token 1, lease `lease-PO03-WA-004-1`
- **Immutable base:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Frozen hypothesis:** A lost callback is recovered from the durable outbox.
- **Disposition:** **PASS**
- **Producer terminal report:** `READY_TO_COMMIT` — `obzio_state = RESULT_STAGED`, `independent_acceptance = NOT_TESTED`.

## What was built

`outbox_relay.py` implements the transactional outbox for result notification.
The load-bearing change is that committing the result and recording the intent
to notify are **one atomic file replacement**, not two independent actions:

- die before the replace → neither exists, the work is simply retried;
- die after the replace → both exist, and the pending outbox row is a durable,
  discoverable instruction to re-notify.

There is no code path that yields a committed result with no outbox row. A
separate `OutboxRelay` drains pending rows against an `UnreliableChannel` and
marks a row acknowledged only on confirmed delivery, so delivery is
at-least-once while the parent's idempotency key keeps the effect exactly-once.

`commit_without_outbox` is included as an explicitly labelled **unsafe control**
reproducing the pre-outbox behaviour, where the notification intent lives only
in the dying process.

## Fault reproduced

This is the shape of the recorded PO-02 Code-2 loss: the worker finished, the
callback went out, nothing arrived, and there was nothing durable left to retry
from. The result was real; the notification was not recoverable.

## Commands and observed results

```
$ python3 outbox_relay.py --demo         # exit 0
$ python3 -m unittest -v test_outbox_relay  # exit 0
```

Full transcript: `evidence/observed-output.txt`.

- 12 tests, **12 passed, 0 failed**, exit 0.
- With the outbox, drop schedule `[True, True, False]`: 3 channel attempts, 1
  delivery, `pending_after_drain = 0`, `parent_ingested = 1`, outbox row
  `ACKNOWLEDGED` after 3 attempts. The lost callback was recovered.
- The loss pattern is **swept, not picked**: every drop schedule up to length
  five (62 schedules, each terminated by a success) recovers to exactly one
  ingestion with an empty outbox. No schedule failed.
- A permanently dead channel (50 consecutive drops) leaves the row `PENDING`
  with an incrementing attempt count — never silently discarded.
- Re-running the relay after success produces no outcomes, so an acknowledged
  row is not re-sent.
- Forced double delivery (a lost acknowledgement putting an already-received row
  back to `PENDING`): the parent genuinely saw **2** deliveries and recorded
  **1** ingested effect.
- Unsafe control: the result is committed (`result_committed = true`), the
  callback is lost, and after restart there are **0** recoverable rows and
  **0** parent ingestions. The correct classification of that state is
  `PROVIDER_COMPLETED_UNCOMMITTED`, which is `PO03-WA-007`'s subject.

## Limitations

- Atomicity here is a single-file `os.replace`, which is the right primitive for
  this fixture but is not a multi-table database transaction. A real deployment
  writing results and outbox rows to different stores needs a genuine
  transaction or an equivalent single-writer log.
- The channel is a deterministic in-process simulation. It models loss, not
  latency, reordering, partial writes on the wire, or byzantine acknowledgement.
- The relay is driven synchronously by the test. Scheduling, backoff and
  poison-row quarantine policy are not implemented.
- Exactly-once effect depends on the receiver honouring the idempotency key;
  that receiver is `PO03-WA-003`'s subject and is only modelled here.
- `decision_changed: []`.
