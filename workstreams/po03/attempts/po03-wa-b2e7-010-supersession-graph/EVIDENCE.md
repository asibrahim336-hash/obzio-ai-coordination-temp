# Evidence — po03-wa-b2e7-010-supersession-graph

## Falsifiable hypothesis

Supersession relationships across instruction and state files form a
directed acyclic graph, and any cycle is a defect.

## What was executed

```
python3 -I workstreams/po03/attempts/po03-wa-b2e7-010-supersession-graph/test_supersession_graph.py
```

Working directory: repository root of this worktree, commit base
`5ef49cb148f5186397acf1303f325f726bb58543`.

Real stdout (verbatim):

```
[PASS] test_extract_targets_handles_dict_with_path
[PASS] test_extract_targets_handles_list_of_dict_with_path
[PASS] test_extract_targets_strips_trailing_prose_after_path
[PASS] test_extract_targets_handles_objects_with_blobsha_suffix
[PASS] test_extract_targets_reports_non_path_string_as_external
[PASS] test_backward_key_superseded_by_inverts_direction
[PASS] test_detect_cycles_returns_empty_for_dag
[PASS] test_detect_cycles_detects_synthetic_cycle
[PASS] test_unreachable_from_root_flags_disconnected_node
[PASS] test_real_repository_supersession_graph_is_a_dag
    files_scanned=371 edge_count=122 node_count=71
[PASS] test_real_repository_no_dangling_supersession_targets
[PASS] test_real_repository_20260819_02_is_unreachable_from_current_root

RESULT: all 12 tests passed
```

Exit code: `0`.

## What the scan actually found (real, not fabricated)

Scanning every committed `.json`/`.jsonl` file in the repository (371
files) for any key whose name contains "supersed" (case-insensitive)
found **9 distinct field-name variants** actually in use: `supersedes`,
`supersedes_pointer`, `superseded_pointer`, `supersedes_as_live_pointer`,
`superseded_by` (the only backward-direction one observed),
`superseded_evidence_chain`, `superseded_and_held_evidence`,
`preserved_superseded_evidence`, `superseded_before_dispatch(ed)`,
`blocked_superseded_unsent`, `supersedes_receipt`, `supersedes_lane_or_source`.
After normalising every value shape actually observed (dict-with-path,
list-of-dict-with-path, list-of-string with trailing prose,
`objects: ["path@blobsha", ...]`, plain string) into `(newer, older)`
edges:

- **122 edges** across **71 nodes**, **0 cycles** (`is_dag: true`) —
  confirms the hypothesis on real data.
- **0 dangling targets** — every file-path resolved from a supersession
  field exists on disk.
- Many `supersedes` occurrences (mostly in `state/SOURCE_CLAIM_REGISTER*`
  files) name a *prose claim or assumption*, not a file
  (e.g. `"Any narrower D-closeout-only interpretation"`,
  `"RCP-PO03-APPOINTMENT-SEED-20260822-v001"`). These do not resolve to a
  path and are reported separately as `external_references` rather than
  silently dropped or miscounted as graph edges/nodes.
- **Genuine finding**: `state/ACTIVE_CONTROL_POINTER_20260819_02.json` is
  in the very same `ACTIVE_CONTROL_POINTER` filename family as the
  designated current root (`state/ACTIVE_CONTROL_POINTER_CURRENT.json`)
  and itself carries `supersedes_pointer -> ...20260819_01.json`, yet it
  is **unreachable** from the current root by forward supersession
  traversal: `CURRENT.json`'s own `superseded_pointer` field jumps
  straight to `...20260819_01.json`, never naming `...20260819_02.json`.
  The only place `...20260819_02.json` is referenced from `CURRENT.json`
  is its `selected_pointer` field, which is a *different, non-supersession*
  relation. This is exactly the class of ambiguity the commission asks to
  make mechanically detectable instead of silently inferred from the
  shared filename prefix.

## Verdict rationale

**PASS**. The hypothesis holds against real committed data: 122
discovered supersession edges over 71 nodes form a DAG with zero cycles.
The cycle detector is not a stub — `test_detect_cycles_detects_synthetic_cycle`
proves it correctly flags an injected 3-node cycle (`a -> b -> c -> a`)
that never touches any real repository file, so the "0 cycles" result on
real data is a genuine negative finding, not an untested default.

Unreachable-node reporting is exercised both synthetically
(`test_unreachable_from_root_flags_disconnected_node`) and against the
live repository, where it surfaces the `...20260819_02.json` finding
above as a **limitation**: "any cycle is a defect" is confirmed
vacuously true (no cycles exist), but the graph also contains real,
non-cyclic structural ambiguity (a same-family sibling pointer that is
referenced by a non-supersession field but not linked into the
supersession chain) that a cycle-only check would not catch.
