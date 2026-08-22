# What this Cursor account and runtime can actually do

Lane `OE-L1-CURSOR-BASELINE`, commission `COM-CUR-ENV-01-20260822-v001`.
Branch `cursor/oe-l1-cursor-baseline-696d`, cut from the immutable base
`fe0a595206e5986de7eaac6cabc619215a1eb81b`.
Terminal state: **`READY_TO_COMMIT`**. Not completed, not accepted. This lane
produced artifacts and stopped at its own boundary; only the root controller
reconciles and only an independent lane accepts.

Everything below was observed inside a single turn on one VM between
`2026-08-22T20:12Z` and `20:45Z`, turn id `run-62aeb48c-5df0-4aaf-9b1b-73d20b409abf`,
turn model `claude-opus-5-thinking-max-fast`.

This document is the readable layer. The evidence lives in three registers
beside it and in the raw command outputs under
`receipts/so02/2026-08-22/oe-l1-cursor-baseline/raw/`:

| File | What it holds |
|---|---|
| `CURSOR-OPERATING-BASELINE-REGISTER.json` | 18 capability records, each labelled and pointed at its raw evidence |
| `GAP-ANALYSIS-AND-IMPROVEMENT-SPEC.json` | 10 prioritised gaps, each with the exact change, the risk and who can make it |
| `CONTROL-SURFACE-ACTIVATION-PROGRAMME.json` | 4 founder-facing actions against the ten-point schema |
| `proposed-cursor-config/` | Ready-to-apply files, inert until applied, with `APPLY.md` |

It extends the CUR-01 baseline rather than repeating it. `CAP-CURSOR-ORCHESTRATOR-MODEL`,
`CAP-EGRESS`, `CAP-ENVIRONMENT-BUILD`, `CAP-MODEL-FAMILY-DIVERSITY-IN-ACCOUNT` and
the R1/R2 route qualifications stand as recorded and are not re-derived.

---

## The eight findings that should change a decision

Ranked by how much the decision changes if you are wrong about them.

### 1. Lane isolation is a per-lane habit that nothing enforces, and its failure is silent and exit-code-zero

`DIRECTLY_REPRODUCED`, and reproduced the hard way: this lane suffered it.

All five lanes of this group are subagents inside **one VM sharing one git
repository**. Three lanes and the root controller each took a `git worktree`
under `/tmp` and were isolated. This lane and L5 both worked in the shared
`/workspace` checkout, whose HEAD was detached at `20:20:34Z`. Three commits
from two lanes then interleaved on that one detached HEAD, so this lane's
second commit carried an L5 commit as an ancestor.

Because a commit on a detached HEAD advances no branch, both lanes' branch refs
stayed at the immutable base. `git push -u origin cursor/oe-l1-cursor-baseline-696d`
pushed that stale ref, printed **`Everything up-to-date`, and exited 0**.

That last sentence is the finding. In this configuration a zero exit from
`git push` is not evidence that anything was published. A lane trusting it
would report `READY_TO_COMMIT` while the reconciling controller reads an empty
branch — a declared denominator diverging from the actual one, produced by
nothing more exotic than two agents sharing a checkout. Commit authorship does
not help: every commit from every lane is authored `Cursor Agent`, so git
metadata attributes nothing to a lane.

Recovered inside the same run with `git worktree add` plus cherry-picking only
this lane's commits, then verified: two commits above base, L5's commit not an
ancestor, zero changed paths outside this lane's two namespaces. Raw evidence:
`raw/shared-worktree-collision.txt`.

The fix is at dispatch, not in the lane: `git worktree add /tmp/<lane> -b <lane-branch> <base-sha>`.
The guard added in response makes the failure loud; only the worktree prevents it.

### 2. Hooks are the only enforcement surface in this runtime, and the repository has none

`DIRECTLY_REPRODUCED` that they are absent; `DOCUMENTED` that they would fire.

There is no `.cursor/hooks.json` anywhere in the repository. `AGENTS.md`
instruction 10 requires `python scripts/check_operator_taxonomy.py` before
commit and **nothing runs it** — the only enforcement is a CI workflow that
runs after the commit already exists.

Meanwhile `core.hooksPath` is already redirected to Cursor's own dispatcher at
`/home/ubuntu/.cursor/agent-hooks/L3dvcmtzcGFjZQ`, and that dispatcher runs a
repository-side hook of the same name if one exists. The insertion point is
built and unused.

This matters more than any other gap because it is the difference between a
rule and a mechanism. `AGENTS.md`, rules and skills are all advice a model may
or may not follow. A `beforeShellExecution` hook returning `deny` is not
advice. Every recurring failure in the diagnosis is currently a policy written
as prose and enforced by nothing.

A caution that belongs next to the finding: the active **team** hooks bundle
registers thirteen hooks, four of which (`beforeMCPExecution`,
`afterMCPExecution`, `beforeTabFileRead`, `afterTabFileEdit`) the documentation
says do not run in cloud agents. Four of thirteen team hooks cannot fire here.

### 3. `.cursor/environment.json` exists, is schema-valid, and has no effect

`DIRECTLY_REPRODUCED`.

The repository file is 135 bytes and sets `name` and `install`. Both are
declared properties of the live schema and the file validates against
`https://cursor.com/schemas/environment.schema.json`.

`environment-info` nevertheless reports
`environmentJson: null`, `name: null`, and the note *"environment.json was found
but contained no recognized configuration fields."* The discriminator is
`name`: the repository sets it, the effective record returns null. The
repository file's fields did not populate the environment record.

The consequences are all observable, not inferred. The install phase generated
a wrapper at `/tmp/cursor/async-install/install-user.sh` that only echoes a skip
message — the log reads *"Started from stale build … skipping install script"*.
`/tmp/cursor/start-user/` does not exist, so no start script ran. The terminals
directory exists and is empty. The boot binding reports `warmFork: cold`. Of
twelve environment builds, one succeeded and eleven were skipped, and **zero**
were manually or agent-requested.

So this estate pays a cold start on every agent and gets no benefit from the
build system. Two of the three fixes need no founder action at all, because
`start` and `terminals` run per agent run and do not depend on a successful
build.

### 4. Cursor's own Agent API is live, complete, and blocked only by a missing key

`DIRECTLY_REPRODUCED` for the surface map; `DOCUMENTED` for what the endpoints do.

Unauthenticated probing, using the 401-versus-404 distinction as the
discriminator (a routing 404 returns `{"message":"Route GET:<path> not found"}`;
an existing but gated route returns HTTP 401 `{"code":"error","message":"Invalid User API Key"}`),
shows both `v0` and `v1` live. `/v1/agents`, `/v1/agents/{id}/runs`, `/v1/models`,
`/v1/repositories` and `/v1/me` all exist and return 401.

`CURSOR_API_KEY` is absent by name census. Egress is unrestricted. This route
is **credential-blocked, not unsupported** — the distinction that decides
whether the answer is a purchase or a dashboard visit.

This is the missing half of the already-qualified R2 route. R2 proved
observation and artifact retrieval over MCP. `POST /v1/agents` and
`POST /v1/agents/{id}/runs` — with an explicit `model.id` per run — are what
would let one orchestrator create and steer other runs. That is exactly what a
five-lane group with a distinct-family independent acceptor needs, and exactly
what currently requires a human to press a button. **This is the single
strongest lever against the founder-as-relay failure.**

### 5. There are two GitHub credentials here, not one, and conflating them gives the wrong answer

`DIRECTLY_REPRODUCED`.

The `gh` CLI holds a `ghs_`-prefixed **GitHub App installation token** — proven
by `GET /user` returning 403 *"Resource not accessible by integration"*. It
carries permissions, not OAuth scopes, and it reaches exactly one repository.
Probed endpoint by endpoint it is read-only: metadata, contents, pull requests,
Actions workflows, environments and collaborators return 200; issues, Actions
secrets and variables, branch protection, webhooks, deployments, code scanning
and Dependabot all return 403.

`git push` uses a **different** credential — an `x-access-token` injected via
six `url.<...>.insteadOf` rewrites in `~/.gitconfig` — and it carries write.
`git push --dry-run` returned `* [new branch]` and exit 0.

Two traps worth naming, because both produce confident wrong conclusions:

- `GET /repos/{r}` returns `permissions: {admin:false, push:false, …}`. That is
  the *user*-permission projection and is all-false for installation tokens
  even when the installation can write. The successful push dry-run contradicts
  it directly.
- `X-Accepted-Github-Permissions` describes what the *endpoint* accepts, not
  what the token holds. Every GET reports `=read`. The HTTP status is the only
  discriminator.

Three consequences follow. Issues are unavailable as a coordination substrate.
Actions secrets cannot be verified from inside an agent, so any activation that
depends on one must be verified through a CI job's behaviour instead. And
`administration: 403` means **no agent can read, let alone set, branch
protection** — the "never write these branches" rule cannot be enforced
server-side by anything an agent configures. It has to be enforced client-side,
which is precisely what a `beforeShellExecution` hook does.

### 6. A full container runtime is sitting here unused, and it is the best available answer to independent acceptance

`DIRECTLY_REPRODUCED`, and absent from the prior baseline entirely.

There is no `docker` CLI, which is why it was missed. But Docker Engine
29.1.4 (API 1.52) with BuildKit is running and its API answers on
`127.0.0.1:2375` **without authentication**, bound to `0.0.0.0`.

An acceptance lane can replay a producer's evidence inside a container with no
network and no inherited credentials. That is a materially stronger
independence claim than running the same replay in the producing agent's own
shell, and it costs nothing and requires no new authority.

Only read-only API endpoints were called. No container was created, pulled or run.

### 7. The browser question was previously answered wrong: the capability exists, the tool does not

`DIRECTLY_REPRODUCED`.

Google Chrome 148.0.7778.96 is installed at `/usr/local/bin/google-chrome` and
works: `--headless=new --dump-dom` returned a fully parsed DOM and exit 0.
`DISPLAY=:1` is live with an Xtigervnc server on `127.0.0.1:5901`, and noVNC
1.2.0 is serving a bridge on `0.0.0.0:26058`.

What is absent is the **agent-facing tool**. No browser, computer-control,
web-search or web-fetch tool appears in this agent's tool list or in either MCP
catalogue. Every documentation claim in this lane had to be established with
`curl` into files.

The correction matters for the halted SO-02 browser batch: the question is not
whether a browser can run here — it demonstrably can — but whether a
*controlled, tool-mediated* browser is needed and how it would be enabled. The
enabling path is not the repository file; the live schema rejects the
`chromeExecutablePath` field the bundled skill associates with computer use.

### 8. The durable store is a per-run mailbox, not cross-run continuity

`DIRECTLY_REPRODUCED`, with one bounded `HYPOTHESIS`.

`/cursor/stores` is a FUSE filesystem, not disk. The daemon is
`cursor-agent-store-fuse --backend-mode direct --bcs-endpoint https://api2.cursor.sh --self-store-id bc-c6f63d58-…`.
It is server-side state over the network, authorised by a pod grant.

Scope is **per top-level run, shared with subagents**: `/cursor/stores` holds
exactly one real directory named for the top-level run's bcId plus a `self`
symlink to it, and this lane — a subagent — resolved `self` to its parent's
bcId. Foreign stores are neither readable nor creatable; `mkdir` of another
bcId fails with *No such file or directory* rather than a permission error, so
the namespace is server-controlled.

It is genuinely bidirectional. The `inbox/` subtree contained two JSONL CI
deliveries written by the **platform**, not by any command in this VM.

Writes of every kind succeeded, including a 1 MiB binary with a stable sha256
on read-back.

Where it is good: receiving asynchronous platform deliveries, holding large or
binary intermediates that should not enter git, and passing state between a
parent and its subagents within one run. Where it must not be used: anything
that needs to outlive the run or be checked by someone else. A new run
necessarily has a new bcId and cannot address this store, and nothing in it is
visible to the founder, to CI or to any independent acceptor — which is exactly
the property CUR-01's custody ladder requires. Putting lineage or acceptance
state here would make it unreadable to every independent checker.

The `HYPOTHESIS`: it very likely survives a VM restart within the same run,
since it is server-side. Untestable here — proving it needs a second run or a
restart of the orchestrator this lane runs inside.

**Disclosed side effect:** the probe cleanup recursively cleared the store tree
and removed the two pre-existing platform CI deliveries along with the probe
files. Their contents are preserved verbatim in `raw/store-inspect.txt` and the
same CI results are durably recorded in the CUR-01 receipts bundle, so no
unique evidence was lost. Recorded here rather than omitted.

---

## Reproduced, documented, hypothesis

The three are never blended in the registers, and the split is worth reading on
its own, because it is where over-claiming would start.

**`DIRECTLY_REPRODUCED` — ran here, output recorded.** All 18 register records.
The repository configuration census. The environment record and its
discrepancy with the repository file. The build history. The team-hook
inventory and the git-hook redirection. The three bundled skills. Both MCP
servers, all 14 `cursor-cloud` tools by schema, and the read-only subset
actually called. The complete 15-leaf agent metadata tree. The store
characterisation and write probes. The GitHub permission map endpoint by
endpoint. Hardware, tmux, background execution and the port census. The Docker
engine version and image list. Chrome, Xvfb and the DOM dump. The five exact
model configurations running in this account. The `api.cursor.com` 401/404
surface map. The secret-name census. Run events and the message queue. The
currentness validator passing. The worktree collision and its recovery. And
the 69-case hook verification.

**`DOCUMENTED` — official source, URL recorded, not run here.** Hook firing
semantics and the cloud-agent hook availability matrix
(`https://cursor.com/docs/hooks.md`). The Cloud Agents API v1 endpoint list and
the OpenAPI document (`https://cursor.com/docs/cloud-agent/api/endpoints.md`,
`https://cursor.com/docs-static/cloud-agents-openapi.yaml`, 59120 bytes,
fetched during this lane). The CLI's real binary name — `agent`, not
`cursor-agent` — and its flags (`https://cursor.com/docs/cli/overview.md`). The
public model catalogue including Kimi K2.7 Code marked *"Hidden by default"*
(`https://cursor.com/docs/models-and-pricing.md`). Build and MCP transport
guidance (`https://cursor.com/docs/cloud-agent/capabilities.md`).

**`HYPOTHESIS` — inference, not evidence.** Exactly one is carried: that the
agent store survives a restart within the same run. It is labelled as such
wherever it appears and nothing is built on it.

The one place these are easy to confuse is the hooks. That the scripts behave
correctly is reproduced across 69 cases. That Cursor *fires* them here is
documented only. Those are different claims and `APPLY.md` refuses to let the
second be assumed: it specifies a firing probe that must refuse a command
someone actually typed before any of it is relied upon.

---

## What could not be verified, and exactly why

Eight items, each with the instrument that would settle it. Full text in the
register's `could_not_verify` block.

| Not verified | Why not | What would settle it |
|---|---|---|
| Whether the saved Team environment record is empty or holds config the repository file loses to | Reading the stored record needs the dashboard; `environment-info` returns only the resolved view, and the two mechanisms are indistinguishable from inside the pod | Open the environment in the dashboard and read the stored JSON |
| Whether a fixed `environment.json` would take effect | Requires `trigger-environment-build`, explicitly excluded from this lane, or starting a fresh agent, which this lane cannot do | `trigger-environment-build` with an `environmentJson` override, then `environment-build-logs`, run by a lane permitted to call it |
| Whether project hooks fire, and whether exit 2 blocks | Requires writing `.cursor/hooks.json` at the repository root — outside this lane's namespace, and doing it silently would bind enforcement architecture across the estate | Apply the staged config on a throwaway branch and run one command the guard should refuse |
| Whether the store survives across runs or a pod restart | Both need a second run or a restart of the orchestrator this lane runs inside | A second run addressing the same store id |
| The account's selectable model list, its default, and whether Kimi is unhidden | `GET /v1/models` needs the absent API key; the dashboard needs founder authentication | `GET https://api.cursor.com/v1/models` with a Cursor API key |
| Whether computer-use tools can be enabled, and where | No such setting is reachable from inside the pod, and the schema field the bundled skill associates with it is rejected by the live schema | Founder inspection of account and environment settings |
| Whether the v1 fleet and worker-token routes exist at other paths | The three paths tried returned routing 404s; enumerating further unauthenticated is guesswork, not evidence | The fetched OpenAPI document read against an authenticated key |
| Whether egress is subject to any allowlist | `environment-info` reports `restricted: false` and every host tried responded, but absence of a block across a handful of hosts is not proof of policy | The environment's egress configuration in the dashboard |

The stronger negative claim about the store **is** reproduced and should not be
softened: it is not addressable from a different run, because the mount exposes
only the `self` store id and foreign paths cannot be created.

---

## What to change

Ten gaps, prioritised, in `GAP-ANALYSIS-AND-IMPROVEMENT-SPEC.json`. Each states
the capability gained, why it matters here, the exact change, the risk, and
whether Cursor can do it in-repo or the founder must act.

Eight of ten are delegable to Cursor in-repo and need no founder action:

| | Gap | Change |
|---|---|---|
| G0 | Shared working tree defeats declared isolation | Per-lane `git worktree` at dispatch, plus the two new guard refusals |
| G1 | No project hooks — governance is unenforced prose | Apply `hooks.json`, the three hook scripts, `verify_hooks.py` and `write-scope.json` |
| G2 | No project rules — no always-applied statement of claim states | Apply the two `.mdc` rules |
| G3 | `environment.json` is inert — no `start`, no `terminals` | Apply the proposed `environment.json`, `install.sh`, `start.sh` and the validators terminal |
| G4 | No repository skills — receipts discipline re-derived each time | Apply the `evidence-receipts` skill, scoped by `paths` |
| G6 | Subagents invisible at the provider layer | Apply the subagent ledger hooks |
| G8 | Container and graphical runtimes present but unused | Use the container runtime for independent replay |
| G9 | No `.cursorignore`, no repository MCP policy statement | Decide and write both |

Two need the founder: **G5** (no Cursor API key) and **G7** (Slack/Linear event
returns, documented in the bundled `subscribe` skill but unavailable without an
account-level integration).

Everything in `proposed-cursor-config/` is staged under `dot-cursor/`, not
`.cursor/`, deliberately. Cursor discovers configuration by walking the
repository for `.cursor/` directories, so staging under a literal `.cursor/`
path — even nested inside a lane namespace — risks it loading immediately and
binding enforcement architecture across the estate without a decision.
`dot-cursor/` is inert and maps one-for-one. `APPLY.md` gives the copy
commands, the validation, the firing probe and the revert.

One entry is marked **do not copy**: `dot-cursor/mcp.json` is a decision record
with an empty `mcpServers` object and `_comment` keys a strict parser may
reject. Read it, decide, then write a real one.

---

## What the founder actually needs to do

Four actions in `CONTROL-SURFACE-ACTIVATION-PROGRAMME.json`, each against all
ten points. Summarised by decision, in sequence:

**FA-CUR-API-01 — issue a Cursor API key. Activate NOW.** The only action that
removes a founder relay step from the critical path of every future multi-lane
dispatch. Issue at `https://cursor.com/dashboard/api`; store as a
**repository-scoped** secret named `CURSOR_API_KEY` in Cursor Dashboard →
Cloud Agents → Secrets. Verify presence without ever reading the value:

```bash
echo "$CLOUD_AGENT_ALL_SECRET_NAMES" | tr ',' '\n' | grep -x CURSOR_API_KEY
```

then authenticate against `/v1/me` and read `/v1/models`. Its pre-activation
state is fully characterised — 401 on every route, absent by name census — so a
post-activation failure is unambiguous rather than mysterious.

**FA-GH-ROUTE-01 — decide the GitHub route. The decision NOW; the widening
probably never.** The recommendation is to grant nothing new and instead set
branch protection directly on the protected branches. Protection works without
the agent being able to read it, and it is free, immediate and reversible. The
agent's current read-only installation is the right shape; widening it to reach
Issues or secrets would add authority for no reproduced need.

**FA-MCP-OAUTH-01 — state the MCP policy explicitly NOW; connect integrations
LATER.** The environment schema accepts `disableAllMcpServers` and
`mcpServerAllowlist` and neither is set, so this repository silently inherits
whatever upstream policy exists. An allowlist naming the intended servers is a
stronger statement than an empty configuration. Prefer HTTP transport over
stdio: with HTTP the server configuration never enters the agent VM. The Slack
and Linear connection is the lowest-value and highest-risk item here —
connecting it before the git pointer chain is unambiguously canonical would add
a second place where "what is current" can be asserted, which is this estate's
signature failure.

**FA-CUR-CLI-01 — Cursor CLI in CI. LATER.** Depends on FA-CUR-API-01 and
introduces recurring spend. No route is currently blocked on it, and the
container runtime already in this VM delivers much of the same independence
value at zero cost and zero new authority.

The OpenAI programme is **OE-L5's**. This lane records only the reproduced
state — `OPENAI_API_KEY` absent, `GET https://api.openai.com/v1/models` returns
401 *"Missing bearer authentication in header"*, egress unrestricted, therefore
credential-blocked not unsupported — and specifies nothing further.

No action in this programme asks the founder to paste a secret into chat.
`CLOUD_AGENT_ALL_SECRET_NAMES` makes that unnecessary: any agent can confirm a
secret's name appears without ever reading its value.

---

## Boundaries kept

No protected branch was written: not `main`, not
`so02/strategic-control-plane-migration-20260822-v001`, not
`cursor/operating-environment-return-20260822-v001`, not
`cursor/so02-cur-orch-qual-01`, and no `po03/*`, `cursor/po03-*`, `soo/*` or
`packs/*`. Read-only `git show` against two of them supplied the prior register
and the manifest formats.

No pull request was opened, commented on, merged or modified. #11 and #12 were
seen only as titles in a `gh pr list` and as `pr_created` entries in the run
event log.

No PO-03 thread, transcript, branch or path was touched. `batch-fetch-details`
— the instrument that would fetch them — was deliberately not called at all,
rather than called carefully. The account run listing was read and only its
model and status fields recorded. SW, PO-01 and MANUS were not messaged,
operated, configured or read.

The halted browser batch was not executed, installed or expanded. The Chrome
and X display reported above are pre-existing base-image components, found by
inspection.

Of the 14 `cursor-cloud` tools, six read-only ones were called. Five that
mutate environment or account state or raise a user-facing request were
excluded by the brief. `environment-build-logs` and `get-automation` were not
needed, and `batch-fetch-details` was excluded on the PO-03 boundary.

No money was spent, no external outreach made, no account setting changed, and
no credential value was printed or stored anywhere — environment variables
appear by name and set/unset state only.

Nothing here binds a tool, a model or an architecture. Every item is a
recommendation carrying its evidence and its risk.
