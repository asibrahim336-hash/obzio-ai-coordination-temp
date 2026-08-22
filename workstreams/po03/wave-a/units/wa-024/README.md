# PO03-WA-024 — GitHub Actions clean-environment claim

Frozen hypothesis: *a clean Actions runner exposes hidden local-state assumptions
that a warm checkout misses.*

This unit tests that hypothesis by execution rather than by argument. It ships a
differential harness that runs the repository's own declared CI commands and the
PO-03 protocol's own provenance checks in three environments, a static control
that finds the same defect classes by inspection, focused tests over synthetic
ground truth, and a one-command clean-environment reproduction.

## Reproduce

From any checkout of this repository, with only `bash`, `git` and `python3`:

```bash
workstreams/po03/wave-a/units/wa-024/harness/run.sh --out /tmp/wa024-report
```

The script clones the requested commit into a fresh directory containing
committed content only, exports a private `HOME` and `TMPDIR`, unsets inherited
`PYTHON*` settings, and then runs four stages from inside that clean clone: the
focused tests, the static control, the differential harness, and the
mechanism-change verifier. It never modifies the caller's checkout and exits
non-zero if a binding expectation is unmet or a proposed change fails to verify.

## Contents

| Path | State | What it is |
| --- | --- | --- |
| `sources/source-claims.json` | source claim | What upstream and in-repository sources say, each pinned to an immutable commit or repository digest. No conclusions. |
| `hypotheses/hypotheses.json` | frozen hypothesis | Eight current-method hypotheses with predictions and refutation conditions, frozen before the reproductions ran. |
| `harness/clean_runner_probe.py` | mechanism | Differential harness over `warm`, `clean_full` and `clean_shallow` environments. |
| `harness/probes.json` | mechanism | The declared repository-native workloads, with per-probe expectations. |
| `harness/local_state_lint.py` | mechanism | Static control for five hidden-local-state defect classes. |
| `harness/external-object-ids.json` | mechanism | Object ids that belong to other repositories, each with a reason. |
| `harness/run.sh` | mechanism | The clean-environment reproduction entry point. |
| `tests/` | test | Focused tests, including adversarial cases and negative controls over synthetic git fixtures. |
| `result/` | result | Reproduction output, disposition, tests, limitations, manifest and producer return. |
| `proposals/mechanism-changes.json` | mechanism change | Three proposed repairs and four evidence-backed rejections. Proposals only; nothing outside this unit was modified. |
| `proposals/patches/` | mechanism change | One unified diff per proposed repair, each against a read-only path. |
| `proposals/verify_mechanism_changes.py` | mechanism change | Applies each patch in a throwaway clone and proves the defect is present before it and absent after. |
| `proposals/strategy-proposals.json` | strategy proposal | Five recommendations for the coordinator. Distinct from the mechanism changes above. |

Source claims, hypotheses, reproduction results, mechanism changes and strategy
proposals are kept in separate files on purpose. A claim is not a hypothesis, a
reproduction is not a mechanism change, and a mechanism change is not a strategy
decision.

## The three environments

| Mode | Tree | Environment | Emulates |
| --- | --- | --- | --- |
| `warm` | the caller's existing working tree | inherited | a long-lived checkout reused between runs |
| `clean_full` | fresh clone, complete history, committed content only | scrubbed | `actions/checkout` with `fetch-depth: 0` |
| `clean_shallow` | fresh clone, depth 1 | scrubbed | `actions/checkout` with its default `fetch-depth` of 1 |

A probe whose outcome differs across these modes has located a hidden
environmental dependence. The harness names the class: `WARM_ONLY_PASS` for local
state, `DEPTH_SENSITIVE` for history, `CLEAN_ONLY_PASS` for ambient contamination
of the warm environment, and `AGREE` when no dependence exists.

`AGREE` is not the same as "no defect". The largest finding in this unit is an
`AGREE` probe: the declared contract-test command contaminates the checkout in
every environment, and a clean runner hides that only because it throws the
workspace away. A comparison between warm and clean is blind to it, which is why
the harness also records whether each probe mutated the tree.

## Boundary

No workflow run was dispatched and no pull request was created or modified, so
every conclusion is labelled CI-equivalent rather than CI-observed; see
`result/limitations.json`. Nothing outside
`workstreams/po03/wave-a/units/wa-024/` was written. The repair proposed for a
shared workflow is a patch in `proposals/patches/`, deliberately not applied.
