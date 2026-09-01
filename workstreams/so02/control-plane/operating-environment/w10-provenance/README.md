# OE-W10 — provenance re-derivation

**Lane:** `OE-W10-PROVENANCE-REDERIVATION` · **Commission:** `COM-CUR-ENV-01-20260822-v001`
**Base commit:** `21c8ef88d01cccf419036d9fdcc164a8769ddf05` · **State:** `READY_TO_COMMIT`
**decision_changed:** `[]` — this classifies constraints and recommends dispositions. It binds no company strategy and applies nothing.

## What this lane was asked to settle

The founder's standing amendment of 2026-08-23 rules that the defect in this
programme was never the existence of constraints but **who authored them**, and
that a constraint traceable neither to his words nor to a named defect is void.
A prior lane classified 76 constraints against that test and got at least one
wrong in a way that invalidates its method: it certified `FB-11`, the
protected-surface prohibition, as founder-bound partly because the commit
carrying it was authored under the founder's git identity.

Assistant lanes commit under that identity as a matter of course. So the whole
classification had to be re-derived against **quoted founder text**.

## The finding in one paragraph

The verbatim founder corpus for this programme is **three utterances totalling
8196 bytes**. The prior register reached 27 founder-bound verdicts across five
source documents and cited that corpus **zero times** — because at its base
commit the corpus did not yet exist. **Ten of the 27 survive a quotation test.**
Nine of the ten survive only restated: eight narrowed to what their founder
sentence actually entails, one widened. Five were not authority at all but
mechanism, with receipts already sitting in the same register attached to
something else. Twelve were not founder material in any form. Two constraints
filed under `EARNED` do not belong there either — one cites a counterfactual
while labelled `DIRECTLY_REPRODUCED`, and one is a named-target prohibition list,
the exact shape the founder voided, hiding in the class a de-restriction lane
would never search.

All 22 prior `ASSISTANT_IMPOSED` verdicts hold, untouched. A method that damaged
one class and left the other two intact was not producing noise.

## Artifacts

| File | What it is |
|---|---|
| `FOUNDER-CORPUS-20260823-v001.json` | The three verbatim founder utterances, extracted by section anchor and hashed. Never retyped. |
| `CORPUS-ADMISSION-20260823-v001.json` | Every candidate document assessed: which are his words, which are documents *about* his authority, and why. |
| `PROVENANCE-REGISTER-20260823-v001.json` | 86 constraints, each with a class, a citation and a justification. |
| `CLASSIFICATION-DIFF-20260823-v001.json` | Every verdict that changed and why — the measurement of the damage. |
| `PURGE-AND-RATIFICATION-20260823-v001.json` | Derived from the register by `provctl.py lists`, so the two cannot disagree. |
| `tools/provctl.py` | The classifier. Stdlib only, no network. |
| `tools/negative_tests_provctl.py` | 27 tests proving it refuses. |

## Running it

```bash
python3 tools/provctl.py build-corpus  ../FOUNDER-STANDING-INSTRUCTION-20260822.md FOUNDER-CORPUS-20260823-v001.json
python3 tools/provctl.py verify-corpus ../FOUNDER-STANDING-INSTRUCTION-20260822.md FOUNDER-CORPUS-20260823-v001.json
python3 tools/provctl.py check FOUNDER-CORPUS-20260823-v001.json PROVENANCE-REGISTER-20260823-v001.json --repo-root <repo>
python3 tools/provctl.py diff  ../w4-platform-roles/DE-RESTRICTION-REGISTER-20260822-v001.json PROVENANCE-REGISTER-20260823-v001.json
python3 tools/negative_tests_provctl.py
```

## What the classifier actually enforces

The founder's rule is that an unclassified constraint is not in force, and that
paraphrase does not qualify. Both are executable here rather than aspirational:

- A constraint with no provenance class is **refused**.
- A `FOUNDER_AUTHORED` verdict whose quotation is not a **literal substring** of
  a corpus segment is refused. A faithful paraphrase of a real founder sentence
  is refused — that is the test that matters, and `test_a_faithful_paraphrase_is_refused`
  proves it fires.
- A quotation lifted from the **ChatGPT advisory proposal** is refused. That
  block sits under a `## Verbatim` heading in the same file as the founder's own
  words, reads as authoritative prose, and carries none of his authority. It is
  the single most dangerous object in the corpus and the extractor excludes it
  by speaker class, so an inattentive rebuild cannot admit it.
- An `EARNED` verdict without a named defect, or whose receipt path does not
  exist at this commit, is refused.
- An `ASSISTANT_AUTHORED` constraint may not be quietly retained; it carries
  `PURGE` or `SEEK_RATIFICATION`, and a ratification request without a single
  binary question is refused.
- Editing one word of the founder record invalidates every quotation in the
  register until the corpus is rebuilt.

A quote that **voids** a constraint is substring-checked exactly as a quote that
authors one. Otherwise a lane could purge a rule by inventing a repeal.

## What this lane deliberately did not do

It removed nothing. Classification and application are separate acts, and a lane
that purged the constraints it classified would be a producer accepting its own
verdict — which `EC-16` forbids and which the founder's independent-acceptance
clause names directly. The root controller applies.

It also did not treat the amendment as licence to strip structure. The founder's
symmetry clause is recorded as `FA-06` and is the brake on the whole exercise:
every control he names in his *What stays* paragraph is retained and marked
founder-ratified, 30 constraints land in `EARNED` on their receipts, and no
manifest, read-back requirement or acceptance mechanism is touched. The test
applied throughout is whether he asked for the **thing**, not whether he wrote
the **file**.

## The one place the prior lane deserves defending

At its base commit `3f3ee110`, `FOUNDER-STANDING-INSTRUCTION-20260822.md` did not
exist — it was written 90 minutes later, and the amendment five hours after that.
Its verbatim corpus was empty. No constraint could have been shown
founder-authored by quotation, so the correct output was *"the corpus is empty;
nothing is classifiable as founder-authored"*, which is a refusal the estate's
own controls would have recognised.

Instead it substituted the best available proxy and returned 27 confident
verdicts. The defect is not that it lacked evidence. It is that it **failed open**
when it lacked evidence, and built a rigorous-looking instrument that measured
the wrong thing. That is the difference the checker in `tools/` is meant to make:
under the same scarcity it refuses rather than substitutes.
