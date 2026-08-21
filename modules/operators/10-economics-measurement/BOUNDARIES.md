# BOUNDARIES — pack 10 · economics-measurement

**MACHINE_ENFORCED** — code raises on violation; a test proves it.
**BEHAVIOURAL_ONLY** — prose. Nothing stops you.

## Permitted

- Measure any configuration for which spend reconciles.
- Report `None` for an undefined ratio.
- Refuse a comparison.
- Publish both components without offering a ranking.

## Prohibited

- A cost event with a basis outside the two declared sets.
- Publishing when events do not reconcile to declared spend.
- Cost per accepted unit when nothing was accepted.
- Counting a unit accepted by its own producer.
- Quoting model cost per accepted unit as the headline number.
- Ranking configurations with materially different harnesses on raw cost.

## Control table

| # | Control | Status | Mechanism | Proof |
|---|---|---|---|---|
| 1 | Every cost is attributed to exactly one class | **MACHINE_ENFORCED** | `classify()` raises `UnattributedCost` for any basis outside the two disjoint closed sets. There is no "other" bucket. | `t02` |
| 2 | Cost cannot leave the report | **MACHINE_ENFORCED** | `reconcile()` compares the event sum to declared spend and raises `UnreconciledSpend` naming the gap in micro-USD. | `t02` (dropping the event still fails, on 500 000) |
| 3 | Model and harness are held apart | **MACHINE_ENFORCED** | separate accumulators; `total = model + harness` re-derived by `checks.py` from the raw events. | `t03`, `t09` |
| 4 | Cost per accepted unit is undefined when nothing was accepted | **MACHINE_ENFORCED** | `None` + `status="NO_ACCEPTED_UNITS"`; `checks.py` additionally asserts the value is not the cost-per-attempt fallback. | `t04` |
| 5 | A self-accepted unit is not an accepted unit | **MACHINE_ENFORCED** | `add_unit` raises `SelfAcceptedUnit`; `checks.py` re-scans `work_units.jsonl`. | `t05`, `t09` |
| 6 | An accepted unit names its acceptor | **MACHINE_ENFORCED** | `add_unit` refuses `accepted=True` with no `accepted_by`. | `t07` |
| 7 | Unit shapes are coherent | **MACHINE_ENFORCED** | zero attempts, `first_pass` with >1 attempt, `first_pass` without acceptance, negative cost — all refused at admission. | `t07` |
| 8 | Configs with unlike harnesses are not ranked on raw cost | **MACHINE_ENFORCED** | amplification ratio > 1.5× → `NOT_COMPARABLE` with a stated reason. | `t03` (100× → refused) |
| 9 | The threshold does not refuse everything | **MACHINE_ENFORCED** | a genuinely like-for-like pair returns `COMPARABLE`. A control that always refuses is not a control. | `t06` (1.11× → comparable) |
| 10 | Every refused comparison still carries an equal-harness re-scoring | **MACHINE_ENFORCED** | pooled harness ÷ pooled attempts as a reference rate; `checks.py` requires it present on every `NOT_COMPARABLE`. | `t03`, `t09` |
| 11 | The model-only view is always published next to the full one | **MACHINE_ENFORCED** | `model_only_cost_per_accepted`, `model_only_ranking`, and `model_only_is_misleading` are mandatory fields on every comparison. | `t03`, `t09` |
| 12 | Every published ratio recomputes from the raw events | **MACHINE_ENFORCED** | `checks.py` rebuilds totals, per-unit ratios and amplification from `cost_events.jsonl` + `work_units.jsonl` and compares. | `t09`, `t10` |
| 13 | Integer money | **MACHINE_ENFORCED (by construction)** | all amounts are integer micro-USD; floats appear only in final ratios, rounded to 6 dp, and are recomputed identically by `checks.py`. | `t09` |
| 14 | Producer cannot advance past `MACHINE_CHECKS_PASSED` | **MACHINE_ENFORCED** | `SelfAcceptanceRefused`. | `t08` |
| 15 | Acceptance re-derived from disk | **MACHINE_ENFORCED** | acceptor re-runs `checks.run_checks`. | `t10` |
| 16 | Ledger append-only; pack code unmodified | **MACHINE_ENFORCED** | hash chain; manifest re-hash. | every run |
| 17 | Events are classified into the **right** class | **BEHAVIOURAL_ONLY** | The pack enforces that every basis is classified. It cannot know that `tool_invocation` spend was booked to the right config, or that retry tokens were not quietly filed as `input_tokens`. **Largest residual risk in this pack** — mis-filing retry cost as model cost is exactly how the weak-model illusion is built, and control 1 does not catch it. | none |
| 18 | Declared spend is the true spend | **BEHAVIOURAL_ONLY** | Control 2 reconciles events to a *declared* total. If the declared total is itself wrong, everything reconciles to the wrong number. | none |
| 19 | "Accepted" means the work was actually good | **BEHAVIOURAL_ONLY** | The pack enforces that acceptance came from someone other than the producer. A lax acceptor inflates the denominator and makes everything look cheap. Cross-read `first_pass_yield` against acceptance rate. | none |
| 20 | The 1.5× amplification threshold is right | **BEHAVIOURAL_ONLY** | A constant. Chosen to admit ordinary variation and refuse an order of magnitude. Not derived from anything. | none |
| 21 | Equal-harness normalisation is the right counterfactual | **PARTIAL** | Holding harness cost per **attempt** constant is one defensible normalisation, not the only one. It assumes harness cost scales with attempts, which is usually but not always true (a fixed-cost review board does not). Published alongside raw numbers, never instead of them. | arithmetic proven, model not validated |
| 22 | Acceptance key unreadable by producer | **BEHAVIOURAL_ONLY here** | single uid. | not proven |

## The specific failure this pack is built against

> a weak model in a strong harness mistaken for a strong model

`t03` runs the measurement on a campaign built to produce exactly that illusion
and asserts every step of the reveal:

| view | says |
|---|---|
| model cost per accepted unit | `weak-in-strong` is **6.32× cheaper** (667 vs 4 211 micro-USD) |
| total cost per accepted unit | `strong-light` **wins** (4 632 vs 7 333) |
| harness amplification | 10.0 vs 0.1 — a **100×** difference |
| verdict | `NOT_COMPARABLE` |
| equal-harness re-scoring | `strong-light` first |
| first-pass yield | 0.2 vs 0.9 |

The last row matters most: `first_pass_yield` reaches the same conclusion
without reference to money at all. When the money metrics and the yield metric
disagree, the accounting is wrong. When they agree, as here, the ranking is
real.

## How the illusion is actually built, and what stops it

`t02` reproduces the mechanism rather than the symptom. 500 000 micro-USD of
scaffold-driver cost — 76% of the weak config's total spend — is booked under
`misc_overhead`. Two independent guards catch it:

1. `UnattributedCost` at admission: `misc_overhead` is in neither set.
2. If you delete the event instead of classifying it, `UnreconciledSpend` fires
   and **names the 500 000 gap**.

Without both, `weak-in-strong` would have published at 1 778 micro-USD per
accepted unit and won on every metric. With them, it publishes at 7 333 and
loses. That single reclassification is the difference between the two answers,
which is why control 1 refuses rather than defaults.

**And control 17 is where this still fails.** If the same 500 000 had been
booked as `input_tokens`, every control in this pack would pass and the weak
config would look strong again. Nothing here validates that a basis is the
*correct* one, only that it is a *declared* one.


---

# COMMIT-FIRST ACCEPTANCE (supersedes the anchored acceptor)

## Why the previous design was replaced

The earlier acceptor was handed `workdir` and re-ran `checks.run_checks`. It
**read the candidate, then judged it**. That configuration is anchored: the
verifier is answering "is this defensible?" rather than "what is the answer?",
and a confident-looking artefact biases the judgement exactly where it must not.
The four-arm token gate (forgery, self-issuance, replay, head-staleness) proved
the acceptance was *unforgeable*. It did not prove it was *unanchored*.

The correction is not to hide the candidate. It is to make the acceptor commit
its own answer first, bound to the run, with the candidate still fully visible
afterwards.

> Provenance note: this change was directed by the coordinating lane, citing
> arXiv 2607.05904 and 2607.24300 (Jul 2026). Those citations are **past this
> operator's knowledge cutoff and were not independently verified here.** The
> design is implemented on the strength of the mechanism, which stands on its
> own: a verifier that commits before reading cannot be anchored by what it
> reads. Treat the specific effect sizes as unverified.

## The three parts, and where each is enforced

| # | Control | Status | Mechanism | Proof |
|---|---|---|---|---|
| C1 | The acceptor commits its own answer before opening any producer artefact | **MACHINE_ENFORCED** | `CommitFirstAcceptor.precommit()` writes `ACCEPTOR_PRECOMMIT` with `sha256(canon(expected) \|\| nonce)` into the hash-chained ledger. `ArtefactWindow.open()` writes `ACCEPTOR_WINDOW_OPENED`. `Run._verify_commit_first` requires commit-seq < window-seq. | `tCF-peek` |
| C2 | `derive()` cannot read the workdir | **MACHINE_ENFORCED (by signature)** | `derive(objective)` takes no path to the producer's directory. Same construction as `DriftAuditor.compare()` taking no `Evidence`. | inspect `acceptance.py` |
| C3 | An acceptor that peeked cannot then commit | **MACHINE_ENFORCED** | a window opened in the current round (since this acceptor's last decision) makes `precommit()` raise `PeekedBeforeCommit`. | `tCF-peek` |
| C4 | The anchored acceptor's token no longer opens the gate | **MACHINE_ENFORCED** | no `ACCEPTOR_PRECOMMIT` in the ledger → `NoPrecommitment`. `AnchoredAcceptor` is kept solely to prove this. | `tCF-anchored` |
| C5 | Divergence defaults REJECT | **MACHINE_ENFORCED** | `compare()` returns a bool; anything other than `True` raises `RejectedByAcceptor`. There is no "close enough" branch. | `tCF-own` |
| C6 | The channel carries one bit plus the reveal | **MACHINE_ENFORCED** | `AcceptanceOutcome` is a frozen dataclass with exactly `run_id`, `accept`, `reveal`, `precommitment`, `token`. `RejectedByAcceptor` stringifies to `"REJECT"`. `check_acceptance_channel_is_one_bit` fails any decision entry carrying `failed`/`report`/`diff`/`reason`/`guidance`/`rubric`. | `tCF-onebit` |
| C7 | The commitment is binding | **MACHINE_ENFORCED** | the token binds `precommit_digest`; the revealed `(expected, nonce)` must hash to the digest committed before the window opened, or `CommitmentMismatch`. | `tCF-own` |
| C8 | Conservative update on reject | **MACHINE_ENFORCED** | the winning commitment must postdate every earlier REJECT, so a rejected run is re-derived rather than re-argued; `max_attempts=2` then `AcceptanceBudgetExhausted`. | `tCF-conservative` |
| C9 | No commitment is fabricated where none can be derived | **MACHINE_ENFORCED** | `derivable=False` → `precommit()` raises `NoIndependentExpectation`; the only route out is `AttestedAcceptance`, which stamps `acceptance_machine_enforced: false`. | pack 10 `t13` |
| C10 | Diagnostics never travel the acceptance channel | **PARTIAL** | detail goes to the acceptor's own `audit_path`, not the return value. Under one uid the producer can still read that file — **BEHAVIOURAL_ONLY**, same class as the acceptance key. | not proven in-sandbox |

## What commit-first does NOT do

It judges **the answer**, not the producer's bookkeeping. An artefact edited in
a way that leaves the answer intact — a forged evidence id, a rewritten internal
counter — is invisible to the acceptor and is caught upstream by `checks.py` at
`MACHINE_CHECKS_PASSED`. The two layers are complementary and both are needed:
machine checks police the process, commit-first acceptance polices the result.

## What this pack's acceptor derives independently — AND WHERE IT CANNOT

**This is the pack where commit-first partially fails, and the pack says so.**

Spend is not observable after the fact by reading the workdir harder. If the
only record of what was spent is `cost_events.jsonl` — which the producer wrote
— then any "independent derivation" is re-reading the producer's file. That is
the anchored configuration wearing a commitment as a hat, and this pack refuses
to do it.

| Situation | Basis | Magnitudes | Arithmetic |
|---|---|---|---|
| An independent meter is supplied (billing export the producer does not write) | `INDEPENDENT_SOURCE` | **MACHINE_ENFORCED** — `t14` catches a fabricated harness total that passed every one of the producer's own checks | MACHINE_ENFORCED |
| No meter | `NONE`, `derivable=False` | **BEHAVIOURAL_ONLY** — no commitment is made, `NoIndependentExpectation` is raised, and the only route out is `AttestedAcceptance`, which writes `acceptance_machine_enforced: false` and `magnitude_acceptance: "BEHAVIOURAL_ONLY"` into the return state | still MACHINE_ENFORCED via `checks.py` |

`t13` proves the refusal and proves the attested artefact is honestly labelled.

Accepted-unit counts come from the meter rather than the producer because the
acceptor is the principal that accepted those units — its own count is not the
producer's claim.

Note what this does **not** fix: control 17 of the main table. A meter that
reports a true total, with retry cost mis-filed as `input_tokens` inside it,
still produces the weak-model illusion. Commit-first verifies the magnitude,
not the taxonomy.
