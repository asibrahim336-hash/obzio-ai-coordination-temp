# Evidence — po03-wa-b2e7-009-current-source-compiler

## Falsifiable hypothesis

The current operator route can be compiled mechanically from repository
pointers rather than inferred from filenames.

## What was executed

```
python3 -I workstreams/po03/attempts/po03-wa-b2e7-009-current-source-compiler/test_compiler.py
```

Working directory: repository root of this worktree (`/home/ubuntu/po03-worktrees/c2`),
commit base `5ef49cb148f5186397acf1303f325f726bb58543`.

Real stdout (verbatim):

```
[PASS] test_extract_readme_order_parses_numbered_backtick_list
[PASS] test_extract_readme_order_empty_when_section_absent
[PASS] test_compiles_real_repository_pointer_chain
    real repo compiler report:
    {"all_named_paths_resolved": true, "current_source_set": ["state/ACTIVE_CONTROL_POINTER_CURRENT.json", "state/FOUNDER_INTENT_CORRECTION_OPERATOR_FUNCTION_TAXONOMY_AND_INSTRUCTION_CONTINUITY_20260819_v001.md", "state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json", "state/operator-system/ACTIVE_INSTRUCTION_STACK.json", "instructions/functions/strategic-operations-orchestration/CURRENT.md", "state/operator-system/AUTHORITY_ENVELOPE_REGISTER.jsonl", "operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md", "templates/NEXT_OPERATOR_PREFLIGHT_CURRENT.md", "state/FOUNDER_CORRECTION_V00X_PHASE_ONE_FULL_SCALE_CHATGPT_OPERATION_20260819_v001.md", "state/operator-system/OPERATOR_APPOINTMENT_REGISTER.jsonl", "state/operator-system/COMMISSION_REGISTER.jsonl", "state/operator-system/RUNTIME_BINDING_REGISTER.jsonl", "dispatch/WORK_THREAD_LAUNCH_CORRECTION_SW_GOOGLE_BOUNDARY_AND_PARALLEL_MODEL_RESEARCH_20260819_v001.md"], "entrypoint": "operations/README.md", "instruction_stack": "state/operator-system/ACTIVE_INSTRUCTION_STACK.json", "membership_agrees": false, "only_in_readme": ["state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json", "state/operator-system/ACTIVE_INSTRUCTION_STACK.json"], "only_in_stack": ["state/FOUNDER_CORRECTION_V00X_PHASE_ONE_FULL_SCALE_CHATGPT_OPERATION_20260819_v001.md", "state/operator-system/OPERATOR_APPOINTMENT_REGISTER.jsonl", "state/operator-system/COMMISSION_REGISTER.jsonl", "state/operator-system/RUNTIME_BINDING_REGISTER.jsonl", "dispatch/WORK_THREAD_LAUNCH_CORRECTION_SW_GOOGLE_BOUNDARY_AND_PARALLEL_MODEL_RESEARCH_20260819_v001.md"], "order_agrees": false, "readme_order": ["state/ACTIVE_CONTROL_POINTER_CURRENT.json", "state/FOUNDER_INTENT_CORRECTION_OPERATOR_FUNCTION_TAXONOMY_AND_INSTRUCTION_CONTINUITY_20260819_v001.md", "state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json", "state/operator-system/ACTIVE_INSTRUCTION_STACK.json", "instructions/functions/strategic-operations-orchestration/CURRENT.md", "state/operator-system/AUTHORITY_ENVELOPE_REGISTER.jsonl", "operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md", "templates/NEXT_OPERATOR_PREFLIGHT_CURRENT.md"], "stack_order": ["state/FOUNDER_CORRECTION_V00X_PHASE_ONE_FULL_SCALE_CHATGPT_OPERATION_20260819_v001.md", "state/ACTIVE_CONTROL_POINTER_CURRENT.json", "state/FOUNDER_INTENT_CORRECTION_OPERATOR_FUNCTION_TAXONOMY_AND_INSTRUCTION_CONTINUITY_20260819_v001.md", "instructions/functions/strategic-operations-orchestration/CURRENT.md", "state/operator-system/AUTHORITY_ENVELOPE_REGISTER.jsonl", "state/operator-system/OPERATOR_APPOINTMENT_REGISTER.jsonl", "state/operator-system/COMMISSION_REGISTER.jsonl", "state/operator-system/RUNTIME_BINDING_REGISTER.jsonl", "dispatch/WORK_THREAD_LAUNCH_CORRECTION_SW_GOOGLE_BOUNDARY_AND_PARALLEL_MODEL_RESEARCH_20260819_v001.md", "operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md", "templates/NEXT_OPERATOR_PREFLIGHT_CURRENT.md"]}
[PASS] test_real_repository_readme_and_stack_currently_disagree
    only_in_readme: ['state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json', 'state/operator-system/ACTIVE_INSTRUCTION_STACK.json']
    only_in_stack: ['state/FOUNDER_CORRECTION_V00X_PHASE_ONE_FULL_SCALE_CHATGPT_OPERATION_20260819_v001.md', 'state/operator-system/OPERATOR_APPOINTMENT_REGISTER.jsonl', 'state/operator-system/COMMISSION_REGISTER.jsonl', 'state/operator-system/RUNTIME_BINDING_REGISTER.jsonl', 'dispatch/WORK_THREAD_LAUNCH_CORRECTION_SW_GOOGLE_BOUNDARY_AND_PARALLEL_MODEL_RESEARCH_20260819_v001.md']
[PASS] test_fails_closed_when_readme_names_missing_path
[PASS] test_fails_closed_when_stack_missing
[PASS] test_fails_closed_when_stack_json_invalid
[PASS] test_succeeds_on_minimal_agreeing_fixture

RESULT: all 8 tests passed
```

Exit code: `0`.

CLI was also run directly against the live repository:

```
python3 -I workstreams/po03/attempts/po03-wa-b2e7-009-current-source-compiler/compiler.py --repo-root .
```

Exit code: `0`, `"status": "RESOLVED"` (full JSON in test output above and reproducible on demand).

## Finding (real, not fabricated)

Mechanical compilation from structured pointers (never from filename
heuristics) succeeds: both `operations/README.md`'s "Read in this order"
list and `state/operator-system/ACTIVE_INSTRUCTION_STACK.json`'s
`resolve_in_order` list parse cleanly and every path either one names exists
on disk (`all_named_paths_resolved: true`).

However, the two lists do **not** agree with each other, at commit
`5ef49cb148f5186397acf1303f325f726bb58543`:

- `only_in_readme` (2 paths named by the entrypoint but absent from the
  stack's own resolve order): `state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json`,
  `state/operator-system/ACTIVE_INSTRUCTION_STACK.json` (the stack does not
  name itself or the operator-system pointer in its own resolve order).
- `only_in_stack` (5 paths named by the stack but absent from the
  entrypoint's list): `state/FOUNDER_CORRECTION_V00X_PHASE_ONE_FULL_SCALE_CHATGPT_OPERATION_20260819_v001.md`,
  `state/operator-system/OPERATOR_APPOINTMENT_REGISTER.jsonl`,
  `state/operator-system/COMMISSION_REGISTER.jsonl`,
  `state/operator-system/RUNTIME_BINDING_REGISTER.jsonl`,
  `dispatch/WORK_THREAD_LAUNCH_CORRECTION_SW_GOOGLE_BOUNDARY_AND_PARALLEL_MODEL_RESEARCH_20260819_v001.md`.

Neither source is unreadable or missing, so the tool does not fail closed;
it surfaces the disagreement as explicit structured output
(`order_agrees: false`, `membership_agrees: false`) rather than silently
picking one list, silently unioning them without saying so, or inferring
"the" route from a filename pattern (e.g. picking the file with `CURRENT`
in its name).

## Verdict rationale

**PASS** for the falsifiable hypothesis as stated: mechanical compilation
from structured repository pointers, without any filename inference, is
demonstrated and works end-to-end against the live repository. The
compiler correctly resolves every named path and fails closed on synthetic
fixtures with a missing pointer, a missing stack file, or invalid stack
JSON (three dedicated tests below the real-repo tests).

The disagreement between the entrypoint's order and the stack's own
`resolve_in_order` is recorded as an explicit **limitation**, not
smoothed over: a fully unambiguous single "current source set" additionally
requires an explicit reconciliation rule (e.g. "entrypoint order wins" or
"union in entrypoint-first order") that is not itself stated by either
pointer document. This tool defaults to a deterministic union
(entrypoint order first, then stack-only entries appended) and reports
that choice plus the raw disagreement so a downstream consumer is never
misled into thinking the two sources already agree.
