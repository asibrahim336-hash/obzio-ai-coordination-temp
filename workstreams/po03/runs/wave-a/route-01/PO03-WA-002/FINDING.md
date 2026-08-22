# PO03-WA-002 — a stale fence token cannot stage or commit

- **Task:** `PO03-WA-002`
- **Route:** `route-01` (transactional-custody), fence token 1, lease `lease-PO03-WA-002-1`
- **Immutable base:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Frozen hypothesis:** A stale fence token cannot stage or commit a result.
- **Disposition:** **PASS**
- **Producer terminal report:** `READY_TO_COMMIT` — `obzio_state = RESULT_STAGED`, `independent_acceptance = NOT_TESTED`.

## What was built

`fenced_sink.py` is a durable, file-backed result sink whose fence register
lives inside the sink rather than in the caller. Every mutating operation
(`acquire`, `stage`, `commit`) takes the caller's fence token as a required
argument and is checked against a strict high-water mark:

- `fence < high_water` → `StaleFenceError`, no state change;
- `fence == high_water` → accepted, the caller is the current holder;
- `fence > high_water` → accepted and the mark is raised, permanently evicting
  every older lease.

The check and the state write happen inside a single `flock` hold, so there is
no check-then-act window, and the state file is updated by write-temp + `fsync`
+ `os.replace` so the guard survives process death.

## Fault reproduced

`reproduce_delayed_worker` stages the delayed-worker overwrite: A leases at
fence 1, stalls; the coordinator re-leases to B at fence 2; B stages and
commits; A then wakes believing its lease is still valid and tries to stage and
commit its obsolete result. Wall-clock expiry cannot stop A — A's own clock says
it still holds the lease. The fence does.

## Commands and observed results

```
$ python3 fenced_sink.py --demo            # exit 0
$ python3 -m unittest -v test_fenced_sink  # exit 0
```

Full transcript: `evidence/observed-output.txt`.

- 15 tests, **15 passed, 0 failed**, exit 0.
- Reproduction timeline: the four fence-2 operations are `ACCEPTED`; both
  stale fence-1 operations are `REFUSED` with `StaleFenceError`.
- Final state: `high_water_fence = 2`, `txn_state = COMMITTED`, committed by
  `worker-B`, `accepted_writes = 2` — the two refusals are not counted as writes.
- `sink_bytes_unchanged_by_rejections = true`: the sink document is byte-identical
  before and after the refusals apart from the appended audit entries.
- The multi-process test (`spawn` context, a genuinely separate interpreter)
  confirms the refusal comes from durable state, not from one process's memory.

### Defect found and fixed during execution

The first execution failed `test_rejection_is_audited_with_both_fences` with an
`IndexError`: the rejection log was empty. The cause was real and in the
component, not the test. `_exclusive` performed its durable write *after* the
`yield`, so when a refusal raised through the context manager the audit append
was discarded along with the exception — a rejected write was indistinguishable
on disk from a write that was never attempted. The write was moved into a
`finally` block so refusal records are persisted. This is the only case where
persisting on the exception path is correct: a refusal mutates nothing but the
audit list.

## Limitations

- The sink is single-task and file-backed. It demonstrates the fencing rule but
  is not a distributed store; cross-host correctness would additionally depend
  on the backing store honouring compare-and-set.
- `flock` is advisory and POSIX-specific. A writer that bypasses this class and
  edits the JSON directly is not prevented.
- The multi-process test proves durability across processes on one filesystem;
  it does not exercise network partition or clock skew directly, which is the
  point — the fence is deliberately clock-free.
- `decision_changed: []`.
