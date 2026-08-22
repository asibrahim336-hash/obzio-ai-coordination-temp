# The scaled ChatGPT-account operating programme

**Lane:** `OE-L5-CHATGPT-SCALE` · **Commission:** `COM-CUR-ENV-01-20260822-v001`
**Parent fence:** `732dd424f8bb646e` · **Immutable start SHA:** `fe0a595206e5986de7eaac6cabc619215a1eb81b`
**State:** `READY_TO_COMMIT` — this is a proposal for founder admission, not a binding.
**Companion register:** `FUNCTION-TOPOLOGY-REGISTER-20260822-v001.json` (machine-checked)

## Evidence discipline used throughout

| Label | Meaning in this document |
| --- | --- |
| `DIRECTLY_REPRODUCED` | This lane ran the command or fetched the URL. Command, URL and date recorded here or in `OPENAI-API-SURFACE-FINDINGS-20260822-v001.md`. |
| `DOCUMENTED` | Stated by an official source; URL recorded. |
| `HYPOTHESIS` | Untested inference by this lane. |

**The design in this document is `HYPOTHESIS`.** The topology, the partition and
all 31 function warrants are proposals. Three things inside it are not:

- the partition's disjointness and the six rejected failure modes are
  `DIRECTLY_REPRODUCED` (Section 5);
- the OpenAI and ChatGPT product-surface facts it relies on are `DOCUMENTED` or
  `DIRECTLY_REPRODUCED`, with URLs and fetch dates in the findings file;
- the account observations it builds on (11 projects, 61 chats in
  `OBZIO — STRATEGIC CONTROL`, 121 ordinary sidebar chats, `CANNOT_ASSESS`
  surfaces, one lane read across 27 messages) are **founder-supplied and treated
  as established input**. This lane did not authenticate to ChatGPT and did not
  reproduce them.

---

## 1. The diagnosis

The account is not failing because it has too many projects. It is failing
because of one structural mistake with three symptoms.

**The mistake: a ChatGPT project is being used as four things at once.** A
project is a *context container*. It is being asked to also carry a *mandate*
(what may be decided), a *run* (a unit of work) and a *record* (what happened).
When one object carries all four, there is nowhere to write down that two
projects share a mandate, and nowhere to write down that a project produced
something that has not been accepted. The failures follow mechanically:

| Symptom | Why the container design causes it |
| --- | --- |
| Overlapping whole-operation commissions | If the mandate lives inside the container, the only way to widen a mandate is to widen the container. Every long-running project drifts towards "the whole operation" because nothing external bounds it. |
| Conflated `proposed / launched / observed / completed / accepted` | One container, one apparent status. The standing of a *mandate* and the standing of a *unit of work* get written into the same word. |
| 121 unclassified sidebar chats | A chat born outside a project has no mandate at all, so nothing can ever claim it, and the only available triage layer is the founder. |
| `OBZIO — STRATEGIC CONTROL` holding 61 chats | The archetype of the first symptom. A container that owns everything owns nothing in particular. |

**The fix is to take the mandate out of the container.** Mandates live in the
repository as *decision-class leases*. A project becomes a runtime binding of
one or more leases, and the binding is visible inside the project itself. Once
the mandate is external and machine-checkable, "the whole operation" stops being
a claimable mandate, and mandate-state and work-state can no longer be written
into the same field.

---

## 2. What the account is being asked to become

The founder's constraint is decisive: *the current account is already a
substantial agent platform; do not reduce it to evidence review or a passive
founder interface.* Everything below is designed against that.

The account's genuine advantages over an API-only route are real and worth
naming, because they determine what belongs there rather than in Cursor or in
the API:

- **Long-lived shared context per project** — instructions, Sources and chats
  that persist across work. `DOCUMENTED`: `https://learn.chatgpt.com/docs/projects.md` (fetched 2026-08-22).
- **A cadence engine** — Scheduled tasks, standalone or inside a chat, with
  RRULE recurrence, able to invoke skills and plugins. `DOCUMENTED`:
  `https://learn.chatgpt.com/docs/automations.md` (fetched 2026-08-22).
- **Reusable capability packaging** — skills as a directory with `SKILL.md`,
  progressive disclosure, explicit `@` invocation or implicit matching by
  description. `DOCUMENTED`: `https://learn.chatgpt.com/docs/build-skills.md` (fetched 2026-08-22).
- **Delegation inside a chat** — subagent workflows that run parallel agents and
  return summaries rather than raw intermediate output. `DOCUMENTED`:
  `https://learn.chatgpt.com/docs/agent-configuration/subagents.md` (fetched 2026-08-22).
- **Connected tools** — plugins and MCP servers bringing context and actions from
  other services into Chat and Work. `DOCUMENTED`: `https://learn.chatgpt.com/docs/plugins.md` (fetched 2026-08-22).

None of these are reachable from the Responses/Conversations API. That is the
central asymmetry of this whole programme and Section 12 states it plainly.

---

## 3. The admission method: the Differentiation Warrant

The brief supplies a twelve-field schema per function. That schema is retained
in full — as the **operating record**. It is not, however, a good *gate*,
because a descriptive schema asks a function to describe itself and every
proposed function describes itself well. Overlapping whole-operation commissions
are written by competent authors.

The gate is therefore adversarial and pre-registered. A function is admitted
only if its warrant defeats three rivals and pre-commits to its own refutation.

| Gate | The question | Rejected if |
| --- | --- | --- |
| 1. Null test | What decision changes if this function does not exist? | Nothing. |
| 2. Absorption test | Name the closest admitted function. Why can it not absorb this inside its current lease? | It can — expand the incumbent instead. |
| 3. Displacement test | Which founder verbs does this remove: relay, retrieve, compare, merge, monitor, triage, remember, arbitrate? | None, unless the function is constitutional. |
| 4. Pre-registered falsifier | What observation, recorded *before* launch, would prove this is not working? | Absent or unobservable. |
| 5. Exit condition | What makes it stop, retire or fold back in? | Absent. Every function is mortal by construction. |

Two further properties make this stronger than the schema alone:

**Cohort admission with a denominator.** Warrants are admitted in waves, and each
wave publishes drafted / admitted / rejected with a reason per rejection. A wave
that reports only its admissions is itself a rejection cause. This is the direct
antidote to a register that only ever grows.

**The absorption test is the anti-proliferation control.** It is what stops the
answer to "we need more functions" from being "add more functions". In this
register the absorption test is what forces, for example, evaluation and
acceptance apart (Section 4) and what would have merged them if the argument had
failed.

---

## 4. The functions

**31 functions over 32 internal decision classes.** The number is not chosen; it
is derived. Every decision class that actually exists in this operation needs
exactly one owner, and a function with no class fails the null test. Change the
class list and the function count changes with it.

Fifteen come from the founder's baseline. Sixteen are **discovered** — each one
justified by a specific thing the evidence shows is unowned today.

### 4.1 The discovered functions and the evidence that demands them

| Function | Decision class it holds | Evidence that nothing owns this today |
| --- | --- | --- |
| `F-CLEARING` — commission clearing and decision-rights registrar | `DC-DECISION-RIGHTS` | Overlapping whole-operation commissions exist. That is only possible if nothing owns the partition. |
| `F-INTAKE` — founder intake, disambiguation and typing | `DC-INTAKE-TYPING` | The repository records exploratory names being converted into a founder setup batch that had to be halted. The failure happened at intake, not later. |
| `F-QUESTIONS` — open-question custody | `DC-OPEN-QUESTIONS` | Open questions currently live in the closing paragraphs of returns and evaporate when the chat scrolls. |
| `F-LOAD` — founder-load accounting | `DC-FOUNDER-LOAD` | "Do not make the founder a relay" is a standing directive that nothing measures. Unmeasured constraints are violated silently. |
| `F-CENSUS` — surface census and locator custody | `DC-SURFACE-INVENTORY` | The counts 11 / 61 / 121 came from a manual founder-side pass, and `runtime-surface-locators.json` still carries `OWNER_CAPTURE_REQUIRED` rows. |
| `F-SALVAGE` — back-catalogue salvage and disposition | `DC-SURFACE-DISPOSITION` | 182 chats are unclassified and the founder has ruled out being the triage layer. |
| `F-BLINDSPOT` — non-assessability management | `DC-BLINDSPOT-STATUS` | `CANNOT_ASSESS` surfaces exist with no owner, no retry route and no expiry. Unowned blind spots decay into assumed-clean. |
| `F-SUPERSEDE` — supersession and contradiction custody | `DC-SUPERSESSION` | The repository contains a corrected provider ID where the wrong one had already propagated. Nothing owns the change graph. |
| `F-ROUTE` — route qualification and degradation | `DC-ROUTE-QUALIFICATION` | A route has already been lost to quota exhaustion with no qualified successor; locators record routes as qualification-pending. |
| `F-QUOTA` — runtime headroom and stop conditions | `DC-QUOTA-HEADROOM` | Same event, different cause: consumption was invisible until it failed. Distinct from procurement, which asks what to buy. |
| `F-PROVIDER-AUDIT` — provider-claim audit | `DC-PROVIDER-CLAIM-STATUS` | The operation is required to treat provider completion as observation, but nothing performs the corroboration that turns an observation into a fact or a contradiction. |
| `F-PORTABILITY` — provider-independence verification | `DC-PORTABILITY` | Portability is a standing requirement that nothing tests, so lock-in accumulates invisibly until a route dies. |
| `F-WAVE` — wave learning and mechanism change | `DC-WAVE-LEARNING` | The directives require every wave to end in a changed live mechanism. Nothing verifies it, so waves can close on documents. |
| `F-REDTEAM` split from `F-ACCEPT` | `DC-ADVERSARIAL-FINDING` | Acceptance only tests the failures it imagines. An adversary with the opposite incentive is a separate function, not a mood. |
| `F-EVAL` split from `F-ACCEPT` | `DC-EVAL-DEFINITION` | If the gate also defines the measure, the measure moves to fit the artifact. |
| `F-DISCLOSURE` registered as deferred | `DC-DISCLOSURE` | The founder deferred this workstream. Registering it as *deferred with an owner and an activation trigger* is what stops another function improvising a disclosure policy in the gap. |

The last one is the subtlest and worth stating explicitly: **registering a
deferred function is itself a mechanism.** `F-DISCLOSURE` holds a lease, builds
nothing, consumes no budget, and its only test is that nothing was built. It
exists so that the gap it leaves cannot be filled by accident.

### 4.2 Where the absorption test did real work

Four pairs look mergeable and are not. Each separation is a decision, with a
reason a reviewer can attack:

- **`F-EVAL` / `F-ACCEPT`.** Evaluation defines the measure; acceptance applies
  it to a specific artifact and must be able to reject something the measure
  would pass. Merged, the gate can be moved to fit the artifact in front of it.
- **`F-ACCEPT` / `F-REDTEAM`.** Acceptance is incentivised to close work; red
  teaming is incentivised to break it. Housed together, the adversarial
  relationship that produces the finding disappears. Their acceptance owners are
  each other, and neither may close a re-adjudication it lost.
- **`F-QUOTA` / `F-ECON`.** Quota asks whether to keep running today and when to
  stop. Economics asks what the options cost. Merged, every operational limit
  becomes a purchasing conversation and the stop is delayed.
- **`F-CENSUS` / `F-SALVAGE`.** Census says what exists and where. Salvage says
  what happens to it. Merged, an inventory gap can be resolved by disposing of
  the item.

The full warrants, authorities, sources, tests, acceptance methods, costs and
wave-learning contributions for all 31 are in the register JSON, one record
each.

### 4.3 What is deliberately *not* claimed here

The register lists eight decision classes held **outside** this account and
therefore unclaimable by any ChatGPT function:

| Class | Held by | Why it matters |
| --- | --- | --- |
| `DC-PROGRAMME-SHAPE` | founder | Reserved. This is the structural block on whole-operation commissions. |
| `DC-OPENV-ARCHITECTURE` | Cursor under `COM-CUR-ENV-01` | ChatGPT does not select the operating-environment architecture. |
| `DC-OPENV-STAGED-GUIDANCE` | Cursor under `COM-CUR-ENV-01` | ChatGPT does not issue a founder setup batch for this scope. |
| `DC-SPEND-COMMITMENT` | founder | Functions compare and recommend; only the founder commits. |
| `DC-IDENTITY-AND-SECRETS` | founder | No function requests a secret in chat or stores a credential value. |
| `DC-THIRD-PARTY-OUTREACH` | founder | Prohibited to all functions. |
| `DC-SW-REACTIVATION` | founder | SW stays paused, unmessaged, unconfigured. |
| `DC-PO-LANE-EXECUTION` | PO lanes | Out of scope, untouched. |

This is how `CHATGPT-SIR-01`'s "do not compete with Cursor's assigned
operating-environment development" stops being an instruction and becomes an
admission-time rejection.

---

## 5. The anti-overlap mechanism (reproduced, not asserted)

**A function is defined by the decision classes it may change, not by the topic
it discusses.** Topic overlap is permitted and encouraged — two functions may
both research models. Decision overlap is arithmetically impossible.

Six components:

1. **Decision-class partition.** Every class has exactly one holder. All
   `decides` sets are pairwise disjoint.
2. **Reserved class.** `DC-PROGRAMME-SHAPE` cannot be claimed. A whole-operation
   commission *is* a commission that claims programme shape, so it is rejected at
   admission by definition rather than discovered later by contradiction.
3. **External holders.** The eight classes in Section 4.3 are listed and
   unclaimable.
4. **Leases with fence tokens.** A holder holds a lease, not a property.
   Changing a holder requires an explicit supersession record naming the previous
   holder and fence. Two functions cannot silently come to share a class.
5. **Minimum-one rule.** A function with an empty `decides` set is decorative and
   fails the null test.
6. **Overlap ledger.** When a non-holder touches a held class it files a
   contribution record — class, holder, evidence label, agree or dissent. This is
   what makes collaboration visible instead of inferred.

### The reproduction

`DIRECTLY_REPRODUCED`, 2026-08-22, from `/workspace` at this branch:

```bash
python3 workstreams/so02/control-plane/operating-environment/l5-chatgpt-scale/scripts/check_function_register.py
python3 workstreams/so02/control-plane/operating-environment/l5-chatgpt-scale/scripts/negative_tests_register.py
```

The first checks twelve invariants over the committed register and exits `0`
with `PASS: all 12 invariants hold`. The second mutates the register into six
failure modes and asserts each is rejected:

| Test | Failure mode injected | Invariant that fired |
| --- | --- | --- |
| NT1 | two functions claim `DC-CAPABILITY-BACKLOG` | I1, I2, I5 |
| NT2 | a function claims `DC-PROGRAMME-SHAPE` | I3, I5, I12 |
| NT3 | a producing function names itself its own acceptance owner | I9 |
| NT4 | a function admitted with an empty `decides` set | I1, I4 |
| NT5 | an assurance container starts hosting producing functions | I8 |
| NT6 | a warrant admitted with no pre-registered falsifier | I10 |

All six were rejected; the script exits `0` with
`PASS: all 6 failure modes rejected by the validator`.

This is the difference between advice and a mechanism. NT1 and NT2 are literally
the two failures the founder identified in the account today, and they now fail
a check rather than a review.

---

## 6. Making overlap, authority, provenance and conflict visible

Roles are not silos here — functions collaborate constantly. That is only safe
if four things are visible **inside the runtime surface where the work happens**,
not only in the repository.

**The header contract.** The first block of every ChatGPT project's instructions
is a generated block containing `slot_id`, hosted `function_id`s, each function's
`decides` / `informs` / `must_not_decide`, `source_path`, the short SHA of the
register commit that generated it, `lease_fence`, `return_route_class` and
`acceptance_owner`.

The SHA is what makes this work. A project whose header SHA does not match the
current register is flagged `STALE_BINDING` by the currentness check and cannot
produce an admissible return until re-bound. **Project instructions become a
derived artifact of the repository rather than a competing source of authority.**
That is the same mechanism that keeps provider memory non-canonical (Section 8),
applied to the other place where provider state quietly becomes authority.

**The chat opening contract.** Every chat's first message states `function_id`,
`decision_class`, `output_lifecycle_state` and the evidence labels it may use. A
chat without this is `UNBOUND`, cannot produce an admissible return, and gets
swept by `F-SALVAGE` like any other unclaimed content. This is what stops the
121-chat problem from regenerating: a new unbound chat is not a new orphan, it is
a known category with a known disposition.

**The overlap ledger.** Rows of `decision_class`, `holder_function`,
`contributing_function`, `wave`, `evidence_label`, `position` (agree / dissent /
abstain), `disposition`, `conflict_id`. A dissent that was overruled is still in
the ledger.

**Conflict as a first-class object,** with states `OPEN`,
`RESOLVED_BY_EVIDENCE`, `RESOLVED_BY_FOUNDER`, `STANDING_DISSENT`. One rule does
most of the work: *a conflict may not be closed by the holder alone when the
contributor's position was `DIRECTLY_REPRODUCED` and the holder's was
`HYPOTHESIS`.* Evidence outranks ownership.

---

## 7. Two lifecycles, because the account conflated two different things

`proposed / launched / observed / completed / accepted` got conflated because one
axis was carrying two questions: *what is the standing of this mandate?* and
*what is the standing of this unit of work?* Separating them makes the
conflation unrepresentable.

**Function axis (the mandate):**
`DRAFTED → ADMITTED → BOUND → OPERATING → SUSPENDED → SUPERSEDED / RETIRED`,
plus `REGISTERED_DEFERRED`.

**Output axis (each unit of work):**
`PROPOSED → COMMISSIONED → DISPATCHED → PROVIDER_OBSERVED → RETURNED → INDEPENDENTLY_CHECKED → ACCEPTED / REJECTED / QUARANTINED`.

Five rules carry the weight:

1. A producing function may write states **up to `RETURNED` and no further**.
2. A transition to `INDEPENDENTLY_CHECKED` or `ACCEPTED` where actor equals
   producer is rejected by the validator. Self-acceptance is not a policy; it is
   unrepresentable.
3. `PROVIDER_OBSERVED` means the provider says it finished. It never implies
   `RETURNED`, never satisfies an acceptance gate, and a provider completion with
   no repository artifact stays at `PROVIDER_OBSERVED` indefinitely and is
   reported that way.
4. Nothing moves backwards from `ACCEPTED` except through a red-team
   re-adjudication.
5. The two axes are separate fields and may never be written into one status
   string.

### The counting rule

**The only throughput number is `ACCEPTED`,** issued by the holder of
`DC-ACCEPTANCE`. Everything else is inventory and must be reported with its
accepted denominator — `RETURNED 14 / ACCEPTED 3`, never `14 returns`.

Explicitly not success: number of projects, number of agents, number of chats,
number of functions admitted. A bare count anywhere in a return is a reporting
defect.

---

## 8. Provider memory never becomes canonical

The rule is easy; the enforcement is the design.

**Context contract.** Every function declares what it may load — repository
artifacts by path and commit, project Sources with recorded provenance,
explicitly pasted text — and what it may not treat as authority: ChatGPT memory,
chat recall, drifted project instructions.

**The cold-instance replay test.** Open a fresh chat in the same project with
memory disabled, supply only the repository artifact list, re-derive the
decision. Same decision: pass. Different decision, or unreachable: the original
decision was memory-dependent and is rejected.

This is runnable rather than aspirational because the control exists:
ChatGPT memory is managed at **Settings → Personalization**, and the desktop app
exposes per-chat memory control. `DOCUMENTED`:
`https://learn.chatgpt.com/docs/customization/memories.md` (fetched 2026-08-22).
The same page states the principle the operation should adopt wholesale: *treat
memories as a helpful recall layer, not as the only source for rules that must
always apply.*

`F-KNOW` runs this test on the knowledge base each wave; `F-CONTINUITY` runs the
harder version — a clean clone with no chat and no provider memory reconstructing
the whole programme.

---

## 9. Return routes that do not run through the founder

Seven route classes, ranked by how little founder involvement they need. Each
function in the register names a primary and a degradation route.

| Class | What it is | Founder involvement | Status | Hard limit |
| --- | --- | --- | --- | --- |
| `R1-repo-native` | A runtime that can already write the repository returns a committed artifact. | none | `DIRECTLY_REPRODUCED` for this lane's own writes | Does not reach ChatGPT UI content. |
| `R2-openai-api` | Responses + Conversations: create, retrieve by ID, list items, background mode with webhooks. | one credential action, then none | credential-blocked; endpoints reachable, returning 401 | Addresses the API platform's own store only. |
| `R3-workspace-agents` | `POST api.chatgpt.com/v1/workspace_agents/{id}/trigger` starts a *published ChatGPT workspace agent* from outside the UI and returns a `chatgpt.com` conversation URL. | workspace admin enablement plus token | reachable, 401 without a token | **Dispatch only** — the agent's response cannot currently be retrieved through the API. |
| `R4-ui-connector-write` | A ChatGPT-side plugin or connector with repository write, so a UI-resident function commits its own return. | one install, then none | candidate, not qualified by this lane | Plan-dependent; must pass `F-ROUTE` before carrying traffic. |
| `R5-scheduled-pull` | A scheduled task re-runs a durable prompt on a cadence and re-emits through `R4`. | none after creation | documented feature, not qualified here | Provides cadence, not transport. Must be governed by `F-AUTOGOV`. |
| `R6-owner-export` | One-shot bulk export of ChatGPT data by the owner. | one action | owner action | A snapshot, not a route. |
| `R0-founder-relay` | The founder copies a result from one place to another. | every message | **classified as a defect** | Budgeted at zero for routine work. |

`R0` being a *named, budgeted defect* rather than an unspoken fallback is the
enforcement. `F-LOAD` holds the per-wave touch-point budget and can reject an
over-budget design and demand a route alternative; any function whose only route
is `R0` fails the displacement test at admission.

The combination that actually removes the founder from the loop for API-native
work is `R2` with `background: true` plus a `response.completed` webhook: the
work runs asynchronously, the completion notifies a server the operation
controls, and the result is retrieved by ID. Nobody polls. See
`OPENAI-ROUTE-ACTIVATION-PROGRAMME-20260822-v001.md`.

---

## 10. The 121 sidebar chats and the 61 project chats

**Nobody triages 182 items by hand — including delegated agents doing it one at a
time under founder supervision.** The mechanism is *disposition by default with
sampled appeal*, owned by `F-SALVAGE`.

**Step 1 — every admitted function publishes a claim predicate.** Keywords,
decision classes, date ranges. This is the only manual input, it is written once
per function, and it is a by-product of admission.

**Step 2 — the sweep assigns each chat to at most one claiming function.** Ties
resolve to the function that owns the relevant decision class. This is a batch,
high-volume, low-reasoning job — precisely the shape the Batch API serves at 50%
cost once `R2` is live (`DOCUMENTED`:
`https://developers.openai.com/api/docs/guides/batch.md`, fetched 2026-08-22),
though the *content* must arrive by a route that can read the UI (Section 12).

**Step 3 — default dispositions apply with no founder decision:**

| Disposition | Applies to | Reversible |
| --- | --- | --- |
| `OPERATE` | claimed, decision-bearing, owner active | n/a |
| `SALVAGE` | claimed, decision-bearing, content routed to `F-INTENT` or `F-KNOW` | n/a |
| `FREEZE_AS_EVIDENCE` | historical value, no live mandate | yes |
| `ARCHIVE_UNCLAIMED` | no decision-bearing content, no claimant | yes — restore from **Settings → Data Controls → Archived chats** |
| `QUARANTINE` | sensitive, or contested | yes |

**Nothing is deleted.** Deletion is a separate, later, explicitly authorised act.
This follows the repository's own rule that superseded material remains evidence.

**Step 4 — only three outcomes need attention,** and the third is the most
valuable output of the whole sweep:

- `CONTESTED` — two functions claim it and neither owns the class.
- `DECISION_BEARING_BUT_UNOWNED` — content that changes a decision no function
  owns. **This is evidence for a new function**, routed to `F-CLEARING` as a
  warrant seed. The back catalogue tells the register what it is missing.
- `SENSITIVE` — routed to `F-SECURITY`.

**Step 5 — the founder sees a fixed-size stratified sample, not 182 items.** The
sample covers the contested set, the unowned set, and a random draw from
auto-archived. The founder's single act is: *confirm or reject the sweep as a
whole.* If the sampled misclassification rate exceeds the threshold declared
before the sweep ran, **the whole sweep is rejected and re-run with corrected
rules** — it is never patched item by item. That is what makes delegated triage
trustworthy without item-by-item review: the founder audits the *process* at a
declared confidence, not the items.

**Then it never recurs.** The chat opening contract (Section 6) means a new chat
is born bound to a function. `F-SALVAGE`'s exit condition is exactly this: it
retires when the unswept backlog is zero and new chats arrive already bound.

### The 61 chats in `OBZIO — STRATEGIC CONTROL`

Same sweep, different container disposition. The container itself is the problem
(Section 1), so it is decomposed: its *mandate* is split into decision classes
distributed across the typed slots, and the *container* is frozen as evidence
with no new chats. Its 61 chats are swept exactly like the 121.

Freezing that container is not archiving the account. It is removing the single
object that made overlapping whole-operation commissions possible, while the
account gains eleven typed operating containers in its place.

---

## 11. The `CANNOT_ASSESS` surfaces

Owned by `F-BLINDSPOT`, with one governing rule: **`CANNOT_ASSESS` never counts
as assessed-clean, and never blocks the rest of the programme.**

Every non-assessable surface gets a dated record with five fields: what was
attempted, the exact failure mode, the route that would resolve it, the retry
trigger, and a **risk-conversion date** after which continued non-assessment
becomes a risk finding in its own right. Blind spots decay; unowned ones decay
into silence, and dated ones decay into escalation.

Two specific dispositions:

**Older project routes that would not render.** Recorded per project with the
client and route used. The resolution route is a *different client or route*, not
a retry of the same one — the desktop app and the web client are different
surfaces (`DOCUMENTED`: `https://learn.chatgpt.com/docs/app.md`, indexed at
`https://learn.chatgpt.com/llms.txt`, fetched 2026-08-22), and `F-ROUTE` owns
choosing which to qualify. If a cluster of failures shares one cause, `F-ROUTE`
qualifies the one route that clears the cluster rather than retrying each.

**The Scheduled interface.** This one is worth being precise about, because a
non-rendering interface is easily mistaken for an absent feature. **Scheduled
tasks are a documented, current ChatGPT capability**: a `Scheduled` view listing
active, paused and completed tasks and recent runs; standalone tasks that start a
new chat per run; in-chat tasks that return to the same chat with its context;
custom cadences including RFC 5545 RRULE; skills and plugins available to the
task; and an explicit statement that Codex CLI and the IDE extension do *not*
provide the Scheduled management interface — web and desktop do. `DOCUMENTED`:
`https://learn.chatgpt.com/docs/automations.md` (fetched 2026-08-22).

So the non-render is a **client or route problem, not a capability gap**. That
matters for the programme, because Scheduled tasks are `R5` — the cadence engine
that lets a UI-resident function re-run without the founder. `F-BLINDSPOT` holds
the record; `F-ROUTE` owns the retry; `F-AUTOGOV` will not let a single task run
until it has a declared premise, bounded fan-out and a proven stop condition.

---

## 12. What this programme honestly cannot do

**The OpenAI Responses and Conversations API does not read the founder's ChatGPT
UI.** It does not see the 11 projects, the 61 project chats, the 121 sidebar
chats, project instructions, project Sources, ChatGPT memory or the Scheduled
view. `/v1/conversations` is a *separate store belonging to the API platform
organisation*. Anything implying otherwise is wrong.

What would actually reach the UI surface, in descending order of directness:

| Route | Reaches | Requires | Verdict |
| --- | --- | --- | --- |
| **Compliance API** | ChatGPT workspace conversation and audit records, for export into an audit or investigation system | a ChatGPT Enterprise / Edu / Teachers workspace and an administrator role; the authenticated reference at `https://chatgpt.com/admin/api-reference` is the source of truth | The only OpenAI-native *read* route to ChatGPT conversation content. `DOCUMENTED`: `https://learn.chatgpt.com/docs/enterprise/compliance-api.md` (fetched 2026-08-22). Plan-dependent — a founder judgment, not a task. |
| **Owner data export** | a snapshot of the account's own data | one owner action in Settings → Data Controls | Good for the one-time back-catalogue sweep. Not a route. |
| **`R4` UI-resident connector with repository write** | whatever the chat can see, pushed out from inside | one install and authorisation on a plan that supports it | The most plausible ongoing return route for UI-resident functions. Unqualified. |
| **Workspace Agents API** | *starts* a published workspace agent and returns its `chatgpt.com` conversation URL | workspace admin enables Workspace agents and personal access tokens; token created in ChatGPT Admin → Access tokens | **Write-side only.** The docs state plainly that the agent's response cannot currently be retrieved through the API. |
| **Authenticated browser or computer operation** | everything a signed-in human sees | the halted browser/setup batch, and an architecture decision owned by Cursor | Out of scope for this lane and currently halted by founder correction. |

The practical consequence for the design: **UI-resident functions and API-native
functions are different populations with different routes.** The register does
not pretend otherwise — every function names its route class, and the functions
whose work lives in the founder's existing projects are the ones that depend on
`R4`/`R5`/`R6`, not on `R2`.

---

## 13. Mapping onto the existing 11 projects

### 13.1 An honest statement of what is known

- **11 projects are founder-reported.** This lane did not authenticate to
  ChatGPT and has not seen their names or IDs, with one exception:
  `OBZIO — STRATEGIC CONTROL`, identified by the founder as holding 61 chats.
- **The repository's launch sheet plans twelve lanes**, `CGPT-01` … `CGPT-12`,
  with specified project names (`workstreams/so02/control-plane/launch/CHATGPT-LANES-NOW.md`).
- **12 planned ≠ 11 observed.** That gap is itself a finding. Either not all
  twelve were created, or some of the 11 are unrelated to the launch sheet, or
  `OBZIO — STRATEGIC CONTROL` occupies one of the eleven slots. It is cheap to
  resolve — one census pass listing project names and IDs — and it is
  `F-CENSUS`'s first job.

So the mapping below is a **procedure plus a slot table**, not a fabricated list
of eleven names. Inventing the names would be exactly the "never invent a
locator" failure the repository already forbids.

### 13.2 The eleven operating slots

Slots are **typed containers, not functions**. A slot may host several functions
if and only if their decision classes are disjoint and its header declares them;
a function may span slots. This is what decouples the number of projects from
the number of functions, and it is why no fixed project count is imposed.

| Slot | Type | Hosts | Why these together |
| --- | --- | --- | --- |
| `P-HALL` | HALL | `F-CLEARING`, `F-CURRENT`, `F-SUPERSEDE`, `F-QUESTIONS`, `F-LOAD`, `F-WAVE` | The only container permitted to write the lease table. Produces no capability output, so it can never be its own acceptance subject. |
| `P-INTAKE` | INTAKE | `F-INTAKE`, `F-INTENT` | The front door. Separate from the hall so a live founder exchange never shares context with lease arithmetic. |
| `P-LEDGER` | LEDGER | `F-CENSUS`, `F-KNOW`, `F-PORTABILITY` | Durable state. High artifact volume, low conversation; the natural home for batch ingest. |
| `P-COLD` | COLD | `F-SALVAGE`, `F-BLINDSPOT` | The past and the unreachable. Separate so sweeping history cannot contaminate live production context. |
| `P-LAB-RESEARCH` | LAB | `F-RESEARCH`, `F-COMMERCIAL`, `F-ECOSYSTEM` | Disjoint classes that genuinely share sources. |
| `P-LAB-CAPABILITY` | LAB | `F-CAPDEV`, `F-PACK`, `F-CONTINUITY` | `F-CONTINUITY` tests packs it did not produce; the header records the separation inside the shared container. |
| `P-LAB-RUNTIME` | LAB | `F-MODELQUAL`, `F-ROUTE`, `F-QUOTA`, `F-AUTOGOV` | The runtime cluster and the highest consumer; the container declares its own reserve. |
| `P-LAB-OPS` | LAB | `F-REMEDIATE`, `F-SECURITY`, `F-ECON` | Operational hygiene and cost, deliberately outside assurance so remediation cannot grade itself. |
| `P-ASSURE-EVAL` | ASSURANCE | `F-EVAL` | Assurance containers host **no** producing function. Independence at the container level, before any individual verdict. |
| `P-ASSURE-ACCEPT` | ASSURANCE | `F-ACCEPT`, `F-PROVIDER-AUDIT` | Isolated context: reads committed artifacts only, never a producing chat. |
| `P-ASSURE-REDTEAM` | ASSURANCE | `F-REDTEAM` | Separate from acceptance so attacker and gate never share history or incentive. |
| `P-EVIDENCE-FROZEN` | FROZEN_EVIDENCE | — | Read-only custody. Receives `OBZIO — STRATEGIC CONTROL` and any other frozen project. No new chats. |

Eleven operate; the twelfth is frozen evidence. **The match to eleven reported
projects is a convenience for migration, not a design constraint** — the slot
count came from separation requirements, and if the census returns a different
number the migration changes, not the topology.

### 13.3 The assignment procedure

`F-CENSUS` produces the project list with IDs; `F-SALVAGE` and `F-CLEARING`
apply this rule to each project, in order:

1. **Does it already carry exactly one slot's worth of disjoint mandate, with
   history worth keeping?** → `REUSE_AS_IS`. Add the header contract. Its chats
   stay.
2. **Does it carry a coherent but different mandate?** → `REPURPOSE`. Container
   and history preserved; instructions replaced with the new header; existing
   chats swept and dispositioned; a supersession edge records the mandate change.
3. **Does it carry more than one slot's mandate, or an unbounded one?** →
   `SPLIT`. Mandate decomposed into classes, container frozen, chats swept.
4. **Is it historical with no live mandate?** → `FREEZE_AS_EVIDENCE`. Becomes a
   Source, no new chats.
5. **Is a slot left with no project?** → `NEW`. Create it with its header
   contract already in place.

### 13.4 The one assignment that is determined today

| Project | Disposition | What it involves |
| --- | --- | --- |
| `OBZIO — STRATEGIC CONTROL` (61 chats) | **`SPLIT` then `FREEZE_AS_EVIDENCE`** | Its mandate is decomposed across the constitutional and assurance slots. Its 61 chats go through the Section 10 sweep. The container is frozen into `P-EVIDENCE-FROZEN`, read-only, no new chats, retained as evidence. A supersession edge records where each part of its mandate went. |

Everything else is `PENDING_CENSUS`, which is the honest state.

### 13.5 What the migration actually involves

Reversible before irreversible; evidence before change. Each step names what to
capture, because an unrecorded migration step is a new blind spot.

| Step | Action | Reversible | Capture |
| --- | --- | --- | --- |
| M0 | `F-CENSUS` lists all projects with names and stable IDs; reconcile against the twelve planned lane names | yes | census rows, the 12-vs-11 reconciliation note |
| M1 | Commit the register; generate one header block per slot from it | yes | register SHA |
| M2 | Apply the assignment procedure; record a disposition per project | yes | disposition table with the rule that fired |
| M3 | Paste the header block into each `REUSE`/`REPURPOSE` project's instructions | yes | header SHA per project |
| M4 | Create `NEW` projects for unfilled slots, header first | yes | new project IDs into the census |
| M5 | Run the claim-based sweep over all chats | yes | per-item disposition, contested list, unowned list |
| M6 | Founder confirms or rejects the stratified sample **as a whole** | yes | sample, measured error rate, verdict |
| M7 | Archive `ARCHIVE_UNCLAIMED` chats | yes — restore path documented | archive log, one restore proving reversibility |
| M8 | Freeze `OBZIO — STRATEGIC CONTROL`; stop new chats there | yes | freeze record, supersession edges |
| M9 | `F-CLEARING` admits wave 1 warrants and publishes the denominator | yes | admission verdicts, rejections with reasons |
| M10 | Qualify one non-`R0` return route end to end before wave 1 produces anything | yes | probe transcripts both directions |

**M10 is the real gate.** Until one non-founder return route is qualified, every
function's return degrades to `R0` and the programme reproduces the problem it
was built to solve — a great deal of good work whose only transport is the
founder.

**Cost of the migration in founder actions:** M6 (one sample verdict), plus at
most one authorisation in M10, plus whatever M0 needs if no delegated route can
list the projects. That is the whole budget, and `F-LOAD` holds it.

---

## 14. Cost, intervention and the founder-load budget

Every function record carries `founder_touch_points_per_wave` with the verbs it
consumes, its runtime cost shape and its stop condition. Summing the register's
declared touch points gives the wave budget `F-LOAD` enforces; a function that
declares more than its warrant's displacement test justifies is rejected.

Three cost shapes are called out because they dominate:

- **`F-SALVAGE`** — high volume, low reasoning per item. The one place where a
  cheap high-throughput configuration and batch dispatch matter most.
- **`F-MODELQUAL`** — high consumption by design. It must run inside a reserve
  declared by `F-QUOTA`, and `F-QUOTA` fails closed: unknown headroom is treated
  as zero headroom for new work.
- **Assurance functions** — medium volume but high reasoning and, critically,
  *isolated context*. `F-ACCEPT` refuses to issue verdicts when it cannot obtain
  isolation, and records the refusal rather than lowering the bar.

No model is bound anywhere. Every `exact_model_configuration` in the register
reads `UNBOUND_FOUNDER_DECIDES`. `F-MODELQUAL` recommends with matched evidence,
denominators and explicit uncertainty; the founder binds.

---

## 15. How each wave improves the next

The compounding loop in the directives becomes enforceable through one function
and one refusal.

`F-WAVE` holds `DC-WAVE-LEARNING` and **will not close a wave without a retained
mechanism delta** — a named live mechanism, an observation before, an observation
after, and a retest in the following wave. A register-only, receipt-only,
schema-only or automation-only wave fails closure. That is the directive's
requirement made structural rather than exhortative.

Four learning channels feed it, each owned:

| Channel | Owner | What it changes next wave |
| --- | --- | --- |
| Admission denominator — drafted / admitted / rejected with reasons | `F-CLEARING` | The warrant template, written against observed rejection causes |
| Rejection causes from acceptance | `F-ACCEPT` | Producer pre-checks, so the commonest rejection is caught before submission |
| Escaped-defect rate — accepted artifacts that later broke | `F-REDTEAM` | Acceptance criteria absorb the escaped classes |
| Measure discrimination | `F-EVAL` | Measures that never discriminated are retired; the set stays small |

And each function's own record names its contribution — for example `F-SALVAGE`
rewrites its claim predicates from the previous sweep's error set rather than
adding rules; `F-ROUTE` qualifies a *structurally different* successor rather
than retrying the route class that failed.

---

## 16. Questions this lane cannot answer

These require founder judgment and are listed here rather than decided. They
belong in `F-QUESTIONS` on day one.

1. **Which ChatGPT plan is the account on, and is an admin-enabled workspace
   available?** This single fact determines whether `R3` (Workspace Agents) and
   the Compliance API exist at all, and therefore whether UI-resident functions
   can ever return without a connector. Everything in Section 12 branches here.
2. **Is a connector or plugin with repository write acceptable on this account?**
   It is the most plausible non-founder return route for UI-resident work, and it
   is a disclosure decision as much as a technical one.
3. **Do the 11 projects correspond to the twelve planned lanes?** Cheap to
   resolve, but it changes the migration arithmetic.
4. **What confidence level should the salvage sample carry, and what
   misclassification rate triggers rejecting a whole sweep?** This is the
   founder's risk appetite, not a technical parameter.
5. **What is the per-wave founder touch-point budget?** The register declares
   demand; only the founder can set supply.
6. **Should `ARCHIVE_UNCLAIMED` ever become deletion, and under what
   authorisation?** This programme never deletes. That is a deliberate default,
   not a permanent answer.
7. **Does the earlier Qwen / Kimi / DeepSeek / Grok allocation still bind?** The
   directives say the role-scope correction neither deletes nor renews it.
   `F-MODELQUAL` cannot recommend into an unresolved allocation without either
   re-opening a settled decision or ignoring one.

---

## 17. What this lane did not do

- Did not authenticate to ChatGPT, obtain any credential, or sign up for
  anything.
- Did not create, rename, freeze or archive any project or chat. Sections 10 and
  13 are specifications for an owner or a UI-resident function to execute.
- Did not verify the 11 / 61 / 121 counts. They are founder-supplied.
- Did not bind a model, an architecture, a plan or a stack.
- Did not touch SW, PO-01, PO-03, MANUS, any protected branch, or any pull
  request.
