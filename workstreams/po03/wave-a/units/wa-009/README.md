# WA-009 bounded source capsule builder

This unit executes `H-PO03-WA-009`: a dependency-free Python builder admits
only explicitly selected, task-tagged, SHA-256-pinned regular files; checks an
exact critical-source set; enforces source-count and byte budgets before
publishing output; and emits a deterministic manifest.

## Request and output contract

`capsule_builder.py` accepts a JSON request with:

- a task ID and source locator;
- a canonical SHA-256 over the sorted path/content-hash source snapshot;
- exact `max_sources` and `max_bytes` budgets;
- the only permitted task-relevance tags;
- the complete set of sources that are critical for recurrence; and
- source entries containing a canonical relative path, expected SHA-256,
  critical flag, relevance tags and rationale.

Unknown fields, absolute/traversing/non-canonical paths, symlinks, non-regular
files, duplicate paths, undeclared relevance tags, hash mismatches, critical
set mismatches and any budget excess are rejected. A rejection leaves no
capsule. A successful build atomically publishes only the admitted source
bytes and `capsule-manifest.json`; existing output is never overwritten.

The manifest contains no timestamp, host path or directory-order input. Its
source and policy arrays are sorted, so equivalent requests produce identical
manifest bytes.

## Run

From the repository root:

```sh
python3 workstreams/po03/wave-a/units/wa-009/capsule_builder.py \
  --source-root workstreams/po03/wave-a/units/wa-009/fixtures/source \
  --request workstreams/po03/wave-a/units/wa-009/fixtures/requests/valid.json \
  --output /tmp/po03-wa-009-capsule
```

Run focused tests and repository-relative recurrence:

```sh
python3 -m unittest discover \
  -s workstreams/po03/wave-a/units/wa-009/tests -v
python3 workstreams/po03/wave-a/units/wa-009/verify_recurrence.py \
  --repo-root .
```

The committed sanitized reproduction includes an unrelated source that is
deliberately not admitted, plus explicit over-byte-budget and
omitted-critical-source requests that must fail.

## Evidence boundary

The mechanism proves admission against a frozen caller-declared relevance
policy; it does not infer semantic relevance from file contents. Each admitted
byte is nevertheless content-pinned and the complete selected set is
snapshot-pinned, making the admitted context independently reproducible.
