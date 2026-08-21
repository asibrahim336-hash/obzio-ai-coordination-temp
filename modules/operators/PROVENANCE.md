# PROVENANCE

Read this before relying on any acceptance result produced by these packs.

## 1. Why acceptance is commit-first

The commit-first acceptance design in these packs was driven by a research
finding. The finding, as it was given to the operators who built the packs,
cited two papers:

- **arXiv 2607.05904**
- **arXiv 2607.24300**

and reported these effect sizes:

- A reference-free judge's **pass rate rose from 0.716 to 0.938** while the
  **true accuracy of the work being judged stayed at roughly 0.20**. The judge
  got more permissive; the work did not get better.
- The judge's **false-positive rate on answers that were actually wrong was
  0.906** — it approved nine of every ten wrong answers.
- Introducing **commit-first acceptance collapsed that false-positive rate from
  0.719 to 0.012**.

## 2. These citations and effect sizes are UNVERIFIED

**`CITED_BUT_UNVERIFIED_BY_PRODUCING_OPERATOR`**

Both pack-building operators explicitly reported that they could **not verify
these citations**. The papers postdate their knowledge cutoff, and neither
operator had retrieval access with which to check them. Neither operator read
the papers. Neither operator confirmed that arXiv 2607.05904 or arXiv 2607.24300
exist, that they say what the finding says they say, or that the numbers above
appear in them.

The operators implemented against the **engineering mechanism**, which stands on
its own reasoning independently of whether those papers exist: if a producer can
revise its claim after seeing whether the claim would pass, the acceptance test
measures the producer's willingness to revise rather than the quality of the
work. Forcing the claim to be committed first removes that degree of freedom.
That argument does not depend on the citations.

Do **not** present the effect sizes in section 1 as confirmed. They are a
reported motivation, carried forward verbatim so it can be checked later by
someone with retrieval access. Until someone does that, treat them as claims of
unknown status.

## 3. Known unenforceable controls, carried forward

These are limitations the producing operators identified in their own work and
deliberately recorded rather than hid. Each one is a place where the packs
*describe* a guarantee they do not actually *enforce*.

### 3.1 The acceptance key sits in the same interpreter as the producer

Acceptance is gated by a key that lives in the same Python interpreter process as
the code being accepted. Any producer able to execute arbitrary code in that
process can read or forge the key. The separation is notional.

**What would be required:** uid separation or host separation — the acceptor must
run as a different user, or on a different machine, from the producer. Neither is
implemented.

### 3.2 Producer and acceptor share `checks.py`

The producer and the acceptor evaluate the same `checks.py` module. A bug in a
check therefore fools both sides identically: the producer believes it has
satisfied the check, the acceptor believes the check was satisfied, and the
shared defect is invisible to the acceptance step.

Independent acceptance requires an independently-derived check implementation.
That does not exist here.

### 3.3 Pack 09 exactly-once is per-key, not per-intent

`09-infrastructure-operation` provides exactly-once semantics **per key**, not
**per intent**. Two distinct intents that resolve to the same key collapse into
one execution; one intent expressed under two keys executes twice. The guarantee
holds only where the key is a faithful, injective encoding of the intent — a
property the pack assumes and does not check.

### 3.4 Pack 10 magnitude acceptance is BEHAVIOURAL_ONLY

`10-economics-measurement` accepts claims about the **magnitude** of an economic
effect on the basis of observed behaviour alone. It has **no independent meter**.
It cannot distinguish a real effect of the claimed size from a behaviour that
merely looks like one. Magnitude acceptance in pack 10 is marked
**`BEHAVIOURAL_ONLY`** and should be read as "behaved consistently with this
magnitude", never as "this magnitude was measured".

## 4. Status of this record

This file records what was known and not known at publication (2026-08-20). The
unverified citations in section 1 and the unenforceable controls in section 3
were carried forward deliberately and in full. Do not remove them without
replacing them with verification — for the citations, retrieval of the papers;
for the controls, an implementation that actually enforces them.
