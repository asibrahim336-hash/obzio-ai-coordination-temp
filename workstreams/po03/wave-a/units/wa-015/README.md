# PO03-WA-015 — Transactional outbox replay

Falsifiable hypothesis (`H-PO03-WA-015`): duplicate and lost callbacks can
replay without duplicate task transitions or external effects.

## Mechanism

`outbox_processor.py` is the executable mechanism. Its durable state is exactly
one append-only journal per store; every projection is rebuilt by replaying
frames from byte zero, so there is no mutable snapshot that a crash can leave
disagreeing with the log.

- **One frame per decision.** An admitted callback commits its task transition
  *and* its outbox enqueue inside a single CRC-framed journal record. A crash can
  therefore never leave a transition without its queued effect, or an effect
  without the transition that authorised it.
- **Inbox deduplication.** `delivery_id` is the idempotency key. An identical
  redelivery is `DUPLICATE_SUPPRESSED` and appends nothing. A redelivery whose
  canonical payload differs is `IDEMPOTENCY_PAYLOAD_CONFLICT`.
- **Terminal versus retriable refusal.** `STATE_MISMATCH` and `FUTURE_FENCE`
  mean "not yet": they are recorded as evidence but do not claim the delivery id,
  so an out-of-order callback still applies once it arrives in order. Every other
  refusal is terminal and claims the delivery id permanently.
- **Idempotent effect sink.** External effects are applied through a sink that is
  idempotent on `effect_key` and is consulted *before* the journal records the
  dispatch. A crash between the two replays as `ALREADY_APPLIED`, never as a
  second external effect. The sink log is the external effect surface: one record
  per key means one effect.
- **Leases and fencing.** A lease transfer bumps the fence by exactly one and
  rebinds the producer. A displaced worker offering the old fence is refused with
  `STALE_FENCE` and cannot commit after ownership transfers.
- **Monotonic checkpoints.** A checkpoint sequence may never regress, and a new
  `CHECKPOINTED` record must strictly advance it.
- **Custody guards.** Only the coordinator may record `COMPLETED`; a producer may
  not review its own result; `RESULT_COMMITTED` requires an external effect; and
  provider `COMPLETED` without a durable commit is reported as
  `PROVIDER_COMPLETED_UNCOMMITTED`, never as completion.
- **Recovery scanner.** A torn tail frame is detected by its length/CRC header,
  truncated, and recorded once. The scanner reports pending effects, uncommitted
  tasks and uncommitted provider completions, and is idempotent.

No wall-clock, path or environment value enters any record or report, so the
compiled evidence is byte-identical across runs, machines and clean clones.

## Layout

| Path | Role |
| --- | --- |
| `outbox_processor.py` | The mechanism: framed journal, inbox dedupe, outbox, idempotent sink, fencing, recovery scanner. |
| `replay_harness.py` | Fault-injecting scenario runner, structural invariant audit, expectation comparison. |
| `verify_replay.py` | Recurrence check of the compiled report against the committed oracle. |
| `compile_artifact_manifest.py` | Deterministic artifact manifest compiler for the owned subtree. |
| `fixtures/sanitized-workload.json` | Sanitized repository-native custody workload: 3 tasks, 38 callbacks. |
| `fixtures/duplicate-callbacks.json` | 7 duplicate-callback scenarios. |
| `fixtures/lost-callbacks.json` | 9 lost-callback and crash-recovery scenarios. |
| `reproduction/expected-report.json` | Frozen byte oracle for the compiled replay report. |
| `tests/` | Focused automated tests for every component above. |
| `result/` | Result slot: hypothesis, reproduction, mechanism change, source claims, tests, limitations, manifest, custody document and return envelope. |

## Injected faults

Each scenario phase may arm a fault at a named durability boundary. A phase that
trips one loses all in-memory state; the next phase reopens the store from bytes
on disk, exactly as a restarted process would.

| Boundary | Failure it reproduces |
| --- | --- |
| `before_journal_append` | Process loss before the callback becomes durable. |
| `after_journal_append` | Lost acknowledgement: the record is durable but the sender never learns it. |
| `journal_torn_write` | Partial write of a journal frame. |
| `before_sink_apply` | Loss before the external effect is attempted. |
| `before_sink_write` | Loss after the effect was decided but before it became durable. |
| `sink_torn_write` | Partial write of a sink record. |
| `after_sink_apply` | Loss between the external effect and the dispatch record. |
| `after_dispatch_record` | Loss after one effect is fully recorded but others remain queued. |

## Reproduce

From a clean clone, with no warm store and no provider memory:

```bash
cd workstreams/po03/wave-a/units/wa-015
python3 -m unittest discover -s tests -t tests      # focused suite
python3 replay_harness.py                            # compiled replay report
python3 verify_replay.py --repeats 6                 # recurrence against the oracle
python3 compile_artifact_manifest.py --output result/artifact-manifest.json --check
cd - && python3 -m unittest discover -s workstreams/po03/tests -t .   # seeded contracts
python3 scripts/check_operator_taxonomy.py
```

`replay_harness.py` exits non-zero if any scenario mismatches its frozen
expectations or violates a structural invariant. `verify_replay.py` exits
non-zero if repeated compilations disagree or diverge from the oracle.
