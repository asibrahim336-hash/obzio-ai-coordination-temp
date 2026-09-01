# De-restriction sweep across the estate

Lane `OE-W4-PLATFORM-ROLES` · commission `COM-CUR-ENV-01-20260822-v001`
Governing input: `FOUNDER-AUTHORITY-20260822T2225Z.json`
Base commit `3f3ee110cf9b769e60c664f758c437dcc582afd3`
State: `READY_TO_COMMIT`. A proposal for admission, not a self-declared binding.

The structured register is `DE-RESTRICTION-REGISTER-20260822-v001.json`. This
document is its readable companion. Where the two differ, the JSON governs,
because it is the artifact the validator reads.

---

## 1. What this sweep was looking for

An earlier ChatGPT reviewing lane, and this Cursor programme partly inheriting
from it, introduced limits the founder did not consent to. The task was to find
them without also stripping the controls that are load-bearing.

That second half is the harder half. Hours before this lane ran, an independent
acceptor refused this programme's own evidence and two reproduced defects came
out of the refusal. Controls of that kind look identical to invented ones from a
distance: both are rules an agent wrote down, and neither traces to the founder.
The only thing that separates them is whether a defect exists that the rule
actually caught. So the sweep is organised around evidence, not around who wrote
the rule.

Every constraint gets exactly one of three verdicts:

| Verdict | Test it must pass | Disposition |
|---|---|---|
| `FOUNDER_BOUND` | Traceable to direct founder intent | Retained. This lane may not remove it. |
| `EARNED_CONTROL` | Invented by an agent **and** cites a defect it demonstrably caught in this estate | Retained, with the defect named |
| `ASSISTANT_IMPOSED` | Invented by an assistant, constrains scope, roles, tooling, topology or pace, **and** cites no defect | Removed, with what it unlocks stated |

The asymmetry in the middle row is deliberate. An agent-invented rule is
presumed removable, and the burden is on the rule to produce its defect. A rule
that cannot name one does not survive on plausibility.

**Result: 76 constraints classified — 27 `FOUNDER_BOUND`, 27 `EARNED_CONTROL`,
22 `ASSISTANT_IMPOSED`.** Five further items were examined and deliberately
excluded from the denominator; §6 says why.

## 2. The removals

Twenty-two constraints are removed. They fall into six kinds of limit, and the
grouping matters more than the individual entries, because the same reflex
produced most of them: when something was uncertain, the response was to stop
and route the uncertainty to the founder, rather than to resolve it.

### 2.1 Sequencing gates that were never load-bearing (AI-01, AI-04, AI-09, AI-10, AI-16, AI-17)

Six gates held work behind a condition that had nothing to do with the work.

`AI-01`, the tranche-02 stage gate, is the parent of the group: nothing beyond
founder tranche 01 may be prescribed until tranche 01 is evaluated. No defect in
this estate is attributable to work proceeding in parallel. Every reproduced
defect here is an evidence-integrity defect, and sequencing would have caught
none of them. Removing it releases the platform role architecture, the
acceptance constitution, the salvage design and the Cursor configuration, none
of which depend on the credential answer the gate was actually waiting for.

`AI-04` is the one whose removal changes the most. The staged Cursor
configuration — hooks, rules, skills, the environment file, the write-scope
guard — was held outside `.cursor/` and kept inert pending an explicit founder
act the founder had already granted. It matters because of `EC-09`: the `gh`
CLI's installation token returns 403 on `administration`, so no agent can read
or set branch protection, which means server-side enforcement is unavailable
from inside an agent and **hooks are the only enforcement surface that exists**.
Holding the hooks inert left the estate with its write-scope rule written in
prose while the mechanism that could refuse a bad write sat on the shelf. The
replacement control is narrower and real: apply on a non-protected branch, never
on `main`.

`AI-09` and `AI-10` are the same gate at two scales — two independent routes
must be qualified before useful work proceeds, and no wave-one function may
produce anything until a non-founder return route is qualified end to end. Both
are contradicted by founder text stating that route acceptance does not gate the
assigned strategic work, and `CURSOR-SCP-01` already superseded the first.
Work proceeds on `R1` GitHub immutable-SHA custody, the one route that survived
independent challenge. The risk `AI-10` was protecting against is real and is
now handled by labelling rather than by blocking: a function whose only return
route is the founder is marked as such and still produces.

`AI-16` and `AI-17` deferred the second execution plane and the Cursor CLI/ACP
route on thin sequencing rationales. `AI-17` is the interesting one, because its
underlying reason — recurring spend — *is* founder-bound and is retained
separately as `FB-21`. What was removed is only the design deferral. The route
can be specified and dry-qualified now without committing a penny, and that
matters disproportionately for `FB-09`, the standing instruction never to create
an exclusive dependency on Cursor: ACP is the documented interface that would let
a different runtime drive the same work if Cursor became unavailable. Deferring
the design of the escape hatch was, in effect, deferring compliance with `FB-09`.

### 2.2 Founder touch-points invented as scarcity (AI-03, AI-13, AI-20)

`AI-03` treated the founder as a rationed resource with a per-wave budget of
dashboard actions, answers and decisions, and empowered a load function to
*reject* an over-budget design. This inverts the founder's actual instruction.
The rule is that the founder must never perform routine retrieval, monitoring,
comparison, merging or coordination — a restriction on the **kind** of work, not
its volume. `FB-06` says the opposite of a budget outright: do not suppress a
high-leverage founder action merely to minimise founder involvement. So the
budget-as-cap is removed and the underlying detector is re-specified rather than
deleted: it now measures whether a task routed to the founder is a routine verb,
and refuses on that basis. A design is never again rejected for asking too much
of the founder when what it asks is genuinely founder-bound.

`AI-13` asked the founder which ChatGPT plan the account holds. It is a fact the
platform can retrieve about itself, and it gates real branches — whether
Workspace Agents and the Compliance API exist for this account. Asking it of the
founder is the routine-retrieval verb `FB-05` forbids.

`AI-20` is a stale founder action still sitting in the live queue: a follow-up
submission required to deliver the operating-environment scope to Cursor, blocked
on a cloud browser hitting a Cloudflare verification loop. It is superseded by
events — Cursor is executing this commission right now, through the lane writing
this sentence. Leaving it queued would ask the founder to relay an instruction to
a platform already carrying it out. Its removal is what lets the founder action
queue be read as a signal rather than as a backlog.

### 2.3 Role limits on ChatGPT (AI-06, AI-07)

These are the two the founder's new authority names most directly, and they are
distinct: one caps ChatGPT's **status**, the other caps its **function**.

`AI-06` calls ChatGPT/SO-02 a supporting function with no scope attached. The
scoped version of that claim is legitimate and is retained as `FB-03`: for the
founder operating environment specifically, ChatGPT does not select architecture
or prescribe a stack. But `CHATGPT-SIR-01` drops the qualifier, and
`control-plane.json` carries the unscoped form into live routing. Unscoped, it
demotes an entire platform on the strength of a boundary that was only ever
about one scope.

`AI-07` reduces ChatGPT's operating function to evidence review, verification
and a founder interface. Its removal is not merely permissive — it reassigns
ChatGPT to the one function in the whole architecture that matches its actual
asymmetry. ChatGPT is the only surface holding the founder's authenticated
context and connected tools. Using it to review evidence Cursor produced spends
a unique capability on a task any lane could do.

### 2.4 Topology and agent-shape limits (AI-08, AI-14, AI-18, AI-19)

`AI-08`, one top-level agent and no subagents, was scoped to the completed
CUR-01 qualification and superseded in three separate documents. It is already
dead in practice: five isolated lanes ran as subagents under one root controller
and this is a sixth. What the removal adds is a **re-inheritance probe**, because
a rule superseded in three places is a rule that can quietly return.

`AI-19` is its live counterpart and is still in force in
`control-plane.json`: Cursor bound as a single operator interface addressed
through one entry agent. Against the reproduced facts this is simply false —
nine top-level cloud agents on this repository, four distinct exact model
configurations, two model families, with subagents and isolated worktrees
beneath them. The unit of dispatch is an agent group, not an agent.

`AI-14` fixed the ChatGPT estate at eleven operating project slots plus one
frozen evidence container. The founder's floor is *at least* ten projects; L5
matched eleven because that was the current inventory, which is a migration
convenience mistaken for a design constraint. Project count now follows function
demand and separation requirements, and a census returning a different number
changes the migration rather than the topology.

`AI-18` placed independent acceptance, evaluation and red-teaming in ChatGPT
assurance projects. This is the sweep's most consequential overrule and §4 of the
architecture document argues it in full.

### 2.5 Tool and surface exclusions (AI-05, AI-11, AI-12, AI-21)

`AI-11` self-excluded the five mutating `cursor-cloud` tools, including
`trigger-environment-build`. The exclusion made L1's single most consequential
finding permanently untestable. This lane reproduced the symptom independently:
`environment-info` returns `environmentJson: null` with the note *"environment.json
was found but contained no recognized configuration fields"*, and the build
records `warmFork: cold`. Every agent in this environment boots unconfigured and
pays a cold start, and the cost recurs per agent — so it scales precisely with
the fanout this architecture calls for. The tool's own description states that
draft builds are appropriate during setup validation and never become what new
agents boot from, so the exclusion was stricter than the platform's own guidance.

`AI-05` left MCP integrations unauthenticated and out of scope. Five namespaces
reachable from this runtime report `needsAuth`: Supabase, Vercel and three
Cloudflare namespaces. They are candidates for authorised access, not
out-of-scope surfaces.

`AI-02` belongs here too, and it is the cleanest example in the register of a
restriction that also wasted a founder action. It asked the founder to issue a
*new* Cursor API key. This lane reproduced that `CURSOR_API_KEY` is absent from
the injected secret names, and that the Supabase MCP namespace is present and
unauthenticated — while the founder states a Cursor API key already exists in
Supabase Edge Secrets. On that evidence the blocker is an unauthorised
integration, not a missing credential. The founder act shrinks from creating and
scoping a new secret to authorising one already-configured integration, and the
estate stops accumulating duplicate keys. The presence of the key remains
founder-stated: confirming it would require authenticating, which is out of
bounds for this lane, so the inference is labelled `HYPOTHESIS` in the receipt
and the founder action is stated as `FJ-02` rather than asserted as fact.

`AI-12` recommended granting nothing new on GitHub. L1 reproduced that Issues,
secrets and branch protection return 403, but a 403 is a description of the
current token, not an argument for keeping it. Removing the recommendation
reopens three options as live candidates the founder can weigh — Issues as the
coordination substrate this architecture needs for conflict objects, Actions
secrets verification, and branch protection — while leaving the decision itself
exactly where it belongs, with the founder.

`AI-21` is the enabling one. It read the commission's *"do not make consequential
account changes"* as a bar on inspecting and configuring Ahmed/Obzio-owned
surfaces at all. The founder authority explicitly grants inspect, access,
configure, connect, use and optimise across the estate, and reserves the stop for
genuine owner acts. Without removing `AI-21`, the removals of `AI-04`, `AI-05`
and `AI-11` would be reclassifications that changed nothing.

### 2.6 A pace rule that would have stopped the estate (AI-22)

`AI-22` is the one I would flag hardest. L5's quota function fails closed:
unknown runtime headroom is treated as zero headroom for new work. It reads as
prudence. In practice it is a permanent stop, because capacity is only
observable at the top-level run layer, so headroom is *almost always* unknown —
and a rule that blocks all new work whenever headroom is unknown blocks all new
work. It also contradicts the founder instruction to seek maximum effective
provider capacity and queue work above the ceiling rather than lower ambition.

The replacement measures the layer that is actually observable, treats unknown as
unmeasured rather than as zero, proceeds under a declared stop condition, and
logs the blind spot with a date to convert it to a measurement.

## 3. The controls that stayed, and what each caught

Twenty-seven controls were invented by agents and are retained because they
caught something. The full defect citations are in the register; these are the
ones that carry the most weight.

**The acceptance controls, earned hours before this lane ran.** An independent
acceptor refused this programme's evidence, and the refusal produced two
reproduced defects. `EC-04`, read-back by recomputation, exists because
substituting a no-network synthetic read-back that named an all-zero commit,
invented transports and a non-manifest path *still let the producer's own
verifier exit 0*. `EC-05`, the allowlist capacity detector, exists because a
synthetic `IDLE`-to-`ERROR` regression passed the producer's denylist detector as
zero interference while strict recomputation failed it — and this lane found an
agent sitting in `ERROR` in this account right now, so the state the denylist
missed is live rather than hypothetical. `EC-03`, manifest material closure,
exists because a bundle's own read-back record was omitted from its manifest.

**The isolation controls, earned by a live collision.** `EC-01` and `EC-02` come
from one incident with two halves. Five lanes shared one VM and one repository;
two of them worked in the same checkout on a detached HEAD, and three commits
from two lanes interleaved. The second half is worse: because a commit on a
detached HEAD advances no branch, `git push -u` printed *"Everything up-to-date"*
and **exited 0 while publishing nothing**. That is why a zero exit from `git push`
is not evidence of publication, and why this lane confirms every push with
`git ls-remote`.

**The self-acceptance controls.** `EC-07` and `EC-16` both trace to `AC-12`:
GitHub Actions genuinely executed the bytes on another machine, but the producer
authored the workflow, the verifier, the tests, the manifest scope and the
success assertions. That is reproducibility wearing a corroboration badge.
`EC-08`, no rewriting a verdict after commit, is the control that let a refusal
survive being inconvenient — without it the party that was refused could have
amended the refusal, and the two defects above would never have surfaced.

**The currentness controls**, reproduced live by this lane against the current
tree: `COMPETING_CURRENTNESS_CLAIM=4`, `NON_ADMISSIBLE_EVIDENCE_OFFERED=21`,
`ADMISSION_OVERCLAIM=8`, `UNDIFFERENTIATED_COMMISSION_OVERLAP=7`,
`ALIAS_USED_AS_LOCATOR=2`. `EC-12` is the resolver that refuses to answer when
claims compete rather than picking the newest or the majority: seven branches
agreeing because they copied each other is one claim wearing seven hats.

**`EC-27` is a split rather than a retention.** The two-independent-routes rule
appears twice in the estate doing two different jobs. As a *gate* on work it is
`AI-09` and is removed. As a *claim standard* it is earned and kept, because
`AC-06`/`AC-07` showed the estate's second route was not independent at all: it
queried the producing run while that run was still `RUNNING`, returned zero
events, committed no raw provider artifact, and depended on the first route for
custody. Same sentence, opposite verdicts, and collapsing them would have been an
error in either direction.

## 4. Three removed restrictions are still live, and I cannot reach them

The scanner (`derestrictctl.py scan`) checks live routing surfaces for removed
restrictions that are still in force. It exits non-zero on three:

| ID | Still live in | Why it persists |
|---|---|---|
| `AI-06` | `commissions/CHATGPT-SIR-01.md` | The unscoped "supporting function" line |
| `AI-20` | `state/control-plane.json` | The stale founder action `FA-SCF01-CURSOR-LAUNCH` |
| `AI-21` | `commissions/CURSOR-OPERATING-ENVIRONMENT-01.md` | The boundaries paragraph read as a bar on configuring |

All three sit outside this lane's write scope, and two are under `state/**` or
`commissions/**` where a write from this lineage would silently set currentness
for every branch that inherits it — the estate's signature failure mode, and the
reason `EC-13` makes those paths prohibited. So the correct action here is to
report them with exact locators rather than to fix them, and let the holder of
those paths apply the change. **This is the sweep's main hand-off: the register
records the removals, but three of them do not take effect until someone with
write access to those two commissions and to `control-plane.json` acts.**

A scanner that only reports its own clean state is not much of a scanner. This
one reports that its own programme has not finished the job.

## 5. The scanner had a defect, and it is in the receipts

The first version of the scanner flagged five re-inheritances. Two were
supersession statements — sentences whose entire purpose is to *remove* the
restriction, such as `CURSOR-SCP-01`'s line that SO-02 does not impose an
architectural one-agent ceiling. A detector that reads a removal as a
re-imposition would have driven exactly the behaviour this sweep exists to
reverse: it would have told a future lane to strip the sentences doing the
de-restricting.

The fix adds negation awareness — a window around each match, checked for
supersession markers — and the classes are now reported separately as
`RE_INHERITED` (3) and `SUPERSESSION_STATEMENT` (2). The pre-fix output is kept
at `receipts/.../raw/derestrict-scan-prefix-negation-defect.txt` under `FB-23`,
nothing is deleted, and it is cited in the register as the defect that earned the
negation rule.

## 6. What was deliberately not classified

Five items were examined and excluded from the denominator rather than forced
into a class. They are provider-behaviour facts: Structured Outputs' `strict`
flag, the roughly ten-minute retention window on unstored background responses,
the Workspace Agents API's inability to return an agent's response, and related
constraints. Each is correctly recorded and load-bearing for routing, but none is
a limit an actor in this estate invented, and none constrains scope, roles,
tooling, topology or pace. Classifying them as `EARNED_CONTROL` would have
inflated the earned count with things no agent earned. They are carried into the
role architecture as routing facts instead, and the register states the exclusion
so the denominator stays honest.

## 7. Removal is not deletion

Every removed constraint keeps its original text, its introduction locator, and
its verdict in the register. `FB-23` holds: superseded material remains evidence.
A future lane that wants to reinstate one of these twenty-two can read exactly
what it said, where it came from, and why it was removed — and if it can produce
the defect evidence that was missing, it should reinstate it. That is the
mechanism, not the exception to it.

---

## Reproducing this

```bash
cd workstreams/so02/control-plane/operating-environment/w4-platform-roles
python3 tools/build_derestriction_register.py --out /tmp/rebuilt.json  # deterministic
python3 tools/derestrictctl.py verify   # every verdict carries the evidence its class requires
python3 tools/derestrictctl.py scan     # exits non-zero: 3 live re-inheritances
python3 tools/negative_tests.py         # 20 failure modes, all rejected
```

`verify` enforces the asymmetry in §1 mechanically: an `EARNED_CONTROL` with no
`defect_caught`, a `FOUNDER_BOUND` with no `founder_source`, or an
`ASSISTANT_IMPOSED` with no `reinheritance_probe` all fail, as does a constraint
dropped without the declared count moving. Negative tests `ND1`–`ND6` prove each
of those rejections rather than asserting them.
