# PO03-WA-005 — a partial artifact write cannot reach RESULT_STAGED

- **Task:** `PO03-WA-005`
- **Route:** `route-01` (transactional-custody), fence token 1, lease `lease-PO03-WA-005-1`
- **Immutable base:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Frozen hypothesis:** A partial artifact write cannot reach `RESULT_STAGED`.
- **Disposition:** **PASS**
- **Producer terminal report:** `READY_TO_COMMIT` — `obzio_state = RESULT_STAGED`, `independent_acceptance = NOT_TESTED`.

## What was built

`staging_gate.py` publishes a result slot only after every declared artifact
verifies. Nothing is ever written into the published slot directly: artifacts go
into a sibling scratch directory, each is fsynced, every one is then **read back
from disk** with its SHA-256 recomputed and its byte count compared, and only
then is the scratch directory promoted with a single `os.rename`.

A half-written slot is worse than a missing one. Missing work is obvious and
gets retried; a truncated artifact behind a confident `RESULT_STAGED` marker
looks complete to every downstream consumer and to any reviewer who checks state
rather than bytes. So a failed stage stays at `RESULT_STAGING` and publishes
nothing.

## Two fault families, deliberately separated

| Fault | Mechanism | Caught by |
| --- | --- | --- |
| Silent short write | the loop completes, nothing raises | readback verification |
| Loud process loss | control flow aborts mid-loop | the abort itself, plus recovery |

The silent one is the dangerous one, because the gate is told the slot is ready.

## Commands and observed results

```
$ python3 staging_gate.py --demo             # exit 0
$ python3 -m unittest -v test_staging_gate   # exit 0
```

Full transcript: `evidence/observed-output.txt`.

- 16 tests, **16 passed, 0 failed**, exit 0.
- Exhaustive short-write matrix over (3 artifacts × 4 truncation points): every
  case was caught with `ARTIFACT_VERIFICATION_FAILED`, none reached
  `RESULT_STAGED`, none published a slot.
- Exhaustive process-loss matrix (before and after each of 3 artifacts): all six
  refused with `PROCESS_LOST_MID_WRITE`, state stayed `RESULT_STAGING`, no slot
  published.
- Truncation reporting is specific: `nested/b.txt`, `BYTES_TRUNCATED`, declared
  200 bytes, observed 50, hashes differ.
- **Same-length corruption** (100 bytes of `A` declared, 100 bytes of `B`
  written) is caught as `HASH_MISMATCH`. A byte-count-only gate would pass this.
- A missing artifact is classified `MISSING_ARTIFACT`, distinct from truncation.
- Verification reads the file, not the declaration: overwriting an artifact
  after it is written is still detected.
- Recovery names and discards crash debris, and a retry after a failed stage
  succeeds.

### Design defect found and fixed during execution

The first execution failed three tests. The cause was in the component: a single
`CrashInjector` conflated truncation with crashing, raising `InjectedCrash`
whenever a truncation was configured. Every truncation therefore aborted the
write loop and **verification was never reached** — the component could not
exhibit the silent short write at all, which is precisely the fault the
hypothesis is about. The injector was split into independent
`truncate_at_index` and `crash_at_index`/`crash_after_index` controls so both
families are exercised on their own paths. The failing tests revealed a real gap
in the fixture rather than a wrong expectation.

## Limitations

- Fault injection is at the application layer. Real short writes from a full
  disk, a failing device or an interrupted `write(2)` are modelled, not induced.
- `os.rename` atomicity holds within a filesystem. Promotion across filesystems
  would not be atomic and is not supported.
- fsync is issued for each artifact and for the parent directory on promotion,
  which is correct on common Linux filesystems but is not a proof of durability
  under arbitrary mount options or virtualised storage.
- The gate verifies artifacts against a declaration made in the same process.
  Reconciling that declaration against an independently authored manifest is a
  provenance concern belonging to route-05, not to this task.
- `decision_changed: []`.
