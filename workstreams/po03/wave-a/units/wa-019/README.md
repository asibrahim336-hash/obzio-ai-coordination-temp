# PO03-WA-019 topology benchmark

This unit tests the frozen hypothesis exactly:

> Centralized, sharded, and event-sourced coordination topologies produce
> distinguishable accepted-throughput and recovery outcomes.

It contains three executable candidates under `candidates/` and one matched,
deterministic logical-clock benchmark. All candidates receive the same 32
sanitized tasks, task order, coordinator-loss tick, four worker slots, and four
coordination operations per tick. The topology implementation—not a changed
workload—determines the response to process loss.

Run from this directory:

```sh
python3 -m benchmark.runner --topology all
python3 -I candidates/centralized.py
python3 -I candidates/sharded.py
python3 -I candidates/event_sourced.py
python3 -I -m unittest discover -s tests -p 'test_*.py' -v
```

The simulator is standard-library-only and writes nothing unless the runner is
given `--output`. The checked-in fixture is synthetic, contains no secrets or
external identifiers, and records its derivation from the immutable repository
source commit. `result/benchmark-results.json` is the executed matched run.

The outcome applies only to this declared model and fixture. It is not a
production topology recommendation or independent acceptance.
