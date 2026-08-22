# Evidence — po03-wa-b2e7-011-alias-resolution

## Falsifiable hypothesis

Colloquial actor aliases can be resolved to a durable function and
appointment, or explicitly refused, without global text replacement.

## What was executed

```
python3 -I workstreams/po03/attempts/po03-wa-b2e7-011-alias-resolution/test_alias_resolver.py
```

Working directory: repository root of this worktree, commit base
`5ef49cb148f5186397acf1303f325f726bb58543`.

Real stdout (verbatim):

```
[PASS] test_is_allowed_field_accepts_alias_runtime_provenance
[PASS] test_is_allowed_field_rejects_routing_field_names
[PASS] test_load_real_alias_register_contains_agents_md_aliases
[PASS] test_resolve_alias_returns_none_for_unknown_alias
[PASS] test_resolve_alias_finds_known_alias_case_insensitively
[PASS] test_fails_closed_when_register_missing
[PASS] test_scan_repository_flags_occurrence_outside_allowed_field
[PASS] test_build_report_reports_unresolved_alias_as_evidence_not_invention
[PASS] test_build_report_never_mutates_scanned_files
[PASS] test_real_repository_agents_md_aliases_all_resolve
    'Operator D' -> {'target_type': 'appointment', 'target_id': 'obzio.appointment.legacy.operator-d.20260818', 'status': 'HISTORICAL_PROHIBITED_FOR_ROUTING', 'replacement': 'Use the current function and appointment pointer; ambiguous occurrences are evidence only.'}
    'Claude extension' -> {'target_type': 'runtime_class', 'target_id': 'obzio.runtime-binding.strategic-operations-orchestration.20260819.001', 'status': 'COLLOQUIAL_RUNTIME_ONLY', 'replacement': 'State function/appointment separately from runtime.'}
    'Claude browser operator' -> {'target_type': 'composite', 'target_id': 'obzio.appointment.strategic-operations-orchestration.20260819.001', 'status': 'DEPRECATED_COMPOSITE_PROHIBITED_FOR_ROUTING', 'replacement': 'Strategic Operations appointment + explicit runtime binding.'}
    'principal AI operator' -> {'target_type': 'composite', 'target_id': 'obzio.appointment.strategic-operations-orchestration.20260819.001', 'status': 'DEPRECATED_CONTEXT_REQUIRED', 'replacement': 'Resolve exact function and appointment.'}
[PASS] test_real_repository_finds_flagged_occurrences_outside_allowed_fields
    occurrence_count=45 allowed=5 flagged=40

RESULT: all 11 tests passed
```

Exit code: `0`.

## What the resolver actually found (real, not fabricated)

Loaded `state/operator-system/OPERATOR_ALIAS_REGISTER.jsonl` (8 rows) and
resolved all four aliases AGENTS.md rule 4 names by example: every one
maps to an explicit `target_type`/`target_id`/`status`/`replacement`
tuple (shown verbatim above). None are unresolved.

Then scanned every committed `.json`/`.jsonl` file (same corpus as unit
010: 371 files) for literal, case-insensitive occurrences of those four
alias strings: **45 occurrences** total.

- **5 occurrences** sit in an allowed field (`alias`, `runtime*`,
  `*recorded_by`, `*provenance*`, `*identity_note*`): the 4 canonical
  rows inside `OPERATOR_ALIAS_REGISTER.jsonl` itself (field `alias`) plus
  one in `state/ACTIVE_CONTROL_POINTER_CURRENT.json`'s
  `execution_record.recorded_by` = `"Claude browser operator (principal
  strategic AI-operator lane)"` — a genuine provenance field, correctly
  classified as allowed.
- **40 occurrences** sit in routing-shaped field names instead —
  `owner`, `owner_function`, `route_owner`, `destination`, `function`,
  `legacy_owner`, `display_name`, `next_dependency`, `scope`, `source`,
  `proposition`, `surface`, `routing_rule`, `rule`, `decision_changed`,
  `premises`, `unchanged_control`, `boundaries`, `programme_outputs`,
  `validity_boundary`, `current_dispatch_objects.route_owner`, etc.,
  concentrated in dated historical/evidence files such as
  `state/OPERATOR_LANE_REGISTER_20260818.jsonl`,
  `state/ACTIVE_CONTROL_DELTA_20260818_0{2,3,4}.json`,
  `state/OPERATOR_CONTINUITY_BASELINE_20260818.json`, and several
  `state/SOURCE_CLAIM_REGISTER*` / `*_REGISTER_DELTA_*` files.

None of these 40 files were modified. `mutated_files` is always `[]`
because this module performs no writes at all.

## Verdict rationale

**PASS**. The hypothesis's two branches are both demonstrated on real
data: (1) every alias AGENTS.md names by example resolves to a durable
`target_type`/`target_id`, and a synthetic fixture alias absent from the
register is correctly reported as `unresolved` rather than mapped to a
guessed value (`test_build_report_reports_unresolved_alias_as_evidence_not_invention`);
(2) resolution and field-context flagging both happen without ever
writing to a scanned file (`test_build_report_never_mutates_scanned_files`,
and `mutated_files == []` on the real-repo run) — i.e. no global text
replacement occurs.

**Limitation, recorded precisely rather than smoothed over**: read
strictly by field name alone, 40 of 45 real occurrences of these four
aliases sit outside "alias, runtime or provenance" fields, in
routing-shaped fields (`owner`, `route_owner`, `destination`, ...) inside
files that are themselves dated 2026-08-18/19 legacy register/delta
records. This resolver does not have enough information to know, from a
field name alone, whether a given historical record has already received
an explicit disposition elsewhere (that cross-check is
`po03-wa-b2e7-015-disposition-completeness`'s job, and whether the file
itself is a launch surface versus evidence is
`po03-wa-b2e7-013-launch-surface-classifier`'s job). This resolver
reports the raw count honestly instead of silently exempting these 40
occurrences or, worse, "fixing" them via a global find/replace, which
AGENTS.md rule 9 and this task's hypothesis both explicitly forbid.
