# Reverting the applied Cursor configuration

Lane `OE-W2-CURSOR-CONFIG-APPLY`, commission `COM-CUR-ENV-01-20260822-v001`.

**Revert SHA: `3f3ee110cf9b769e60c664f758c437dcc582afd3`**

That is the tip of `cursor/operating-environment-return-20260822-v001` at the
moment this lane branched, and it is `HEAD` immediately before the apply. At
that commit the repository contains exactly one file under `.cursor/`:

```
100644 blob 7d2c912bd58fbf81346ddbb1bb70a13b60b1838a     135	.cursor/environment.json
sha256 af09d9f4d242d95e7f8701a817218178346b2ead32cbe085059d28e8fc85b2d6
```

and **no `.gitignore` and no `.cursorignore` at all**. That second fact is what
breaks the revert command `APPLY.md` documents, so read the next section before
using it.

## The documented revert does not work

`APPLY.md` says:

```bash
git checkout <SHA-noted-in-step-1> -- .cursor .gitignore
```

Run against the applied tree it fails, and it fails in the worst possible way:

```
$ git checkout 3f3ee110cf9b769e60c664f758c437dcc582afd3 -- .cursor .gitignore
error: pathspec '.gitignore' did not match any file(s) known to git
exit=1
RESULT: .cursor still has 15 files (base has 1); .gitignore still present: yes
```

Two separate defects, both `DIRECTLY_REPRODUCED`:

1. **`.gitignore` does not exist at the revert SHA.** The apply step is what
   creates it. A pathspec naming a path absent from the target tree is an
   error, and `git checkout` with a pathspec is atomic — it aborts before
   touching anything. So the command does not partially revert. It reverts
   **nothing**, including `.cursor`, while reporting a message about
   `.gitignore` that gives no hint the rest was skipped too.

2. **Even with a valid pathspec it would be incomplete.** `git checkout <SHA>
   -- .cursor` restores only the paths present in that tree. The twelve files
   the apply added are not in it, so they would survive the revert and the
   working tree would end up in a state that never existed.

There is a third defect in the optional backup beside it:

```bash
mkdir -p .cursor-backup-$(date -u +%Y%m%dT%H%M%SZ)
cp -a .cursor/. ".cursor-backup-$(date -u +%Y%m%dT%H%M%SZ)/" 2>/dev/null || true
```

`date` is called twice. If the two calls straddle a second boundary the copy
target does not exist, `cp` fails, and the failure is swallowed by
`2>/dev/null || true` — leaving an empty directory that looks like a backup. A
backup that is silently empty is worse than no backup, because it will be
trusted. This lane did not rely on it; the git SHA above is an exact and
sufficient record of what was replaced.

## The revert that does work

Run from the repository root, on the branch carrying the apply.

```bash
git rm -r -q --cached --ignore-unmatch .cursor .gitignore .cursorignore
rm -rf .cursor .gitignore .cursorignore
git checkout 3f3ee110cf9b769e60c664f758c437dcc582afd3 -- .cursor
```

Line by line, because each one is load-bearing:

- `git rm --cached` drops the added paths from the **index**. Without it the
  index keeps entries for the twelve added files and the next commit
  reintroduces them. `--ignore-unmatch` makes it safe when a path is already
  absent, which is what lets the same command handle `.cursorignore`, a file
  this lane decided not to create.
- `rm -rf` clears the **working tree**, which is what removes the added files.
  The `git checkout` on its own cannot, because they are not in the target
  tree.
- `git checkout <SHA> -- .cursor` restores the one file that does exist at
  base, into both the index and the working tree.

### Verify it, do not assume it

```bash
git diff --cached --name-status 3f3ee110cf9b769e60c664f758c437dcc582afd3 -- .cursor .gitignore .cursorignore
git diff        --name-status 3f3ee110cf9b769e60c664f758c437dcc582afd3 -- .cursor .gitignore .cursorignore
sha256sum .cursor/environment.json
```

Both diffs must print nothing, and the hash must be
`af09d9f4d242d95e7f8701a817218178346b2ead32cbe085059d28e8fc85b2d6`.

This procedure was executed end to end in a disposable worktree at the applied
commit before being written down. Observed result:

```
  .cursor file count : 1   (base: 1)
  .gitignore present : no   (base: no)
  environment.json   : af09d9f4d242d95e7f8701a817218178346b2ead32cbe085059d28e8fc85b2d6
  base was           : af09d9f4d242d95e7f8701a817218178346b2ead32cbe085059d28e8fc85b2d6
  index  vs base diff: ''  (empty == identical)
  worktree vs base   : ''  (empty == identical)
```

Full transcript, including the failing documented command run against the same
tree: `receipts/so02/2026-08-22/oe-w2-cursor-config/raw/revert-test.txt`.

## Discarding the branch instead

If the intent is to abandon the work rather than restore paths within it, the
branch simply is not integrated. Nothing on `cursor/oe-w2-cursor-config-696d`
reaches any other branch until someone merges it, and this lane opened no pull
request.

Do not reach for `git reset --hard`. It is refused by `write-scope.json` rule
`HISTORY-REWRITE`, and the reason is the one that matters here: it destroys the
immutable-SHA custody the receipts depend on.

## What revert does and does not reach

Rules, skills and hook scripts are read from the working tree, so reverting
them is complete and immediate.

`environment.json` is different, and in this estate more different than
`APPLY.md` assumes. `APPLY.md` warns that environment changes affect newly
started agents, so a running agent keeps what it started with. True, but it is
not the operative constraint here. This environment is **db-managed**:
`environment-info` reports `environmentJsonPath: null` and `source: Team`, and
`trigger-environment-build` accepted an `environmentJson` override, which its
own contract says is rejected for repo-file managed environments. So the
repository file is not this environment's configuration source, and reverting
it changes nothing about what agents run — just as applying it changed nothing.
Both the apply and its revert are statements about the file, not about the
running environment, until the environment record itself is changed. That is a
founder action and it is specified in `W2-FOUNDER-ACTIONS-20260822-v001.md`.

The draft build produced by this lane,
`bld-20260822-f72bf7be-cef7-425f-bc38-e86ae43d5e47`, needs no revert. Its log
records `Warming skipped (draft)`, it was built from a non-default ref and is
therefore not promotable, and no snapshot was proposed or taken.
