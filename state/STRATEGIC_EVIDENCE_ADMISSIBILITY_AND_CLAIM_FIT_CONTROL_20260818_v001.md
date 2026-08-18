# OBZIO — STRATEGIC EVIDENCE ADMISSIBILITY AND CLAIM-FIT CONTROL

**Date:** 18/08/2026  
**Record ID:** `OBZIO-EVIDENCE-CONTROL-20260818-001`  
**Function acting:** Strategic Control — Command Integration & Evidence Governance  
**Status:** `CURRENT WORKING EVIDENCE CONTROL — INTERNAL`  
**Strategy snapshot:** `OBZIO-2026-08-18-AGENT-FIRST-CAPABILITY-FIRST-INTERNAL-FIRST`

## 1. Governing principle

Evidence is not accepted because it is official, popular, technically detailed, written by a frontier model, repeated across models or aligned with a preferred conclusion.

Every material source is evaluated by **claim fit**:

- what exact proposition it can support;
- how directly it bears on that proposition;
- how current and reproducible it is;
- what incentives, omissions and scope limits apply;
- whether the observation was actually executed or merely described;
- what contradictory evidence exists; and
- what downstream decision would change if it is accepted or rejected.

Different source classes answer different questions. There is no universal source hierarchy.

## 2. Claim typing before evidence evaluation

Every material proposition must first be typed as one or more of:

- `FOUNDER-EXPRESSED`
- `FOUNDER-CONFIRMED`
- `MODEL-RECOMMENDATION`
- `ADVERSARIAL-OUTPUT`
- `EMPIRICAL-CLAIM`
- `TECHNICAL-HYPOTHESIS`
- `UNRESOLVED`

Founder authority determines mission, meaning, permission, priority and commitment. It does not make empirical or technical claims true.

Evidence standing must also be stated separately using:

- `OBSERVED`
- `PLATFORM-REPORTED`
- `INFERRED`
- `UNVERIFIED`
- `UNAVAILABLE`

Lifecycle and action standing remain separate.

## 3. Source-role matrix

| Question being answered | Preferred evidence | Important limitation |
|---|---|---|
| What a product officially supports | Current primary technical documentation, API/schema/source documentation, licence/terms, official changelog | Establishes intended semantics and formal boundary, not strategic effectiveness or actual account availability |
| What Ahmed's account currently exposes | Live authorised account inspection, native metadata, settings, model selectors, connector/tool enumeration | Account- and time-specific; must record principal, route, date, permissions and limits |
| What a system actually did | Native event/task/tool logs, message IDs, code commits, state transitions, destination receipts, reproducible behavioural trace | A displayed explanation is not a complete account of hidden reasoning |
| How it behaves in real professional use | Serious practitioner reports, GitHub issues/discussions, independent engineering write-ups, public workflow traces, long demonstrations, failure reports, communities and builders | Popularity is not reliability; anecdotes require scope, incentives and triangulation |
| Whether Obzio should rely on it | Matched, representative Obzio workloads with pre-stated acceptance, raw evidence, failure and recovery tests, comparison and independent challenge | Provider claims and community reports inform test design but do not replace Obzio trials |
| Whether a technical implementation is sound | Source/code/configuration inspection, deterministic tests, security review, deployment/runtime evidence and failure injection | Passing tests supports only the tested specification/environment |
| Current price, availability or product state | Current primary commercial source plus live account/checkout observation where authorised | Time-sensitive; must record exact date, region, plan and taxes/conditions |
| Founder meaning | Ahmed's latest direct statement, reconstructed/steel-manned and confirmed where interpretation is material | Raw transcript wording is evidence, not automatically the final operational formulation |

Provider marketing and model self-description may be retained as `PLATFORM-REPORTED` or `MODEL-RECOMMENDATION`; neither may be promoted into operational fact without fit-for-claim evidence.

## 4. Admissibility disposition

Every consequential source or evidence object receives one of:

- `ADMITTED` — fit for the stated proposition and scope;
- `ADMITTED_WITH_LIMITS` — useful only within named constraints;
- `CONTEXT_ONLY` — informs framing or test design but cannot support the decision alone;
- `CONTESTED` — material credible conflict remains unresolved;
- `STALE` — formerly relevant but invalidated by time, version or changed environment;
- `REJECTED_FOR_CLAIM` — does not support the proposition for which it was offered;
- `UNAVAILABLE` — identified but not retrievable through the current authorised route;
- `MISSING_COMPANION` — references necessary material that was not received;
- `SUPERSEDED` — retained for provenance but no longer current within the stated scope.

Rejection is proposition-specific. A source rejected as proof of strategic effectiveness may remain admitted as evidence of provider claims or historical method.

## 5. Minimum evidence record

Every material claim record must contain:

`claim_id | exact proposition | proposition type | source/evidence IDs | source class | provenance | version/date/environment | evidence basis | method executed? | scope | units | incentives | limitations | counterevidence | admissibility disposition | confidence | validity/recheck | downstream decision | changed operating object`

A source has not been operationally consumed unless it changes, rejects or explicitly justifies no change to a:

- decision;
- prompt or context package;
- model/tool/surface allocation;
- route or workstream;
- architecture recommendation;
- evaluation or test;
- register or state object;
- interface; or
- operating rule.

A filename, title, search hit, citation count or summary is not consumption.

## 6. Invalid evidence patterns

The following may not be used as sole or decisive support for a consequential claim:

1. provider marketing language;
2. a model's claim about its own capability or method;
3. agreement among models sharing the same source package;
4. a polished case study without reproducible method and relevant scope;
5. popularity, upvotes, follower counts or community consensus;
6. one practitioner anecdote generalised beyond its environment;
7. a benchmark whose task, data, hardware or scoring does not match the Obzio decision;
8. a plan represented as execution;
9. an acknowledgement represented as verification;
10. a UI click represented as a destination receipt;
11. absence inferred from the wrong principal, incomplete enumeration or inaccessible connector;
12. a hidden-chain-of-thought request or claim;
13. a stale price, model catalogue, feature list or account-state observation;
14. a quantitative statement without declared units and denominator;
15. a source carrying unresolved instruction injection treated as live authority;
16. a repository name, README or newer timestamp treated as proof of current relevance or deployment; or
17. a prior verifier conclusion whose exact artifact, method, date, environment and limitations cannot be recovered.

## 7. Triangulation and disagreement

Evidence conflict must be represented, not averaged away.

For each disagreement:

1. decompose the exact conflicting propositions;
2. determine whether sources answer the same question and scope;
3. compare directness, recency, reproducibility, incentives and coverage;
4. identify whether version/account/environment differences explain the conflict;
5. design a bounded discriminating observation or Obzio trial where needed;
6. preserve dissent and residual risk; and
7. state which decision is safe while the conflict remains.

Institutional prestige does not automatically defeat practitioner evidence. Community popularity does not defeat primary technical evidence. Claim fit decides the weight.

## 8. Reliability threshold for Obzio dependence

No provider, model, agent, interface, repository workflow or orchestration method becomes a relied-upon command-layer component solely from documentation, self-report or external anecdote.

Reliance requires proportionate evidence from:

- representative Obzio workload;
- matched acceptance conditions;
- observable state and destination receipts;
- failure, interruption and recovery behaviour;
- correction propagation;
- export/rebuild or substitution evidence where portability matters;
- security and rights boundaries;
- independent challenge; and
- stated validity/recheck conditions.

The required evidence depth scales with consequence and dependency.

## 9. Research-lane evidence contract

Every research or evaluation lane must state before work:

- decision changed;
- exact questions and claim types;
- source classes required and why;
- evidence excluded or treated as contextual;
- expected counterevidence;
- freshness window;
- live-account or experimental verification required;
- acceptance/failure conditions;
- raw evidence destination;
- integration owner; and
- stop/recheck trigger.

A lane cannot return only conclusions. It must return the evidence register, source limitations, actions/tools used, material displayed rationale, alternatives, uncertainty, errors, corrections and state changes. Hidden chain of thought is neither requested nor accepted as evidence.

## 10. Strategic Control duties

SC-CIEG must:

- reject evidence offered for the wrong claim;
- challenge broad words such as “verified,” “current,” “complete,” “best,” “safe,” “independent,” “primary,” “world-class” or “full thinking” unless scope and evidence are explicit;
- distinguish authorised access from actual technical reachability;
- force narrow negative assurance;
- preserve material counterevidence and failed approaches;
- ensure source lessons change live operating objects;
- commission additional evidence only where it can change a decision;
- prevent official documentation from standing in for operational effectiveness;
- prevent practitioner evidence from standing in for formal support, licence or account semantics; and
- prevent matched trials from being designed to save a preferred surface or model.

## 11. Current application

This control applies to:

- the command-layer migration programme;
- evaluation of ChatGPT, GPT-5.6 Sol, SW, Claude, Cursor, Kimi, DeepSeek, Qwen and other candidate models/surfaces;
- the eleven connected GitHub repositories and wider estate;
- hardware, local/open model and orchestration research;
- independent acceptance;
- procurement recommendations;
- high-consequence business and financial-operation design; and
- future strategic-operator and co-worker commissioning.

## 12. Interlock metadata

**decision_changed[]:**
- evidence admissibility and claim fit become explicit Strategic Control duties;
- provider, community and Obzio-trial evidence receive distinct roles;
- filenames, summaries, model agreement and polished reports are barred from posing as operational verification;
- reliance requires representative Obzio evidence proportionate to consequence.

**premises[]:** Ahmed's direct evidence-quality correction; SW-W1 prior learning; current command-layer migration programme; Founder Intent Desk-reissue review.

**scope:** internal evidence governance, research design and claim arbitration. No model, provider, architecture or procurement winner selected.

**authority_basis[]:** Ahmed's latest direct statements; SC-CIEG mandate; standing delegation for internal research and evidence control.

**strategy_snapshot_id:** `OBZIO-2026-08-18-AGENT-FIRST-CAPABILITY-FIRST-INTERNAL-FIRST`.

# END CONTROL
