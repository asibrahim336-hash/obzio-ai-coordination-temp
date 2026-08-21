# BOUNDARIES — strategic-orchestration

Every control below is labelled with how it is actually enforced.

- **MACHINE** — code refuses the act. A caller using the public API cannot
  perform it. Named check or code path given.
- **BEHAVIOURAL_ONLY** — prose. Nothing in this pack detects or prevents a
  violation. It holds only as long as the operator chooses to honour it.

A control is only MACHINE if a test in `test_pack.py` demonstrates the refusal.
Anything else is BEHAVIOURAL_ONLY, including controls that *feel* obvious.

## Permitted acts

| Act | Bound |
|---|---|
| Read the objective document and decomposition spec | Must contain `id`, `statement`, `budget_units`, `deadline_iso` |
| Emit commissions with acceptance criteria and an authority ceiling | Ceiling never exceeds the orchestrator's own |
| Produce a routing table and wave order | Order must respect declared dependencies |
| Reconcile supplied returns and report gaps | Report only; never repair |
| Write the four artefacts plus journal and return state | Into the run directory only |

## Prohibited acts

| # | Prohibited act | Enforcement | Mechanism |
|---|---|---|---|
| P1 | Advancing past `INDEPENDENT_ACCEPTANCE` without a reviewer reveal | **MACHINE** | `machine.advance()` gate; `AcceptanceError`. Test: `test_producer_cannot_self_advance` |
| P2 | Naming itself as its own reviewer | **MACHINE** | `OperatorMachine.__init__` raises `SelfAcceptanceError`. Test: `test_self_review_machine_refused` |
| P3 | Forging an acceptance token | **MACHINE** | SHA-256 preimage on `c_accept`. Test: `test_forged_acceptance_refused` |
| P4 | Turning a REJECT into an ACCEPT using the revealed reject secret | **MACHINE** | Split per-verdict secrets. Test: `test_verdict_upgrade_refused` |
| P5 | Replaying a valid reveal from another run | **MACHINE** | Reveal bound to `run_digest`. Test: `test_replayed_reveal_refused` |
| P6 | Editing artefacts after acceptance | **MACHINE** | Digest recheck on entry to `COMPLETE`. Test: `test_post_acceptance_tamper_detected` |
| P7 | Committing more budget than the objective holds | **MACHINE** | `engine.decompose` raises; `CHK-SO-01`. Test: `test_overcommit_refused` |
| P8 | Commissioning a dependency cycle | **MACHINE** | `engine._assert_acyclic`. Test: `test_cycle_refused` |
| P9 | Emitting a commission with no acceptance criteria | **MACHINE** | `engine.decompose`; `CHK-SO-02` |
| P10 | Delegating authority above the orchestrator's ceiling | **MACHINE** | `CHK-SO-03` authority ladder. Test: `test_authority_escalation_caught` |
| P11 | Skipping a lifecycle state | **MACHINE** | `next_state()` is strictly ordinal+1. Test: `test_no_state_skipping` |
| P12 | Reusing/rewinding a finalised machine | **MACHINE** | `_finalised` flag. Test: `test_machine_not_reusable` |
| P13 | Reporting a reconciliation as clean while gaps exist | **MACHINE** | `CHK-SO-06`. Test: `test_injected_missing_return_blocks_progress` |
| P14 | Performing the work inside a commission rather than routing it | **BEHAVIOURAL_ONLY** | Nothing stops the orchestrator process from doing engineering work itself. No artefact would reveal it. |
| P15 | Writing a self-serving decomposition (splitting to dodge review) | **BEHAVIOURAL_ONLY** | Budget and cycles are checked; *judgement quality* of the split is not machine-assessable |
| P16 | Fabricating the `returns` input before passing it in | **BEHAVIOURAL_ONLY** | Returns are trusted at the boundary. This pack has no provenance proof for them — see Weaknesses |
| P17 | Drifting into a declared non-goal | **PARTIAL / WARN-ONLY** | `CHK-SO-08` does substring matching on titles only. Trivially evaded by rewording. Do not treat as a control |
| P18 | Monkeypatching the spine in-process to bypass the gate | **BEHAVIOURAL_ONLY** | Python offers no intra-process isolation. Requires a process/OS boundary to enforce |

## Journal durability

`journal.json` is flushed after **every** transition and on every guard
refusal, not only at `COMPLETE`. A run that aborts mid-lifecycle therefore
still leaves a readable record of how far it got and why it stopped — which is
what `continuity-recovery` reads. This is a spine property
(`obzio_spine/machine.py`), shared by all five packs.


## Commit-first acceptance (supersedes identity-only acceptance)

The earlier design proved the acceptor was a **different identity** and that
its token bound this exact artefact set. It did not prove the acceptor formed
an **independent judgement**. An acceptor handed the workdir, reading the
artefacts and then deciding, is *anchored* to the thing it is judging.
Unforgeable and unanchored are different properties; the old gate had the
first and implied the second.

The acceptor now derives its own expected result from the run's **declared
inputs only**, and hash-commits it **before any artefact exists**. At the gate
it reveals that commitment; the machine compares the producer's artefacts
against it and **divergence defaults to REJECT**, enforced by the machine
rather than by the acceptor's discretion.

| # | Prohibited act | Enforcement | Mechanism |
|---|---|---|---|
| C1 | Committing an expectation after any artefact exists | **MACHINE** | `OperatorMachine.register_expectation` raises `AnchoringError`. Test: `test_anchored_acceptor_is_refused` |
| C2 | Running at all without a committed expectation | **MACHINE** | `advance()` refuses to leave PREFLIGHT. Test: `test_commit_first_is_mandatory` |
| C3 | Committing twice, or revising after seeing the work | **MACHINE** | `register_expectation` refuses a second commitment |
| C4 | Retrofitting an expectation to match the artefacts | **MACHINE** | SHA-256 commitment over salt+expectation+inputs; `verify_expectation` |
| C5 | Accepting despite divergence from the commitment | **MACHINE** | Machine overrides the ACCEPT bit and forces REJECT. Test: `test_divergence_forces_reject_over_acceptor_bit` |
| C6 | Returning a rationale, diff, or rubric to the producer | **MACHINE (by type)** | `AcceptanceReturn` carries one bit plus reveals; `Reveal.note` was deleted. Divergence detail goes to the acceptor's sink |
| C7 | Deriving the expectation from the producer's own engine | **MACHINE (structural)** | `assert_no_import` parses the oracle's AST. Test: `test_oracle_does_not_import_engine` |
| C8 | Two implementations silently disagreeing | **MACHINE** | Disagreement is divergence, and divergence is REJECT |

### This pack's oracle: `INDEPENDENT_ORACLE`

`oracle.py` recomputes commission ids, committed budget, missing/orphan/
duplicate returns, unmet criteria and wave count from the objective, spec and
returns using plain set and integer arithmetic. It does not import `engine.py`
(AST-enforced), and its wave layering is a separately written Kahn pass.

**Covers:** the reconciliation arithmetic — the part that is a fact.
**Does not cover:** whether the decomposition is a *good* one, whether each
commission is sensibly scoped, whether the routing chose the right pool, or
whether the returns are truthful about work actually done. Those are
judgements and the oracle does not pretend to them.

### What commit-first does NOT buy

It defeats **anchoring**. It does not defeat a **shared blind spot**. Both the
oracle and the engine in this pack were written by the same author against the
same specification. They are two implementations, not two adversaries. A
misconception present in the spec is present in both, and they will agree
enthusiastically on the same wrong answer.

`Derivation` states the strength of the claim on every run and it is recorded
in `return_state.acceptance_independence`:

| Value | Meaning |
|---|---|
| `INDEPENDENT_ORACLE` | separately-written code, does not import the engine |
| `PARTIAL_ORACLE` | covers only a subset of the output; the rest is uncommitted |
| `SHARED_ENGINE` | same code — proves reproducibility only, **not** independence |
| `NONE` | no derivable expectation; acceptance is `BEHAVIOURAL_ONLY` |

Genuine independence would require an oracle written by a different party who
had not seen this implementation. Nothing in this repository delivers that,
and no wording here should be read as claiming it.

## Known weaknesses in this pack's controls

1. **Return provenance is unproven.** P16. Returns arrive as a plain list of
   dicts. There is no signature tying a return to the operator that was
   commissioned. A caller can hand this pack whatever returns produce a clean
   reconciliation. Fixing this needs the same commitment scheme used for
   acceptance, applied per-commission.
2. **`CHK-SO-08` is not a control.** It is a lint with a warning severity and
   a naive substring match. It is listed to be honest that non-goal drift is
   effectively unpoliced.
3. **The authority ladder is a fixed list.** A capability introduced with an
   authority string outside `LADDER` is silently skipped by `CHK-SO-03`
   rather than refused. That is a real gap.
