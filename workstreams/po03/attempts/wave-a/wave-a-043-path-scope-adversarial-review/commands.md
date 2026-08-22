# Exact commands

Every command below was run on the Cursor cloud VM with `git version 2.43.0` and CPython `3.12.3`.
`SLOT` abbreviates `workstreams/po03/attempts/wave-a/wave-a-043-path-scope-adversarial-review`.
`CLONE` abbreviates `/home/ubuntu/po03-wave-a-043-path-scope-adversarial-review-isolated`.

## 1. Admission, read-only

Run from the pre-existing checkout at `/workspace` without mutating it.

```bash
git fetch origin po03/repository-engineering-portable-runtime-20260822-v001
git show origin/po03/repository-engineering-portable-runtime-20260822-v001:workstreams/po03/control/events/wave-a-043-path-scope-adversarial-review/000003-running.json
git show origin/po03/repository-engineering-portable-runtime-20260822-v001:workstreams/po03/control/tasks/wave-a-043-path-scope-adversarial-review/input.json
git show origin/po03/repository-engineering-portable-runtime-20260822-v001:workstreams/po03/control/tasks/wave-a-043-path-scope-adversarial-review/acceptance.json
```

## 2. Capsule hash verification from immutable Git bytes

```bash
git cat-file blob 1bb843b2a81fd8d73617caf2f1db81909266bb6e:workstreams/po03/COMMISSION.md | sha256sum
git cat-file blob 1bb843b2a81fd8d73617caf2f1db81909266bb6e:workstreams/po03/contracts/transactional-result.schema.json | sha256sum
git cat-file blob 06210fb82ba2b0b9e30b2a9c752ca781c0d2d466:workstreams/po03/contracts/transactional-result.schema.json | sha256sum
git cat-file blob 06210fb82ba2b0b9e30b2a9c752ca781c0d2d466:workstreams/po03/tools/check_path_scope.py | sha256sum
git diff 1bb843b2a81fd8d73617caf2f1db81909266bb6e 06210fb82ba2b0b9e30b2a9c752ca781c0d2d466 \
  -- workstreams/po03/contracts/transactional-result.schema.json
git diff --name-status 06210fb82ba2b0b9e30b2a9c752ca781c0d2d466 \
  origin/po03/repository-engineering-portable-runtime-20260822-v001 \
  -- workstreams/po03/tools/check_path_scope.py workstreams/po03/tests/ \
     .github/workflows/po03-contracts.yml workstreams/po03/contracts/
```

## 3. Isolation: fresh clone into the exact absent path

```bash
test ! -e "$CLONE"
git clone --no-hardlinks --branch po03/repository-engineering-portable-runtime-20260822-v001 "$REMOTE" "$CLONE"
cd "$CLONE"
git rev-parse --absolute-git-dir
git rev-parse --path-format=absolute --git-common-dir
cat .git/objects/info/alternates   # absent
git worktree list
git ls-remote --heads origin po03/wave-a-043-path-scope-adversarial-review   # empty, fail closed if not
git checkout -b po03/wave-a-043-path-scope-adversarial-review 06210fb82ba2b0b9e30b2a9c752ca781c0d2d466
```

## 4. Freeze the hidden cases

```bash
python3 -I $SLOT/tests/generate_cases.py
sha256sum $SLOT/hidden-cases.json
# b2180bb19422b9d2272ef0dacb77e263766a437b0f2fb36005cb493acb7f143e
```

## 5. Commit and push the implementation before running the evaluation

```bash
git add $SLOT
git diff --cached --name-only        # owned slot only
git commit -m "po03 wave-a-043: freeze hidden path-scope adversarial cases and harness"
python3 -I workstreams/po03/tools/check_path_scope.py
python3 scripts/check_operator_taxonomy.py
git push -u origin po03/wave-a-043-path-scope-adversarial-review
# implementation commit 4097f24b0935dfc482d29bae7e1ce169d5f17340
```

## 6. Evaluate the guard

```bash
python3 -I $SLOT/tests/generate_cases.py --check          # proves the frozen file was not hand-edited
python3 -I $SLOT/tests/harness.py --out $SLOT/observed-results.json
python3 -I $SLOT/tests/harness.py --out /tmp/observed-determinism.json   # repeat-run determinism
python3 -I -m unittest discover -s $SLOT/tests -p 'test_*.py' -v
python3 -I -m unittest discover -s workstreams/po03/tests -p 'test_*.py'  # shared suite, unmodified
```

Recorded outcomes: `generate_cases.py --check` exit 0; both harness runs exit 0 and produce identical
`summary`, `path_results` and `git_results`; 9 adversarial tests pass; the 76 shared tests pass. The
full transcript is `run-transcript.txt`.

## 7. Commit and push the evidence

```bash
git add $SLOT
git commit -m "po03 wave-a-043: record path-scope adversarial evaluation evidence"
git push -u origin po03/wave-a-043-path-scope-adversarial-review
```

## 8. Final verification from a separate fresh read-only clone

```bash
git clone --no-hardlinks --branch po03/wave-a-043-path-scope-adversarial-review "$REMOTE" \
  /home/ubuntu/po03-043-readback-final
cd /home/ubuntu/po03-043-readback-final
git rev-parse HEAD
git ls-remote origin po03/wave-a-043-path-scope-adversarial-review     # remote tip equality
git diff --name-only 06210fb82ba2b0b9e30b2a9c752ca781c0d2d466...HEAD  # base..result path confinement
python3 -I workstreams/po03/tools/check_path_scope.py --base 06210fb82ba2b0b9e30b2a9c752ca781c0d2d466 --head HEAD
python3 -I $SLOT/tests/readback.py
```

## Reproducing this review from a clean clone

```bash
git clone --branch po03/wave-a-043-path-scope-adversarial-review <repository> po03-043
cd po03-043
python3 -I workstreams/po03/attempts/wave-a/wave-a-043-path-scope-adversarial-review/tests/generate_cases.py --check
python3 -I -m unittest discover \
  -s workstreams/po03/attempts/wave-a/wave-a-043-path-scope-adversarial-review/tests -p 'test_*.py' -v
```

No network access, provider memory, `/tmp` state or uncommitted file is required. The harness creates
its own throwaway repositories under a fresh temporary directory and removes them.
