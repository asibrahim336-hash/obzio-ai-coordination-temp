# BOUNDARIES — founder-intent-processing

**MACHINE** = code refuses it, with a named test. **BEHAVIOURAL_ONLY** = prose
only; nothing here detects a violation.

## Permitted acts

| Act | Bound |
|---|---|
| Segment the correction into claims with byte spans | Spans must reproduce source exactly |
| Classify scope (STANDING / ONE_OFF / AMBIGUOUS) and polarity | Marker-based; ambiguity is preserved, not resolved |
| Fire implication rules | Rules are declared data; the fired `rule_id` is recorded |
| Map implications to registered surfaces by tag | Only surfaces present in the registry |
| Emit change orders | Description only; no surface is edited |

## Prohibited acts

| # | Prohibited act | Enforcement | Mechanism |
|---|---|---|---|
| P1 | Advancing past `INDEPENDENT_ACCEPTANCE` alone | **MACHINE** | Spine gate. Test: `test_producer_cannot_self_advance` |
| P2 | Self-review | **MACHINE** | `SelfAcceptanceError` at construction. Test: `test_self_review_machine_refused` |
| P3 | Attributing a paraphrase to the founder | **MACHINE** | `CHK-FI-01` span-vs-source byte comparison. Test: `test_injected_paraphrase_detected` |
| P4 | Presenting an inference as a literal claim | **MACHINE** | `CHK-FI-02` requires `inferred: true`. Test: `test_unmarked_inference_caught` |
| P5 | An implication with no traceable source claim | **MACHINE** | `CHK-FI-03`. Test: `test_untraceable_implication_caught` |
| P6 | An affected surface with no change order | **MACHINE** | `CHK-FI-04`. Test: `test_surface_without_order_caught` |
| P7 | A change order aimed at an unaffected surface | **MACHINE** | `CHK-FI-05`. Test: `test_phantom_surface_order_caught` |
| P8 | Silently dropping a correction (implication reaching zero surfaces) | **MACHINE** | `CHK-FI-06`. Test: `test_orphan_implication_blocks_progress` |
| P9 | Acting on LOW confidence without founder confirmation | **MACHINE** | `CHK-FI-07`. Test: `test_low_confidence_requires_confirmation` |
| P10 | Promoting a ONE_OFF claim onto a policy surface | **MACHINE** | `CHK-FI-08`. Test: `test_oneoff_promotion_caught` |
| P11 | Normalising/trimming the correction before extraction | **MACHINE (indirect)** | Any normalisation breaks spans and trips `CHK-FI-01`. Test: `test_normalisation_would_break_spans` |
| P12 | Editing the actual surface files | **BEHAVIOURAL_ONLY** | This pack writes only into its run directory by construction, but nothing *prevents* the process from opening a surface file and writing to it |
| P13 | Mis-classifying scope because a marker was absent | **BEHAVIOURAL_ONLY / KNOWN-WEAK** | Classification is substring matching on a fixed marker list. See Weaknesses |
| P14 | Choosing bad implication rules | **BEHAVIOURAL_ONLY** | The rule set is a judgement call. Machine checks its *consistency*, never its *correctness* |
| P15 | Monkeypatching the spine in-process | **BEHAVIOURAL_ONLY** | Needs a process boundary |

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

### This pack's oracle: `PARTIAL_ORACLE`

`oracle.py` independently recovers the **literal claims** — the founder's own
words at byte offsets — using a character-scan segmenter that is a different
implementation from `engine.segment`'s regex. It also commits a set of
structural invariants that follow from the spec rather than the output.

**Covers:** the literal claims, and the invariants (every claim verbatim,
every inference marked, every implication reaching a surface, LOW-confidence
orders gated).
**Does not cover:** the **system implications**. Which rules should fire on a
given correction is a judgement; re-deriving them would mean copying the rule
table, and two copies of one rule table are one opinion stored twice, not two
opinions. Committing to them would be faking independence, so this pack does
not. That half of the output is accepted on `BEHAVIOURAL_ONLY` terms and the
`uncovered` list says so on every run.

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

1. **Scope and polarity classification is keyword matching, not comprehension.**
   `_scope_of` and `_polarity_of` are substring matches over fixed marker
   lists. Writing `test_classifier_blind_spot_is_demonstrated` found two real
   gaps: `"for this one"` was missing from the one-off markers, and `"did not"`
   was missing from the prohibition markers — so a prohibition was being
   classified as a DIRECTIVE. Both are now fixed, which is precisely the
   problem: they were fixed by *adding more strings*, and the next unlisted
   phrasing fails the same way. "That approach tends to create rework
   downstream" carries no marker at all and still misclassifies; the test
   asserts that observed behaviour rather than hiding it.
   The mitigation is directional, not complete: misclassification lands on
   AMBIGUOUS, which routes to a clarification surface at LOW confidence and
   cannot reach a standing-policy rule. So the classifier fails toward asking
   rather than toward silently rewriting policy. That is a property worth
   having, but it is not comprehension, and this pack should never be
   described as understanding what a founder meant.
2. **`CHK-FI-01` proves provenance, not honesty of selection.** An operator can
   quote verbatim and still mislead by quoting only half a sentence. The span
   check cannot see the omission.
3. **Sentence segmentation is regex-based.** "Ship by Jan. 5, not Feb." splits
   at "Jan." The spans stay verbatim so nothing is fabricated, but the claim
   boundaries are wrong. Abbreviation handling is not implemented.
4. **The registry is trusted input.** If a surface is missing from the
   registry, `CHK-FI-06` fires only when an implication reaches *zero*
   surfaces. An implication reaching one of three real surfaces looks clean.
   Registry completeness is unverified — the largest gap in this pack.
