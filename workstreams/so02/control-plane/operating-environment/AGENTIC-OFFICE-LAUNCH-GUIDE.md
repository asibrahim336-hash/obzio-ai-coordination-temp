# The agentic office — launch guide

**For:** Ahmed Sadek, founder of Obzio, sitting in front of a browser tonight.
**Produced by:** lane `OE-W5-AGENTIC-OFFICE-GUIDE`, commission `COM-CUR-ENV-01-20260822-v001`.
**Governed by:** `.cursor/rules/00-founder-standing-authority.mdc`, `FOUNDER-STANDING-INSTRUCTION-20260822.md`, `FOUNDER-AUTHORITY-20260822T2225Z.json`.
**State:** `READY_TO_COMMIT`. A proposal for admission. Nothing here is accepted, and nothing here binds a tool, a model, an architecture or any company strategy.

This is the guide you asked for: *"the best guide to the current Cursor interface
and setup that allows me to launch the way I want, at the scale I expect, with
the results I expect."* You also asked to be pointed at one if it already
existed. It did not. **No such guide existed anywhere in this repository before
this file**, which is why this is the deliverable rather than another
architecture document.

It is written to be operated, not admired. If you finish a section and still
don't know which button to press, that section has failed.

---

## 0. How to read this

Three labels appear throughout, and they are not decoration. They are the
difference between something you can act on and something you should check.

| Label | Means | How to challenge it |
|---|---|---|
| `DIRECTLY_REPRODUCED` | A command ran here and this was its output | Re-run the command. It is given. |
| `DOCUMENTED` | Cursor's own documentation says so, fetched live during this lane | Re-fetch the URL. Every one is recorded with its date, byte length and sha256. |
| `HYPOTHESIS` | An inference. Nothing in this guide depends on one. | The instrument that would settle it is named. |

**Every interface claim in section 2 is `DOCUMENTED` from a live fetch, never
recalled.** Cursor's interface changes; a UI described from memory is an
unfalsifiable claim. 61 pages were fetched, hashed and mapped to the sections
they support, in
[`w5-agentic-office/INTERFACE-EVIDENCE-20260822-v001.json`](w5-agentic-office/INTERFACE-EVIDENCE-20260822-v001.json).
Re-fetch them all with
`bash workstreams/so02/control-plane/operating-environment/w5-agentic-office/tools/refetch_docs.sh`.

Where a step could not be verified, it says so in place. Nothing is smoothed over.

---

## 1. What the office is

A "dedicated office of coordinated agents" is not a metaphor here. It is a
specific set of Cursor objects that already exist in your account, arranged so
they cannot collide.

| The office concept | The actual Cursor object | Where it lives | Who creates it |
|---|---|---|---|
| A **desk** — one worker doing one job | A **cloud agent**: an isolated Ubuntu VM with your repo cloned, your dependencies installed, and a full desktop | `cursor.com/agents`, one page per agent | You, or another agent |
| The **office floor** — everyone at once | The **agents list** at `cursor.com/agents` (web, any device) or the **Agents Window** (desktop app) | Same page | Exists already |
| A worker's **private desk space** | A **git worktree** plus a **branch** — its own working directory, its own files, its own git HEAD | `/tmp/<lane>` inside the VM; `cursor/<lane>-<suffix>` on GitHub | The lane, at dispatch |
| The **building** — tools, dependencies, secrets, network | A saved **environment** and its **Builds** | `cursor.com/dashboard/cloud-agents#environments` | You, once |
| A worker's **skills and seniority** | The **model** chosen for that run, with its effort and context window | Model selector on the agent page | You, or the dispatcher |
| **Standing orders everyone follows** | `AGENTS.md` and `.cursor/rules/*.mdc` in the repository | Already in this repo | The office |
| **House rules that actually refuse things** | `.cursor/hooks.json` — a `beforeShellExecution` hook returning `deny` | Already in this repo (see blocker B3) | The office |
| A **specialist you call in** | A **subagent** — own context window, own result returned to its parent | Inside a run; `.cursor/agents/*.md` for named ones | The parent agent |
| The **night shift** | An **automation** — a cloud agent on a schedule or an event trigger | `cursor.com/automations` | You, once |
| **Waiting for something to happen** | A **subscription** — the agent sleeps and wakes on a GitHub, Slack, Linear or timer event, keeping full context | Inside a run, via `/subscribe` | The agent |
| The **filing cabinet of record** | The **git repository**. Not any provider's memory. | GitHub | Everyone |

`DOCUMENTED`, all of it: <https://cursor.com/docs/cloud-agent.md>,
<https://cursor.com/docs/agent/agents-window.md>,
<https://cursor.com/docs/subagents.md>,
<https://cursor.com/docs/configuration/worktrees.md>,
<https://cursor.com/docs/cloud-agent/automations.md>,
<https://cursor.com/docs/cloud-agent/capabilities.md> — all fetched 2026-08-23.

### The one distinction that makes the whole thing work

**A seat is a unit of authority. An agent is a unit of dispatch.**

The office has eight seats (section 4). It has no fixed number of agents, and it
never will. One seat can be filled by one agent or by fifty; the number is chosen
from capacity, cost and the shape of the work, and it carries no authority with
it. That separation is what lets the office grow to whatever your capacity allows
without ever creating a second holder for a decision — which is the failure that
actually breaks multi-agent operations, and the one this estate already
demonstrably has.

`DIRECTLY_REPRODUCED`: compiled live against this repository, the currentness
compiler reports `UNDIFFERENTIATED_COMMISSION_OVERLAP=7` and
`COMMISSION_ID_COLLISION=1` — including **two commissions asserting
whole-operation authority over the same scope with no supersession edge, both
binding the same runtime actor**. Adding agents to an estate that cannot tell two
mandates apart multiplies the collision, not the output. Reproduce it, writing
only to `/tmp`:

```bash
python3 workstreams/so02/control-plane/operating-environment/l4-currentness-recovery/tools/currentctl.py \
  compile --repo-root . --out /tmp/projection.json
```

Read the `findings` line of its output. (`rolectl.py check` is a different
instrument and answers a different question — whether the *seat* partition is
sound. Both are run at dispatch; neither substitutes for the other.)

### What already exists, so you are not starting from zero

`DIRECTLY_REPRODUCED` in this run unless marked otherwise:

- **11 top-level cloud agents** have run on this repository under your one
  account, across **4 distinct exact model configurations** and **2 model
  families**. Eight of them were created inside an **804-millisecond window** —
  one dispatch action, not eight.
- **The applied `.cursor/` tree**: four hooks with 69 passing behavioural cases,
  two always-applied rules, an evidence skill, an MCP policy, and a write-scope
  declaration.
- **A machine-checked authority partition**: 36 decision classes, 26 functions,
  14 invariants, 20 proven rejections. Ten classes are reserved to you and
  unclaimable, which is what makes a "whole-operation" seat *structurally
  impossible* rather than merely discouraged.
- **An admission ladder** that refuses to let a pull request, a ZIP, a file count,
  an agent existing or an acknowledgement count as completed capability.
- **18 reproduced records** of what this account can actually do, and 10 ranked gaps.

The office is not being invented tonight. It is being **constituted and pointed
at work**.

---

## 2. The Cursor interface you actually have tonight

You are on a Chromebook. That means the **web surface**, and the web surface is
enough for everything in this guide's launch sequence.

Each URL below was probed without a session and returned a redirect to Cursor's
own authenticator — which confirms the address is real and that only you can open
it (`DIRECTLY_REPRODUCED`, receipt:
`receipts/so02/2026-08-22/oe-w5-agentic-office/raw/dashboard-url-probe.txt`).

### The seven pages that matter

| Open this | What it is | What you do there |
|---|---|---|
| **`cursor.com/agents`** | The office floor. Every cloud agent, running and finished. | Start an agent. Pick its model and repo. Read a run. Send follow-ups. Add MCP servers from the **MCP dropdown**. |
| **`cursor.com/dashboard/cloud-agents`** | Cloud Agents settings. | **Secrets** tab. Default model, default repository, base branch. Network access. Team follow-ups. Long-running agents. The **My Settings** toggle for auto-fixing CI failures. |
| **`cursor.com/dashboard/cloud-agents#environments`** | Environments. | Create or edit the environment. Read which install script runs, which secrets exist, and the Builds tab with version history and **Restore**. |
| **`cursor.com/automations`** | The night shift. | Create an automation: pick a trigger, write a prompt, choose tools, choose repository scope, set permissions, activate. |
| **`cursor.com/dashboard/usage`** | The Spending tab. | The only place a *real* cost number exists. Both usage pools, remaining allowance, on-demand charges. |
| **`cursor.com/dashboard/api`** | API keys. | Where a Cursor API key would be issued — **but do not issue one**, see blocker B1. |
| **`cursor.com/dashboard/integrations`** | Source control and third-party connections. | Connect GitHub/GitLab/Bitbucket. Where Slack and Linear would be connected. |

Also: `cursor.com/marketplace` for automation templates, and
`cursor.com/dashboard/settings` for team-level settings including MCP
configuration.

`DOCUMENTED`: <https://cursor.com/docs/cloud-agent.md>,
<https://cursor.com/docs/cloud-agent/settings.md>,
<https://cursor.com/docs/cloud-agent/setup.md>,
<https://cursor.com/docs/cloud-agent/automations.md>,
<https://cursor.com/docs/models-and-pricing.md>, fetched 2026-08-23.

### Talking to a running agent — the four keys

This is worth knowing precisely, because it is the difference between steering an
agent and interrupting it.

| You want to | Do this | What happens |
|---|---|---|
| Add a next task | Type it, press **Enter** | Queued. Runs after the current task. Drag to reorder. |
| Redirect it **now** without breaking it | Type it, press **Enter twice**, or click **Send now** | Delivered at the agent's next tool call. In-flight work is preserved. |
| Interrupt immediately | **Cmd+Enter** | Appended to your most recent message and processed right away. |
| Give it a long-lived objective | `/goal <objective>` | The agent works toward it across messages instead of treating each message as a fresh job. |

Steering with **Send now** is available on `cursor.com/agents` today.
`DOCUMENTED`: <https://cursor.com/docs/agent/overview.md>, fetched 2026-08-23.

### What is desktop-only, and whether you need it

| Desktop-only | What it gives you | Do you need it tonight? |
|---|---|---|
| **Agents Window** (`Cmd+Shift+P` → Open Agents Window) | Multi-workspace, diffs view, local↔cloud handoff, UI-native worktrees, cloud subagents via `/in-cloud`, `/babysit` a PR | **No.** Every one of those has a web or in-prompt equivalent for this office. |
| `/worktree`, `/best-of-n`, `/apply-worktree` | Isolated checkouts and multi-model comparison, driven from the IDE | **No.** Lanes create worktrees with `git worktree add` in their own prompt, which is what this office does anyway. |
| MCP OAuth | Authenticating an MCP server | **No — and this is the one people get wrong.** Cursor registers a **web callback** at `https://www.cursor.com/agents/mcp/oauth/callback` for the web and Cursor Agents surfaces. The desktop callback `http://localhost:8787/callback` is a *second* option, not a requirement. You can authenticate MCP servers from a browser. |

`DOCUMENTED`: <https://cursor.com/docs/agent/agents-window.md>,
<https://cursor.com/docs/configuration/worktrees.md>, <https://cursor.com/docs/mcp.md>,
fetched 2026-08-23.

Note the Agents Window went generally available with Cursor 3 on 2026-04-02, so
if you *do* pick up a desktop later, it is there. It is an accelerator, not a
prerequisite.

---

## 3. Launching at scale

### How many agents can run at once

Two different kinds of answer, and they should not be blended.

**`DOCUMENTED`:** *"You can run as many agents as you want in parallel, and they
do not require your local machine to be connected to the internet."*
(<https://cursor.com/docs/cloud-agent.md>, fetched 2026-08-23.) Each cloud agent
gets its own isolated VM with a full desktop
(<https://cursor.com/docs/cloud-agent/capabilities.md>).

**`DIRECTLY_REPRODUCED`:** on your account, 11 top-level agents, one repository,
4 exact model configurations, 2 families, and a burst of 8 created inside 804 ms.
Nothing was throttled, queued or refused in any way this instrument can see.

**What that does not establish:** a ceiling. Nobody has tried thirty. A census of
what *did* run is not a measurement of what *may* run, and this guide will not
pretend otherwise. Full record:
[`w5-agentic-office/CONCURRENCY-EVIDENCE-20260822-v001.json`](w5-agentic-office/CONCURRENCY-EVIDENCE-20260822-v001.json).

### One orchestrator with subagents, or many top-level agents?

This is the single most consequential topology choice, and there is a reproduced
finding that decides it.

| | One run, many subagents | Many top-level cloud agents |
|---|---|---|
| VM | **One, shared** | One each, isolated |
| Filesystem and git repository | **One, shared** | One each |
| Failure blast radius | One VM's problem is everyone's | Contained |
| Project hooks (`.cursor/hooks.json`) | **Do not fire** for a lane in a worktree — the project root is `/workspace`, not the worktree | Project root *is* the checkout, so the hook sits where Cursor reads it |
| Dispatch cost | One message | One start per agent, or one API call each once B1 clears |
| Coordination | Parent holds all context | Coordinate through git |
| Best for | Tightly coupled work that must share intermediate state | **Everything else, and everything in this office** |

`DIRECTLY_REPRODUCED` — this run is a subagent, and:

- `/cursor/stores/self` resolves to the **parent run's** id, not this lane's own.
  This lane's own id ends `…019c4d9f13e1`; the store it is handed ends
  `…2f2dcbef696d`. The durable store is scoped per top-level run and **shared
  with every subagent under it**, so what one lane writes there a sibling can
  overwrite. Receipt:
  `receipts/so02/2026-08-22/oe-w5-agentic-office/raw/identity-and-environment-probe.txt`.
- Sibling lanes' worktrees (`/tmp/oe-l1` … `/tmp/oe-w4`) are visible from inside
  this lane. Same VM, same disk, same git repository.
- The shared `/workspace` checkout's HEAD is **detached** right now.

That last point is the load-bearing one, and it has already cost this estate a
recovery. Two lanes worked in the shared `/workspace` checkout. Three commits
interleaved on one detached HEAD. A commit on a detached HEAD advances no branch,
so both lanes' branch refs stayed at the base commit — and then:

> `git push -u origin <branch>` pushed the stale ref, printed
> **`Everything up-to-date`, and exited 0.**

**In this configuration a zero exit from `git push` is not evidence that anything
was published.** A lane trusting it reports success while the branch is empty.
Every commit from every lane is authored `Cursor Agent`, so git metadata
attributes nothing to a lane either.

Two consequences run through the rest of this guide:

1. **Every lane takes its own `git worktree` at dispatch.** Not as hygiene — as
   the only thing that prevents the collision.
2. **Every publication is confirmed with `git ls-remote`**, compared against
   `git rev-parse HEAD`. Never with an exit code.

### How work is partitioned so agents do not collide

Not by topic. Topics overlap; that is what topics do. **By decision class.**

Before any wave is dispatched, every unit of work is attached to exactly one of
26 decision classes, each held by exactly one seat. Ten further classes are
reserved to you and cannot be claimed by any seat at all. Because those ten
include programme shape and company strategy, **a seat wide enough to be a
"whole-operation" seat would have to claim a reserved class, and would fail
admission**. The failure is not discouraged; it is structurally unavailable.

Verify before every dispatch:

```bash
python3 workstreams/so02/control-plane/operating-environment/w5-agentic-office/tools/officectl.py check
python3 workstreams/so02/control-plane/operating-environment/w4-platform-roles/tools/rolectl.py check
```

`DIRECTLY_REPRODUCED`: both pass today — 8 seats, 26 classes held, 10
founder-reserved, 14 invariants; and 5 platforms, 36 classes, 26 functions, 14
invariants. Twenty mutations of the seat register are each rejected by
`tools/negative_tests.py`, including the two that would quietly undo the whole
design: a seat imposing a fixed agent count, and a seat routing its results
through you.

Seats **may** overlap and collaborate. What is forbidden is *silent* overlap. A
seat touching a class another seat holds files a contribution row — class, holder,
contributor, wave, evidence label, position (agree / dissent / abstain),
disposition, conflict id. Two rules make it work:

- **Evidence outranks ownership.** A holder whose position is `HYPOTHESIS` may not
  close a conflict against a contributor whose position is `DIRECTLY_REPRODUCED`.
- **An unresolved conflict never blocks work.** It attaches to the work as a
  standing dissent. No lane idles waiting for your reply.

### How results return

Every seat returns to the **repository**, on its own branch, with a manifest.
Never through you. The route where you carry a result is named explicitly in the
register — `R0-founder-relay` — and it is classified as a **defect**, so a seat
cannot quietly adopt it: `officectl.py` refuses any seat that names it.

Verification and reporting are the platform's job, not yours. The nightly
automation in
[`w5-agentic-office/prompts/30-automation-briefs.md`](w5-agentic-office/prompts/30-automation-briefs.md)
does the retrieval, the comparison and the `git ls-remote` checks, and reports
only what changed and what is stuck.

---

## 4. The seats

Eight seats. Each has one mandate, a disjoint set of decision classes, a return
route, and an acceptance owner that is never itself. Full machine-checked
definitions:
[`w5-agentic-office/OFFICE-SEAT-REGISTER-20260822-v001.json`](w5-agentic-office/OFFICE-SEAT-REGISTER-20260822-v001.json).

| Seat | Mandate in one line | Decides | Returns | Accepted by |
|---|---|---|---|---|
| **`S-CHIEF`** Chief of staff | Runs the office: assigns classes to seats, dispatches waves, removes founder-relay steps. Decides nothing about *quality*. | Decision rights, founder load, wave learning, open questions | A wave record on a branch | `S-ACCEPT` |
| **`S-REGISTRAR`** Registrar | Owns what is current, what supersedes what, what is admitted to which rung, and where the bytes live. | Currentness, supersession, admission, custody | A recomputed projection plus a ledger diff | `S-ACCEPT` |
| **`S-BUILD`** Builder | Builds the operating environment and the capabilities on it; fixes reproduced defects. | Capability development, remediation, environment architecture, staged guidance | A branch of committed artefacts, each with a path, a hash and a re-runnable command | `S-ACCEPT`, plus `S-ADVERSARY` for fixes |
| **`S-ACCEPT`** Acceptor | The only seat that can call a claim independently validated. Never the producer. | Acceptance, evaluation definition | A criteria commit that **precedes** a verdict commit | `S-ADVERSARY` |
| **`S-ADVERSARY`** Adversary | Rewarded for finding breaks: forges evidence, audits provider claims, checks the acceptor. | Adversarial finding, provider-claim audit | Negative tests as executable code, each forgery kept as a regression test | `S-ACCEPT` |
| **`S-RUNTIME`** Runtime steward | Which routes work, how much headroom exists, whether the estate survives losing a provider. | Route qualification, quota headroom, portability | A route table with the probe command and the observed response | `S-ACCEPT` |
| **`S-SCOUT`** Scout | Brings in what exists outside the estate as candidates with evidence — never as decisions. | Research frontier | A candidate register where every entry names a URL, a date and a hash | `S-ACCEPT` |
| **`S-ESTATE`** Estate liaison | The only seat whose asymmetry is authenticated access to your own accounts. Runs outside Cursor. | Estate inventory, integration alignment, intent capture, intent corpus, surface disposition, blind spots | An inventory and an intent record with provenance, committed by a Cursor seat | `S-ACCEPT`, in Cursor |

**How many agents fill each seat.** `S-CHIEF` is one at a time — two dispatchers
recreate the undifferentiated-mandate failure. Every other seat is unbounded.
`S-BUILD` and `S-SCOUT` are where you spend spare capacity; `S-ACCEPT` and
`S-ADVERSARY` are where you spend it when you want the output to *mean* something.

**Why acceptance lives in Cursor and not with a second vendor.** Independence
decomposes into six properties — isolated context, criteria committed first,
evidence custody, distinct model identity, adversarial tests, and no
self-modification of the verdict — and **not one of them requires a second
provider**. This is not theory: an acceptance lane ran inside Cursor, on a
different model family from its producer, with criteria committed beforehand and
no founder in the loop, and it **refused the root controller's own evidence**.
Two of its findings were then reproduced against the producer's own tooling. A
separate lane, which never read that verdict, reached the same conclusion by a
different instrument.

The one residual class that genuinely needs a second domain is **claims about
Cursor's own behaviour** — a defect in the runtime is correlated across every lane
inside it, and the shared-worktree collision and the exit-zero push are exactly
that class. GitHub Actions is the cheapest second execution domain and is already
reproduced here.

**The ten classes reserved to you**, which no seat can claim: programme shape,
company strategy, spend commitment, identity and secrets, third-party outreach,
SW reactivation, external authorisation, pointer supersession, model-allocation
binding, disclosure policy.

---

## 5. The results contract

So that *"the results I expect"* is a defined thing rather than a hope.

### What comes back, every time

For every lane, in its final message and in its committed record:

1. **The branch**, and the **pushed commit SHA confirmed against `git ls-remote`** —
   not against a zero exit code.
2. **A manifest** covering every file it wrote, each with `path`, `size_bytes`
   and `sha256`, plus `entry_count` and a `bundle_sha256` that a third party can
   recompute independently.
3. **A reproducible command** per claim: an argv and an expected exit code that
   someone without provider access can re-run.
4. **Evidence labels** on every claim.
5. **What it could not verify, and the exact instrument that would settle it.**
6. **What genuinely needs your judgment** — which never includes retrieval,
   monitoring, comparison, merging or coordination.

### The six rungs, and the one you should ask about

| Rung | What it takes |
|---|---|
| `PROPOSED` | Someone wrote down a scope. Nothing ran. |
| `LAUNCHED` | A named runtime was dispatched against a stable, resolvable locator. |
| `OBSERVED` | Output was seen **at that locator**. |
| `DURABLE` | The output is in git at a named commit **and has been read back from the remote by hash**. |
| `INDEPENDENTLY_VALIDATED` | A separately-identified evaluator re-ran the claim against criteria fixed **before** reading the result. |
| `ACCEPTED` | A founder-bound decision on top of validation. **A producer can never self-accept.** |

The rungs are monotonic and cannot be skipped. When you ask an agent "is this
done", the answer you want is a rung and its evidence — not an adjective.

### What can never count as completed capability

These are hard-coded as non-admissible, and any of them **caps the subject at
`PROPOSED`**:

> a pull request existing · a branch existing · a ZIP archive · a file count ·
> an agent existing, running or completed · a prompt sent · an acknowledgement ·
> a provider saying "completed" · a receipt count · a document describing a
> mechanism · a documented lesson that changes no executable gate

That list is not rhetoric. Independent compilation of this repository found
**nothing in the estate qualifying above `OBSERVED`**, with eight of sixteen
workstreams claiming more than their evidence supported. The ladder exists
because that happened.

### The report you should demand

Ask for exactly this shape and refuse anything else:

> *What moved on the ladder, in both directions. What `S-ACCEPT` refused and why.
> What is blocked, on whose exact act, and for how long. What needs my judgment.
> Nothing else.*

Raw counts — agents launched, branches pushed, files written — are **inventory**
and are reported as inventory. The only throughput number that means anything is
`ACCEPTED`, and only `S-ACCEPT` issues it.

---

## 6. The launch sequence

Seven stages. Stages 0–3 stand the office up and can be done in one sitting.
Stages 4–6 are the operating loop.

Each stage says: what you open, what you do, what Cursor does on its own, the
expected result, how to verify, what failure looks like, and how to roll back.

---

### Stage 0 — Confirm the ground you are standing on

**You open:** `cursor.com/agents`
**You do:** Start one cloud agent on `asibrahim336-hash/obzio-ai-coordination-temp`.
Any model. Paste:

```
Run these and report the raw output, nothing else:

  bash workstreams/so02/control-plane/operating-environment/w5-agentic-office/tools/capture_run_evidence.sh $(git rev-parse --show-toplevel)
  cat receipts/so02/2026-08-22/oe-w5-agentic-office/raw/run-evidence.txt

Then answer three questions from that output alone:
  1. Is CURSOR_API_KEY present in the secret-name census?
  2. Does /cursor/stores/self resolve to this run's own id, or a parent's?
  3. Do both validator suites pass?

Change nothing. Commit nothing. Open no pull request.
```

**Cursor does autonomously:** provisions a VM, clones the repo, runs the probes.
**Expected result:** the seven probe blocks, and answers: `ABSENT`; its own id
(this is a top-level run, so it has its own store); both `PASS`.
**Verify:** read the output. That is the verification.
**Failure looks like:** the agent not starting at all — check that source control
is connected at `cursor.com/dashboard/integrations` and that you are on a paid
plan. Or a validator failing, which means something changed and stage 1 waits.
**Roll back:** nothing to roll back. This stage writes nothing.

---

### Stage 1 — Make the environment real *(fixes blocker B2)*

**You open:** this exact page — no searching required:

> <https://cursor.com/dashboard/cloud-agents/environments/e/69dbfc52-9df5-11f1-a7d1-d6b4613131ce>

(That is the environment already bound to this repository. Its id was read from
this run, `DIRECTLY_REPRODUCED`. The general route is
`cursor.com/dashboard/cloud-agents#environments`.)

**Why:** the repository's `.cursor/environment.json` is valid, schema-correct —
and **inert**. `DIRECTLY_REPRODUCED` in this run: `environment-info` reports
`source: Team`, `environmentJson: null`, `name: null`, and the note
*"environment.json was found but contained no recognized configuration fields."*
This environment is database-managed, so the **saved record** is its configuration
source, not the file. Every agent therefore pays a cold start and the office's own
validators terminal never runs.

The same probe reports **`build: null`** — this pod booted just-in-time rather
than from any prebuilt environment build. That is the cold start observed
directly, not inferred from the missing config.

**You do:** either paste the repository file's fields into the saved environment,
or click **Update with Agent** and let Cursor inspect the repo and propose a
setup. The file to mirror is:

```json
{
  "name": "Obzio AI Coordination",
  "install": "bash .cursor/install.sh",
  "start": "bash .cursor/start.sh",
  "disableAllMcpServers": false,
  "terminals": [
    { "name": "control-plane-validators",
      "command": "bash .cursor/terminals/validators-watch.sh" }
  ]
}
```

**Cursor does autonomously:** runs a Build — clones repos, runs `install` to
completion, captures the resulting disk state, and makes it the active Build that
new agents boot from.

**Expected result:** a `SUCCEEDED` Build in the **Builds** tab.
`DIRECTLY_REPRODUCED` precedent: a draft build of this install script succeeded in
47 seconds, with `install.sh`'s own output in the log line by line, ending
`OPERATOR TAXONOMY CHECK: PASS` and `[INSTALL] Exit code: 0`.

**Verify:** start a new agent and have it report `environment-info`.
`environmentJson` should be non-null and `name` should read `Obzio AI
Coordination`. Then check `/tmp/cursor/start-user/` exists, which proves the start
phase ran.

**Failure looks like:** `environmentJson` still `null` — the save did not take.
Or a failed Build, which is *safe*: a failed Build never replaces the active one,
so agents keep starting from the last good state while you read the logs.

**Roll back:** **Restore** from version history in the environment's version
list. One click.

**Not verified, stated plainly:** whether `terminals` takes effect could not be
tested from inside an agent — the build-override API accepts only `install`,
`start` and `snapshot` and rejected `name` and `terminals` outright. Whether
`start.sh` runs on an agent run as opposed to during a Build is carried as a
`HYPOTHESIS`, settled by the `/tmp/cursor/start-user/` check above.

---

### Stage 2 — Two owner acts that remove founder-relay steps forever

Both are yours alone. Neither asks you to paste a secret into a chat, ever.

#### 2a. Mirror the Cursor API key you already have *(fixes blocker B1)*

**Do not issue a new key.** That request was superseded and withdrawn: a second
key doubles the revocation surface for nothing.

**You open:** `supabase.com/dashboard` → the project holding it → **Edge
Functions → Secrets** → reveal. Then `cursor.com/dashboard/cloud-agents` →
**Secrets**.
**You do:** add a secret named **exactly** `CURSOR_API_KEY`, scoped to
`asibrahim336-hash/obzio-ai-coordination-temp`.
**Cursor does autonomously:** injects it as an environment variable at pod start
for every future run.
**Expected result:** every subsequent agent can call `api.cursor.com` — including
`POST /v1/agents`, the endpoint that lets one agent create and steer another
instead of you pressing a button.
**Verify — without ever reading the value.** Start a **new** run (secrets are
injected at pod start, so the run that stores it cannot see it) and have it run:

```bash
echo "$CLOUD_AGENT_ALL_SECRET_NAMES" | tr ',' '\n' | grep -x CURSOR_API_KEY
bash workstreams/so02/control-plane/operating-environment/w3-credential-estate/tools/verify-cursor-api-key.sh
```

Expect the name to appear and the script to print `VERIFIED` and exit 0.
**Failure looks like:** still `401` after a fresh run — the name is wrong or the
scope excludes this repository. The pre-state is fully characterised
(`DIRECTLY_REPRODUCED`: 401 on `/v1/me`, `/v1/agents`, `/v1/models`,
`/v1/repositories`; 404 with a *different body shape* on a nonexistent route), so
a post-activation failure is unambiguous rather than mysterious.
**Roll back:** delete the secret. Nothing else changes.

#### 2b. Set branch protection in GitHub *(fixes blocker B4)*

**You open:** GitHub → repository → Settings → Branches.
**You do:** protect `main`, `so02/*`, `po03/*`, `soo/*`, `packs/*`.
**Why this and not the alternative:** no agent can read *or* set branch
protection — the GitHub App installation token returns 403 on administration
(`DIRECTLY_REPRODUCED`, endpoint by endpoint). Protection works perfectly well
without the agent being able to read it. **Do not widen the agent's GitHub
permissions to make it readable**; that adds authority for no reproduced need.
**Expected result:** a push to a protected branch is refused by GitHub itself
rather than only by lane discipline.
**Verify:** the protection rules appear in Settings → Branches.
**Failure looks like:** a push to a protected branch succeeding.
**Roll back:** remove the rule.

---

### Stage 3 — Seat the chief of staff

**You open:** `cursor.com/agents` → new agent → this repository → a strong
reasoning model.
**You do:** paste
[`w5-agentic-office/prompts/00-chief-of-staff-standing-brief.md`](w5-agentic-office/prompts/00-chief-of-staff-standing-brief.md)
from the line marked `---` onward.
**Cursor does autonomously:** the agent reads the governing documents, compiles
current state from the repository rather than from claims, runs both validator
suites, chooses a wave, and dispatches lanes — each with its own branch, its own
worktree and a stated write scope.
**Expected result:** a wave record on a branch naming what was dispatched, to
which seat, with which locator.
**Verify:** `cursor.com/agents` shows the lanes. For each, `git ls-remote origin
<branch>` matches what the lane reported.
**Failure looks like:** two lanes on the same branch, or a lane working in
`/workspace`, or a validator failure at dispatch. All three are refusals the chief
of staff is instructed to make; if one slips through, `S-ADVERSARY` catches it in
stage 5.
**Roll back:** the lanes wrote only their own branches. Delete the branches.
Nothing merged, nothing promoted, no pull request opened.

---

### Stage 4 — Run a wave

**You open:** nothing, ideally. This is the office working.
**You do:** at most, steer. Type a correction on the chief of staff's page and
press **Enter twice** to deliver it at the next tool call without breaking
in-flight work.
**Cursor does autonomously:** lanes work, commit, push, confirm publication with
`git ls-remote`, and stop at `READY_TO_COMMIT`.
**Expected result:** every lane returns a branch, a confirmed SHA, a
`bundle_sha256`, its evidence labels, and its unverified items.
**Verify:** you don't. `S-ACCEPT` does, and the nightly automation does the
`ls-remote` sweep. If you find yourself checking branches by hand, that is a
defect in the office, not a task — say so and it gets absorbed.
**Failure looks like:** a lane reporting success on a branch whose remote ref did
not move. This is the exit-zero push failure and it is **silent by construction**;
the automation in `prompts/30-automation-briefs.md` §B exists specifically to
catch it.
**Roll back:** delete the wave's branches.

---

### Stage 5 — Accept, or refuse

**You open:** nothing.
**You do:** nothing. **This is the stage you must stay out of.** Merging verdicts
is an arbitration act, and the design deliberately keeps you out of evidence
comparison.
**Cursor does autonomously:** `S-ACCEPT` commits its criteria *before* reading
any result, re-derives every hash from a fresh clone with its own hasher, and
issues `PASS` / `REFUSE` / `INCONCLUSIVE`. `S-ADVERSARY` attacks the machinery,
forges evidence that should be rejected, audits every provider status claim, and
checks the acceptor. Briefs:
[`w5-agentic-office/prompts/20-acceptance-and-adversary-briefs.md`](w5-agentic-office/prompts/20-acceptance-and-adversary-briefs.md).
**Expected result:** claims at `INDEPENDENTLY_VALIDATED`, or refused with the
command and output that refused them.
**Verify:** `git log` shows the criteria commit preceding the verdict commit.
That ordering *is* the independence evidence, and it is checkable by you in one
command if you ever want to.
**Failure looks like:** a verdict with no earlier criteria commit, or an acceptor
running the producer's own verifier. A fabricated read-back naming a nonexistent
commit once passed a producer's verifier here — which is why the acceptor writes
its own.
**Roll back:** a verdict is evidence and is never deleted. A wrong verdict is
superseded by a later one with a recorded edge.

**If several acceptors run:** do not merge their verdicts. **Any `REFUSE`
stands**, and concordance is reported with its denominator. That rule is declared
in advance precisely so comparison never becomes a new arbitration seat.

---

### Stage 6 — Put the office on a clock

**You open:** `cursor.com/automations`
**You do:** create three automations from
[`w5-agentic-office/prompts/30-automation-briefs.md`](w5-agentic-office/prompts/30-automation-briefs.md):
the nightly standup (schedule trigger), the push verifier (push-to-branch
trigger), and the weekly founder-load detector (schedule trigger). For each: pick
the trigger, paste the prompt, set **Repositories** to this repository — the
default for cron triggers is *no repository*, which cannot read code — set
**Permissions** to `Private`, save and activate.

**Faster route — let Cursor configure them.** There is an **`/automate` skill**
that takes the workflow in plain language and sets the triggers, instructions and
tools for you. Paste a brief from that file and say *"set this up as an automation
on this repository"* rather than filling the form by hand. `DOCUMENTED`:
<https://cursor.com/docs/cloud-agent/automations.md>, fetched 2026-08-23.
**Cursor does autonomously:** runs them without you. Automations use each model's
**maximum** context window with no toggle, so pick the model deliberately.
**Expected result:** a nightly report of what moved, what is stuck, and whose act
unblocks it. Nothing else.
**Verify:** the first scheduled run appears in the automation's history.
**Failure looks like:** an automation with no repository attached producing a
report about nothing.
**Roll back:** deactivate it. One toggle.

**Reach for a subscription instead of an automation** when the office needs to
*wait* rather than run on a clock: an agent subscribes to GitHub PR activity, CI
results, or a timer, ends its turn, and wakes with full context when the event
arrives. `/subscribe`, or just say what to wait for. Maximum 180 days.
`DOCUMENTED`: <https://cursor.com/docs/cloud-agent/capabilities.md>, 2026-08-23.

---

### What you personally do, and what you must not

**Yours, and genuinely only yours:**

| | Act | Where |
|---|---|---|
| 1 | Mirror the existing `CURSOR_API_KEY` into Cloud Agent Secrets | Supabase dashboard → Cursor dashboard |
| 2 | Set branch protection | GitHub → Settings → Branches |
| 3 | Make the saved environment real | `cursor.com/dashboard/cloud-agents#environments` |
| 4 | Set a spend limit, deliberately | `cursor.com/dashboard/usage` |
| 5 | Authenticate MCP servers you want, via the **web** OAuth callback | MCP dropdown at `cursor.com/agents` |
| 6 | Answer the six judgment questions in section 8 — once each | Anywhere |

**Not yours, ever.** If any of these reaches you, it is a defect in the office and
saying so is the correct response:

> retrieving a result · monitoring a run · comparing evidence · merging verdicts ·
> coordinating between lanes · checking whether a push landed · counting anything ·
> re-typing something a platform can read · pasting a secret into a chat

---

## 7. Scale and cost reality

Full record with every input labelled:
[`w5-agentic-office/SCALE-AND-CEILING-20260822-v001.json`](w5-agentic-office/SCALE-AND-CEILING-20260822-v001.json).

### What running an office actually costs

Cloud agents bill at the selected model's **API rate**, and a larger context
window increases both token use and cost (`DOCUMENTED`,
<https://cursor.com/docs/cloud-agent.md>). Two pools reset monthly: **Cursor
Models** (Grok 4.6, Grok 4.5, Composer 2.5) with generous included usage, and
**Other Models** — third-party models at API price — with a dollar inclusion.

| Plan | Price | Other Models included |
|---|---|---|
| Pro | $20/mo | $20 |
| Pro Plus | $60/mo | $70 |
| Ultra | $200/mo | $400 |

Cursor's own guidance for *"power users (multiple agents/automation)"* is **often
$200+/month of total usage**. `DOCUMENTED`:
<https://cursor.com/docs/models-and-pricing.md>, fetched 2026-08-23.

### The model choice matters more than the agent count

Same wave, same assumed token volumes per agent, eight agents, eight waves a month:

| Model | Pool | Per agent | Per wave (×8) | Per month (×8 waves) |
|---|---|---|---|---|
| Claude Opus 5 | Other Models | $21.50 | $172 | $1,376 |
| GPT-5.6 Terra | Other Models | $9.20 | $73.60 | $589 |
| Composer 2.5 | **Cursor Models** | $3.35 | $26.80 | $214 |

**The token volumes behind those numbers are assumptions, not measurements.**
Nothing inside an agent pod exposes token consumption; inventing a figure would be
the confident, useless answer. Recompute with your own numbers:

```bash
python3 workstreams/so02/control-plane/operating-environment/w5-agentic-office/tools/cost_model.py \
  --agents 8 --model claude-opus-5 --input-mtok 2 --output-mtok 0.3 --cache-read-mtok 8 --waves-per-month 8
```

The tool prints which of its inputs are documented and which are assumed. **The
only real number is on the Spending tab at `cursor.com/dashboard/usage` after one
wave has run**, and it supersedes every figure above.

The practical consequence: **cast the wave by model.** Cheap, fast, high-parallelism
models for scouting and search. Expensive models only where judgment is the
product. Running everything on the most capable model is the single largest
avoidable cost in an office this shape.

Also `DOCUMENTED`: running five subagents in parallel uses roughly five times the
tokens of one agent, because each has its own context window
(<https://cursor.com/docs/subagents.md>).

### Where the real ceiling is

Ranked by how binding it actually is:

| # | Ceiling | Binding? | Evidence |
|---|---|---|---|
| 1 | **Disjoint work.** The office can only usefully run as many agents as there are non-overlapping partitions. The currentness compiler reports 7 undifferentiated commission overlaps and 1 id collision in this estate *today*. | **Yes** | `DIRECTLY_REPRODUCED` |
| 2 | **Acceptance capacity.** Only accepted output counts. Producers scale cheaply; a wave of twenty builders that nothing checks lands entirely at `OBSERVED`. | **Yes** | `DIRECTLY_REPRODUCED` |
| 3 | **Money.** Model choice moves the same wave's bill by more than 6×. | **Yes** | `DOCUMENTED` |
| 4 | **One VM and one git HEAD**, for subagents of a single run. | **Yes** | `DIRECTLY_REPRODUCED` |
| 5 | **Your attention** — binding in the default arrangement, removed by design in this one. | No, as designed | `DIRECTLY_REPRODUCED` |
| 6 | A platform concurrency cap. | Not observed | `HYPOTHESIS` |

**The honest ceiling:** there is no documented cap on parallel cloud agents and
none was hit here; the highest simultaneous dispatch actually observed on your
account is **8 agents inside 804 ms**, with 11 total, unthrottled. Agent count has
never been the scarce resource in this estate. **Disjoint work and independent
acceptance are.** If a cap does exist it will appear as agents sitting in
`NOT_YET_STARTED` rather than starting, and the census tool would show it — the
probe is simply to dispatch a wave larger than any so far and read the lifecycle
statuses.

---

## 8. What is not ready yet, and the exact unblocking action

Nine blockers, each with its verification, its failure signature and **what
proceeds without it** — because no blocker is allowed to idle a lane. Full record:
[`w5-agentic-office/BLOCKERS-20260822-v001.json`](w5-agentic-office/BLOCKERS-20260822-v001.json).

| | Blocker | Exact unblocking action | Who | Proceeds without it? |
|---|---|---|---|---|
| **B1** | The office cannot dispatch itself — Cursor's Agent API is credential-blocked (401 on real routes, 404 on fake ones; `CURSOR_API_KEY` absent from the name census) | Mirror the **existing** key from Supabase Edge Secrets into a repository-scoped Cloud Agent secret named exactly `CURSOR_API_KEY`. **Do not issue a new key.** | You | Yes — waves start by hand instead |
| **B2** | `.cursor/environment.json` is valid and inert; this environment is database-managed | Paste the config into the saved environment, or click **Update with Agent** | You, or an authorised agent | Yes — a cold start is slower, not broken |
| **B3** | The write-scope guard does not fire for lanes in worktrees (project root is `/workspace`) | Scale by **top-level agents** rather than subagents-in-worktrees, then prove it with `.cursor/hooks/probe_hook_firing.py --arm` / `--check`. **Never** test it by running `git push origin main` | The office | Yes — the adversary seat checks after the fact instead |
| **B4** | No agent can read or set branch protection (403 on administration) | Set branch protection in GitHub directly. Do **not** widen the agent's permissions | You | Yes |
| **B5** | Slack and Linear returns unavailable | Connect at `cursor.com/dashboard/integrations` — **recommended: not yet** | You | Yes — GitHub and timer subscriptions cover the office |
| **B6** | `S-ESTATE` has no qualified route into custody; only you currently carry captured intent to git | First **discover** whether a GitHub connector is already on the account's ChatGPT plan — that is the liaison seat's own job, not a question for you. Only if not does it become a disclosure-and-install decision | The seat, then possibly you | Yes — every Cursor-resident seat is unaffected |
| **B7** | MCP integrations unauthenticated | Add and enable at the MCP dropdown on `cursor.com/agents`. OAuth has a **web callback**, so a browser is enough. Prefer **HTTP** transport — the server config never enters the agent VM | You | Yes |
| **B8** | Computer use exists in the VM but no agent-facing tool is present | Read `cursor.com/dashboard/cloud-agents` to see whether Computer use is enabled for this account. The documentation is not internally consistent about which plans get it, so read the account, not the docs | You | Yes — nothing in this sequence needs it |
| **B9** | Four dead `AUREA_E2E_*` secrets are injected into every run; the Supabase host does not resolve (NXDOMAIN, while `supabase.co` itself responds) | Confirm whether still meaningful and remove at `cursor.com/dashboard/cloud-agents` | You | Yes |

### The six things that genuinely need your judgment

None is retrieval, monitoring, comparison, merging or coordination. Each is either
an owner act or a risk-appetite question with no technically correct answer.

| | Question | Why it cannot be delegated |
|---|---|---|
| **FJ-A** | How large should a wave be, in money? | Spend is founder-reserved. Set a per-month and a per-wave ceiling **once**, and the office sizes waves against it and never asks again. |
| **FJ-B** | Which competing pointer claim wins, PR #6 or PR #7? | An authority act, not a compilation result. The resolver correctly refuses, and that refusal is right behaviour rather than a gap. |
| **FJ-C** | Is indefinite provider-side retention of founder-intent material acceptable? | Risk appetite, not a technical question. |
| **FJ-D** | Is the requirement **open weights**, or **runnable by us**? | Different properties with different architectures behind them, and only the second delivers sovereignty. A named model in the directives is roughly 2.78 trillion parameters — the weights are public and no laptop will ever run them. |
| **FJ-E** | Is GitHub acceptable as sole host of canonical state? | A concentration risk you should price: GitHub is simultaneously canonical state, primary execution and the corroborating execution domain. A periodic `git bundle` is the zero-cost interim and the office will do it regardless. |
| **FJ-F** | Should a delegated sweep's acceptance threshold be set once, in advance? | Accepting work at a stated confidence level is risk appetite — but it can be decided **once**. Declare the acceptable error rate and the office self-accepts under the rule and informs you, instead of asking every time. |

---

## Where this guide's own evidence lives

| Artefact | What it holds |
|---|---|
| [`w5-agentic-office/OFFICE-SEAT-REGISTER-20260822-v001.json`](w5-agentic-office/OFFICE-SEAT-REGISTER-20260822-v001.json) | The eight seats, machine-checked as a strict refinement of the w4 partition |
| [`w5-agentic-office/INTERFACE-EVIDENCE-20260822-v001.json`](w5-agentic-office/INTERFACE-EVIDENCE-20260822-v001.json) | 61 documentation pages with URL, status, bytes, sha256, fetch time, and the section each supports |
| [`w5-agentic-office/CONCURRENCY-EVIDENCE-20260822-v001.json`](w5-agentic-office/CONCURRENCY-EVIDENCE-20260822-v001.json) | The account census and what it does and does not establish |
| [`w5-agentic-office/SCALE-AND-CEILING-20260822-v001.json`](w5-agentic-office/SCALE-AND-CEILING-20260822-v001.json) | Measured vs documented vs inferred, and the ranked ceilings |
| [`w5-agentic-office/BLOCKERS-20260822-v001.json`](w5-agentic-office/BLOCKERS-20260822-v001.json) | Nine blockers and six judgment items, in full |
| [`w5-agentic-office/prompts/`](w5-agentic-office/prompts/) | Paste-ready briefs for every seat and every automation |
| `receipts/so02/2026-08-22/oe-w5-agentic-office/` | Raw command output and the manifest covering every file |

### Check this guide rather than trusting it

```bash
cd workstreams/so02/control-plane/operating-environment/w5-agentic-office
python3 tools/officectl.py check          # 14 invariants over the seats
python3 tools/negative_tests.py           # 20 failure modes, each rejected
python3 tools/build_seat_register.py --root ../../../../.. --out /tmp/rebuilt.json   # deterministic
bash    tools/refetch_docs.sh             # re-fetch and re-hash every cited page
bash    tools/capture_run_evidence.sh "$(git rev-parse --show-toplevel)"
cd ../w4-platform-roles && python3 tools/rolectl.py check && python3 tools/negative_tests.py
```

### What this guide folds in rather than restates

- `l1-cursor-baseline/` — 18 reproduced capability records, 10 ranked gaps, the control-surface activation programme
- `w2-cursor-config/` and the applied `.cursor/` tree — hooks with 69 proofs, rules, the evidence skill, the MCP policy, and the finding that the environment file is inert
- `w3-credential-estate/` — the integration auth matrix and the route to the key that already exists
- `w4-platform-roles/` — the decision-class partition and the 14 invariants that are this office's constitution
- `l4-currentness-recovery/` — the admission ladder and `currentctl.py`
- `l5-chatgpt-scale/` — 31 differentiated functions and 12 typed project slots
- `tools/` — `lane_guard.py` and `evidence_integrity.py`
- `SYNTHESIS-OE-20260822-v001.md`, and `FOUNDER-TRANCHE-01.md` under its supersession header

### What this guide deliberately does not do

It binds no tool, no model and no architecture — every recommendation carries its
evidence and its risk, and the choice stays yours. It imposes no fixed number of
agents, projects or teams, and it treats no raw count as success. It asks you to
paste no secret anywhere. It removes no control that caught a real defect in this
estate, and it inherits no limit that an assistant invented.

And it does not accept itself. This document is `READY_TO_COMMIT` — a proposal for
admission. The seat that can say otherwise is `S-ACCEPT`, and it has not run
against this yet.
