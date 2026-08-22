# PO03-WA-037 — Transport debris detected and dispositioned without deletion

- **Wave / route:** `PO03-WAVE-A-20260822` / `route-05` (`provenance-and-paths`)
- **Commission:** `COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001`
- **Frozen hypothesis:** Repository disposition detects transport debris without deleting evidence.
- **Result slot:** `workstreams/po03/runs/wave-a/route-05/PO03-WA-037/`
- **Base commit:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Parent-verified canary:** `13d90932fd7f02f7f26c3e280bd54cff50bd8809`
- **Exact model configuration:** `claude-opus-5-thinking-high`
- **Lease / fence token:** `lease-PO03-WA-037-1` / `1`
- **Acceptance contract SHA-256:** `1a2a3cf218469e67f594be89471ccd6dff8e8a0863ca227996bb691522b329f9`
- **Immutable input capsule SHA-256:** `0049f7876581bf03867b235af5e74d48534c26b18a1a1d0817f0bc7a064b4bce`
- **Immutable input manifest SHA-256:** `f66ba25343ceb8ce7810a7b241dd80b042b3b888ba498dcd61e48a29863c2f66`

## What was built

A scanner that classifies transport debris - the residue of moving work between
machines, editors and runtimes - and records a disposition for each item without
ever removing it. Eighteen rules cover bytecode and tool caches, platform
metadata, AppleDouble archive residue, editor swap and backup files, merge
leftovers, unresolved conflict markers detected by content rather than by name,
and zero-byte files. Dispositions distinguish regenerable debris
(`IGNORE_RULE`) from debris that carries irreproducible run information
(`RETAIN_AS_EVIDENCE`) and from items needing a human decision
(`QUARANTINE_RECORD`, `REVIEW_REQUIRED`).

## Adversarial case

Non-destructiveness is proved three ways rather than asserted. A SHA-256 census
of the whole fixture tree is taken before and after every run and compared;
`--policy delete` is accepted by the parser purely so it can be refused with a
distinct exit code; and `self_audit` parses the module's own source with `ast`
and fails if any deletion or writable-open call is present. Two control tests
keep these from being vacuous: one deletes a file and shows the census reports
`DELETED`, and one plants a module containing `os.unlink`, `shutil.rmtree` and
`open(p, 'w')` and shows the static audit flags all three.

## Commands

Run from `workstreams/po03/runs/wave-a/route-05/PO03-WA-037/` with the repository's system Python
(3.12.3, standard library only — no third-party packages and no network):

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 src/transport_debris_disposition.py --help
```

The exact invocations used for this attempt, together with their full output and
exit codes, are recorded verbatim in `evidence/run-log.txt`.

## Observed results

21 unit tests pass. The debris fixture yields 7 findings across all four
dispositions with `deleted: 0`, `non_destructive: true` and an empty
`self_audit_offences`; the census is byte-identical before and after
(`files_before=8 files_after=8 census_identical=True`). `--policy delete` exits
3 with `DELETION_PROHIBITED` and leaves the census unchanged. A file containing
only `=======` is not a false positive, since all three conflict markers are
required.

## Limitations

Classification is heuristic and rule-driven: a file that is genuinely authored
but happens to end in `.orig` will be flagged, which is the safe direction given
that no action follows automatically. Conflict-marker detection reads the whole
file and skips anything containing a NUL byte in its first 8 KiB, so binary
files with embedded markers are not examined. The component proposes ignore
rules; it does not write them, because `.gitignore` is outside the owned
subtree.

## Disposition

**PASS** — the hypothesis holds: debris is detected and dispositioned, and non-destructiveness is demonstrated by census, by refusal and by static self-audit.

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
