# PO-03 — Repository Engineering and Portable Runtime Principal

```yaml
commission_id: COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001
institutional_function: obzio.function.repository-engineering-portable-runtime
appointment: PO-03
runtime: Cursor Cloud
strategy_restarted: false
decision_changed: []
lifecycle: COMMISSIONED_NOT_YET_EXECUTING
repository: asibrahim336-hash/obzio-ai-coordination-temp
pinned_base_sha: 5db7affeb7f00763e148e6d98a33ee6b751f2def
branch: po03/repository-engineering-portable-runtime-20260822-v001
po01_instruction: DO_NOT_INTERRUPT
```

Continue the existing Obzio programme. Do not redesign strategy or claim authority from Cursor.

## Collision boundary

Wave-one writes are restricted to:

- `workstreams/po03/**`
- `receipts/po03/**`
- `.github/workflows/po03-*.yml`

Treat as read-only:

- `packs/**`
- `modules/operators/**`
- `_transport/**`
- `modules/work_unit_contract/**`
- existing `state/**` and `dispatch/**` current-pointer files
- every PO-01 branch and artefact
- `.cursor/environment.json`

A path-scope guard must fail CI for writes outside the allowlist. Do not modify `cursor/setup-dev-environment-b5ce` or PR #8. Do not merge or promote anything.

## Mission

1. Record the account-qualified repository, pinned base, branch, Cursor run/agent IDs, models, reasoning controls, context, tools and permissions before substantive work.
2. Freeze exact source SHAs, evaluation criteria and expected evidence before reading producer narratives.
3. Build substantive repository-native mechanisms for:
   - current-source and supersession compilation;
   - portable runtime execution from a clean clone;
   - independent operator-pack qualification;
   - manifest, provenance and changed-path enforcement;
   - repository disposition and transport-debris detection.
4. Reproduce PO-01 pack claims from immutable commits without modifying its branches. Detect missing files, non-portable paths, manifest gaps and process-boundary failures.
5. Exercise the resulting capability in Cursor and a clean GitHub Actions environment without SW memory, local hidden state, `/tmp` dependencies or uncommitted files.
6. Repair only inside the PO-03 namespace during wave one. Produce integration-ready patches separately; do not apply them to PO-01 namespaces.
7. Return material code, tests and CI effects—not settings, topology, a plan or readiness report.

## Mandatory receipts

Commit:

- `workstreams/po03/evidence/source-lock.json`
- `workstreams/po03/evidence/criteria-freeze.json`
- `workstreams/po03/evidence/reproduction-results.json`
- `workstreams/po03/evidence/repository-disposition.json`
- `workstreams/po03/MANIFEST.sha256`
- `receipts/po03/2026-08-22/producer-execution.json`
- `receipts/po03/2026-08-22/ci-clean-clone.json`
- `receipts/po03/2026-08-22/independent-acceptance-request.json`

The return must include repository, branch, commit and draft-PR URLs; complete changed-file list; workflow-run URLs; test commands and results; hashes; failures, repairs, unresolved constraints and exact owner-blocked acts.

## Acceptance candidate controls

- A fresh checkout reproduces tests without provider memory or hidden state.
- Every claimed input is pinned by repository and SHA.
- Injected corruption, missing-file and interrupted-run cases are detected.
- Producer tests and clean-process CI are reported separately.
- PO-03 must not self-mark the work independently accepted.
- Finish as an acceptance candidate for SO-02/PO-02 review.
