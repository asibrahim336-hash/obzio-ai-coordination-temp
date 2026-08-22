# PO03-WA-017 — zero-base repository-factory candidates

This unit executes three different repository-factory architectures against one
hash-frozen, sanitized PO-03 workload:

1. `central-gate`: shared FIFO, global write lock, synchronous central verifier.
2. `lease-shards`: partitioned FIFOs, local locks, monotonic fences, per-shard
   verification, and recovery-only coordination for observed conflicts.
3. `event-log`: optimistic workers, append-only result events, asynchronous
   reducer, and replay-derived accepted state.

The fixture was committed before simulator execution. The preregistered
comparison fixes safety gates, throughput spread, pairwise materiality, and
independence criteria. Candidate algorithms are implemented in separate modules
and do not inherit a shared scheduler.

Run from a clean clone:

```sh
python3 -I workstreams/po03/wave-a/units/wa-017/simulator.py \
  --output workstreams/po03/wave-a/units/wa-017/result/simulation-results.json

PYTHONDONTWRITEBYTECODE=1 python3 -I -m unittest discover \
  -s workstreams/po03/wave-a/units/wa-017/tests \
  -p 'test_*.py' -v
```

The simulator uses only the Python standard library, deterministic logical
ticks, frozen JSON, and repository-relative paths. It performs no network call
or external write. Its claims are bounded to this simulation; no architecture
is selected or bound for production.
