# Evidence — po03-wa-b2e7-014-pointer-conflict-adversarial

## Falsifiable hypothesis

Two pointers claiming currentness for the same function is a detectable
conflict rather than a silent last-writer-wins.

## What was executed

```
python3 -I workstreams/po03/attempts/po03-wa-b2e7-014-pointer-conflict-adversarial/test_pointer_conflict.py
```

Working directory: repository root of this worktree, commit base
`5ef49cb148f5186397acf1303f325f726bb58543`.

Real stdout (verbatim):

```
[PASS] test_fixtures_are_synthetic_and_isolated
[PASS] test_conflicting_fixtures_are_refused
[PASS] test_dangling_fixture_is_refused
[PASS] test_valid_fixture_resolves_successfully
[PASS] test_absent_marker_is_refused_not_defaulted
[PASS] test_mixing_valid_and_conflicting_still_refuses_whole_pool
[PASS] test_real_repository_naive_status_heuristic_finds_every_historical_version
    naive heuristic on real data: 9/9 files simultaneously claim 'CURRENT' in status
[PASS] test_real_repository_authoritative_marker_narrows_to_exactly_one
[PASS] test_real_repository_operator_system_pointer_and_stack_do_not_conflict
[PASS] test_compare_fields_detects_synthetic_mismatch

RESULT: all 10 tests passed
```

Exit code: `0`.

## Adversarial fixtures (synthetic, inside this unit's own subtree only)

Five synthetic JSON files under `fixtures/`, each carrying an explicit
`_fixture_note` marker so they can never be mistaken for real repository
pointers, and none of them mutate any real pointer file:

- `conflict_a.json` / `conflict_b.json`: both carry
  `alias_id: "FIXTURE-CONFLICTING-CURRENT"` — proves
  `resolve_authoritative` raises `PointerConflictError` on a true
  conflict, including when a valid third candidate is mixed into the
  same pool (`test_mixing_valid_and_conflicting_still_refuses_whole_pool`).
- `dangling.json`: uniquely claims its marker but its
  `selected_pointer.path` names a file that exists nowhere in the
  repository — proves `resolve_target_exists` raises
  `PointerConflictError` rather than silently accepting a broken
  reference.
- `valid_current.json` + `valid_target.json`: a genuine, non-conflicting,
  non-dangling pair — proves the resolver actually succeeds and returns
  the correct target when there is nothing wrong
  (`test_valid_fixture_resolves_successfully`).

## Real-repository finding (not fabricated)

Scanning every real `state/ACTIVE_CONTROL_POINTER_*.json` file (9 files:
07 through 12 dated 2026-08-18, `_01`/`_02` dated 2026-08-19, and
`CURRENT.json`) for a naive "does the `status` field contain the
substring `CURRENT`" heuristic finds **9 of 9** — every single
historical version, including six long-superseded ones, carries a
`status` value beginning `CURRENT_...` (e.g.
`CURRENT_PACKAGE_READY_UNSENT`, `CURRENT_FINAL_V006_SUCCESSOR_REISSUE_READBACK_VERIFIED_UNSENT`,
`CURRENT_V009_SUCCESSOR_CONTROL_READBACK_VERIFIED_NOT_TRANSMITTED`,
`CURRENT_V010_FULL_SCALE_CHATGPT_CONTROL_READBACK_VERIFIED_NOT_TRANSMITTED`,
`CURRENT_ALIAS`). A resolver that trusted this field, or any
filename-based heuristic, would have to treat all nine as simultaneously
current — the exact silent-last-writer-wins failure mode this task asks
to make detectable.

The safe alternative — requiring an exact, unique
`alias_id == "OBZIO-ACTIVE-CONTROL-POINTER-CURRENT"` marker — correctly
narrows the same 9-candidate pool to exactly one winner:
`state/ACTIVE_CONTROL_POINTER_CURRENT.json`
(`test_real_repository_authoritative_marker_narrows_to_exactly_one`).

As a real-data control (not adversarial), the same conflict-comparison
primitive (`compare_fields`) was run against the actual
`state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json` and
`state/operator-system/ACTIVE_INSTRUCTION_STACK.json` on the five
identity keys `function_id`, `appointment_id`, `commission_id`,
`authority_envelope_id`, `runtime_binding_id`: no conflict was found —
this independently corroborates
`scripts/check_operator_taxonomy.py`'s own pointer/stack consistency
check (unit `po03-wa-b2e7-012` separately reproduced that script's PASS
verdict) using a different, self-contained implementation.

## Verdict rationale

**PASS**. The hypothesis is demonstrated on both synthetic and real data.
The resolver never silently picks a winner by last-writer-wins,
filename, or file order: `resolve_authoritative` and
`resolve_target_exists` both raise `PointerConflictError` (refuse) on
conflicting or dangling candidates, proven by three independent
synthetic fixtures plus a mixed-pool test, and `compare_fields` is proven
non-stub by a synthetic mismatch test
(`test_compare_fields_detects_synthetic_mismatch`). The real repository
supplies a genuine, non-fabricated example of exactly the dangerous
pattern the hypothesis warns about (9/9 files claiming "CURRENT" in
their status field) and confirms the correct resolution mechanism
narrows it to one, unlike a naive filename/status heuristic which would
not.
