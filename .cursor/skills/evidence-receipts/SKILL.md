---
name: evidence-receipts
description: Produce a hash-bound receipt bundle for a work unit and verify it by remote read-back. Use whenever a work unit is finishing, whenever a claim reaches READY_TO_COMMIT or beyond, or whenever someone asks whether a result is real.
paths: receipts/**,workstreams/**,state/**
---

# Evidence receipts

A result that cannot be read back by an instrument the producing run does not
control is not a result. This skill is the procedure for making one.

## When to use

Use this when a work unit is finishing, when a claim is about to reach
`READY_TO_COMMIT` or beyond, or when someone asks whether an existing result
is real. Do not use it to decorate work that has not finished.

## The bundle

A receipt bundle is a directory under `receipts/<workstream>/<date>/<unit>/`
containing the artifacts plus a `MANIFEST.json`:

```json
{
  "manifest_id": "<UNIT>-MANIFEST",
  "bundle_root": "receipts/<workstream>/<date>/<unit>",
  "entries": [{"path": "...", "sha256": "...", "size_bytes": 0}],
  "entry_count": 0,
  "bundle_sha256": "..."
}
```

`bundle_sha256` is the sha256 of the canonical JSON of the entries list, and
canonical means exactly this:

```python
json.dumps(entries, sort_keys=True, separators=(",", ":"))
```

Any other serialisation produces a different hash and silently breaks
comparability with every earlier bundle. Sort `entries` by `path` before
hashing so the bundle hash is stable regardless of how the files were walked.

## Procedure

1. Write every artifact first. Do not hash a tree you are still editing.
2. Walk the bundle root, and every other path the unit wrote, and compute
   `sha256` and `size_bytes` per file.
3. Sort by `path`, compute `bundle_sha256` as above, write `MANIFEST.json`.
4. Commit and push the isolated branch. Record the immutable commit SHA.
5. Read it back **from the remote, addressed by that SHA**, not from the local
   working tree. A clean `git fetch` of the SHA into a fresh clone, or the
   GitHub git/blobs API, both qualify. Two independent transports are better
   than one.
6. Compare byte-for-byte and record `entries_compared`, `bytes_compared` and
   `mismatches`. A read-back with `mismatches` greater than zero is a failure,
   not a note.

## What the receipt does and does not establish

It establishes custody: these exact bytes exist at this commit and can be
retrieved by anyone with the SHA. It establishes nothing about whether the
work is correct or sufficient. Independent acceptance is a separate act by a
separate party and cannot be issued by the run that produced the bundle.

## Failure handling

Every check must fail closed. If a path is missing, a hash differs, a branch
does not exist, or a lineage is unrelated, report the exact discrepancy and
exit non-zero. Never fabricate a value to complete a manifest, never report an
absent CI run as a pass, and never widen a comparison until it succeeds.
