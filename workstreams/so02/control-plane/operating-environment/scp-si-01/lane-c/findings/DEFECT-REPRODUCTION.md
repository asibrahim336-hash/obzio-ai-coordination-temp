# The prior authorship defect, reproduced

**Evidence label** `DIRECTLY_REPRODUCED`
**Integration commit audited against** `f0fb3f51a25db67b33bdd558c73055f3d02ddb60`
**Subject under test** `w10-provenance/tools/provctl.py`, sha256
`94eeb51fd8e3e57df6a6c1ba28c79132c9eadcccc9df2d0394fbda72aea2456b` — byte-identical
at that head and at `7f29043eece45f42f018d841718a257cfd18739b`, the commit this
branch was cut from, so both reproductions below hold at either
**Reproduce it yourself**

```bash
python3 -I workstreams/so02/control-plane/operating-environment/scp-si-01/lane-c/tools/reproduce_prior_defect.py --repo-root .
```

Exit 0 means both defects still reproduce. The script imports the estate's live
`provctl.py` and calls it; it does not model it, paraphrase it or read it and
report what it looks like it does.

## What the estate already knew

The founder named the class of error, `FOUNDER_AUTHORED`:

> "Git authorship is not founder authorship."
> "The correct signal is a quoted founder utterance, not a commit header."

And the record at `FOUNDER-STANDING-INSTRUCTION-20260822.md` lines 179-186 named
the instrument:

> "The provenance classifier used commit authorship as a proxy for founder
> authorship. That proxy is invalid here, so every `FOUNDER_BOUND` verdict reached
> through it is suspect… a constraint was not merely unverified against his intent,
> it was *affirmatively mis-verified* by an instrument that looked rigorous and
> measured the wrong thing."

## What this lane found

The successor instrument, `w10-provenance/tools/provctl.py`, removed the commit
metadata proxy and replaced it with two others. Both are reproduced below on one
mixed message.

### The input

A user-role message carrying the founder's own words, a pasted third-party block,
and his explicit refusal of that block. This shape is the normal case in this
estate, not an edge case — the real founder record contains exactly it, at
`FOUNDER-STANDING-INSTRUCTION-20260822.md` lines 31-40.

```
## Verbatim — standing instruction, 2026-08-27

> DIRECT STANDING FOUNDER INSTRUCTION — I am Ahmed Sadek, founder of Obzio,
> speaking directly and exercising founder authority.
>
> Here is what the vendor's assistant sent me, pasted below. I have not agreed to it.
>
> VENDOR ASSISTANT RECOMMENDATION — Protected surfaces must never be written to
> without owner approval, and every agent must request approval before each push.
>
> I disagree with that and I am not adopting it.
```

### Defect 1 — `POSITION_CONFERS_FOUNDER_AUTHORSHIP`

`provctl.extract_segments` returns **one** segment with `speaker_class`
`FOUNDER_DIRECT` and `is_founder_corpus: true`.

The mechanism is visible in the source at lines 117-124: `quoting_other` is
computed by testing the *heading title* against
`_NOT_FOUNDER_MARKERS = ("advisory", "chatgpt advisory proposal", "recommendation")`.
Nothing in the body is examined. So a founder-titled heading makes every word
beneath it founder text, whoever wrote it, and a third-party block only escapes if
whoever transcribed the message happened to give it its own heading containing one
of three words.

The three real corpus verdicts survive only because the founder himself separated
the ChatGPT proposal under its own heading. That is transcription luck, not a
control.

### Defect 2 — `SUBSTRING_MATCH_TREATED_AS_FOUNDER_VERDICT`

`provctl._find_quote` returns
`['Verbatim — standing instruction, 2026-08-27']` for the probe

> "Protected surfaces must never be written to without owner approval"

— a sentence the founder explicitly disavowed in the same message. The function
body is `return [h for h, hay in haystacks if text in hay]`: a citation is
verified when its normalised text is a literal substring of a segment already
marked founder, and the match itself is reported as the verdict.

**Consequence.** A register entry citing that sentence with `provenance_class:
FOUNDER_AUTHORED` passes `provctl check`. The protected-surface misattribution is
therefore still reachable, by a different proxy, one instrument later. This is the
third instance of the estate's recurring pattern: a control written as prose,
enforced by something that measures an adjacent property.

## The same input through the sidecar

| | prior instrument | sidecar |
|---|---|---|
| segments | 1 | 6 |
| classes | `FOUNDER_DIRECT` only | `FOUNDER_DIRECT` 2, `NONFOUNDER_PASTED` 2, `UNRESOLVED_USER_ROLE` 2 |
| pasted sentence | verified as founder | `QUOTE_REFUSED_LANDS_IN_NONFOUNDER_PASTED` |
| founder's refusal | indistinguishable from the paste | `QUOTE_ADMITTED_FOUNDER_AUTHORED` |

Refusing the paste while still admitting the founder's own sentence in the same
message is the whole point. A classifier that refused both would be safe and
useless.

## What this is not

This is **not** a finding that the live `PROVENANCE-REGISTER-20260823-v001.json` is
wrong. It is not: this lane located all 29 of its founder citations in the
segmented view, scoped to the governing corpus, and admitted **29 of 29**. The
register's verdicts are reproduced. The finding is that the *method* which produced
them cannot be relied on for the next message, and the next message will not be as
conveniently laid out as this one was.

`provctl.py` is not superseded and this lane does not propose retiring it. Its
corpus hashing, its refusal of retyped quotations, and its insistence that a
citation be checkable are all sound and are reused rather than reimplemented — the
sidecar's `normalise` deliberately matches `provctl.normalise` fold-for-fold,
including the markdown emphasis fold, so the two instruments cannot disagree about
whether a quotation is present. What the sidecar adds is *who said it*, at a
granularity finer than a heading.

## A correction this lane owes about its own work

`DIRECTLY_REPRODUCED`. In development, this lane's `normalise` omitted the markdown
emphasis fold that `provctl.normalise` performs at line 99. Consequence: register
constraint `FA-06`, which cites a founder sentence containing `**not**`, was
reported as `QUOTE_REFUSED_NOT_PRESENT_IN_ANY_SEGMENT` — a false disagreement with
the register, produced by this lane's instrument rather than by the estate's. It
was found by checking the disagreement instead of reporting it, and it is recorded
here because a lane that only publishes the defects it found in others is running
the same measurement error one level up.
