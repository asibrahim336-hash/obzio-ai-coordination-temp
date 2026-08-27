# DEF-21 applicability audit

**Structural finding to honour:** "DEF-21 was invisible to sequential fault injection and
was found only by deterministic simulation. Any fencing or lease claim needs
interleaving-aware testing. Chain validity does not imply fence uniqueness." `DOCUMENTED`
(commission, `SCP-SI-01-SYSTEM-MAP.md:47`).

## Audit: does any mechanism this lane touched hold a fencing or lease claim?

Checked directly, not assumed, against every module this delivery's four defects reach:

- `provctl.py` / `provctl_paragraph_guard.py` (Defect 1) — classifies constraint
  provenance from a static corpus and a static register. No claim, no holder, no token,
  no concurrent writer. **Not applicable.**
- `write_admission.py` / `evidence_gate_wiring.py` (Defect 2) — a per-write admission
  decision, single evaluation, no retained holder state across calls. The existing
  `check_concurrency_gate` (unmodified by this lane) already reads a live remote ref at
  decision time, which is the correct defence against a different hazard (two writers
  racing the same ref) — but it is not a lease: nothing is granted, held, or superseded.
  **Not applicable.**
- `gate_claim_state.py` / `gate_claim_state_fixed.py` (Defect 3, and the PROJECTION_WORDS
  half of Defect 4) — inspects one already-completed turn's transcript for the shape of a
  premature-completion claim. No fencing or lease object exists here either; the "claim"
  in `gate_claim_state.py`'s own name is an agent's completion claim in prose, not a
  fencing/lease token. **Not applicable.**
- `currentctl.py` / `currentctl_supersession_split.py` (DEF-SCP-01, Defect 4) — reads two
  git-scoped hashes (an artifact at its recorded commit, and the same path at branch tip)
  and reports one of four verdicts. This is the closest of the four to a "check something
  against a moving reference" shape, so it received the closer look:

  **Residual TOCTOU note, named rather than silently accepted (`HYPOTHESIS`, not
  reproduced):** `check_artifact_hash_with_supersession` performs the at-commit read and
  the at-tip read as two sequential `git cat-file` calls. Between them, in a live
  multi-writer repository, the branch tip could move again. This is a genuine
  time-of-check-to-time-of-use gap in the *reporting* of `EVIDENCE_SUPERSEDED` (the tool
  could report a tip hash that is itself already stale by the time a human reads the
  finding) — but it is not a fencing or lease claim in DEF-21's sense: `currentctl` grants
  nothing, holds nothing, and issues no token whose uniqueness could be violated by
  interleaving. Nothing here is *decided* under the race; a finding is *reported*, and the
  next run re-reads the tip fresh. DEF-21's own language — "chain validity does not imply
  fence uniqueness" — describes two concurrent holders each believing they hold a valid
  fence; there is no holder here to duplicate.

## Where DEF-21 actually belongs, and why this lane does not chase it there

The only fencing/lease vocabulary this lane found in the tree is `l5-chatgpt-scale`'s
decision-class lease table (`"grant, suspend and supersede decision-class leases with
fence tokens"`, `FUNCTION-TOPOLOGY-REGISTER-20260822-v001.json:107-108`) and
`currentctl.py`'s own `test_a_lease_token_is_not_work` (`RefGraphTests`, unmodified by this
lane — it tests that a coordination token is not miscounted as delivered scale, which is a
different property than fence uniqueness under interleaving). Neither is a mechanism this
lane's four defects touch, and building a new fencing/lease test harness for either would
be exactly the parallel-suite and other-namespace violations the hard boundaries forbid.
This section exists so the requirement to honour DEF-21 is answered by an explicit audit
— "checked, not applicable to the four defects in this delivery, here is why" — rather than
by silence.

Provenance: this whole document is `EARNED` where it names why a mechanism does or does
not qualify, `DOCUMENTED` where it cites another artifact's language, and the TOCTOU
observation is explicitly `HYPOTHESIS` — asserted as a reasoned risk, not reproduced with a
failing test, because no fencing/lease object exists in this lane's mechanisms for such a
test to interleave against.
