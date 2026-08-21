# BOUNDARIES — independent-acceptance

**MACHINE** = code refuses it, with a named test. **BEHAVIOURAL_ONLY** = prose
only; nothing here detects a violation.

## Permitted acts

| Act | Bound |
|---|---|
| Read any file under the subject root | Read-only handle; no write method exists |
| Import and execute the subject's `checks.py` | Against the subject's artefacts only |
| Verify the subject's manifest and digests | Recomputation, never trust |
| Emit findings, a scope record, a verdict, and an independence proof | Into the review directory only |

## Prohibited acts

| # | Prohibited act | Enforcement | Mechanism |
|---|---|---|---|
| P1 | Writing any file inside the subject | **MACHINE** | `WriteFence.check` raises `ProductionAttemptError`. Test: `test_fence_refuses_write_into_subject` |
| P2 | Placing the review output inside the subject | **MACHINE** | `WriteFence.__init__` refuses; `CHK-IA-03`. Test: `test_review_dir_inside_subject_refused` |
| P3 | Modifying the subject by any route, fence or not | **MACHINE** | `IndependenceProof` digest snapshot/re-verify; `CHK-IA-02`. Test: `test_out_of_band_subject_edit_voids_review` |
| P4 | Reviewing work this reviewer produced | **MACHINE** | Admission compares `subject.producer_id` to `reviewer_id`. Test: `test_cannot_review_own_work` |
| P5 | ACCEPT while holding a blocking finding | **MACHINE** | `Review.verdict()` + `CHK-IA-04`. Tests: `test_accept_with_blocking_finding_caught`, `test_verdict_is_derived_not_chosen` |
| P6 | REJECT with nothing to justify it | **MACHINE** | `CHK-IA-04`. Test: `test_unjustified_reject_caught` |
| P7 | A finding with no reproducible evidence | **MACHINE** | `CHK-IA-05`. Test: `test_evidence_free_finding_caught` |
| P8 | A vacuous review (no probes run) | **MACHINE** | `CHK-IA-06` mandatory probe list. Test: `test_vacuous_review_caught` |
| P9 | Trusting the subject's `check_report.json` | **MACHINE** | `CHK-IA-07` requires recomputation. Test: `test_forged_subject_check_report_detected` |
| P10 | Advancing past `INDEPENDENT_ACCEPTANCE` alone | **MACHINE** | Spine gate — applies to the reviewer too. Test: `test_reviewer_cannot_self_advance` |
| P11 | The reviewer accepting its own review | **MACHINE** | `SelfAcceptanceError`. Test: `test_reviewer_self_review_refused` |
| P12 | Reviewing an empty subject | **MACHINE** | Recovery guard raises. Test: `test_empty_subject_refused` |
| P13 | Reviewing with no expectations | **MACHINE** | Admission requires a required-artefact list. Test: `test_review_without_expectations_refused` |
| P14 | **Missing a defect that is really there** | **BEHAVIOURAL_ONLY** | The probe list is finite and hand-written. Nothing measures what it does not look for. This is the pack's largest limitation |
| P15 | Colluding with the subject's producer out of band | **BEHAVIOURAL_ONLY** | Identity separation is checked on *labels*. Two ids can be one person |
| P16 | Reading the subject and acting on it elsewhere | **BEHAVIOURAL_ONLY** | The fence governs writes into the subject, not what the process does with what it read |
| P17 | Executing the subject's `checks.py` (arbitrary code) | **BEHAVIOURAL_ONLY / RISK** | `P-04` imports and runs code from the subject pack. A hostile subject gets code execution in the reviewer. See Weaknesses |
| P18 | Monkeypatching the spine or the fence in-process | **BEHAVIOURAL_ONLY** | Needs a process boundary |

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

### This pack's oracle: `PARTIAL_ORACLE`, and it is ONE-SIDED

Note which thing is hidden. The acceptor of a review **must** read the
subject — that is its input. What the anchoring check hides until after the
commitment is the **review's own output**: findings, verdict, scope.

A fully independent expectation of a verdict would mean re-deriving every
probe, i.e. reimplementing the reviewer. So `oracle.py` derives only a **lower
bound on strictness**: it independently detects structural defects no
competent review could miss (absent return_state, incomplete run, a
self-reviewed subject, a self-contradictory check report, missing or empty
required artefacts). If any exist, the verdict MUST be REJECT.

* **Catches** a false ACCEPT over a structurally broken subject — the
  false-positive direction, which is the rubber-stamp failure mode.
* **Cannot catch** a false REJECT, and cannot catch a subject that is
  structurally clean but substantively wrong.

`test_one_sided_oracle_admits_it_cannot_catch_false_reject` demonstrates the
gap rather than asserting it. "One-sided" must be read as one-sided.

There is also a recursion worth naming: this pack produces a review, so its
own acceptance is subject to the same gate one level up. The regress stops
where someone decides to stop checking, and that decision is outside the
machine.

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

1. **The probe set bounds the review.** Seven probes are implemented. They
   catch structural and self-contradiction defects: absent artefacts,
   incoherent completion claims, reports that disagree with recomputation,
   broken digest bindings, tampered journals. They do **not** assess whether
   the subject's work is *correct*, *well-judged*, or *fit for purpose*. A
   subject that is internally consistent and substantively wrong passes every
   probe. "ACCEPT" from this pack means "no structural defect detected", and
   should never be read as "this is good work".
2. **`P-04` executes code from the subject.** Recomputing the subject's checks
   means importing its `checks.py` and running it inside the reviewer process.
   That is the only way to avoid trusting its report, and it is a genuine
   privilege boundary violation: a hostile subject pack executes arbitrary
   code as the reviewer, and could patch the reviewer's own fence or findings
   in memory. The correct fix is a subprocess with a restricted working
   directory; that is not implemented here.
3. **Identity separation is nominal.** `CHK-IA-01` compares two strings. If
   the same operator runs under two ids, every identity control in this pack
   passes. Nothing here can distinguish two principals from one principal with
   two labels.
4. **`IndependenceProof` is snapshot-based, not continuous.** It compares
   digests at scope time and at verdict time. A modification made and then
   perfectly reverted inside that window is invisible. It detects net change,
   not the absence of writes.
5. **`P-05` verifies the pack, `P-01`–`P-04` verify the run.** If the caller
   passes no `subject_pack_dir`, `P-04` degrades to an ADVISORY finding and
   `CHK-IA-07` then fails the review — which is the safe direction, but it
   means a review without the pack directory can never pass, and that
   constraint is not obvious from the call signature.
