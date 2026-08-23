# The constitution of ChatGPT's functions in the Obzio operation

Lane `OE-W8-CHATGPT-CONSTITUTION` · commission `COM-CUR-ENV-01-20260822-v001`
Base commit `5a8923ab3f8b13b3ac80ee747d9a2aad3d756382`
Governing inputs: `.cursor/rules/00-founder-standing-authority.mdc`,
`../FOUNDER-STANDING-INSTRUCTION-20260822.md`,
`../FOUNDER-AUTHORITY-20260822T2225Z.json`.

A proposal for admission, not a self-declared binding. It binds no company
strategy, names no model, tool or architecture as bound, creates no obligation
or spend, and imposes no fixed number of projects, agents or functions.

Four parts: **A** adjudicates the founder's recorded ChatGPT advisory proposal
function by function; **B** specifies how context recovered from an arbitrary
thread is admitted as evidence and how two conflicting threads are ranked;
**C** specifies how the account's back catalogue is triaged without the founder
doing it by hand; **D** is the ordered list of things only Ahmed can do.

## Evidence discipline

| Label | Meaning in this bundle |
|---|---|
| `DIRECTLY_REPRODUCED` | This lane ran the command or fetched the URL. Command or URL, and date, recorded; receipt under `receipts/so02/2026-08-22/oe-w8-chatgpt-constitution/raw/`. |
| `DOCUMENTED` | An official source cited by URL with its fetch date, **or** a prior lane's reproduction cited by repository path. Prior-lane reproductions are never relabelled as this lane's own. |
| `HYPOTHESIS` | Untested inference. Never used to establish that a route works. Every one carries the test that would settle it and the fallback if it fails. |

Two things this bundle does **not** do, and says so rather than implying
otherwise. It did not authenticate to ChatGPT or acquire any credential, so
every claim about the founder's account is documentary or hypothetical, never
observed. And it does not build the route evidence table — that is a sibling
lane's single deliverable. Where a function's home depends on a route, this
document names the route, states whether its viability is established, and
gives the fallback.

---

# Part A — Adjudicating the advisory proposal

The founder recorded a ChatGPT recommendation and labelled it advisory,
explicitly not a founder ruling and not a replacement for his established
intent. He asked for it to be assessed against the wider operation, for what is
strategically useful to be retained, and for the strongest practical way to
constitute and connect these functions to be identified. He asked for
**assessment, not endorsement**.

## A.0 The proposal reads as seven clauses. It contains twelve functions, and the bundling is load-bearing

Decomposed by what each clause would actually *do*, the proposal is twelve
functions — and the two clauses that bundle are precisely the two where a
function that should be retained is packaged with one that should not.

| Clause as written | Decomposes into |
|---|---|
| "voice capture, read-back, interpretation and decision support" | `P1` capture · `P2` read-back · `P3a` interpretation-in-the-moment · `P3b` interpretation-of-record · `P3c` decision support |
| "authenticated discovery of projects, Library, integrations, plugins and connected accounts" | `P4` authenticated discovery |
| "recovery of relevant prior context" | `P5` context recovery |
| "research and strategic challenge" | `P6a` research · `P6b` strategic challenge |
| "specialist parallel work" | `P7` specialist parallel work |
| "independent evaluation" | `P8` independent evaluation |
| "translation of agent returns into precise founder actions" | `P9` return translation |

This is not pedantry, and it is the first substantive finding. `P3a` is
inseparable from capture and belongs in ChatGPT; `P3b` is interpretation of
record and belongs in Cursor, where it can be checked against the whole estate.
Left bundled as "interpretation", the clause reads as one function, and
admitting it admits both. The same is true of `P6`: live challenge to the
founder's framing is genuinely ChatGPT-shaped, and general research is not.

A proposal that bundles a strong function with a weak one is not being
deceptive. It is describing a *conversation*, in which those things do happen
together. The constitution's job is to notice that a conversation is not a
topology.

## A.1 The twelve verdicts

Full records, each with the asymmetry test, the evidence, the displacement and
the conditions, are in `FUNCTION-ADJUDICATION-20260822-v001.json`, which governs
where it differs from this prose.

| | Function | Verdict | One-line reason |
|---|---|---|---|
| `P1` | Voice capture | **RETAIN** | Real, exclusive, and reproduced: this runtime has no audio device and a non-interactive stdin. |
| `P2` | Read-back | **RETAIN, promoted to a gate** | The only moment the founder can refuse an interpretation at zero cost. Too important to be a feature. |
| `P3a` | Interpretation in the moment | **RETAIN, bounded** | Inseparable from read-back. Bounded to disambiguation, never to record. |
| `P3b` | Interpretation of record | **RELOCATE → Cursor** | Must be checkable against the whole estate and must survive the thread ending. |
| `P3c` | Decision support | **RETAIN, fenced** | Support is not decision. Fenced by the decision-class partition that already exists. |
| `P4` | Authenticated discovery | **RETAIN — the strongest item, and undersold** | The only function that spends the only asymmetry. Upgraded from an answer to a census artifact. |
| `P5` | Context recovery | **RETAIN, conditional on Part B** | Genuinely unique and genuinely dangerous. Without an admission rule this verdict would be wrong. |
| `P6a` | Research | **RELOCATE → Cursor**, except over the authenticated estate | No asymmetry. Cursor has unrestricted egress and lands research where it can be checked. |
| `P6b` | Strategic challenge | **RETAIN, narrowed** | Live challenge to *framing*, yes. Challenge to *artifacts* is red-teaming and lives elsewhere. |
| `P7` | Specialist parallel work | **RELOCATE → Cursor**, with a named exception | Parallelism is Cursor's demonstrated asymmetry. Parallel work with no return route scales the relay. |
| `P8` | Independent evaluation | **REJECT as acceptance; RELOCATE the retained fragment** | Adjudicated in full in A.3. |
| `P9` | Return translation | **REJECT as stated; RELOCATE the residue** | Founder-as-relay wearing the costume of automation. Named in A.4. |

Counting the verdicts: two retained outright, four retained with a promotion, a
bound or a narrowing, one retained conditionally, three relocated, two rejected
with a fragment relocated from each. The proposal's central claim survives; its
distribution of work does not.

## A.2 What the proposal gets right, stated plainly

It is worth separating this from the corrections, because the corrections are
longer and length is not weight.

**The proposal's own summary of its strongest contribution is correct, and the
rest of the proposal is weaker than that summary.** Its closing paragraph says
the strongest immediate contribution may be to inventory and expose the
capabilities already available through Ahmed's account, then connect or route
them into Cursor so Cursor can use the maximum useful authorised context, tools
and execution capacity. That is exactly right, it matches the founder's own
recorded `immediate_useful_role` in
`FOUNDER-AUTHORITY-20260822T2225Z.json`, and it is the one thing in the estate
that nothing else can do. Everything before that paragraph is a list of things
a capable assistant can do; that paragraph is the one thing this *particular*
assistant, on this *particular* account, uniquely can.

**Its self-limiting clause is unusually good.** "ChatGPT should not assume that
its current thread contains the complete estate or impose its own structure" is
the correct diagnosis of its own principal failure mode, offered unprompted. It
is also, precisely, the problem Part B exists to solve — so the proposal
identified the hard problem and left it open rather than papering over it.

**Voice is stronger than the proposal claims.** The proposal lists voice as
capture and read-back. `DIRECTLY_REPRODUCED` (`https://learn.chatgpt.com/docs/features/voice.md`,
fetched 2026-08-23): ChatGPT Voice in the desktop app supports natural
turn-taking with interruption mid-response, and it "can start separate threads
for longer tasks, check existing threads, and send follow-up instructions",
bringing "progress, blockers, and results back to your voice conversation so
you can keep talking while work continues". That is not a capture interface. It
is a dispatch and status console operated by speech. The proposal undersells
its own best card — and A.4 explains why that same capability is also the most
dangerous thing in the proposal.

## A.3 Independent evaluation: adjudicated head-on

The proposal asks ChatGPT to perform independent evaluation. A prior lane moved
independent acceptance into Cursor. This section decides between them rather
than deferring to either.

### The prior position, and where it is incomplete

`w4-platform-roles/PLATFORM-ROLE-ARCHITECTURE-20260822-v001.md` §4 decomposes
"independent" into six properties — isolated context, separate criteria,
evidence custody, distinct identity, adversarial tests, no self-modification of
the verdict — and shows that not one of them requires a second provider. It
then records the demonstration: an acceptance lane ran inside Cursor, on a
different model family from its producer, with criteria committed beforehand
(`9a390df3`), and **refused the root controller's own evidence**, after which
two of its findings were reproduced against the producer's own tooling
(`DOCUMENTED`: `l3-independent-acceptance/VERDICT.json`).

That reasoning is sound and I adopt it. But the decomposition has a gap, and
the gap is the strongest available argument *for* the proposal, so it must be
put fairly before it is answered.

**The missing property is evaluator capture through shared instruction
lineage.** Every Cursor lane in this estate reads the same always-applied rule
file, the same `AGENTS.md`, the same commission text, and a dispatch written by
the same root controller. Model-family diversity does not break that: the
acceptor and the producer are reading the same constitution. `L3` could refuse
the producer's *evidence*. It could not have refused "this entire commission is
aimed at the wrong problem", because that judgment was not in its criteria and
its criteria came from the same lineage. Framing error is the class of error
that produces an entire workstream of confidently wrong work, and no amount of
in-Cursor independence detects it.

Does the founder's ChatGPT account break that lineage? **Yes — genuinely.** It
holds his own prior thinking, developed with him over an extended period, which
is not derived from any root controller's dispatch. That is a real independence
property Cursor cannot manufacture, and W4's table misses it because W4
decomposed independence into properties of the *verdict process* and not into
properties of the *criteria's origin*.

So the proposal is pointing at something real. It has simply attached it to the
wrong function.

### The rejection

**`DC-ACCEPTANCE` does not move to ChatGPT.** ChatGPT does not issue admissible
acceptance verdicts. Four reasons, in order of force:

1. **A verdict is the highest-consequence artifact in the estate and has the
   weakest available transport.** Acceptance is what moves a subject up the
   admission ladder to `ACCEPTED`. If that artifact's only route to custody is
   the founder carrying it, the estate's acceptance gate runs at founder
   bandwidth — and the non-negotiable forbids exactly that. Worse, a verdict
   that cannot be re-derived from committed evidence by a third party is not a
   verdict; it is an opinion with a timestamp. `DOCUMENTED`
   (`l4-currentness-recovery/README.md`): the admission ladder requires an
   evaluator identity distinct from the producer *and* evidence reachable now.
   A conversation satisfies neither.

2. **Context saturation is anti-correlated with the property acceptance needs
   most.** L5 already specifies that the acceptance container "reads committed
   artifacts only, never a producing chat"
   (`l5-chatgpt-scale/CHATGPT-SCALE-OPERATING-PROGRAMME-20260822-v001.md` §13.2).
   The founder's account is the single surface in the estate where an acceptor
   would sit inside the producing context — 182 chats of it — with no
   mechanical way to demonstrate it read only the artifact. The cold-instance
   replay test exists and could be run there, but it would be run *by the
   surface it is testing*, which is the self-acceptance prohibition displaced
   one level up rather than satisfied.

3. **It spends the one asymmetry on a task with no asymmetry.** This is W4's
   argument and the founder's own: the recorded `immediate_useful_role` is
   discovery and alignment, not review. Every hour of authenticated-account
   capability spent grading a Cursor artifact is an hour not spent on the only
   thing that account can do.

4. **There is a fourth reason that applies even if the first three were
   solved**, and it is the one I would keep if I could keep only one.
   Acceptance derives its value from being boring, mechanical, cheap and
   frequent. Housing it in the surface where the founder is present converts
   every refusal into a conversation with the founder. A gate that must be
   discussed is a negotiation, and a negotiated gate is not a gate. The
   proposal's own framing — ChatGPT as a *founder-facing* capability — is what
   disqualifies it here: founder-facing is the correct design for capture and
   the wrong design for refusal.

The one residual class W4 identifies — claims about Cursor's own behaviour,
where a runtime defect is correlated across every lane inside it — is real, and
ChatGPT is *not* the answer to it either. W4 routes it to GitHub Actions as a
second execution domain and a hosted open-weight route as a second cognition
domain. Both are cheaper than ChatGPT and both have return routes. ChatGPT
would be a third option, worse on both axes.

### The retained fragment

**`DC-FRAMING-CHALLENGE` — a new decision class, held by ChatGPT.** It is not a
subdivision of acceptance and it must not be described as one.

| | |
|---|---|
| **Subject** | The commission, not the artifact. "Is this the right problem?", not "is this evidence sound?" |
| **Output** | A challenge object, not a verdict. It enters the contribution ledger as a `dissent` row against a decision class held elsewhere. |
| **Unique qualification** | Its criteria originate in the founder's own recorded thinking rather than in the dispatch lineage. Nothing in Cursor has that. |
| **Distinct from** | `DC-ADVERSARIAL-FINDING` (red team, Cursor: attacks the artifact) and `DC-EVAL-DEFINITION` (Cursor: defines the measure). |
| **Blocking power** | None. Under `V5`, an unresolved conflict attaches to the work as a standing dissent and no lane idles waiting. |
| **Transport requirement** | Low, and that is the point. A challenge is a paragraph; it rides the same capture route as `P1`/`P2`. A verdict would need a route strong enough to bind. |
| **Falsifier** | Pre-registered: if across a declared number of waves no challenge is ever upheld and none changes a commission, the function is decorative and retires. |

The proposal's instinct was sound. The correction is that the thing ChatGPT can
uniquely contribute to assurance is **a differently-sourced question**, not
**a verdict** — and the two need completely different transport, completely
different context hygiene, and completely different blocking power. Merging
them is what made the proposal wrong.

## A.4 Return translation, and naming the relay pattern

**`P9` is rejected as stated.** "Translation of agent returns into precise
founder actions" is founder-as-relay wearing the costume of automation, and it
is worth being exact about the mechanism because the disguise is good.

Agent returns already live in git. For ChatGPT to translate them, one of two
things must happen. Either ChatGPT reads git — in which case the translation is
happening against an artifact a Cursor lane already produced, and the producing
lane could have produced the founder action directly; W3 and L5 already do
exactly this, ten fields per action. Or the founder carries the returns into
ChatGPT — which is the relay, and no amount of ChatGPT capability changes what
the founder is doing in that loop. He is the transport.

The tell is that the pattern **feels** like automation because the founder's
side of it is conversational. He speaks, something happens, he hears a result.
Every individual exchange is pleasant and fast. What is hidden is that his
attention is on the critical path of every item, so the throughput of the whole
operation is bounded by his available hours — which is the precise thing the
non-negotiable exists to prevent, and the precise thing a count of "how easy
was that exchange" will never reveal.

**Where the pattern appears in the proposal.** It is in `P9` explicitly. It is
latent in `P8`, because a verdict that must be spoken to the founder to reach
anything is a relayed verdict. And it is latent in `P7`, because parallel work
whose results have no return route does not remove founder load, it multiplies
the number of results he must carry — parallelism without a return route scales
the relay rather than replacing it. That is the sharpest reason `P7` relocates.

**A distinction the constitution needs, so this test is not over-applied.**
Founder-*device* dependency is not founder-*relay* dependency. A route that
runs on Ahmed's machine — the ChatGPT desktop app writing to a local clone,
say — has him supplying hardware and an authenticated session, not attention
per item. He authorises once; thereafter the agent writes and pushes and he
reads nothing. That passes. The test is whether **his attention is on the
critical path of each item**, not whether his hardware is. A constitution that
conflates the two would reject the single most promising custody route in Part
D for the wrong reason.

**The retained residue.** One genuinely useful thing survives: *rendering* an
already-committed, already-specified founder action into his live voice
conversation at the moment he asks "what do you need from me". That is a read
over an artifact, it changes nothing, it produces nothing that must return, and
it is the good half of what `P9` was reaching for. It is folded into `P3c`
decision support rather than registered as a function of its own — it fails the
null test on its own, since nothing decides differently because of it.

## A.5 Where each function lives, and what the placement costs

| Function | Home | What it displaces | What its placement costs |
|---|---|---|---|
| `P1` capture | ChatGPT (desktop, voice) | Intent lost between thought and record | Nothing, once custody exists. Everything, until it does. |
| `P2` read-back | ChatGPT, as an admission gate | Later supersessions to correct misread intent | One extra spoken exchange per consequential interpretation |
| `P3a` interpretation-in-moment | ChatGPT, bounded | Founder restating himself | Must be bounded, or it becomes `P3b` by drift |
| `P3b` interpretation-of-record | Cursor | A provider's reading becoming constitutional | Latency: the record lags the conversation |
| `P3c` decision support | ChatGPT, fenced by the partition | Founder deciding without options in front of him | Requires the fence to be checkable, not merely stated |
| `P4` discovery | ChatGPT — its home function | Every credential-blocked route staying blocked on an unknown | Perishable: a census is true on the day it runs |
| `P5` context recovery | ChatGPT, admitted only via Part B | Founder as the estate's memory | The admission rule is not optional overhead; it is the whole cost |
| `P6a` research | Cursor; ChatGPT only over the authenticated estate | — | Splits a habit the founder currently has in one place |
| `P6b` framing challenge | ChatGPT | Consensus between lanes that share a lineage | Only valuable if it is allowed to be unwelcome |
| `P7` specialist parallel work | Cursor; ChatGPT only where the authenticated estate is required | — | The exception must name its return route or it is not an exception |
| `P8` acceptance | Cursor (unchanged) | — | — |
| `P9` return translation | Nowhere. Residue folded into `P3c` | — | — |

Two structural rules hold across every row and are not negotiable per function.

**Capture without custody is memory, not record.** `DOCUMENTED`
(`w4-platform-roles/PLATFORM-ROLE-ARCHITECTURE-20260822-v001.md` §3): provider
memory is never constitutional authority; a captured intent becomes binding only
once it is a typed, durable event in git. Every ChatGPT-resident function above
therefore has a custody dependency, and if that dependency is unmet the function
still runs — it just produces `RECOVERED_UNCOMMITTED` candidates rather than
evidence. It is not blocked; it is unadmitted. This is the same distinction
`EC-11` already draws for provider completion.

**A function whose only return route is the founder fails admission.** That is
L5's displacement test and W4's `V7` substitution requirement, applied here. It
is why `P7` relocates and why `P8`'s fragment is a paragraph rather than a
verdict.

---

# Part B — The intent admission rule

The founder's account contains threads of wildly varying authority, and he is
explicit that no single thread is the complete founder intent. `P5` recovers
context from those threads. This part specifies how that context is admitted, at
what standing, and what stops a persuasive old thread being mistaken for current
intent.

It is executable. `tools/intentctl.py` derives standing, resolves contested
decision classes and fails closed, and `tools/negative_tests_intentctl.py`
injects sixteen ways the rule could be defeated and requires each to be caught.
Everything below is what those two files do; if the prose and the code disagree,
the code is the rule and the prose is the defect.

## B.1 The unit of admission is the utterance, not the thread

This is the whole move, and everything else follows from it.

A thread is a container of utterances of mixed standing: the founder's own
words, an assistant's paraphrase of them, the assistant's own proposals, and the
founder acknowledging an assistant proposal — which is not the same as the
founder authoring it. Treating the thread as the atom forces one standing onto
all four.

And that is exactly how "a persuasive old thread is mistaken for current intent"
happens. **Persuasiveness is a property of prose. Standing is a property of an
utterance's speaker and speech act.** They are independent, so a thread can be
overwhelmingly persuasive and contain no founder decision at all. A rule that
ranks threads is ranking the wrong thing.

The estate already proves the point, in a file it wrote by hand.
`FOUNDER-STANDING-INSTRUCTION-20260822.md` contains, in one commit, three
utterances of three different standings: the founder's standing instruction
(controlling), his clarification on the account (a decision), and the ChatGPT
advisory proposal he quoted (explicitly not binding). Admitted as one object at
one standing, **the advisory proposal would have inherited founder authority
from the file that quotes it.** The founder prevented that himself, by labelling
it. The rule reaches the same verdict without needing him to.

`DIRECTLY_REPRODUCED`, receipt `raw/intentctl-reproduction.txt`:

```
$ python3 tools/intentctl.py standing --id urn:obzio:w8:utterance:chatgpt-advisory-proposal-20260822
  "standing": "S1", "standing_name": "CONTEXT", "admitted": false
  "derivation": ["table[FOUNDER_QUOTING_OTHER][QUOTATION] = S1"]
```

Same file, same commit, same author, quoted in the founder's own voice — and the
class it touches, `DC-CHATGPT-FUNCTIONS`, resolves to `NO_ADMITTED_CLAIM`. The
proposal contests nothing. That is the correct result, and it is the result this
lane's own Part A depends on being true.

## B.2 The standing lattice

Five rungs, because collapsing authority to a scalar is what produces "this
sounds important, so treat it as binding".

| | Name | May | May not |
|---|---|---|---|
| `S0` | `INADMISSIBLE` | — | anything |
| `S1` | `CONTEXT` | inform | change any decision class |
| `S2` | `FOUNDER_SIGNAL` | inform, raise an open question, seed a warrant | decide |
| `S3` | `FOUNDER_DECISION` | decide within its declared scope | stand over future operations |
| `S4` | `FOUNDER_CONTROLLING` | decide, and stand until directly amended | — |

**Most of the back catalogue lands at `S1`, and that is the correct outcome, not
a failure of recovery.** A rule whose output is mostly "this is context" is
doing its job; a rule that finds binding intent everywhere has found none.

Standing is derived from a table indexed by speaker class and speech act — never
from how the text reads. `FOUNDER_DIRECT` × `DIRECTIVE` is `S3`. `FOUNDER_DIRECT`
× `EXPLORATION` is `S1`, because the founder thinking aloud is not the founder
deciding. Anything absent from the table is an error, never a default.

Four caps and one promotion sit on top of the table:

- **`CAP-PARAPHRASE`** — an utterance not recorded verbatim is capped at `S1`,
  whoever paraphrased it. A summary of a founder directive is an assistant
  utterance *about* a directive. This is the founder's own instruction that
  summaries must never distort intent, made mechanical.
- **`CAP-ALIAS-LOCATOR`** — "the chat where we discussed the roadmap" is `S0`.
  An alias resolves to whatever the reader happens to be looking at.
- **`CAP-UNCONFIRMED-VOICE`** — a voice capture with no confirmed read-back is
  capped at `S2` and labelled `CAPTURED_UNCONFIRMED`. This is Part A's promotion
  of read-back from a feature to a gate, expressed as an arithmetic consequence
  rather than a policy.
- **`CAP-ACKNOWLEDGEMENT`** — see B.3.
- **`PROMOTE-DESIGNATED`** — an `S3` becomes `S4` when the founder designated it
  as standing. Designation is a founder act, never an inference from tone.

## B.3 The laundering path, closed

The single most likely way an advisory proposal becomes founder intent is not
forgery. It is assent. The founder says "yes, do that" to an assistant proposal,
and the *proposal* is then recorded as founder intent because a founder utterance
is attached to it.

**`CAP-ACKNOWLEDGEMENT`**: an acknowledgement's effective standing for a scope is
the lesser of its own standing and the standing of what it acknowledges. What the
founder authored was the assent. The assent is genuinely his and genuinely `S3`;
the proposal is still `S1`.

The rule has to cut both ways or it is a veto rather than a rule, so: if he
restates the content himself, the restatement is his utterance and carries his
standing in full. `restates_content_verbatim` is the discriminator, and both
directions are tested (`NT1`, `NT1b`).

This matters here specifically. The founder's own diagnosis of the prior error
was that "ChatGPT mistakenly limited Obzio's plan to you acting primarily as a
planner" — a case of an assistant's framing having acquired more standing than it
earned. `CAP-ACKNOWLEDGEMENT` is the mechanical form of that correction.

## B.4 Custody is a different axis from standing

An uncommitted founder directive genuinely is a founder directive. It is simply
not yet admissible.

- **Standing** = how much authority the utterance carries.
- **Custody** = `COMMITTED` or `RECOVERED_UNCOMMITTED`.
- **Admitted** iff `custody == COMMITTED and standing >= S2`.

Collapsing these would force a choice between admitting content that is still
sitting in a provider and denying that the founder said something. `NT9` holds
the line: a recovered `S4` directive with `RECOVERED_UNCOMMITTED` custody derives
`S4` correctly and contributes zero admitted candidates. This is the same
distinction the estate already draws when a provider reports completion with no
committed artifact.

## B.5 Ranking two conflicting threads

An admission rule that cannot rank two conflicting threads has not solved
anything, because competing claims of what is current is this estate's recorded
failure mode. The resolution order is fixed, declared in advance, and executed
by `intentctl.py resolve`.

| Step | Test | If it decides |
|---|---|---|
| 1 | Filter to admitted utterances whose **declared scope** contains the contested class | candidate set |
| 2 | Is the maximum standing held by exactly one candidate? | `STANDING` |
| 3 | Among those tied at the top, does exactly one supersede all others **by name**? | `NAMED_SUPERSESSION` |
| 4 | Are all remaining candidates direct founder utterances, at equal standing, with **trusted** timestamps that strictly order them? | `FOUNDER_PRECEDENCE_RECENCY` |
| 5 | Otherwise | `UNRESOLVED` — fail closed |

**Step 4 is the founder's own precedence clause**, which reads "Direct founder
intent, most recent first". It is honoured exactly where he stated it and
extended nowhere. It never applies across standings, never to an assistant
utterance, and never where scope overlap was inferred from topic keywords.

**Step 4 also requires knowing which utterance is more recent, and most recovered
context does not establish that.** A conversation URL identifies a conversation,
not when a message inside it was made. So `timestamp_trust` is `TRUSTED` only for
a repository locator pinned to a commit, or an export record carrying a message
timestamp — and an untrusted timestamp does not lower standing, it removes one
resolution path. This is the load-bearing subtlety of the whole rule: **the
founder authorised recency, and the rule refuses to fake the input recency
needs.**

**Step 5 is where the failure mode is actually caught.** `UNRESOLVED` fires on
equal standing, overlapping declared scope, no named supersession, and at least
one untrustworthy timestamp — which is precisely the shape of a persuasive old
thread recovered from the account. It does not win. It also does not silently
lose. The contested class retains its previously admitted value, no lane is
blocked, and the founder receives **one binary question** naming both locators
rather than two documents to read.

Scope discipline does more work than it appears to. Scope is a set of declared
decision-class identifiers, never inferred from topic. Most apparent conflicts
are two utterances about the same subject touching different classes — not
conflicts at all. Keyword matching would manufacture them, and manufactured
conflicts consume the one resource this entire design exists to protect.

## B.6 What the rule forbids, stated plainly

**Recovering context by reading a thread and reporting what it means is
inadmissible above `S1`, however accurate it is.** That is the single most
natural way to use the account, and it is exactly what the rule refuses, because
accuracy that cannot be checked is indistinguishable from confidence.

The recovery protocol instead returns *utterance records*: verbatim text, a
stable locator, speaker class, speech act, declared scope. Fields it cannot
establish are left absent, never guessed — and an absent speaker class is
`UNATTRIBUTED`, which is `S0`. Then the records land in git, and only then are
they evidence.

## B.7 Is it executable? Yes, and here is what it catches

`DIRECTLY_REPRODUCED`, 2026-08-23, receipt `raw/intentctl-reproduction.txt`:

```bash
cd workstreams/so02/control-plane/operating-environment/w8-chatgpt-constitution
python3 tools/intentctl.py validate                 # PASS: 4 utterances, schema and locator discipline hold
python3 tools/intentctl.py conflicts                # PASS: no contested class unresolved (exit 0)
python3 tools/intentctl.py resolve --scope DC-OPERATING-AUTHORITY
python3 tools/negative_tests_intentctl.py           # PASS: all 16 failure modes rejected
```

The live ledger holds four real utterances transcribed from repository files with
pinned commits. It resolves `DC-OPERATING-AUTHORITY` between two `S4` founder
utterances by `FOUNDER_PRECEDENCE_RECENCY` — the correct step, on a real pair —
and it resolves `DC-CHATGPT-FUNCTIONS` to `NO_ADMITTED_CLAIM` because the only
utterance touching it is the advisory proposal at `S1`.

The sixteen rejected failure modes, each an actual way this could go wrong:

| | Injected | Caught by |
|---|---|---|
| `NT1` | assent to an assistant proposal claimed as founder intent | `CAP-ACKNOWLEDGEMENT` |
| `NT1b` | the founder restating content himself, which must **not** be suppressed | the discriminator both ways |
| `NT2` | a recovered directive stored as a paraphrase, claiming standing | `CAP-PARAPHRASE` |
| `NT3` | a founder directive whose only locator is a display alias | `CAP-ALIAS-LOCATOR` |
| `NT4` | a recovered thread with no verifiable time contesting a current statement | step 5, fail closed |
| `NT4b` | the conflict arriving as reading material rather than one question | the question is generated |
| `NT5` | a newer assistant utterance beating an older founder directive | step 2 |
| `NT6` | supersession claimed against a target not in the ledger | named, never inferred |
| `NT7` | scope given as a topic keyword | scope discipline |
| `NT8` | voice capture with no confirmed read-back, claiming standing | `CAP-UNCONFIRMED-VOICE` |
| `NT9` | a recovered directive still in the provider, settling a class | the custody axis |
| `NT10` | an utterance with no established speaker claiming founder standing | `UNATTRIBUTED` → `S0` |
| `NT11` | the founder thinking aloud, admitted as a decision | the standing table |
| `NT12` | a repository locator naming no commit | locator discipline |
| `NT13` | the rule refusing to decide where the founder authorised recency | step 4 must still fire |
| `NT14` | date order overriding a named supersession | step 3 precedes step 4 |

`NT13` is there deliberately. A rule that refuses every conflict would pass every
other test on this list and be useless. The rule has to decide where the founder
said to decide, and fail closed only where deciding would mean inventing the
input.

## B.8 Where this connects, and what it does not claim

It plugs into the estate's existing admission ladder rather than competing with
it: standing answers *how much authority does this carry*, the ladder answers
*how far up may this subject move*, and both must pass. A recovered utterance at
`S4` still cannot lift a subject above `PROPOSED` on its own.

Two honest limits. The rule assumes utterance records can be produced with
verbatim text and stable locators — which depends on the recovery route, and
**`P5`'s route is not established by this lane**. If no route produces verbatim
text with locators, the rule still runs; it simply admits almost nothing, which
is the correct failure. And `record_kind` is carried on every record so a fixture
can never be mistaken for a real founder utterance: the four in the live ledger
are `REAL` and transcribed from committed files, and every synthetic record used
in testing is constructed inside the test file and marked `ILLUSTRATIVE`.
