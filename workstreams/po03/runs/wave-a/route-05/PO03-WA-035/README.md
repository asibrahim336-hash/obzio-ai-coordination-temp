# PO03-WA-035 — Renames are checked on both source and destination

- **Wave / route:** `PO03-WAVE-A-20260822` / `route-05` (`provenance-and-paths`)
- **Commission:** `COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001`
- **Frozen hypothesis:** Renames are checked on both source and destination paths.
- **Result slot:** `workstreams/po03/runs/wave-a/route-05/PO03-WA-035/`
- **Base commit:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Parent-verified canary:** `13d90932fd7f02f7f26c3e280bd54cff50bd8809`
- **Exact model configuration:** `claude-opus-5-thinking-high`
- **Lease / fence token:** `lease-PO03-WA-035-1` / `1`
- **Acceptance contract SHA-256:** `3f6f3ccb4f3c5baf8cf7aabc34033f0101d003e70badd275d96ef60816ef2ca0`
- **Immutable input capsule SHA-256:** `50e83d179136fe74a0b1b41c9c2173ebfd6e49907762d4dfd86c7da6a3225921`
- **Immutable input manifest SHA-256:** `f66ba25343ceb8ce7810a7b241dd80b042b3b888ba498dcd61e48a29863c2f66`

## What was built

A rename admissibility guard that treats a rename as two path facts rather than
one changeset entry. It classifies every rename into a four-cell matrix over the
ownership predicate and reports escape (`owned -> foreign`) separately from
capture (`foreign -> owned`), because the two have different remedies. It also
flags an owned-to-foreign rename as `evidence_leaves_subtree` so the deletion
semantics of the move are visible, and flags case-only renames, which are no-ops
on case-insensitive filesystems. Two NUL-delimited git spellings are parsed:
`git diff --name-status -z` and `git status --porcelain=v1 -z`, whose rename
entries list the new path before the old one.

## Adversarial case

Two tests demonstrate the insufficiency of a single-endpoint guard directly: for
the capture case the destination-only predicate answers "owned" (admit) while
the two-endpoint guard rejects, and symmetrically for the escape case. An
end-to-end test builds a throwaway git repository in a temporary directory,
performs a real `git mv` out of the owned subtree, and feeds genuine
`git diff --find-renames --name-status -z` bytes to the guard.

## Commands

Run from `workstreams/po03/runs/wave-a/route-05/PO03-WA-035/` with the repository's system Python
(3.12.3, standard library only — no third-party packages and no network):

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 src/rename_guard.py --help
```

The exact invocations used for this attempt, together with their full output and
exit codes, are recorded verbatim in `evidence/run-log.txt`.

## Observed results

22 unit tests pass, including the two real-git cases. The internal rename payload
exits 0; the mixed payload (escape, capture, out-of-scope) exits 1 with three
rejections carrying `REJECTED_DESTINATION_NOT_OWNED`, `REJECTED_SOURCE_NOT_OWNED`
and `REJECTED_BOTH_ENDPOINTS_NOT_OWNED` respectively. Truncated rename records
are refused at parse time rather than silently dropped.

## Limitations

The guard consumes git's rename detection rather than performing its own; a
rename that git reports as an unrelated delete plus add is seen as two separate
entries and must be caught by the changed-path guard instead. Similarity scores
are parsed but not used in the verdict. Case-only renames are flagged, not
rejected, because the correct remedy (a two-step rename) is a producer decision.

## Disposition

**PASS** — the hypothesis holds: both endpoints are evaluated, and the tests show that checking either endpoint alone would admit a real violation.

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
