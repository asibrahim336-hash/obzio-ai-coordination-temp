# PO03-WA-002 current-source compiler

The dependency-free CLI compiles a hash-bound explicit pointer into a
deterministic current-source manifest. It accepts exactly one `CURRENT`
candidate per logical source, retains `SUPERSEDED` candidates as evidence, and
returns exit code `2` without creating or replacing output on ambiguity or any
provenance failure.

Run the sanitized Obzio reproduction:

```bash
python -I workstreams/po03/wave-a/units/wa-002/current_source_compiler.py \
  workstreams/po03/wave-a/units/wa-002/fixtures/superseded/pointer.json \
  --repository workstreams/po03/wave-a/units/wa-002/fixtures/superseded
```

Run the focused black-box recurrence suite:

```bash
python -I -m unittest discover \
  -s workstreams/po03/wave-a/units/wa-002/tests \
  -p 'test_*.py' -v
```

## Pointer contract

Each pointer is itself `CURRENT` and contains one or more unique logical
selections. Every candidate supplies a repository-relative normalized POSIX
path, exact SHA-256, source ID, and `CURRENT` or `SUPERSEDED` standing. A
superseded candidate must name the selected current source in `superseded_by`.

Each source repeats its ID, logical name, and standing inside the hash-bound
document. Pointer and source declarations must agree. Unknown or duplicate
JSON fields, hash drift, non-portable paths, symlinks, traversal, missing
current candidates, multiple current candidates, and broken supersession
edges are rejected.

The `fixtures/current`, `fixtures/superseded`, and `fixtures/ambiguous`
repositories are sanitized and contain no production state, secrets, external
effects, or PO-01 material.
