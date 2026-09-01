# Platform role architecture

Lane `OE-W4-PLATFORM-ROLES` · commission `COM-CUR-ENV-01-20260822-v001`
Governing input: `FOUNDER-AUTHORITY-20260822T2225Z.json`
State: `READY_TO_COMMIT`. A proposal for admission, not a self-declared binding.
This binds no company strategy and names no model or architecture as bound.

The structured register is `PLATFORM-ROLE-REGISTER-20260822-v001.json`:
5 platforms, 36 decision classes, 26 functions, 8 return routes, 8 explicit
overrules of earlier lanes, 6 items reserved for founder judgment. It is
validated by `rolectl.py` against 14 invariants, with 14 of the 20 negative tests
(`NR1`–`NR9`, `NL1`–`NL5`) proving those invariants actually reject.

---

## 1. The method: roles from asymmetries, not from hierarchy

The instruction was to decide roles *from capabilities* rather than inherit a
proposed structure. So the question for each platform is not "what has it been
doing" but: **what can this platform do that no other platform in the estate
can?** A role built on a shared capability is an org chart. A role built on an
asymmetry is an architecture, because it survives the platforms changing.

Applying that test produces a different shape from the inherited one, and the
difference concentrates on ChatGPT — which had been assigned evidence review, a
task with no asymmetry behind it at all, while its actual unique capability sat
unused.

One consequence runs through everything below. `FB-07` holds that no provider
holds canonical state; the repository is canonical and runtimes stay
substitutable. So every role here is a role over **work**, never over **state**.
That is what makes the architecture indifferent to which provider is healthy
this week, and it is why every function in the register must name a substitution
route (`V7`, invariant `I13`) — the concrete form of `FB-09`'s prohibition on
exclusive dependency. Without a named substitute, dependency accumulates
silently until a route dies and the estate discovers it had one.

## 2. The five platforms

### Cursor — execution and acceptance platform of record

Cursor's asymmetries, all `DIRECTLY_REPRODUCED`:

- It writes the canonical store directly and provably. `R1` GitHub
  immutable-SHA custody is the one route that survived independent challenge —
  a fresh clone fetched the evidence commit and matched all 13 listed entries.
- It is **already** a multi-agent platform: nine top-level cloud agents on this
  repository, four distinct exact model configurations, two model families, one
  account. A fifth configuration exists below the top level.
- A single run holds isolated subagents, each in its own worktree, branch and
  namespace. This lane is one of them.
- It has a full container runtime for hermetic replay with no network and no
  inherited credentials: Docker Engine 29.1.4 on `127.0.0.1:2375`. There is no
  `docker` CLI, which is why it went unnoticed.
- Egress is unrestricted, so no allowlist change gates any route proposed here.

So Cursor is where work executes and where acceptance is constituted. The
correct unit of dispatch is an **agent group** — several lanes, distinct model
configurations, isolated worktrees, one deterministic shared-state writer
(`EC-10`) — not a single operator interface addressed through one entry agent.
That last framing is `AI-19`, removed, and it is contradicted by the nine agents
already running.

Two capabilities are present but not reachable by an agent: browser/computer
control (Chrome 148 headless and a live VNC display exist; no agent-facing tool
does) and Cursor's own Agent API (`/v1/agents`, `/v1/models` and others return
401 rather than 404, so it is credential-blocked, not unsupported). These are
unlocks, not absences.

### ChatGPT — discovery, integration and authority-capture platform

This is where the architecture departs most sharply from the inherited one.

ChatGPT's asymmetry is not reasoning, and it is not evidence review. It is
**access**. It is the only surface in the estate holding the founder's
authenticated context — dozens of projects, hundreds of chats — and the only one
with connectors and plugins reaching Ahmed/Obzio systems Cursor cannot touch. It
also runs on the founder's own cadence, in the place the founder already is.

Assigning that platform to review evidence Cursor produced spends a unique
capability on a task any lane could do. Its role here is instead: discover and
verify Ahmed/Obzio's existing accounts, integrations, plugins, connectors, tools
and context, and align them so that **Cursor receives maximum useful authorised
access**. Every credential-blocked route in this estate is blocked on something
discoverable inside ChatGPT's reach rather than on something that must be built.

ChatGPT is a platform, so it operates at platform scale: multiple projects above
the ten-project floor, multiple models, Work agents, connectors, skills and
scheduled cadence, holding decision classes of its own rather than only
supplying evidence.

### GitHub — custody, plus a second execution domain and an unused event substrate

GitHub is the canonical store, and `EC-11` is the rule that keeps that meaningful:
provider completion without a committed artifact is `PROVIDER_COMPLETED_UNCOMMITTED`,
never `DURABLE`.

Two things about GitHub are underused. First, it is not only custody — Actions
genuinely executed the bytes **on another machine**, which makes it the cheapest
second execution domain the estate has, and §4 gives that a specific job. Second,
Issues are an event substrate the agent does not use at all; they are the obvious
home for the conflict objects in §5. Issues currently return 403, which is a fact
about the present token and not an argument against the design — that is `AI-12`,
removed, with the grant decision left to the founder.

The risk is concentration: GitHub is simultaneously canonical state, primary
execution and the corroborating execution domain. Two cheap mitigations exist —
a second remote, or a periodic `git bundle`. The bundle needs no new account and
no founder act, which is why it is listed first. Whether that is sufficient is
`FJ-06`.

### SW — paused, and planned as a producer

SW is not messaged, operated, configured or made central here. Planning its
future role is permitted, so: when it returns, SW's asymmetry is **fanout** —
a high-volume factory producing candidate mechanisms.

That determines its position precisely. A high-fanout producer is valuable only
under acceptance it does not control, so SW is a producer whose output enters
through the same acceptance gate as everything else, and it is never a
coordinator. Volume without an independent gate is how an estate accumulates
plausible artifacts nobody verified — which `EC-14` already caught in a milder
form, with eight of sixteen workstreams claiming more than their evidence
supports.

### Open and local model routes — the substitutability proof

Their role is not primary execution. It is to make `FB-07` and `FB-09`
enforceable rather than aspirational, by proving the estate can run on a
substitute.

The important distinction is that **open weights are not the same as a runnable
route**. What the estate needs is an adapter boundary thin enough that a
different model family can be swapped behind it. Nearest-term that is a hosted
open-weight route, which supplies a second cognition domain for the residual
acceptance class in §4; later it can be a local plane. Whether the founder's
requirement is *open weights* or *runnable by us* is a real fork with different
architectures behind it, and it is `FJ-05` rather than something this lane
should quietly decide.

## 3. Who owns founder-intent capture

**ChatGPT captures, the repository holds custody, Cursor compiles and enforces.**
Capture, custody and interpretation-of-record are three different jobs, and the
common failure is to award all three to whichever platform does the first.

Capture must happen where the founder actually is, and `FB-14` requires the
interface to be voice-first with semantic strengthening and read-back of any
consequential interpretation **in the same exchange**. Cursor cloud agents are
asynchronous, have no microphone, and cannot interrupt — they structurally cannot
do read-back-in-the-moment. ChatGPT can. So capture is ChatGPT's.

Custody cannot also be ChatGPT's, because `FB-08` states plainly that provider
memory is never constitutional authority. A captured intent becomes binding only
once it is a typed, durable event in git.

Interpretation-of-record is Cursor's, because interpretation must be checkable
against the whole estate and enforced by mechanisms — the validators in this
lane are examples — and that requires the platform that writes the canonical
store.

This split has one unresolved dependency: capture in ChatGPT is only complete
when the captured intent reaches git. Today no qualified ChatGPT-to-repository
write route exists. That is `FJ-01`, the highest-leverage single unlock for
ChatGPT in the whole architecture. There is a cheaper possibility worth testing
first — if a GitHub connector is already available on the account's plan, ChatGPT
could reach the canonical store through the existing `R1` route rather than
needing a bespoke connector. That is a `HYPOTHESIS`, and confirming it is exactly
ChatGPT's own discovery function, so it should be settled by discovery before it
is escalated as a founder decision.

## 4. Where independent acceptance lives

**In Cursor, multi-lane by default, and multi-provider only for one specific
class of claim.** This overrules L5, which placed acceptance in ChatGPT assurance
projects.

The reasoning is to stop treating "independent" as a property of the vendor and
decompose it into the properties actually required. Each one, and what it truly
needs:

| Property | Actually requires | Second provider? |
|---|---|---|
| Isolated context | a different run | No — L3 ran as a subagent in the same account and still refused |
| Separate criteria | commit ordering | No — criteria commit `9a390df3` precedes the verdict |
| Evidence custody | the repository | No — `AC-04` passed from a fresh clone |
| Distinct identity | a different exact model, ideally a different family | No — two families already live in this one account |
| Adversarial tests | an actor rewarded for finding a break | No |
| No self-modification of the verdict | write-scope fencing | No |

Not one requires a second provider. And this is not a theoretical result: an
acceptance lane ran **inside Cursor**, on a different model family from its
producer, with criteria committed beforehand and no founder in the loop, and it
**refused the root controller's own evidence** — after which two of its findings
were reproduced against the producer's own tooling. Separately, L4 reached the
same conclusion about a workstream without reading L3's findings. The arrangement
demonstrably produces genuine refusals.

Against that, a ChatGPT-resident acceptor would sit in the estate's most
context-saturated surface, which *reduces* context isolation, and its verdict
would have no qualified return route to custody.

There is one residual class that no arrangement inside a single provider covers:
**claims about the Cursor platform's own behaviour**. A defect in the runtime is
correlated across every lane inside it. The shared-worktree collision and the
exit-zero push are precisely this class — no number of Cursor lanes would have
been independent of them. For that class only: GitHub Actions is the cheapest
second *execution* domain and is already reproduced; a hosted open-weight route
behind the adapter boundary is the cheapest second *cognition* domain.

Several acceptance lanes may run and be compared, and comparison must not become
a new arbitration seat. So verdicts are **tallied by a rule declared in advance**
— any `REFUSE` stands — with concordance reported alongside its denominator. No
founder merges verdicts, because merging verdicts is an arbitration act and
`FB-05` keeps the founder out of evidence comparison.

## 5. How overlapping functions surface conflicts

Roles here are explicitly not silos: functions may overlap and collaborate where
that produces a stronger result, **provided authority, provenance, conflicts and
acceptance stay visible**. The founder instruction was to design that mechanism
rather than assert the principle, so it is executable and its rejections are
proven by negative tests.

The mechanism is an **authority envelope plus a contribution ledger**, enforced
by `rolectl.py`:

- **`V1` Authority envelope.** One function, one appointment, one authority
  statement, one runtime binding, one return/evaluation route. These are exactly
  the five fields `AGENTS.md` rule 8 already requires, so this satisfies the
  repository's own rule instead of competing with it.
- **`V2` Runtime is not authority.** A runtime binding records where a function
  executes; it never grants standing, and a rename never removes standing. A
  function whose only recorded authority is its runtime is rejected. This is
  `AGENTS.md` rules 3 and 6 made mechanical.
- **`V3` Decision-class partition.** Every class has exactly one holder; ten
  classes are reserved to the founder and unclaimable; a function with an empty
  `decides` set is decorative and fails admission.
- **`V4` Contribution ledger.** A non-holder touching a held class files a row:
  class, holder, contributor, wave, evidence label, position (agree / dissent /
  abstain), disposition, conflict id. **This is the part that makes overlap
  safe.** Overlap is permitted; *silent* overlap is not. Collaboration becomes a
  record rather than an inference, and an overruled dissent stays in the ledger
  instead of vanishing.
- **`V5` Conflict as a first-class object,** with states `OPEN`,
  `RESOLVED_BY_EVIDENCE`, `RESOLVED_BY_FOUNDER`, `STANDING_DISSENT`. Two rules
  matter. Evidence outranks ownership: a holder whose position is `HYPOTHESIS`
  may not close a conflict against a contributor whose position is
  `DIRECTLY_REPRODUCED`. And an unresolved conflict **never blocks work** — it
  attaches to the work as a standing dissent, so no lane idles waiting for a
  founder reply.
- **`V6` Acceptance independence**: no function is its own acceptance owner, no
  producing function sits in an assurance container, and the acceptance holder's
  own acceptance owner is the adversary.
- **`V7` Substitution route** required per function, as in §1.

Why this is estate-wide rather than ChatGPT-shaped: L5's overlap ledger made
overlap visible *inside* ChatGPT and listed everything else as "held elsewhere",
so cross-platform overlap was not representable and could not be checked. Here
every decision class in the estate has exactly one holder and every holder names
its platform, so an overlap between a Cursor lane and a ChatGPT project is the
same kind of object as an overlap between two projects.

Visibility also has to live in the surface where work actually happens, not only
in a register: the agent brief and `AGENTS.md`-reachable rules for Cursor, the
project instruction header for ChatGPT, and a fail-closed CI check for GitHub.

This is not decoration. Run live against the estate, the partition rule finds
`UNDIFFERENTIATED_COMMISSION_OVERLAP=7` and `COMMISSION_ID_COLLISION=1`,
including two commissions asserting whole-operation authority over the same
scope.

## 6. The 121 chats and 11 projects, without hand triage

`FB-05` forbids routing this to the founder as retrieval work, and 121 chats is
exactly the kind of backlog that quietly becomes a founder afternoon. Three
changes make it a delegated sweep, and two of them overrule L5.

**Run it from the owner's data export, not from an API route.** No API can read
the ChatGPT UI's conversation content. L5 noted the owner export and treated it
as a snapshot rather than a route — but for a one-time back-catalogue sweep, a
snapshot is the *correct* instrument. One owner action produces the export, and
everything after it is fully delegable to Cursor, which can process it in a
container at essentially zero further founder cost. This should be the primary
path, not a footnote.

**Replace confirmation-per-sweep with a pre-declared threshold.** Accepting a
sweep at a stated confidence level is a risk-appetite decision, so it stays
founder-bound — but it can be decided *once, in advance*. The founder declares
the acceptable error rate; if measured error on a stratified sample comes in
under it, the sweep self-accepts under the pre-declared rule and the founder is
informed rather than asked; if it comes in over, the sweep is rejected and
re-run. The founder's job shrinks from confirming every sweep to setting one
threshold.

**Salvage is recurring, not one-off.** L5 retires the salvage function when the
unswept backlog reaches zero and new chats arrive pre-bound. That exit is
unreachable: a chat-opening contract binds only chats spawned by bound functions,
while ordinary founder-initiated chats start unbound by construction. So the
backlog never reaches zero and the function never retires — a permanent cost
disguised as a migration. It is re-specified as an inexpensive recurring sweep
with a **rate target** rather than a zero target, and budgeted as ongoing so the
cost is planned rather than discovered.

The projects are handled by the same logic as `AI-14`: project count follows
function demand and separation requirements, above the founder's floor of ten. A
census returning a number other than 11 changes the migration, not the topology.

## 7. Where I overruled an earlier lane

Eight overrules are recorded in the register. The four that matter most:

1. **Acceptance moves from ChatGPT to Cursor** (overrules L5 §13.2). Evidence:
   acceptance already ran in Cursor on a different model family, refused the root
   controller's own evidence, and had two findings reproduced. A ChatGPT-resident
   acceptor would have less context isolation and no return route. §4.
2. **ChatGPT is reassigned from evidence review to discovery and integration**
   (overrules `CHATGPT-SIR-01` and L5's assurance framing). Evidence: its only
   asymmetry is authenticated access to the founder's accounts and connected
   tools, which evidence review does not use. §2.
3. **Salvage becomes recurring with a rate target** (overrules L5 §10). Evidence:
   the stated exit condition is structurally unreachable. §6.
4. **The fail-closed quota rule is replaced** (overrules L5 §14). Evidence:
   headroom is only observable at the top-level run layer, so "unknown headroom
   means zero headroom" is a permanent stop, and it contradicts the founder
   instruction to seek maximum effective capacity and queue above the ceiling.

I am authorised to overrule these lanes and not to overrule the founder. Where a
founder instruction and an earlier lane conflict, the founder text governs and
the lane position is recorded as superseded rather than deleted (`FB-23`).

## 8. What genuinely needs founder judgment

Six items. None is retrieval, monitoring, comparison, merging or coordination —
those are the estate's work. Each of these is either an owner act only the
founder can perform, or a risk-appetite question with no technically correct
answer.

| ID | Question | Why it cannot be delegated |
|---|---|---|
| `FJ-01` | May a ChatGPT connector hold repository write? | Disclosure and installation decision; the highest-leverage ChatGPT unlock |
| `FJ-02` | Authorise the existing Supabase integration so the Cursor API key already in Edge Secrets becomes reachable | Owner-scoped OAuth consent. Replaces the removed request for a *new* key |
| `FJ-03` | Is indefinite provider-side retention of founder-intent material acceptable? | Risk appetite, not a technical question |
| `FJ-04` | Which competing pointer claim wins, PR #6 or PR #7? | `FB-24`: an authority act, not a compilation result. The resolver correctly refuses |
| `FJ-05` | Does the Qwen / Kimi / DeepSeek / Grok allocation still bind, and is the requirement open weights or runnable by us? | `FB-17`: neither silently dropped nor newly bound |
| `FJ-06` | Is GitHub acceptable as sole host of canonical state, or should a second remote exist? | Concentration risk the founder should price. A `git bundle` is the zero-cost interim |

Note what is *not* on this list: which ChatGPT plan the account holds. That was
`AI-13`, removed, because it is a fact the platform can retrieve about itself.

## 9. Verifying this document

```bash
cd workstreams/so02/control-plane/operating-environment/w4-platform-roles
python3 tools/build_role_register.py --out /tmp/rebuilt.json   # deterministic
python3 tools/rolectl.py check          # 14 invariants
python3 tools/negative_tests.py         # 20 failure modes, all rejected
```

`rolectl.py` fails if two functions hold one decision class, if a function claims
a founder-reserved class, if a function is its own acceptance owner, if a
producing function sits in an assurance container, if a function's only recorded
authority is its runtime, if a function has an empty `decides` set, or if a
function names no substitution route. Negative tests `NR1`–`NR9` mutate the
register to trigger each of those rejections, and `NL1`–`NL5` do the same for the
contribution ledger and the conflict rules — including the one that matters most
for §5, `NL1`, where a holder tries to close a conflict on a `HYPOTHESIS` against
a contributor's `DIRECTLY_REPRODUCED` evidence. The invariants are demonstrated
rather than claimed.
