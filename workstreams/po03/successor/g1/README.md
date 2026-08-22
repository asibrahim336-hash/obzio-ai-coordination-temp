# G1 — Wave A transactional factory controls

G1 is the executable state of the PO-03 namespace after Wave A. It is code, tests and CI
configuration, not a description of intended work.

Its immutable locator is the head of `cursor/po03-wave-a-transactional-factory-5086`.
Commits `d67598a` through that head are all G1. The head SHA is not embedded here because a
file cannot contain the SHA of the commit that introduces it; recover it with
`git rev-parse cursor/po03-wave-a-transactional-factory-5086`.

## What G1 adds over G0

G0 is the seeded tree at branch point `552b12eacee637716451492a98980fb0da19ff3e`: two JSON
Schemas, a dependency-free validator, 23 invariant tests and a clean-runtime unittest job.
G0 had no changed-path enforcement, no manifest, no disposition compilation and no
directory-level custody validation, even though the commission names the first of those as
mandatory.

### Tools

- `tools/path_scope_guard.py` — rejects any changed path outside
  `workstreams/po03/`, `receipts/po03/` and `.github/workflows/po03-*.yml`. Paths are
  normalised before the decision, so traversal segments, redundant separators, prefix
  collisions such as `workstreams/po03x/`, case variants, absolute paths, backslash
  separators and git-quoted paths are all rejected rather than interpreted.
- `tools/manifest.py` — writes and verifies `MANIFEST.sha256` over every git-tracked file in
  the subtree, excluding itself and bytecode caches. Refuses git modes `120000` and `160000`
  so a symlink cannot import content from outside the subtree it claims to cover.
- `tools/repository_disposition.py` — read-only. Resolves the pointer-reachable path set from
  `operations/README.md` and `state/operator-system/ACTIVE_INSTRUCTION_STACK.json`, classifies
  every file in the governance directories as `CURRENT`, `SUPERSEDED` or `UNCLASSIFIED`, and
  cross-checks the taxonomy gate's required-alias set against the alias register.
- `tools/emit_unit_results.py` — generates one transactional-result document per counted unit,
  reading artifact bytes from immutable git objects at the recorded commit rather than from
  the working tree. Units without a resolvable commit are skipped and reported.
- `tools/validate_contracts.py` — gains a `validate-dir <kind> <directory>` mode and now
  rejects unknown keys at every closed object, closing a divergence where the published
  schemas declared `additionalProperties: false` while the executable reader ignored it.

### Tests

`tests/test_path_scope_guard.py`, `tests/test_manifest.py`,
`tests/test_repository_disposition.py`, `tests/test_control_evidence.py` and the extended
`tests/test_validate_contracts.py`. The 23 G0 invariant tests are unchanged and still pass.

The out-of-allowlist rejection fixture performs a real mutation and a real
`git diff --name-only` inside a throwaway repository under `/tmp`. No path outside the
allowlist is ever written in this repository to produce that evidence.

`tests/test_control_evidence.py` exists because the commission forbids invented values. It
asserts that every 40-hex commit id in the PO-03 records resolves to a real commit, that every
frozen source hash equals the bytes at the branch point, that every artifact hash equals its
committed blob, that every test cited in the evidence is actually defined, and that no
committed document grants itself acceptance.

### CI

`.github/workflows/po03-contracts.yml` runs four gates on pull requests and on pushes to
`po03/**` and `cursor/po03-**`: the changed-path allowlist, the unittest suite, manifest
verification, and validation of every emitted result document. The changed-path base resolves
to the pull-request base, then the push `before` commit, then the merge base against the PO-03
base ref, and only then `origin/main`. Both diff invocations pass `--no-renames`, because
rename detection reports only the destination path and would let a rename out of the allowlist
delete a governance file invisibly.

### Records

`control/` holds the model capability register, work-unit registry, path ownership, ordered
event log and recovery state. `metrics/` holds the metric definitions, one row per counted
unit and the generation comparison. `research/` holds eight hypotheses and their reproductions.
`evidence/` holds the source lock, criteria freeze, repository disposition, scale ladder, model
allocation, fault matrix and the validated wave compounding receipt.

## What G1 does not establish

- No independent acceptance. Every unit is `NOT_TESTED` or `PENDING`; nothing is self-accepted.
- No cross-family review. No agent-dispatch capability is exposed to this worker.
- No 64-unit Wave A. Ten genuine units ran; the target is recorded `NOT_YET` in
  `evidence/scale-ladder.json` rather than padded.
- No live fault injection against real unreliable infrastructure, and therefore no
  demonstrated recovery. See `evidence/recovery-fault-matrix.json`.
- No measured compounding lift. See `metrics/generation-comparison.json`.
- No CI result yet. The gates above had not executed on GitHub at the time of writing, because
  the branch had not been pushed.
