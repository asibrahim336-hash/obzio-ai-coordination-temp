# PO03-WA-011 deterministic manifest generator

This unit tests `H-PO03-WA-011`: repeated manifest compilation over the same
relative paths and bytes is byte-identical regardless of traversal order.

`manifest_generator.py` validates portable relative paths, reads only regular
files without following a final symlink, sorts records by UTF-8 path bytes,
hashes file bytes with SHA-256, and emits canonical UTF-8 JSON. The manifest
does not admit clocks, hostnames, absolute roots, traversal order, mtimes,
ownership, inode numbers, or permissions.

The sanitized repository-native workload is under `fixtures/source/`.
`fixtures/shuffled-orders.json` freezes four deliberately different traversal
orders. `reproduction/expected-manifest.json` is the committed byte oracle.
`verify_recurrence.py` compares that oracle with all four frozen orders, all
six permutations of the three-file set, eight repeated compilations, and
filesystem discovery.

Run from repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s workstreams/po03/wave-a/units/wa-011/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 \
  workstreams/po03/wave-a/units/wa-011/verify_recurrence.py --repo-root .
```

Compile one frozen order to standard output:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  workstreams/po03/wave-a/units/wa-011/manifest_generator.py \
  --root workstreams/po03/wave-a/units/wa-011/fixtures/source \
  --paths-json workstreams/po03/wave-a/units/wa-011/fixtures/shuffled-orders.json \
  --order seed-1102
```

The guarantee applies to an identical canonical relative-path set and
identical file bytes. Filesystem name portability beyond UTF-8 NFC and
protection against a hostile concurrent writer that can evade size and
mtime-based change detection are explicitly outside the demonstrated claim.
