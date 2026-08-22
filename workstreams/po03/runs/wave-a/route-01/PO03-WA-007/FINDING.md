# PO03-WA-007 — provider completion without a durable commit is reclassified

- **Task:** `PO03-WA-007`
- **Route:** `route-01` (transactional-custody), fence token 1, lease `lease-PO03-WA-007-1`
- **Immutable base:** `44de68e52a0baa480a8a8c0b95fd5071391dd4a1`
- **Frozen hypothesis:** Provider completion without a durable commit is reclassified automatically.
- **Disposition:** **PASS**
- **Producer terminal report:** `READY_TO_COMMIT` — `obzio_state = RESULT_STAGED`, `independent_acceptance = NOT_TESTED`.

## What was built

`reclassifier.py` keeps `provider_state` and `obzio_state` on two axes that
never merge. A provider reporting `COMPLETED` is stating a true fact *about the
provider*; it says nothing about whether Obzio holds a durable, verifiable
result. Conflating the two is what produced the recorded PO-02 Code-2 outcome —
a unit counted complete with no locator anyone could open.

Obzio state is **derived, never accepted**. There is no input field on
`Observation` by which a caller can assert `obzio_state` or `durable_commit`,
and the suite asserts that absence directly. `COMPLETED` is not in the derivable
set at all: coordinator completion after independent acceptance is not something
a producer-side classifier can mint.

"Durable commit" is likewise not a boolean the caller may claim. A locator is
*resolved* against a commit resolver, and five distinct non-durable observations
are separated: no locator, unresolvable locator, resolvable but unpinned
content, hash mismatch, and zero artifacts.

## Commands and observed results

```
$ python3 reclassifier.py --demo             # exit 0
$ python3 -m unittest -v test_reclassifier   # exit 0
```

Full transcript: `evidence/observed-output.txt` (the demo's 36-row matrix is
truncated there; the suite exercises every row).

- 19 tests, **19 passed, 0 failed**, exit 0. All passed on first execution.
- Full matrix of 6 provider states × 6 commit shapes = **36 rows**:
  `false_completions = []`. No input produces `COMPLETED`.
- Every row with provider `COMPLETED` and a non-durable commit maps to exactly
  one state: `PROVIDER_COMPLETED_UNCOMMITTED`.
- Each non-durable shape is reported with its own reason
  (`NO_RESULT_COMMIT_LOCATOR`, `LOCATOR_UNRESOLVABLE`,
  `NO_DECLARED_MANIFEST_HASH`, `MANIFEST_HASH_MISMATCH`, `NO_ARTIFACTS`), and the
  hash mismatch carries both the declared and the observed digest.
- A durable commit outranks a `FAILED`, `CANCELLED` or `UNKNOWN` provider report:
  a real committed result is not discarded because the provider errored.
- Recorded PO-02 Code-2 fixture (provider `COMPLETED`, no locator) reclassifies
  to `PROVIDER_COMPLETED_UNCOMMITTED`.

### Cross-checked against the seeded repository validator

Every derived document is re-validated with the repository's own
`workstreams/po03/tools/validate_contracts.py`, so this component cannot drift
from the contract it must satisfy. `contract_violations = []` across all 36 rows.

The cross-check is shown to be capable of failing, not merely of passing: taking
the same PO-02 fixture and forging `obzio_state = "RUNNING"` makes the seeded
validator emit the `PROVIDER_COMPLETED_UNCOMMITTED` error, and forging
`obzio_state = "COMPLETED"` with `completion_actor = "worker-1"` is likewise
rejected.

## Limitations

- The commit resolver is an in-memory fixture. Against a real Git remote,
  "resolvable" would additionally depend on network reachability and on
  distinguishing a genuinely absent object from a transient fetch failure — a
  distinction this fixture does not model, and one where a false
  `LOCATOR_UNRESOLVABLE` would wrongly reclassify a good result.
- Verification pins the manifest hash only. It does not walk the manifest to
  confirm each artifact resolves; that reconciliation belongs to route-05.
- Provider states are taken from the seeded contract enum. A provider emitting a
  state outside it raises rather than being mapped, which is deliberate but means
  new provider vocabulary needs an explicit decision.
- `decision_changed: []`.
