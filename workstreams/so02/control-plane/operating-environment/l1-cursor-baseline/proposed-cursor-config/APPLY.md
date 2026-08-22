# Applying the staged Cursor configuration

Nothing in this directory is active. This is a staged proposal produced by lane
`OE-L1-CURSOR-BASELINE`. Applying it changes how every agent on this repository
behaves, so it is written to be reviewed and decided, not merged by default.

## Why the directory is called `dot-cursor/` and not `.cursor/`

Cursor discovers rules, skills and hooks by walking the repository for
`.cursor/` directories. Staging these files under a literal `.cursor/` path —
even nested deep inside a lane namespace — risks Cursor loading them
immediately, which would bind enforcement architecture across the estate
without a decision. That is the exact failure mode this lane was told to avoid.

`dot-cursor/` is inert. The mapping is one-for-one:

```
proposed-cursor-config/dot-cursor/<path>   →   <repository-root>/.cursor/<path>
```

## What applying it would change

| Target path | Effect | Blast radius |
|---|---|---|
| `.cursor/environment.json` | Replaces a 135-byte file that has no observable effect with one that adds `start` and `terminals`. | Every future cloud agent on this repository. Not the currently running one. |
| `.cursor/install.sh` | New. Runs during environment Builds. | Build pods only. |
| `.cursor/start.sh` | New. Runs at the start of every agent run, including runs booting from a stale Build. | Every future agent run. |
| `.cursor/terminals/validators-watch.sh` | New. A named tmux terminal polling currentness every 30s. | Every future agent run. |
| `.cursor/hooks.json` | New. Registers four project hooks. | **Every agent turn on this repository, including this estate's other lanes.** |
| `.cursor/hooks/guard_write_scope.py` | New. Refuses protected-branch writes, PR writes, history rewrites, and commits over a failing currentness check. | Every shell command matching `git` or `gh `. |
| `.cursor/hooks/gate_claim_state.py` | New. Enqueues one follow-up turn when a terminal claim lacks its evidence. | Every turn that ends with `status: completed`. |
| `.cursor/hooks/ledger_subagent.py` | New. Append-only local ledger of subagent start/stop. | Observation only; writes to `.cursor/.run/`. |
| `.cursor/write-scope.json` | New. The single declarative source for protected branches and paths. | Read by the guard. Editing it is the only way to change what is refused. |
| `.cursor/rules/00-claim-states.mdc` | New. `alwaysApply: true`. | Prepended to every agent turn's context. |
| `.cursor/rules/10-currentness-and-write-scope.mdc` | New. `alwaysApply: true`. | Prepended to every agent turn's context. |
| `.cursor/skills/evidence-receipts/SKILL.md` | New. Scoped by `paths` to `receipts/**`, `workstreams/**`, `state/**`. | Surfaced only when an agent touches those paths. |
| `.cursor/mcp.json` | **DO NOT COPY.** | — |

`.cursor/mcp.json` here is a decision record, not an apply-ready file. Its
`mcpServers` object is deliberately empty and it carries `_comment` keys that a
strict parser may reject. Read it, decide, then write a real one. Copying it
into place would achieve nothing and might break MCP loading.

## Apply

Run from the repository root, on a branch that is **not** protected.

```bash
# 1. Record what is being replaced, so the revert is exact rather than remembered.
mkdir -p .cursor-backup-$(date -u +%Y%m%dT%H%M%SZ)
cp -a .cursor/. ".cursor-backup-$(date -u +%Y%m%dT%H%M%SZ)/" 2>/dev/null || true
git rev-parse HEAD   # note this SHA; it is the revert target

# 2. Copy everything except mcp.json.
SRC=workstreams/so02/control-plane/operating-environment/l1-cursor-baseline/proposed-cursor-config/dot-cursor
mkdir -p .cursor/hooks .cursor/rules .cursor/skills .cursor/terminals
cp "$SRC/environment.json" "$SRC/hooks.json" "$SRC/write-scope.json" .cursor/
cp "$SRC/install.sh" "$SRC/start.sh" .cursor/
cp "$SRC/terminals/validators-watch.sh" .cursor/terminals/
cp "$SRC/hooks/"*.py .cursor/hooks/
cp -r "$SRC/rules/." .cursor/rules/
cp -r "$SRC/skills/." .cursor/skills/
chmod +x .cursor/install.sh .cursor/start.sh .cursor/terminals/validators-watch.sh

# 3. Do not let the per-pod scratch directory enter git.
grep -qxF '.cursor/.run/' .gitignore 2>/dev/null || echo '.cursor/.run/' >> .gitignore
```

### Verify before committing

```bash
# Schema — the live schema sets unevaluatedProperties:false, so one stray field
# invalidates the whole file. Validate against the live schema, never against a
# remembered field list.
curl -sL https://cursor.com/schemas/environment.schema.json -o /tmp/env.schema.json
python3 - <<'PY'
import json; from jsonschema import Draft201909Validator
errs=list(Draft201909Validator(json.load(open('/tmp/env.schema.json'))).iter_errors(
    json.load(open('.cursor/environment.json'))))
print('environment.json', 'VALID' if not errs else [e.message for e in errs])
PY

# Syntax
python3 -m py_compile .cursor/hooks/*.py
bash -n .cursor/install.sh .cursor/start.sh .cursor/terminals/validators-watch.sh
python3 -c "import json;[json.load(open(f)) for f in ['.cursor/hooks.json','.cursor/write-scope.json']];print('json ok')"

# The guard must refuse a protected push and allow a lane push.
echo '{"command":"git push origin main","cwd":"'$PWD'"}' \
  | python3 .cursor/hooks/guard_write_scope.py | python3 -c 'import json,sys;print("main  ->",json.load(sys.stdin)["permission"])'
echo '{"command":"git status","cwd":"'$PWD'"}' \
  | python3 .cursor/hooks/guard_write_scope.py | python3 -c 'import json,sys;print("status->",json.load(sys.stdin)["permission"])'
```

Expected: `main -> deny`, `status-> allow`.

### The one thing that is not verifiable before applying

Whether Cursor actually loads and fires `.cursor/hooks.json` in this runtime is
`DOCUMENTED`, not reproduced. Cursor's documentation states that cloud agents
run project hooks and that exit code 2 blocks the action; no hook was installed
or fired during the lane that produced this. Every script here has been
executed standalone against synthetic input and behaves correctly — that is
reproduced — but standalone correctness and hook-firing are different claims.

Prove the second one immediately after applying, on a throwaway branch:

```bash
git checkout -b throwaway/hook-firing-probe
git push origin main   # must be refused BY THE HOOK, not by the guard script run by hand
```

If it is not refused, the hooks are not loading. Stop and diagnose before
relying on any of this. Do not assume the guard is protecting anything until
you have seen it refuse something you actually typed.

## Revert

```bash
git checkout <SHA-noted-in-step-1> -- .cursor .gitignore
# or, if a backup directory was made:
rm -rf .cursor && mv .cursor-backup-<timestamp> .cursor
```

Reverting is complete and immediate for rules, skills and hooks — they are read
from the working tree on each turn. It is **not** immediate for
`environment.json`: environment changes affect newly started agents, so an
already-running agent keeps the configuration it started with, and a Build that
already ran keeps its recorded state until the next Build.

## Risks worth stating plainly

1. **The guard runs on every `git` and `gh ` command in every lane.** A regex
   that is too broad blocks legitimate work. The guard fails open on any
   unexpected condition — malformed input, missing config, a crash — precisely
   so a bug degrades to no protection rather than to a wedged estate. That is a
   deliberate trade: it means a silently broken guard protects nothing, so the
   firing probe above is not optional.

2. **The stop gate can enqueue an extra turn.** `loop_limit: 3` bounds it. It
   fires on textual patterns in changed files, so it will occasionally fire on
   an honest artifact that merely quotes the word `COMPLETED`. The cost is one
   follow-up turn; the alternative is the failure this estate keeps having.

3. **`alwaysApply: true` rules consume context on every turn.** Both rule files
   are deliberately short. If they grow, move the detail into a `paths`-scoped
   skill, which is what the `evidence-receipts` skill is for.

4. **`start.sh` failing prevents a successful agent start.** Every step in it
   is individually guarded and the currentness check is explicitly
   non-fatal — a currentness break must block promotion, not the running
   programme.

5. **This binds nothing about tools, models or architecture.** No model is
   selected, no MCP server is enabled, no external service is contacted, and no
   browser stack is installed. The halted SO-02 browser batch is untouched.
