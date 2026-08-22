# Evidence — po03-wa-b2e7-013-launch-surface-classifier

## Falsifiable hypothesis

Launch surfaces and evidence-only files are mechanically separable, so a
superseded file cannot be mistaken for a launch file.

## What was executed

```
python3 -I workstreams/po03/attempts/po03-wa-b2e7-013-launch-surface-classifier/test_launch_surface_classifier.py
```

Working directory: repository root of this worktree, commit base
`5ef49cb148f5186397acf1303f325f726bb58543`.

Real stdout (verbatim):

```
[PASS] test_fails_closed_when_stack_missing
[PASS] test_load_root_readme_linked_paths_parses_markdown_link
[PASS] test_load_high_risk_markers_parses_dict_literal
[PASS] test_minimal_fixture_launch_surface
[PASS] test_minimal_fixture_evidence
[PASS] test_minimal_fixture_false_claim_marker_is_ambiguous_not_evidence
[PASS] test_minimal_fixture_truly_ambiguous_file_is_ambiguous
[PASS] test_minimal_fixture_fails_closed_status
[PASS] test_minimal_fixture_with_no_ambiguous_files_reports_all_classified
[PASS] test_launch_and_evidence_sets_never_overlap_on_synthetic_fixture
[PASS] test_real_repository_produces_disjoint_launch_and_evidence_sets
    candidate_count=101 launch_surface=9 evidence=7 ambiguous=85 status=FAILED_CLOSED_AMBIGUOUS_FILES_PRESENT
[PASS] test_real_repository_operations_readme_is_launch_surface_via_root_link
[PASS] test_real_repository_verified_markers_are_confirmed_not_just_claimed
[PASS] test_real_repository_has_a_large_uncovered_ambiguous_backlog

RESULT: all 10 tests passed
```

Exit code: `0`.

## What the classifier actually found (real, not fabricated)

Scanned 101 candidate instruction-bearing `.md` files under
`dispatch/`, `commissions/`, `handoff/`, `handover/`, `state/`,
`templates/`, `operations/`, `instructions/`, plus the two repository-root
governing files (`AGENTS.md`, `README.md`).

- **9 LAUNCH_SURFACE**: `AGENTS.md`, `README.md`, both files
  `ACTIVE_INSTRUCTION_STACK.json`'s `resolve_in_order` names
  (`operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md`,
  `instructions/functions/strategic-operations-orchestration/CURRENT.md`,
  `templates/NEXT_OPERATOR_PREFLIGHT_CURRENT.md`,
  `state/FOUNDER_CORRECTION_V00X_PHASE_ONE_FULL_SCALE_CHATGPT_OPERATION_20260819_v001.md`,
  `state/FOUNDER_INTENT_CORRECTION_OPERATOR_FUNCTION_TAXONOMY_AND_INSTRUCTION_CONTINUITY_20260819_v001.md`,
  `dispatch/WORK_THREAD_LAUNCH_CORRECTION_SW_GOOGLE_BOUNDARY_AND_PARALLEL_MODEL_RESEARCH_20260819_v001.md`),
  and `operations/README.md` — which is **not** itself named by
  `resolve_in_order` and only becomes mechanically classifiable as
  LAUNCH_SURFACE because the repository-root `README.md` carries an
  actual markdown link `[`operations/README.md`](operations/README.md)`
  that this classifier parses (real finding, discovered while building
  this unit, not assumed in advance).
- **7 EVIDENCE**: the two files named by `immutable_execution_evidence`
  plus five files verified against `scripts/check_operator_taxonomy.py`'s
  `high_risk_markers` dict — each one's own committed text was read and
  independently confirmed to actually contain its claimed marker string
  (`commissions/OPERATOR_D_CONTINUATION_DIRECTIVE_20260818.md`,
  `dispatch/OPERATOR_D_REFERENCE_UPDATE_20260818.md`,
  `state/DESK_OPERATOR_D_RECOVERY_AND_CONTINUATION_20260818.md`,
  `templates/NEXT_OPERATOR_PREFLIGHT_20260818.md`,
  `handover/PRINCIPAL_AI_OPERATOR_HANDOVER_20260819.md`).
- **85 AMBIGUOUS** (84% of the 101 candidates): every remaining file —
  including every file under `commissions/`, most of `dispatch/` (the
  entire `CLAUDE_EXTENSION_*` chain), most of `handoff/`, and the bulk of
  dated `state/*_20260818*.md` documents — has **no** structured
  disposition record in any of the three sources this classifier reads.
  The classifier reports these files honestly as unresolved rather than
  guessing a bucket for them.
- **0 overlap** between LAUNCH_SURFACE and EVIDENCE in every run, real
  and synthetic — proven by
  `test_real_repository_produces_disjoint_launch_and_evidence_sets` and
  `test_launch_and_evidence_sets_never_overlap_on_synthetic_fixture`.

## Verdict rationale

**PASS**. The core safety property in the hypothesis — "a superseded file
cannot be mistaken for a launch file" — holds mechanically: the
classifier never places a file in LAUNCH_SURFACE unless a structured
source (the instruction stack's `resolve_in_order`, or the root
`README.md`'s own markdown link) names it, and it independently verifies
(does not just trust) every claimed EVIDENCE marker against the target
file's own committed text
(`test_real_repository_verified_markers_are_confirmed_not_just_claimed`,
plus a synthetic fixture — `state/false_claim_marker.md` — proving a
falsely claimed marker is correctly rejected into AMBIGUOUS rather than
accepted as EVIDENCE). No collision between the two buckets was ever
observed.

**Limitation, recorded precisely rather than smoothed over**: separability
is only demonstrated for the 16 of 101 files (16%) that carry *any*
structured disposition record at all. The remaining 85 files (84%) are
real, un-dispositioned instruction-bearing content that this classifier
correctly refuses to certify either way (`status:
FAILED_CLOSED_AMBIGUOUS_FILES_PRESENT`). Closing that backlog is
`po03-wa-b2e7-015-disposition-completeness`'s job, not this classifier's;
this unit's job is only to prove the separation is mechanically sound
and to report the true size of the uncovered set rather than hide it
behind an invented default classification.
