# PO-03 Wave A 043 — independent adversarial review of the path-scope guard

Task: `wave-a-043-path-scope-adversarial-review`
Function: independent-evaluation
Artefact under review: `workstreams/po03/tools/check_path_scope.py`, sha256 `d0c207b1710e5ea4026319d6250d1f85ec91c327f8250c552e2a0ed627881b97`, evaluated at commit `06210fb82ba2b0b9e30b2a9c752ca781c0d2d466`
Hypothesis under test: *the scope guard rejects modified, added, copied, renamed, and deleted out-of-allowlist paths*
Verdict: **REFUTED**

## What was done

Ninety-two pure path strings and twenty-eight repository-shaped scenarios were written and rendered to `hidden-cases.json` before the guard was executed against any of them. Each case carries two independent judgements: `commission_requirement`, the oracle verdict derived from the collision boundary in `workstreams/po03/COMMISSION.md`, and `predicted_guard_disposition` or `predicted_guard_exit_code`, this reviewer's prediction. Keeping them apart means a wrong prediction is scored against the reviewer while the finding is still scored against the guard.

The pure path cases call `violations()` directly and touch no filesystem. Each one is also re-run through the command-line interface with `--path`, and the two agreed on every case that argv can express. The repository cases are replayed inside throwaway Git repositories created under a temporary directory and deleted afterwards, so the dangerous mutations — deleting a current-pointer file, absorbing a PO-01 artefact, adding a submodule outside the allowlist — exist only in scratch repositories and never as a durable write here.

The frozen file was executed once before the implementation commit, to confirm the harness ran at all. It was not edited afterwards, and its sha256 `b2180bb19422b9d2272ef0dacb77e263766a437b0f2fb36005cb493acb7f143e` is recorded in `frozen-criteria.json` so an acceptor can confirm that no prediction moved after an observation.

## Result

Twenty-eight sanctioned cases produced zero false positives. The guard did not block a single legitimate PO-03 write, including file names containing spaces, tabs, newlines, quotes, zero-width characters and both Unicode normalisation forms. That matters as much as the misses: a scope guard that blocks its own commission gets disabled.

Ninety-two out-of-allowlist cases produced five that the guard admitted. They fall into two mechanisms.

### F-001 — the source path of a rename is invisible to the guard

`changed_paths()` asks Git for `git diff --name-only --diff-filter=ACMRDTUXB -z base...head`. Rename detection has been on by default since Git 2.9, so a moved file comes back as one `R` entry, and `--name-only` prints only that entry's destination. The deleted source path is never emitted and therefore never reaches `normalize()`, `is_allowed()` or `violations()`.

The consequence is that a PO-03 branch can delete any read-only file in the repository, provided it moves the content into the PO-03 subtree rather than removing it outright:

```
$ git mv state/ACTIVE_CONTROL_POINTER_CURRENT.json workstreams/po03/control/absorbed.json
$ git diff --name-status base...HEAD
R100    state/ACTIVE_CONTROL_POINTER_CURRENT.json    workstreams/po03/control/absorbed.json
$ git diff --name-only base...HEAD
workstreams/po03/control/absorbed.json
$ python3 check_path_scope.py --base base --head HEAD
PO03_PATH_SCOPE_PASS changed_paths=1
```

The protected file is gone from the head tree and the guard exits zero. Case `GIT-012` runs the same mutation against `workstreams/po01/producer-result.json`, so the mechanism reaches the PO-01 non-interference boundary the commission calls absolute, which is the one boundary with no fallback control behind it.

Three contrast cases locate the defect precisely rather than leaving it as an anecdote. `GIT-009` renames in the other direction, out of the allowlist, and the guard correctly rejects it, because there the escaping path *is* the destination. `GIT-013` performs the same net mutation as `GIT-010` but rewrites the content so similarity falls below the detection threshold; Git then reports `D` plus `A` and the guard correctly rejects it. `GIT-014` repeats `GIT-010` verbatim with `diff.renames` set to `false` and the guard again rejects it. So the allowlist logic is sound, the normalisation is sound, and the failure lives entirely in what `--name-only` chooses to print. Whether the guard holds depends on a Git configuration default and on a similarity score, neither of which the guard states or pins.

Both jobs in `po03-contracts.yml` call the same helper, so this is not confined to one invocation. Neither committed test file can see it: `test_check_path_scope.py` and `test_path_scope.py` both exercise `violations()` and `is_allowed()` with literal strings, and neither one ever builds a repository or calls `changed_paths()`. The gap is not that the tests are wrong; it is that they test the half of the guard that works.

### F-002 — the workflow rule crosses a path separator

`is_allowed()` admits a path when it starts with `.github/workflows/po03-` and ends with `.yml`. The commission writes that boundary as `.github/workflows/po03-*.yml`, and in ordinary pathname-glob semantics `*` does not match a separator. The pair of anchored string tests places no such restriction, so `.github/workflows/po03-guard/payload.yml` and `.github/workflows/po03-a/b/c/deep.yml` are both admitted at any depth.

Eight sibling lookalikes in the same family are correctly rejected — `not-po03.yml`, `po03-guard.yaml`, `po03-guard.yml.bak`, `po03_guard.yml`, `PO03-guard.yml`, `sub/po03-guard.yml`, `.github/workflowspo03-x.yml` and `.github/actions/po03-x.yml` — so the rule is tight in every dimension except depth.

The practical risk is bounded: GitHub Actions loads workflow files placed directly in `.github/workflows`, not from nested directories, so an admitted nested file is unlikely to execute by itself. That mitigation is reasoned from the invocation surface and is recorded as untested here, which is why the finding rests on the commission boundary rather than on an execution claim. `.github/**` is outside the writable set, and for a PO-03 branch this guard is the only mechanical control over it.

### F-003 — the push-triggered job is red on every branch creation

The workflow passes `github.event.before` straight through as `BASE_SHA`. On a push that creates a branch, GitHub sets that field to forty zeros, `git diff` refuses the range, and the guard exits 2. That is correct fail-closed behaviour and produces no false green. It is reported because a step that goes red for a benign reason on every new branch teaches reviewers to skim past it, and F-001 has already blunted the same control.

## What the guard gets right

Worth stating plainly, because an adversarial review that lists only misses misrepresents the artefact. Every boundary confusable held: `workstreams/po03x/`, `workstreams/po030/`, `workstreams/po03-extra/`, `workstreams/po03.bak/`, a bare file named `workstreams/po03`, the same set on the `receipts` side, and the unanchored forms `aworkstreams/po03/…` and `x/workstreams/po03/…`. Every case variant held, which matters because a case-insensitive checkout would resolve `Workstreams/po03/x` onto the real directory. Every traversal and separator form was rejected, including `..` after an allowed prefix, doubled separators, absolute paths, `./` prefixes, trailing separators, Windows separators, and both orderings of an embedded NUL byte. Six Unicode confusables were rejected, including a Cyrillic `о` inside `po03` and a zero-width space between `po03` and its separator, which are the forms a human reviewer of a diff would not catch. All seven PO-01 path forms were rejected as pure strings; PO-01 escapes only through the rename mechanism of F-001.

The `-z` form of the diff invocation is load-bearing and correct: `GIT-004` adds an in-allowlist file whose name contains a newline, and a line-oriented reader would split it into two fragments and reject a legitimate write. Non-UTF-8 path names fail closed at exit 2, though by inheritance rather than by design — `UnicodeDecodeError` is caught only because it subclasses `ValueError`, which is worth knowing before anyone narrows that handler.

## Reviewer error

The frozen records for `GIT-010` and `GIT-012` are internally inconsistent. Their prose rationale predicted the miss in terms, and their numeric `predicted_guard_exit_code` field nevertheless carried `1`. The harness compares the numeric field, so both are reported as refuted predictions. The frozen file was left byte-identical to the bytes that were evaluated rather than corrected after the fact, so the inconsistency stays visible. Treat the prose as the actual prediction and the numeric mismatch as a lapse in this reviewer's freeze discipline. It changes no finding, because every oracle verdict derives from `commission_requirement`, which was and remains `REJECT`.

## Standing

No shared code was modified. `check_path_scope.py`, both existing path-scope test files and `po03-contracts.yml` are byte-identical at the controller head named in the immutable input, at the dispatch base and at the controller tip observed during admission. Candidate remediations are described in `findings.json` and deliberately not applied; they belong to the owner of the shared guard, and applying them here would put a reviewer's fix beyond independent review.

This attempt makes no completion or acceptance claim. Independent acceptance is `NOT_YET`.
