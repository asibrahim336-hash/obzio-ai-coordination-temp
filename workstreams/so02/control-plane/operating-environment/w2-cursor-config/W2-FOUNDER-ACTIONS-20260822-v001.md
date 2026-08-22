# Actions that genuinely require the founder

Lane `OE-W2-CURSOR-CONFIG-APPLY`, commission `COM-CUR-ENV-01-20260822-v001`.

Per the standing rule in `FOUNDER-AUTHORITY-20260822T2225Z.json` — *"Where a
platform genuinely requires the founder's personal action, or his action is
materially more efficient for the intended purpose, return the exact action and
continue everything else without waiting"* — this lane did not wait on any of
these and did not ask for approval of anything the authority already covers.
Everything else in the lane completed.

Three actions. Each states what to do, why an agent cannot do it, what it
unblocks, and how to verify it worked without anyone reading a secret aloud.

---

## FA-W2-ENV-01 — Make the applied `environment.json` actually govern this estate

**Priority: first. It is the only one of the three that is currently blocking a
proven-working improvement from having any effect.**

### The finding this rests on

`DIRECTLY_REPRODUCED`. This environment is **db-managed, not repo-file
managed**, so `.cursor/environment.json` in the repository is not its
configuration source:

- `environment-info` returns `environmentJsonPath: null`, `source: Team`,
  `environmentJson: null`, `name: null`, with the note *"environment.json was
  found but contained no recognized configuration fields."*
- `trigger-environment-build`'s own contract states the `environmentJson`
  override *"is not supported for repo-file managed environments (see
  environmentJsonPath in environment-info) and is rejected for them"*. This
  environment **accepted** the override and built successfully.

Both together settle the question L1 recorded as unverifiable from inside the
pod. The saved Team record is the source; the repository file is not read as
one.

So the applied file is correct, schema-valid against the live schema, and
**inert**. Applying it changed no behaviour, and reverting it would change none
either.

### What the draft build already proved

Draft build `bld-20260822-f72bf7be-cef7-425f-bc38-e86ae43d5e47` (`SUCCEEDED`,
47 seconds, `source AGENT`, `triggerType MANUAL`) ran with
`install: bash .cursor/install.sh` supplied as an override against this branch,
and its log shows the script executing end to end:

```
>>> obzio install: begin
Python 3.12.3
git version 2.43.0
OPERATOR TAXONOMY CHECK: PASS
>>> obzio install: complete
[INSTALL] Exit code: 0
```

The content works. Only the wiring is missing.

### The action

Open the environment editor:

`https://cursor.com/dashboard/cloud-agents/environments/e/69dbfc52-9df5-11f1-a7d1-d6b4613131ce`

Either of two routes. **Route A is recommended** because it keeps the
configuration reviewable in git rather than in a dashboard field:

**Route A — make the repository file authoritative.** Point the environment at
the repository's `environment.json` so `environmentJsonPath` resolves instead
of being `null`. After that, the file this lane applied becomes the live
configuration and every future change to it is a reviewed commit.

**Route B — paste the configuration into the saved record.** Set install, start
and terminals to match `.cursor/environment.json` on this branch:

```json
{
  "name": "Obzio AI Coordination",
  "install": "bash .cursor/install.sh",
  "start": "bash .cursor/start.sh",
  "disableAllMcpServers": false,
  "terminals": [
    {
      "name": "control-plane-validators",
      "command": "bash .cursor/terminals/validators-watch.sh",
      "description": "Re-runs the operator taxonomy currentness check and the control-plane validators whenever tracked state changes, so a currentness break is visible in a terminal the agent can read instead of being discovered by CI after the commit exists."
    }
  ]
}
```

Route B splits the configuration across two places, which is this estate's F1
failure shape applied to environment config. If it is chosen, record that the
dashboard record is canonical and the repository file is a copy.

### Why an agent cannot do it

The tool that would write it, `propose-environment-json`, still requires the
user to review and save, and this lane is explicitly forbidden from calling it
or `take-environment-snapshot`. Changing what agents boot from is out of scope
for a lane by design.

### Verify it worked

Any agent, on its next run:

```bash
# start actually ran
ls /tmp/cursor/start-user/            # exists, rather than absent
cat .cursor/.run/runtime-binding.json # written by start.sh at boot
cat .cursor/.run/secret-names.json    # names only, no values

# the environment record now carries the config
# cursor-cloud environment-info -> environmentJson non-null, name non-null
```

The pre-activation state is fully characterised above, so a post-activation
failure will be unambiguous rather than mysterious.

### Residual, stated honestly

`terminals` has never been executed anywhere. It could not be: the draft-build
override schema accepts only `install`, `start` and `snapshot`, and rejected
`name` and `terminals` with `unrecognized_keys`. Whether the validators
terminal works is unproven, and the first run after this action is what proves
it.

---

## FA-W2-MCP-01 — Authenticate the five MCP servers that are connected but unusable

### The finding

`DIRECTLY_REPRODUCED`. Of eight MCP namespaces exposed to this run:

| Namespace | Status |
|---|---|
| `cursor-cloud` | ready (Cursor built-in) |
| `cursor-subscriptions` | ready (Cursor built-in) |
| `Cloudflare-docs` | ready |
| `Supabase` | **needsAuth** |
| `Vercel` | **needsAuth** |
| `Cloudflare-bindings` | **needsAuth** |
| `Cloudflare-builds` | **needsAuth** |
| `Cloudflare-observability` | **needsAuth** |

Each returns *"This MCP server requires authentication before its tools can be
used."* Five of eight namespaces are configured and inert.

The authority in force is explicit that this is in scope: *"MCP integrations
left unauthenticated and treated as out of scope -> IN SCOPE. Maximum useful
authorised access is the objective. Unauthenticated integrations are a blocker
to remove, not a boundary to respect."*

### The action

Complete the OAuth flow for each server in the Cursor desktop IDE, which is
where MCP authentication is performed. Cloud agent VMs have no access to
user-level configuration, so this cannot be initiated from inside a run.

Suggested order, by what it unblocks rather than by convenience:

1. **Supabase** — see FA-W2-MCP-02 below; it is the only route this lane found
   to the Cursor API key the founder says already exists.
2. **Vercel**, then the three Cloudflare servers — deployment and observability
   surfaces. Nothing in this commission is currently blocked on them, so they
   are activation, not remediation.

### Verify it worked

Any agent: query the namespace status. `needsAuth` becomes `ready` and the
tool list is non-empty. No secret is read or printed at any point.

### Note on repository policy

`.cursor/environment.json` now carries `"disableAllMcpServers": false`, and no
`mcpServerAllowlist` is set. So authenticating these servers makes them
available to agents in this environment immediately, with no further
repository change. That was the deliberate reason for choosing the permissive
value; the reasoning is in `W2-MCP-POLICY-DECISION-20260822-v001.json`.

---

## FA-W2-MCP-02 — Bridge the existing Cursor API key into the Cloud Agent secret namespace

### The finding

`DIRECTLY_REPRODUCED`, by name census only — no value was read, printed or
stored:

```
CLOUD_AGENT_ALL_SECRET_NAMES = AUREA_E2E_SUPABASE_PUBLISHABLE_KEY,
                               AUREA_E2E_SUPABASE_URL,
                               AUREA_E2E_USER_EMAIL,
                               AUREA_E2E_USER_PASSWORD
CURSOR_API_KEY present by name : NO
CURSOR_API_KEY set             : UNSET
```

This reproduces L1's census independently and unchanged.

`FOUNDER-AUTHORITY-20260822T2225Z.json` records that a Cursor API key **already
exists in Supabase Edge Secrets**, supersedes the earlier request to issue a new
one, and states that requesting a duplicate is prohibited as wasteful and as a
credential-proliferation risk.

This lane could not verify that key: the `Supabase` MCP namespace is
`needsAuth`, and no other route to Supabase Edge Secrets exists from inside a
pod. So the key is not absent — it is **unreachable from here**, which is a
different problem with a different fix.

### The action

Do **not** issue a new key. Instead, after FA-W2-MCP-01 authenticates Supabase,
retrieve the existing key from Supabase Edge Secrets and store it as a
**repository-scoped** secret named exactly `CURSOR_API_KEY` in
Cursor Dashboard -> Cloud Agents -> Secrets.

If it turns out the stored key has been revoked or was never issued, that is a
new fact and supersedes this action — say so rather than quietly issuing a
replacement.

### Verify it worked

Without ever reading the value:

```bash
echo "$CLOUD_AGENT_ALL_SECRET_NAMES" | tr ',' '\n' | grep -x CURSOR_API_KEY
```

Then, from an agent, authenticate against `/v1/me` and read `/v1/models`. The
pre-activation state is fully characterised — 401 on every route, absent by
name census — so a post-activation 401 means the key is wrong rather than
missing.

### What it unblocks

G5, which L1 identifies as the single strongest lever against the
founder-as-relay failure: `POST /v1/agents` and `POST /v1/agents/{id}/runs`
with an explicit per-run `model.id` are what let one orchestrator create and
steer other runs, including selecting a distinct-family independent acceptor,
without a human pressing a button per lane.

---

## Not a founder action, but it needs a dispatcher

Whether project hooks fire when `.cursor/hooks.json` is present at the project
root is still open, and this lane deliberately left it open — settling it needs
a write into the shared `/workspace` checkout, which would alter every
concurrently running sibling lane's turns in the same VM.

It is settled by dispatching one cloud agent run with this branch checked out
as its project root, then running:

```bash
python3 .cursor/hooks/probe_hook_firing.py --arm
# run the three inert commands it prints, through the agent's shell tool
python3 .cursor/hooks/probe_hook_firing.py --check
```

Exit 0 means hooks fire and the guard's refusals are real. Exit 1 means they do
not, and nothing in `write-scope.json` should be described as enforced.

Until that returns exit 0, treat every boundary in `write-scope.json` as
documentation. See `W2-FINDINGS-20260822-v001.md` for why this matters more
than it looks: the per-lane worktree that G0 requires is the thing that puts
the hooks outside the directory Cursor reads them from.
