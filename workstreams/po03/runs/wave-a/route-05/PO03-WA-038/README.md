# PO03-WA-038 — Generated artifacts retain source, tool, configuration and parent lineage

- **Wave / route:** `PO03-WAVE-A-20260822` / `route-05` (`provenance-and-paths`)
- **Commission:** `COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001`
- **Frozen hypothesis:** Generated artifacts retain source, tool, configuration, and parent lineage.
- **Result slot:** `workstreams/po03/runs/wave-a/route-05/PO03-WA-038/`
- **Base commit:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Parent-verified canary:** `13d90932fd7f02f7f26c3e280bd54cff50bd8809`
- **Exact model configuration:** `claude-opus-5-thinking-high`
- **Lease / fence token:** `lease-PO03-WA-038-1` / `1`
- **Acceptance contract SHA-256:** `bcad2a4ff53e5d83400fc74b70bdca45b31ced58f964f116c1f4826b70cd6531`
- **Immutable input capsule SHA-256:** `c26b9a4119a0edc95b5cb555b75bb8b278dc1f438bd22a6f23d728e6f37df07d`
- **Immutable input manifest SHA-256:** `f66ba25343ceb8ce7810a7b241dd80b042b3b888ba498dcd61e48a29863c2f66`

## What was built

A provenance ledger that pins the four facts a generated artifact needs in order
to be reproducible: the source bytes it derived from, the tool that derived it
(pinned by the SHA-256 of the tool's own source, not merely a version string),
the configuration that steered the tool (canonicalised so key order cannot
change the digest), and the parent record ids forming the lineage DAG. Each
record seals those facts into an `attestation_sha256` over a canonical JSON
serialization. Verification re-derives the attestation and re-hashes every
referenced file, and walks parent edges to the roots.

## Adversarial case

The fixture is a two-stage pipeline, so lineage has real depth. Tests then break
one link at a time: mutate a source after recording, mutate the output, replace
the tool source while keeping the version string identical, delete a source
file, tamper with the configuration body, edit a field without resealing, point
a record at a non-existent parent, introduce a two-node cycle, and make a record
its own parent. One test goes further: it forges the file and then reseals the
record, showing that a resealed attestation still fails because the recorded
digests no longer match the bytes.

## Commands

Run from `workstreams/po03/runs/wave-a/route-05/PO03-WA-038/` with the repository's system Python
(3.12.3, standard library only — no third-party packages and no network):

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 src/lineage_recorder.py --help
```

The exact invocations used for this attempt, together with their full output and
exit codes, are recorded verbatim in `evidence/run-log.txt`.

## Observed results

23 unit tests pass. Each break produces its specific finding - `SOURCE_DRIFT`,
`OUTPUT_DRIFT`, `TOOL_DRIFT` at an unchanged version string, `MISSING_FILE`,
`CONFIG_TAMPERED`, `ATTESTATION_MISMATCH`, `BROKEN_LINEAGE`, `CYCLE_DETECTED`.
Reordering configuration keys leaves the digest unchanged while changing a value
does not. The intact ledger exits 0; the tampered ledger exits 1 reporting
source drift, tool drift and broken lineage together.

## Limitations

The attestation is an integrity digest, not a signature: it detects accidental
and careless tampering but not a determined actor who recomputes every digest
and rewrites the files to match. Binding to an identity would need signing keys,
which are outside this commission's authority. Lineage records what the producer
declares it used; `UNRECORDED_SOURCE` only fires when the caller supplies an
independent list of expected sources.

## Disposition

**PASS** — the hypothesis holds for all four provenance facts, with the signature limitation recorded rather than claimed as covered.

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
