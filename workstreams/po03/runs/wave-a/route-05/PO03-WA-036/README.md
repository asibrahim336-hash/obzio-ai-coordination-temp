# PO03-WA-036 — Independent reconciliation of every artifact hash and byte count

- **Wave / route:** `PO03-WAVE-A-20260822` / `route-05` (`provenance-and-paths`)
- **Commission:** `COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001`
- **Frozen hypothesis:** Every manifested artifact hash and byte count is independently reconciled.
- **Result slot:** `workstreams/po03/runs/wave-a/route-05/PO03-WA-036/`
- **Base commit:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Parent-verified canary:** `13d90932fd7f02f7f26c3e280bd54cff50bd8809`
- **Exact model configuration:** `claude-opus-5-thinking-high`
- **Lease / fence token:** `lease-PO03-WA-036-1` / `1`
- **Acceptance contract SHA-256:** `6199c68fb197ac75167c3625698755166d9238e92ea329a62132b47e49ccfccf`
- **Immutable input capsule SHA-256:** `7f3fc0e6e173171ffb9a77a6285695e58bc30a2ae4ddd6314a3f9dbb3476a407`
- **Immutable input manifest SHA-256:** `f66ba25343ceb8ce7810a7b241dd80b042b3b888ba498dcd61e48a29863c2f66`

## What was built

A reconciler that treats a manifest as a claim and re-derives it from the bytes.
It checks forward (every manifested artifact exists and its SHA-256 and byte
count match a fresh streamed read) and in reverse (every file under the root
appears in the manifest), so a manifest cannot be made to pass by omission.
Hash and length come from the same chunked read rather than from `stat`, so a
manifest whose byte count agrees with the inode but not with the content stream
is still caught. Aggregate `artifact_count` and `total_bytes` are reconciled
against the artifacts actually examined.

## Adversarial case

Nine defects are injected one at a time: a single flipped byte with the length
preserved, a truncation, a deleted artifact, a directory substituted for a file,
a symlink substituted for a file, an uppercase hash, a duplicate artifact id, a
duplicate content URI, and a manifested path escaping the root. Two further
tests drop an artifact from the manifest and add a stray file on disk to
exercise the reverse direction.

## Defect found and corrected during execution

During development the reverse-containment check used `Path.resolve()`, which
follows symlinks. That collapsed two distinct defects into one verdict: a
symlink substituted for a manifested file reported `PATH_ESCAPES_ROOT` instead
of `NOT_A_REGULAR_FILE`. The test caught it and containment was changed to a
lexical comparison, which keeps the two findings separable.

## Commands

Run from `workstreams/po03/runs/wave-a/route-05/PO03-WA-036/` with the repository's system Python
(3.12.3, standard library only — no third-party packages and no network):

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 src/manifest_reconciler.py --help
```

The exact invocations used for this attempt, together with their full output and
exit codes, are recorded verbatim in `evidence/run-log.txt`.

## Observed results

23 unit tests pass. Each injected defect produces exactly its own finding, and
the flipped-byte case reports `SHA_MISMATCH` with the byte count still matching,
which is the case a length-only check would miss. Against a tampered fixture the
CLI exits 1 reporting `SHA_MISMATCH`, `BYTES_MISMATCH` and `UNMANIFESTED_FILE`
together; the honest fixture exits 0.

## Limitations

Reconciliation proves that bytes on disk match the manifest at the moment of the
run; it says nothing about whether those bytes are the intended content, which
is the lineage question PO03-WA-038 addresses. Containment of `content_uri` is
lexical by design so that symlink substitution reports as
`NOT_A_REGULAR_FILE` rather than being silently followed; symlink target
containment remains PO03-WA-034's guard. The reverse check depends on the caller
passing correct `--exclude` values for files the manifest legitimately omits.

## Disposition

**PASS** — the hypothesis holds, and this component is used below to independently reconcile all eight task manifests in the route receipt.

## Artifacts

`manifest.json` lists every file in this slot with its SHA-256 and byte count.
`result.json` is the transactional result record for this attempt and conforms
to `workstreams/po03/contracts/transactional-result.schema.json`.

## Transactional state

| Field | Value |
| --- | --- |
| Provider state | `RUNNING` (provider state is tracked separately from Obzio state) |
| Obzio state | `RESULT_STAGED` |
| Producer terminal report | `READY_TO_COMMIT` — the producer ceiling for this lease |
| Completion actor | `null` — only the coordinator may record completion |
| Independent acceptance | `NOT_TESTED` — the producer does not self-accept |
| `decision_changed` | `[]` |

This attempt is not COMPLETED and not ACCEPTED. Independent assurance and
coordinator ingestion are separate acts performed outside this result slot.
