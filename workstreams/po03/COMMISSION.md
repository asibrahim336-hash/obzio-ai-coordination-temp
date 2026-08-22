# PO-03 — Repository Engineering and Portable Runtime Principal

```yaml
commission_id: COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001
commission_revision: v002
amendment_id: AMD-COM-PO03-COMPOUNDING-FACTORY-20260822-v002
amends_not_restarts: true
institutional_function: obzio.function.repository-engineering-portable-runtime
appointment: PO-03
runtime: Cursor Cloud
strategy_restarted: false
decision_changed: []
lifecycle: COMMISSIONED_NOT_YET_EXECUTING
repository: asibrahim336-hash/obzio-ai-coordination-temp
pinned_base_sha: 5db7affeb7f00763e148e6d98a33ee6b751f2def
prior_commission_commit: 887b3c1ac2dec49d5f36d31593e416f651486aee
prior_observed_head: d627119351a6dc0e90158705abf6aab96e26b3dd
branch: po03/repository-engineering-portable-runtime-20260822-v001
po01_instruction: DO_NOT_INTERRUPT
```

Continue the existing Obzio programme. This revision changes the execution method and acceptance standard before launch; it does not replace the mission, change company strategy, widen write authority, or restart PO-03. Do not claim authority from Cursor.

## Collision boundary

Wave-one writes remain restricted to:

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

A path-scope guard must fail CI for writes outside the allowlist. Do not modify `cursor/setup-dev-environment-b5ce` or PR #8. Do not merge or promote anything. Only the integration controller may write shared PO-03 paths; every subordinate writer receives a unique worktree/branch and owned subtree.

## Original mission — preserved

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

## Operating-method correction — active before execution

PO-03 must run the original mission and a continuous discovery portfolio concurrently. The operating loop is executable, not a report:

`operate → observe → measure → challenge → research → discover → reproduce → learn → change the live mechanism → independently test → retain/delete/supersede → launch a stronger successor → repeat`

Keep all of these functions substantively staffed throughout execution:

1. current-plan engineering and clean-runtime reproduction;
2. zero-base strategy challenge, alternative generation and opportunity discovery;
3. current frontier research across official documentation, practitioner repositories, papers, labs, communities, competing agent systems, postmortems and failure traces;
4. controlled reproduction of external claims on sanitized Obzio workloads;
5. independent evaluation, adversarial review and hidden-case generation;
6. model, tool, runtime, context, memory, coordination and topology evaluation;
7. semantic/ontology/state-contract improvement;
8. operating-system measurement and failure recovery;
9. successor compilation and executed comparison;
10. open discovery of useful work neither the founder nor this commission named.

The list seeds discovery; it is not an exclusion boundary. Strategy findings remain proposals until the founder interlock binds them. PO-03 may autonomously improve its in-scope execution mechanism and must test each material change before retaining it.

### Strongest-model policy

Record the exact models/configurations actually exposed by the current Cursor account before delegation. As verified in current Cursor documentation on 2026-08-22, the available frontier families include `claude-opus-5`, `gpt-5.6-sol`, `gemini-3.1-pro`, and `composer-2.5`; account exposure still must be observed rather than assumed.

- Lead/integrator default: `claude-opus-5` with high thinking, because Cursor recommends that variant for strongest results.
- Independent chief challenger and parallel engineering default: `gpt-5.6-sol` at the highest exposed reasoning setting.
- Independent long-context/whole-tree and alternative-generation default: `gemini-3.1-pro` at its highest exposed setting.
- `composer-2.5` is used only as a distinct Cursor-harness hypothesis or when a preregistered matched evaluation shows a functional advantage; never as a routine cheaper substitute.
- Instantiate the strongest configurations repeatedly when independent cognition is useful. Do not use Auto where an exact frontier model can be selected and logged.
- Do not optimise downward for token or monetary cost during this window. Cost is measured as an operating property, not used as an automatic downgrade rule.
- A weaker configuration is admissible only after a frozen paired evaluation demonstrates a functional advantage for that work class. Record the exception and evidence.
- If an exact family/configuration is unavailable, record observed `NOT_SUPPORTED`; do not manufacture availability or diversity.

Use bounded, hashed source capsules and measured context admission. Highest reasoning does not mean indiscriminate context dumping.

### Capacity-seeking scale

Wave A contains at least **64 substantive independent work-unit attempts** across the standing functions. Begin at the maximum safe active concurrency Cursor exposes, keep every available slot filled, and use isolated cloud VMs/worktrees. If the provider caps active concurrency, record the exact observed ceiling and complete the 64 attempts in queued cohorts; do not reduce the work to a conventional small fleet.

After Wave A demonstrates zero false completion, zero result loss and zero path collision, run Wave B with at least **128 substantive attempts**, then continue expanding while independently accepted throughput and discovery yield improve. A work unit counts only if it owns a distinct falsifiable hypothesis, executable component, reproduction, test, adversarial case or acceptance decision and leaves a durable result. Renamed clones, inventories, plans, idle sessions and duplicated summaries do not count.

For consequential decisions, require at least three independently generated candidates and blind adversarial review from at least two different frontier model families when exposed. Reviewers freeze criteria before receiving producer conclusions. Use `/best-of-n`, subagents on isolated machines, worktrees and cloud-agent goal continuity when they improve evidence; record the exact mechanism used.

### Research-to-mechanism conversion

Every admitted external method follows:

`source claim → frozen hypothesis → Obzio reproduction → result → live mechanism change or evidence-backed rejection → independent recurrence test`

A research summary alone is not a completed unit. The first substantive return must contain at least 12 current-method hypotheses, at least six Obzio reproductions, and at least two independently tested mechanism changes or evidence-backed rejections. Source, reproduction, mechanism-change and strategy-proposal states remain distinct.

## Transactional result custody — hard precondition

The seeded files `contracts/transactional-result.schema.json`, `contracts/wave-compounding.schema.json`, `tools/validate_contracts.py`, their tests and `po03-contracts.yml` are active controls. Strengthen them; do not bypass them.

Every material unit follows:

`CREATED → LEASED → RUNNING → CHECKPOINTED* → RESULT_STAGING → RESULT_STAGED → RESULT_VERIFIED → RESULT_COMMITTED → PARENT_INGESTED → COMPLETED → ACCEPTED | REJECTED`

Provider `COMPLETED` is merely an observation. If no verified durable result commit exists, Obzio state is `PROVIDER_COMPLETED_UNCOMMITTED`, never `COMPLETED`.

Before dispatch, durably write immutable task input, configuration, source hashes, acceptance hashes, exact model/configuration, owned paths, result slot, idempotency key, lease and fence token. Verify that the child can write and independently read back a synthetic canary. If no durable sink exists, do not delegate material work through that route.

A subordinate may report only `READY_TO_COMMIT`. Before Obzio completion:

1. result, logs, tests, limitations and complete artifact manifest are written;
2. hashes and byte counts are verified;
3. the result is committed to a deterministic `po03/*` remote branch or ingested by the controller;
4. another process reads every artifact back by immutable SHA;
5. the parent records ingestion;
6. only the coordinator sets `COMPLETED`;
7. a different producer may then accept or reject it.

Use an append-only ledger, transactional outbox, leases, fencing, monotonic checkpoints and a recovery scanner. Lost callbacks must replay. Duplicate callbacks must be harmless. An expired/stale worker must not commit after ownership transfers.

Run fault injection after every state transition, including process/session loss, lost return message, partial write, pre/post commit failure, pre/post push failure, stale lease, duplicate callback, corrupt or missing artifact, network interruption, parent restart and entire provider-runtime loss. Acceptance requires zero false completion, 100% recovery of committed results, automatic resume/rerun of uncommitted tasks from immutable input, zero duplicate external effects, complete hash coverage and no founder relay.

Freeze the lost PO-02 Code-2 packaging return as `PROVIDER_COMPLETED_UNCOMMITTED / UNRECOVERED_AFTER_FOUR_REPORTED_ROUTES / NOT_ACCEPTED`. Use it as a fault fixture; do not call it a completed deliverable.

## Operating-system measurement

Define metrics before optimisation and record one row per counted unit. At minimum capture IDs/parents/functions, runtime, exact model/reasoning, prompt/source/context hashes, available token and cost data, queue/active/wall/review time, tools/effects, checkpoints, retries, result commit/read-back, first-pass outcome, independent disposition, defects/rework, founder action, provider block, collision and recovery events.

Report independently accepted throughput, first-pass acceptance, escaped-defect/false-green rate, cycle and recovery time, coordination overhead, founder interventions, context waste where measurable, orphan/duplicate/collision/false-complete counts, research-to-reproduction conversion, lesson-to-live-change conversion, per-model contribution/disagreement and successor lift. Never invent unavailable values; use `NOT_SUPPORTED` with the observed boundary.

## Successor-generation test

Run three measured generations on one frozen public suite plus evaluator-held novel cases:

- `G0`: the pre-amendment controller reconstructed from immutable source;
- `G1`: this high-scale transactional factory;
- `G2`: a successor compiled from G1 failures and accepted lessons.

Each generation must be executable code/configuration with tests, not a document. At least three independently supported lessons must change live mechanisms and receive recurrence tests. Every changed route receives `RETAIN`, `DELETE`, `SUPERSEDE`, `RETEST` or `REJECT`, preserving lineage.

Hard guardrails: zero out-of-allowlist writes, zero PO-01 contact/mutation, zero protected acts or secret exposure, zero false completion, 100% critical-correctness assertions, and clean-clone reproduction without provider memory, `/tmp`, uncommitted files or a warm checkout. Claim compounding only from measured lift on preregistered metrics with no quality regression. If evidence does not show lift, repair and rerun or retain `NOT_YET`.

## PO-01 non-interference remains absolute

PO-01 remains active, outcome-pending and unaccepted. PO-03 may read immutable PO-01 commits and may observe a volatile branch only to pin a new read-only SHA. It must not contact, message, pause, redirect, restart, manage or otherwise signal PO-01; write to its branches, paths, PRs, artifacts or workspaces; or use producer narrative as independent evidence. A PO-01 defect produces a frozen test and isolated PO-03 repair candidate, never an in-place repair.

## Mandatory durable outputs

Retain every v001 receipt and additionally commit and hash:

- `workstreams/po03/control/model-capability-register.json`
- `workstreams/po03/control/work-unit-registry.jsonl`
- `workstreams/po03/control/path-ownership.json`
- `workstreams/po03/control/events/`
- `workstreams/po03/control/recovery-state.json`
- `workstreams/po03/metrics/metric-definitions.json`
- `workstreams/po03/metrics/work-unit-runs.jsonl`
- `workstreams/po03/metrics/generation-comparison.json`
- `workstreams/po03/research/hypotheses.jsonl`
- `workstreams/po03/research/reproduction-ledger.jsonl`
- `workstreams/po03/evidence/scale-ladder.json`
- `workstreams/po03/evidence/model-allocation-and-exceptions.json`
- `workstreams/po03/evidence/recovery-fault-matrix.json`
- `workstreams/po03/evidence/compounding-results.json`
- `workstreams/po03/successor/g1/`
- `workstreams/po03/successor/g2/`
- `receipts/po03/2026-08-22/amendment-activation.json`
- `receipts/po03/2026-08-22/transactional-recovery.json`
- `receipts/po03/2026-08-22/successor-generation.json`

The path-scope workflow must include a deliberate out-of-allowlist mutation fixture and prove rejection.

## Mandatory v001 receipts — preserved

Commit:

- `workstreams/po03/evidence/source-lock.json`
- `workstreams/po03/evidence/criteria-freeze.json`
- `workstreams/po03/evidence/reproduction-results.json`
- `workstreams/po03/evidence/repository-disposition.json`
- `workstreams/po03/MANIFEST.sha256`
- `receipts/po03/2026-08-22/producer-execution.json`
- `receipts/po03/2026-08-22/ci-clean-clone.json`
- `receipts/po03/2026-08-22/independent-acceptance-request.json`

The return must include repository, branch, commit and draft-PR URLs; complete changed-file list; workflow-run URLs; test commands/results; hashes; failures, repairs, unresolved constraints and exact owner-blocked acts.

## Acceptance candidate controls

PO-03 is an acceptance candidate only when:

- the preserved v001 mission has substantive code, tests and CI effects;
- account-observed strongest-model use and heterogeneous allocation are evidenced;
- Wave A has 64 substantive durable results or an exact provider ceiling was observed and fully saturated in queued cohorts;
- every counted unit has a terminal durable disposition and immutable locator;
- strategy, research, reproduction, evaluation, OS and successor functions produced tested material effects;
- transactional recovery and fault injection pass;
- OS metrics cover every counted unit without invented values;
- G0/G1/G2 and holdout evidence establish or refuse the claimed lift;
- a fresh checkout reproduces the complete suite;
- all changed paths remain inside the original allowlist;
- PO-01 non-interference is evidenced;
- an independent acceptance request is issued.

PO-03 must not self-mark the work independently accepted. Use only `PASS`, `FAIL`, `NOT_YET`, `NOT_SUPPORTED` or `OWNER_BLOCKED`, with exact evidence for every non-PASS outcome.
