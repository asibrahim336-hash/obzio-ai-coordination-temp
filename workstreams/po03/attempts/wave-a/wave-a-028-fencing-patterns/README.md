# Wave A 028 — fencing patterns

This result slot contains a standard-library-only, deterministic reproduction
of stale-owner writes and fencing-token edge cases.

Run from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 \
  workstreams/po03/attempts/wave-a/wave-a-028-fencing-patterns/run_fixtures.py

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s workstreams/po03/attempts/wave-a/wave-a-028-fencing-patterns/tests \
  -p 'test_*.py' -v
```

The fixture runner returns exit code 0 only when all frozen observations match.
It can also write canonical output:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 \
  workstreams/po03/attempts/wave-a/wave-a-028-fencing-patterns/run_fixtures.py \
  --output workstreams/po03/attempts/wave-a/wave-a-028-fencing-patterns/evidence/fixture-output.json
```

`analysis.md` gives the disposition. `research.md` records source claims,
derived edge cases and refuting outcomes. The unsafe API in
`fencing_model.py` exists only as a fault fixture.

This attempt does not claim Obzio completion or independent acceptance.
