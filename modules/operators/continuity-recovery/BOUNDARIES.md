# BOUNDARIES — continuity-recovery

**MACHINE** = code refuses it, with a named test. **BEHAVIOURAL_ONLY** = prose
only; nothing here detects a violation.

## Permitted acts

| Act | Bound |
|---|---|
| Walk the recovery root and read every file | Read-only |
| Record a fact | Only via `Ledger.record(key, source, pointer)`, which reads the value **from the file** |
| Declare a gap | Must name what is missing and why |
| Report a contradiction | Must cite two sources; resolution is fixed at `UNRESOLVED_BY_DESIGN` |
| Write recovery artefacts | Outside the recovery root only |

## Prohibited acts

| # | Prohibited act | Enforcement | Mechanism |
|---|---|---|---|
| P1 | Advancing past `INDEPENDENT_ACCEPTANCE` alone | **MACHINE** | Spine gate. Test: `test_producer_cannot_self_advance` |
| P2 | Self-review | **MACHINE** | `SelfAcceptanceError`. Test: `test_self_review_machine_refused` |
| P3 | Recording a value that is not at the cited pointer | **MACHINE** | `Ledger.record` reads from the file; `CHK-CR-01` re-resolves independently. Tests: `test_injected_fabricated_fact_detected`, `test_ledger_cannot_be_told_a_value` |
| P4 | Citing a source that does not exist | **MACHINE** | `ProvenanceError` at record time; `CHK-CR-01`. Test: `test_dangling_source_detected` |
| P5 | A pointer that does not resolve | **MACHINE** | `resolve_pointer` raises rather than returning None. Test: `test_pointer_miss_raises_not_none` |
| P6 | A fact with no provenance | **MACHINE** | `Fact` has no constructor omitting it; `CHK-CR-02`. Test: `test_fact_requires_provenance` |
| P7 | Citing a source outside the recovery root | **MACHINE** | `CHK-CR-03`. Test: `test_out_of_root_source_caught` |
| P8 | Leaving scanned files unaccounted for | **MACHINE** | `CHK-CR-04` used ∪ ignored must cover scanned. Test: `test_unaccounted_file_caught` |
| P9 | Resolving a contradiction by choosing a value | **MACHINE** | `CHK-CR-05`. Tests: `test_injected_contradiction_is_reported_unresolved`, `test_resolved_contradiction_caught` |
| P10 | Absorbing a gap silently | **MACHINE** | `CHK-CR-06` cross-checks three counts. Test: `test_hidden_gap_caught` |
| P11 | Non-deterministic recovery | **MACHINE** | `CHK-CR-08` re-runs recovery and compares digests. Test: `test_recovery_is_byte_reproducible` |
| P12 | Writing output inside the recovery root | **MACHINE** | Recovery guard refuses. Test: `test_output_inside_root_refused` |
| P13 | Accepting side-channel/conversational input | **MACHINE (by signature)** | `build_machine` takes only a root path; the admission guard raises on any kwarg. Test: `test_side_channel_input_refused` |
| P14 | Recovering from an empty root | **MACHINE** | Recovery guard raises. Test: `test_empty_root_refused` |
| P15 | **Mis-modelling what the artefacts mean** | **BEHAVIOURAL_ONLY** | Provenance proves a value was *read*, never that reading it that way was *right*. See Weaknesses |
| P16 | Missing state that no artefact records | **BEHAVIOURAL_ONLY** | Unrecorded state is unrecoverable by definition. The gap report only lists absences the engine knows to look for |
| P17 | Trusting a forged artefact in the root | **BEHAVIOURAL_ONLY** | Recovery verifies provenance *within* the corpus; it cannot tell a genuine artefact from a well-formed fake |
| P18 | Monkeypatching the spine in-process | **BEHAVIOURAL_ONLY** | Needs a process boundary |


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

`oracle.py` re-walks the corpus with `os.walk` and `json.load` and re-derives
the headline facts: run count, completed runs, packs seen, producer ids,
orphan directories, and objective-level contradictions. It restates the
state-bearing filename set rather than importing `engine.INTERESTING`, so it
is a second opinion about what counts as state rather than an echo.

**Covers:** the structural counts — the confabulation-sensitive numbers.
**Does not cover:** whether the semantic mapping from artefact to state is
*right*; state no artefact records (unknowable from inside the corpus);
whether a well-formed artefact is genuine or forged; the full gap list.

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

1. **Provenance proves sourcing, not interpretation.** `CHK-CR-01` proves the
   value at `reconciliation.json/missing_returns/0` really is `"C-B"`. It
   proves nothing about whether "an entry in `missing_returns`" *means* an
   outstanding commission. Every semantic mapping in `engine.recover` is a
   hand-written judgement, unverified by any check. A wrong mapping produces
   perfectly-provenanced nonsense.
2. **The gap report is bounded by what the engine looks for.** Gaps are emitted
   from a fixed set of conditions (`final_state != COMPLETE`, `REJECT`
   verdicts, `missing_returns`, open PRs, orders awaiting confirmation, orphan
   run directories, missing acceptance events). State that was never written
   down produces no gap and no signal — it is simply absent, and the report
   will look clean. **This remains the pack's most dangerous property: a
   confident, complete-looking recovery over an incomplete corpus.**
   `open_items` counts known unknowns only. There is no measure of unknown
   unknowns and there cannot be one from inside the corpus.

   Two instances of this were found by writing the tests and are now fixed,
   which is worth recording because both produced a *clean-looking* report:
   - **Orphan runs were invisible.** A run that stopped before writing
     `return_state.json` was not a "run dir", so it contributed no facts and
     no gaps. A corpus full of abandoned work recovered as spotless. Orphan
     directories are now detected and surfaced
     (`test_gaps_are_enumerated_not_guessed`).
   - **Interrupted runs left no journal.** The spine flushed `journal.json`
     only at the terminal transition, so the run whose state most needed
     recovering was exactly the run with no journal. The spine now flushes the
     journal after every transition and on every guard refusal.
3. **Contradiction detection is narrow.** One contradiction class is
   implemented: two runs asserting different values for the same field of the
   same objective id (budget, deadline, statement). Disagreements about
   commissions, owners, or PR state are not compared at all. The control that
   matters (`CHK-CR-05`, do not resolve) is sound; the detection feeding it is
   thin.

   An earlier version keyed contradictions on the *pack name* and compared
   `accepted_run_digest`. That produced a **false positive on every normal
   corpus**: two independent runs of the same pack legitimately have different
   digests, and the engine reported them as contradicting. A detector that
   cries wolf on correct data is worse than no detector, because it trains the
   reader to dismiss the report. Caught by
   `test_recovery_after_contradiction_is_resolved_upstream`.
4. **Determinism is verified over a static corpus.** `CHK-CR-08` re-runs
   recovery and compares digests, which catches ordering and set-iteration
   nondeterminism. It cannot catch nondeterminism that depends on the corpus
   changing between runs, and it does not run under concurrent modification.
5. **`INTERESTING` is a filename allowlist.** An artefact carrying real state
   under an unrecognised filename is marked ignored-with-reason and passes
   `CHK-CR-04` cleanly. The inventory check proves nothing was *silently*
   dropped; it does not prove nothing *important* was dropped.
