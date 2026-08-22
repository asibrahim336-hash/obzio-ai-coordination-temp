# Evidence — po03-wa-b2e7-016-semantic-state-contract

## What was executed

1. Unit tests:

```
$ PYTHONDONTWRITEBYTECODE=1 python3 -I test_state_contract.py
```

Real captured output is in `test_output.txt` (24 tests, all `ok`, `OK`
overall exit code 0). The `FAILED_CLOSED` JSON block at the end of that file
is the actual printed stdout of `TestMainCLI.test_missing_repo_files_fails_closed_exit_code`,
which calls `state_contract.main()` directly against an empty temp directory
with none of the eight operator-system source files present — this is the
expected fail-closed output of that one test case, not a suite failure.
`python -I` runs isolated (no user site-packages, no `PYTHONPATH`); only the
standard library (`unittest`, `json`, `copy`, `tempfile`, `pathlib`,
`argparse`, `sys`) is used.

2. Real-repository run of the validator itself:

```
$ PYTHONDONTWRITEBYTECODE=1 python3 -I state_contract.py --repo-root .
```

Full real output captured in `real_repo_run.json`: `all_valid: true`,
`total_records: 20`, `total_errors: 0` across all eight kinds
(operator_system_pointer, instruction_stack, authority_envelope, commission,
function, appointment, runtime_binding, alias).

## Scope and grounding

"The operator-system vocabulary" is scoped precisely to the eight record
kinds committed under `state/operator-system/` — the directory literally
named "operator-system" and the exact domain input this cohort's pointer
chain names (`ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json`,
`ACTIVE_INSTRUCTION_STACK.json`, `AUTHORITY_ENVELOPE_REGISTER.jsonl`, plus
the four sibling registers PO-03 must also treat as domain input:
`COMMISSION_REGISTER.jsonl`, `FUNCTION_REGISTER.jsonl`,
`OPERATOR_APPOINTMENT_REGISTER.jsonl`, `RUNTIME_BINDING_REGISTER.jsonl`,
`OPERATOR_ALIAS_REGISTER.jsonl`).

The pinned `CONTRACT` dict in `state_contract.py` is not invented: for every
kind, `required_fields` is the exact key intersection across every currently
committed record of that kind, and `allowed_status_values` is the exact set
of `status` values those same records actually use. `TestContractMatchesRepoSnapshot.test_derived_contract_matches_pinned_contract_for_every_kind`
independently re-derives both from the live files (via `derive_full_contract`)
and asserts an exact match against the pinned `CONTRACT`, for every one of
the eight kinds — proving the contract is a grounded snapshot, not a guess.

## The falsifiable claim, tested directly

`TestUndefinedStateRejectedOnRealData.test_undefined_status_rejected_for_every_real_kind`
takes the actual first real record of every one of the eight kinds
(genuinely currently valid: `validate_record` returns `[]` for the
unmodified record), deep-copies it, sets only its `status` field to a
synthetic value that has never appeared anywhere in this repository
(`UNDEFINED_STATE_NEVER_COMMITTED_ANYWHERE`), and asserts the validator
rejects it with exactly one precise, named error. This directly demonstrates
the hypothesis: *"undefined states cannot enter"* — because a document
carrying an undefined state fails `validate_record` and is not
indistinguishable from a valid one.

`TestValidateRepoSynthetic` additionally builds a small synthetic
operator-system directory (all required fields present, one deliberately
undefined function status) and shows `validate_repo` isolates exactly the
one bad record without affecting the other seven valid kinds, then flips
the bad status to a defined one and shows the same repo becomes fully valid
— proving the negative finding is real by reversing it.

## Non-mutation

`state_contract.py` only reads files via `Path.read_text` / `Path.is_file`;
it never writes to any path. `TestUndefinedStateRejectedOnRealData.test_real_files_are_never_mutated_by_validation`
byte-compares all eight real `state/operator-system/**` source files before
and after running every validation call in this suite and asserts equality.

## Boundary / limitation

- The contract enforces only two invariants per kind: presence of every
  currently-required field, and membership of the `status` field in the
  currently-observed vocabulary. It does not reject unrecognised additional
  fields (an "open world" on the field set), matching this repository's own
  stated additive-only migration doctrine
  (`operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md`) rather than
  inventing a stricter closed-schema rule the repository does not itself
  assert. `TestValidateRecord.test_extra_unrecognised_fields_are_not_rejected`
  documents this design choice explicitly.
- This contract's vocabulary is pinned to a point-in-time snapshot of
  `state/operator-system/**` as committed at the pinned working base
  `5ef49cb` (this cohort's own unit commits never touch that directory, so
  the snapshot is unaffected by units 009-015). If new legitimate status
  values are committed to that directory in the future, `CONTRACT` would
  need a corresponding, explicitly reviewed update — by design, since an
  enforceable contract that silently widened itself to match new content
  would not actually prevent undefined states from entering.
- This unit does not attempt to constrain the separate, already-enforced
  `obzio_state` / `RESULT_STATES` vocabulary defined in
  `workstreams/po03/tools/validate_contracts.py` (read-only reference, not
  modified): that is a distinct transactional-result-protocol vocabulary,
  not the operator-system vocabulary this unit's falsifiable hypothesis
  names.
