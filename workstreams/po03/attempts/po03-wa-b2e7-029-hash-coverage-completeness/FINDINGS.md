# po03-wa-b2e7-029-hash-coverage-completeness

Function: `manifest-provenance-and-changed-path-enforcement`.

## Falsifiable hypothesis

Hash and byte-count coverage over counted artifacts is total, so a partially
hashed result cannot be counted.

## Executable component

`coverage_assert.py` audits the manifests the live emitter actually produced.
Unit 025 verifies a manifest against a source it generated from; this unit
starts from the commit and refuses to believe the manifest's own arithmetic. For
each slot it enumerates the files the artifact commit really holds, re-reads
every one with `git cat-file`, and refuses on:

`MANIFEST_MISSING`, `MANIFEST_UNPARSEABLE`, `MISSING_FIELD`, `NO_ARTIFACTS`,
`ARTIFACT_NOT_AN_OBJECT`, `DUPLICATE_LOGICAL_NAME`, `HASH_MISSING`,
`HASH_MALFORMED`, `BYTES_MISSING`, `BYTES_NOT_POSITIVE_INT`,
`LOCATOR_FOREIGN_COMMIT`, `LOCATOR_OUTSIDE_SLOT`,
`ARTIFACT_MISSING_FROM_COMMIT`, `MEASURED_HASH_MISMATCH`,
`MEASURED_BYTES_MISMATCH`, `COUNT_DISAGREEMENT`, `TOTAL_BYTES_DISAGREEMENT`,
`UNCOVERED_FILE`, `COVERED_FILE_NOT_IN_COMMIT`, `RESULT_MISSING`,
`RESULT_UNPARSEABLE`, `RESULT_DISAGREES_WITH_MANIFEST`,
`MANIFEST_SHA256_MISMATCH`, `NO_SUCH_SLOT`, `NO_SLOTS_FOUND`.

`audit_documents` takes parsed documents so a candidate manifest can be audited
without committing it first, which is what makes the test suite cheap.

## Verdict

PASS for the corpus that exists. Auditing commit `HEAD` before this unit's own
component was committed:

```
PO03_COVERAGE_PASS slots=4 artifacts=22 measured_bytes=164079
excluded_by_declaration=manifest.json,result.json
```

Every one of the 22 artifacts across the four completed slots was re-read from
its artifact commit and matched its recorded hash and byte count exactly.

Tests: 34, OK.

## Finding: the emitter's exclusion is by basename at any depth

`emit_result.py` filters counted artifacts with
`Path(path).name not in ("manifest.json", "result.json")`. The name test applies
at any depth, so a payload file committed at `<slot>/nested/manifest.json` is
durably in the commit and never appears in the manifest, and nothing in the
emitter reports it. This auditor excludes those two names **only at the root of
a slot**, so it requires `<slot>/nested/manifest.json` to be covered and reports
`UNCOVERED_FILE` when it is not. Two tests pin the behaviour, and unit 032
demonstrates the gap against the live emitter rather than against a model of it.

## Finding: forged self-consistency does not survive measurement

A manifest with an entry deleted and its `artifact_count` and `total_bytes`
adjusted to match the remaining entries is internally consistent. The auditor
still reports `UNCOVERED_FILE` and reports no trailer complaint, because the
commit and not the manifest is the authority. Asserted by
`test_an_omitted_entry_is_refused_even_with_consistent_totals`.

## Observed limitations

1. Coverage is judged against the artifact commit, so a file that was never
   staged is invisible here too. That class belongs to a working-tree source
   (unit 025) and to unit 032's adversarial run.
2. A slot with artifacts but no `manifest.json` is reported `MANIFEST_MISSING`
   rather than skipped. That is correct for a gate but means a whole-repository
   audit exits 1 while any producer is mid-unit, exactly as unit 026's walk does.
3. The auditor checks that `result.json` agrees with `manifest.json` and that the
   result's `manifest_sha256` reproduces the committed manifest bytes. It does
   not re-validate the result against the transactional-result schema; that is
   `workstreams/po03/tools/validate_contracts.py`, which the emitter already
   runs before writing.
4. Building a scratch repository costs roughly twelve seconds on this runner, so
   the suite deliberately shares one repository per test class and mutates
   candidate manifests in memory. An earlier draft built one repository per case
   and took over four minutes, which would have been unusable in a gate.
