# PO03-WA-014 A02 — lease and fencing store

This unit tests the frozen hypothesis:

> Monotonic fence tokens prevent an expired worker from committing after
> ownership transfer.

`mechanism/lease_fence.py` is a dependency-free SQLite implementation. The
store allocates tokens inside a `BEGIN IMMEDIATE` transaction. A commit must
present the exact current token, owner, lease ID, and an unexpired lease. Fence
validation precedes idempotency replay handling, so an old callback is rejected
even if it repeats a request that was valid before transfer.

The sanitized concurrency fixture gives worker A fence 1, expires that lease,
transfers ownership to worker B at fence 2, commits B's payload, and only then
releases A to attempt its delayed commit. The stale attempt must raise
`StaleFence`, and the durable store must contain exactly B's commit.

Run from the repository root with bytecode disabled:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -I -m unittest discover \
  -s workstreams/po03/wave-a/units/wa-014/tests -p 'test_*.py' -v

PYTHONDONTWRITEBYTECODE=1 python3 -B -I \
  workstreams/po03/wave-a/units/wa-014/mechanism/run_concurrency_fixture.py

PYTHONDONTWRITEBYTECODE=1 python3 -B -I \
  workstreams/po03/wave-a/units/wa-014/mechanism/run_recurrence.py \
  --iterations 64
```

Tests and fixtures create and remove SQLite scratch files only beneath this
owned unit. No external service, secret, production state, PO-01 surface, or
pull request is contacted.

Evidence is separated by state:

- `evidence/source-claims.json`: claims from immutable repository sources;
- `evidence/frozen-hypotheses.json`: preregistered falsifiers;
- `evidence/sanitized-reproduction.json`: executed fixture disposition;
- `evidence/mechanism-changes.json`: implementation disposition;
- `evidence/strategy-proposals.json`: non-binding proposals (none);
- `result/`: command evidence, limitations, manifest, and producer return.

This producer reports only `READY_TO_COMMIT`. Coordinator completion and
independent acceptance remain unset.
