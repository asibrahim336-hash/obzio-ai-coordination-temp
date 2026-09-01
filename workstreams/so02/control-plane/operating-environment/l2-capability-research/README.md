# OE-L2 — capability research for the founder operating environment

**Lane** `OE-L2-CAPABILITY-RESEARCH` · **Commission** `COM-CUR-ENV-01-20260822-v001`
**Fence token** `d5e76252f0ea259d` · **Immutable start SHA** `fe0a595206e5986de7eaac6cabc619215a1eb81b`
**Branch** `cursor/oe-l2-capability-research-696d` · **Lifecycle state** `READY_TO_COMMIT`

Nothing here binds a tool, model or architecture. The commission reserves selection
to the founder; this lane supplies evidence and a recommendation.

## Read in this order

1. **`TOPOLOGY-COMPARISON.md`** — five topologies compared end to end, the
   recommendation, and the nine questions that need founder judgement rather than
   more research. Start here.
2. **`CAPABILITY-MAP.json`** — 32 capability requirements across the ten commissioned
   areas plus six cross-cutting invariants. Each requirement carries an acceptance
   test, the failure mode if it is absent, its disclosure surface, and how it differs
   on the Chromebook today versus the MacBook later. Written without naming
   implementations so candidates are judged against requirements.
3. **`CANDIDATE-REGISTER.json`** — 73 candidates, 65 carrying GitHub maintenance
   signals harvested live on 2026-08-22, with a verdict and its basis for each.
4. **`NAME-RESOLUTION.json`** — how each ambiguous seed resolved, including the full
   probe record for `Aircrift/Aircraft`, which remains `UNRESOLVED`.

## Evidence discipline

Every claim is labelled `DIRECTLY_REPRODUCED` (a command this lane ran, with the
URL and fetch date recorded), `DOCUMENTED` (an official source this lane fetched) or
`HYPOTHESIS` (untested inference). Recommendations rest only on the first two.

Raw evidence is under `receipts/so02/2026-08-22/oe-l2-capability-research/raw/`:
`github-signals.jsonl` (live repository signals), `docs/` (fetched documents, each
with a `.meta.json` recording status, effective URL, fetch timestamp and body hash),
`openrouter-models.json` and `model-qualification-table.json`.

## Reproducing the evidence

From the repository root:

```bash
B=workstreams/so02/control-plane/operating-environment/l2-capability-research
R=receipts/so02/2026-08-22/oe-l2-capability-research

# live GitHub maintenance signals for every candidate
python3 $B/tools/gh_probe.py < $B/tools/candidates-github.txt > $R/raw/github-signals.jsonl

# official documentation and READMEs
OE_EVIDENCE_DIR=$R/raw/docs OE_MAX_CHARS=14000 \
  python3 $B/tools/fetch_doc.py <slug> <url>

# exact-model qualification table from the live gateway catalogue
curl -sS https://openrouter.ai/api/v1/models > $R/raw/openrouter-models.json
python3 $B/tools/model_table.py $R/raw/openrouter-models.json > $R/raw/model-qualification-table.json

# rebuild the register (mechanical join of judgement and evidence)
python3 $B/tools/build_register.py $B/tools/candidate-assessments.json \
  $R/raw/github-signals.jsonl > $B/CANDIDATE-REGISTER.json

# rebuild and verify the receipt manifest
python3 $B/tools/build_manifest.py $R/MANIFEST.json $B $R
```

Signals will differ from the recorded run because the sources are live. That is the
point: `CANDIDATE-REGISTER.json` records what was true on 2026-08-22, and re-running
shows what has changed since.

## Lane isolation

This lane committed from a dedicated git worktree rather than from `/workspace`,
because `/workspace` shares one `.git` with the other four lanes and a sibling lane's
commit had already landed on this branch before the isolation was put in place. That
commit was byte-identical to one already present on the sibling's own branch, so
resetting this branch to the immutable start SHA lost no work. All subsequent commits
stage explicit namespace paths rather than using `git add -A`.
