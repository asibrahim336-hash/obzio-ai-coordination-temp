# WA-005 — repository disposition detector

This unit tests `H-PO03-WA-005`: repository debris and superseded
transport artifacts can be classified without deleting unique evidence.

## Mechanism

`repository_debris_detector.py` is a dependency-free, read-only classifier.
It requires an explicit inventory containing canonical relative paths, roles,
standing, supersession links, expected SHA-256 values, byte counts, and
evidence claims. It recomputes file identity and produces dispositions that
conform to `disposition.schema.json`.

Safety is fail-closed:

- names never determine standing or disposition;
- missing, changed, linked, non-regular, or metadata-ambiguous artifacts are
  retained pending review;
- a superseded artifact with unique bytes or unique evidence claims is retained
  as evidence;
- only a hash-verified byte duplicate with a valid current successor can be a
  removal candidate;
- even removal candidates are only reported—the detector has no deletion mode;
- output cannot be written into the inventoried source root and existing output
  is never overwritten.

Classification and disposition are distinct. `SUPERSEDED_TRANSPORT_REDUNDANT`
and `REDUNDANT_DEBRIS` mean that a human or separately authorised mechanism may
review the artifact for removal. `SUPERSEDE_RETAIN` deliberately preserves a
superseded transport occurrence as lineage.

## Run

From the repository root:

```sh
python3 workstreams/po03/wave-a/units/wa-005/repository_debris_detector.py \
  scan workstreams/po03/wave-a/units/wa-005/fixtures/unique-evidence/inventory.json

python3 -m unittest discover \
  -s workstreams/po03/wave-a/units/wa-005/tests -p 'test_*.py' -v
```

The four committed fixtures cover positive redundant debris, a filename-based
negative case, superseded transport, and superseded unique evidence.
`evidence/reproductions/` contains their executable outputs. Source claims,
hypotheses, reproductions, mechanism changes, and strategy proposals are kept
in separate evidence records.
