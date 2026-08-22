# Executable G0 baseline reconstruction

This result executes exact controller source from immutable commit
`1bb843b2a81fd8d73617caf2f1db81909266bb6e` against the frozen local
comparison suite. It does not infer a historical run from source availability.

Run from this directory:

```sh
python3 tools/run_g0.py --output observed/result-contract.json
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The output contract separates:

- `reconstruction_status`: whether exact source was verified and executed;
- `baseline_quality_status`: observed G0 decisions against explicit oracles;
- `successor_lift_claim`: always `NOT_YET` here because G1, G2, independent
  holdouts, and historical generation metrics are outside this result.

`historical_controller/` is byte-identical to selected Git objects at the
historical head. The runner changes only module root bindings and the clock so
each fixture uses a fresh temporary local repository and deterministic time.
Post-head hardening is disclosed but excluded from G0 execution.

The final `manifest.json` inventories every durable file except itself using
slot-relative paths, SHA-256 values, byte counts, and Git blob IDs.
