# PO03-WA-033 — Changed-path guard rejecting an out-of-allowlist mutation

- **Wave / route:** `PO03-WAVE-A-20260822` / `route-05` (`provenance-and-paths`)
- **Commission:** `COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001`
- **Frozen hypothesis:** A changed-path guard rejects one deliberate out-of-allowlist mutation.
- **Result slot:** `workstreams/po03/runs/wave-a/route-05/PO03-WA-033/`
- **Base commit:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Parent-verified canary:** `13d90932fd7f02f7f26c3e280bd54cff50bd8809`
- **Exact model configuration:** `claude-opus-5-thinking-high`
- **Lease / fence token:** `lease-PO03-WA-033-1` / `1`
- **Acceptance contract SHA-256:** `a95fde86df2ca4d21e2fb89b07b43d8f0c207e5ee84b914d42c18e268d32e64c`
- **Immutable input capsule SHA-256:** `5b229bc0d3bccba93070fd6c50de4873124bc79da9a98cd6f9aeb8a4452660f8`
- **Immutable input manifest SHA-256:** `f66ba25343ceb8ce7810a7b241dd80b042b3b888ba498dcd61e48a29863c2f66`

## What was built

A lexical changed-path guard that evaluates a candidate changeset against a
declared write allowlist before anything is committed. Allowlist entries are
directory subtrees or exact file paths; subtree matching is anchored at a path
component boundary, so `PO03-WA-033/` never admits `PO03-WA-0330/x`. Candidate
paths are normalised (`./`, doubled separators, interior `..`) before comparison
so that a cosmetic spelling cannot smuggle a write past a prefix test, and
absolute paths, drive-qualified paths, NUL bytes and traversal above the
repository root each get their own rejection verdict rather than being folded
into a single failure.

## Adversarial case

The rejected-path fixture is a four-entry changeset containing one legitimate
in-slot write plus three deliberate escapes: a shared control ledger
(`workstreams/po03/control/leases/route-05.json`), a sibling route's slot, and a
path above the repository root. The guard exits 1 and attributes each rejection
individually.

## Commands

Run from `workstreams/po03/runs/wave-a/route-05/PO03-WA-033/` with the repository's system Python
(3.12.3, standard library only — no third-party packages and no network):

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 src/changed_path_guard.py --help
```

The exact invocations used for this attempt, together with their full output and
exit codes, are recorded verbatim in `evidence/run-log.txt`.

## Observed results

23 unit tests pass. The clean changeset exits 0 with `admissible: true`; the
deliberate rejected-path fixture exits 1 with three rejections
(`REJECTED_NOT_IN_ALLOWLIST` twice, `REJECTED_ESCAPES_ROOT` once) while the
in-slot path is still reported as allowed. An unusable allowlist exits 2.

## Limitations

The guard is purely lexical: it decides on path strings and never touches the
filesystem. It therefore cannot see that an admitted path resolves elsewhere
through a symlink, which is exactly the residual gap PO03-WA-034 covers. It also
takes the changeset as given and does not itself derive one from git.

## Disposition

**PASS** — the hypothesis holds: a deliberate out-of-allowlist mutation is rejected, with the escape attributed to a specific path and verdict.

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
