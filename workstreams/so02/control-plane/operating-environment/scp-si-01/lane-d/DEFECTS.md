# Deliverable 1 — four defects, each a failing pre-fix test, a mechanism change, and a passing rerun

Lane D, SCP-SI-01. Every claim below is labelled `DIRECTLY_REPRODUCED`, `DOCUMENTED`, or
`HYPOTHESIS`. Every constraint proposed is labelled `FOUNDER_AUTHORED`, `EARNED`, or
`ASSISTANT_AUTHORED`; unclassified is void and none is left unclassified here.

All four extend the **existing** harness named in the system map, per the hard boundary
against a parallel suite. No new test runner, fixture format, or assertion style was
introduced; each new test class sits inside the file that already tests the module it
regresses.

---

## Defect 1 — user-role / exact-substring mistaken for founder authorship

**Class:** `EARNED`, named `DEF-SCP-D-01` in this lane's own provenance ledger (no prior
cohort had named this exact failure mode; the commission's prose description is the
founder-relayed report this defect answers).

**Mechanism found broken:** `provctl.py`'s `_corpus_haystacks` builds its quotation-
matching haystack from a founder-attributed segment's *entire* raw text, keyed only by
whether the segment's `## Verbatim` heading carries a `_NOT_FOUNDER_MARKERS` string. A
segment can correctly be a founder-authored container while embedding, mid-paragraph, a
sentence the founder is quoting from someone else and explicitly disclaiming in the same
breath. The heading carries no marker, so the embedded disclaimed sentence certified as
`FOUNDER_AUTHORED` by plain substring containment.

**Extended, not duplicated:**
`workstreams/so02/control-plane/operating-environment/w10-provenance/tools/negative_tests_provctl.py`,
new class `Defect1EmbeddedDisclaimedAttributionTests`, added beside the file's existing
`ProvctlNegativeTests`.

**Mechanism change:** `provctl_paragraph_guard.py` (lane-d namespace) —
`_founder_only_text` splits a founder segment's raw text on `"\n\n"` (the same paragraph
grain `extract_segments` already joins on) and drops any paragraph containing a
`_NOT_FOUNDER_MARKERS` string before the haystack is built, applying the heading's own
trusted marker set one level deeper.

**Pre-fix failure → passing rerun (`DIRECTLY_REPRODUCED`, full transcript at
`evidence/DEFECT-1-TRANSCRIPT.txt`):**
```
--- pre-fix: unmodified provctl.py check (defect fixture) ---
PASS: 1 constraints, each classified, each citation checkable      <- wrongly admits it
exit=0

--- post-fix: lane-d provctl_paragraph_guard.py check (same fixture) ---
FAIL ADVERSARIAL-01: QUOTATION_NOT_IN_CORPUS - 'Protected surfaces must never be written
  to without owner approval, an' appears in no founder segment. Paraphrase does not
  qualify.
exit=1
```
Non-regression: the real 86-constraint register passes both the unmodified and the
guarded checker identically (`test_the_fix_does_not_regress_the_real_86_constraint_register`).

**Canonical patch proposed, not applied in place** (this lane's write boundary excludes
`w10-provenance/tools/provctl.py` itself):
`workstreams/so02/control-plane/operating-environment/scp-si-01/lane-d/patches/provctl.py.patch`.

---

## Defect 2 — hash-valid but unparsable artifact

**Class:** `EARNED`, named `DEF-SCP-D-02`. Already reproduced live by the commission
before this lane started (a lane published truncated JSON whose digest matched its
manifest exactly and passed closure); this lane's job was to check whether
`evidence_integrity.verify_artifact_validity` — which already exists — actually catches it,
and it does not get called from the one place that needed it.

**Mechanism found broken:** `write_admission.py`'s `check_evidence_gate`, `MANIFEST_CLOSURE`
branch, calls only `evidence_integrity.verify_manifest_closure`. That function checks that
every present path is covered by a hash and that `bundle_sha256` binds the entry list as
written — it never opens the files. A truncated, syntactically-broken JSON artifact,
correctly hashed and correctly listed, passes unchanged.

**Extended, not duplicated:**
`workstreams/so02/control-plane/operating-environment/tools/test_write_admission.py`, new
cases `test_injection_6d_the_unpatched_gate_wrongly_admits_a_hash_valid_but_unparsable_artifact`,
`test_injection_6e_the_lane_d_mechanism_fix_correctly_refuses_it`,
`test_injection_6f_the_fix_does_not_regress_a_genuinely_valid_manifest`, added inside the
file's existing `TheSixInjectionsTests` class (this is injection 6's own sub-case, not a
seventh injection — the six-injection framing the file already used is preserved).

**Mechanism change:** `evidence_gate_wiring.py` (lane-d namespace) —
`check_evidence_gate_with_artifact_validity` wires
`evidence_integrity.verify_artifact_validity` into the `MANIFEST_CLOSURE` branch alongside
the existing closure check. Also carries `verify_artifact_at_commit` and
`compare_to_branch_tip`, reused directly for DEF-05/DEF-16 (§ below) and for the DEF-SCP-01
fix (Defect 4), rather than being re-derived three times.

**Pre-fix failure → passing rerun (`DIRECTLY_REPRODUCED`, full transcript at
`evidence/DEFECT-2-TRANSCRIPT.txt`):** all 26 cases in `test_write_admission.py` pass,
including the three new ones; the unpatched-gate case constructs the exact truncated-JSON
artifact the commission described, confirms the unmodified `check_evidence_gate` admits it,
then confirms the lane-d wiring refuses it and that a genuinely valid manifest is
unaffected.

**Canonical patch proposed, not applied in place:**
`workstreams/so02/control-plane/operating-environment/scp-si-01/lane-d/patches/write_admission.py.patch`.

**DEF-05/DEF-16 honoured here too:** `evidence_gate_wiring.compare_to_branch_tip` is the
same function `test_def05_def16_supersession.py` exercises directly (§ below) and that
`currentctl_supersession_split.py` reuses for Defect 4 — one implementation, three
citations, not three forks.

---

## Defect 3 — `COMPLETED` without entry health and a read-back receipt (`FALSE_SUCCESS`)

**Class:** `EARNED`, named `DEF-SCP-D-03`.

**Mechanism found broken:** `.cursor/hooks/gate_claim_state.py`'s `saw_receipt` check is
substring-based: a prose sentence merely *mentioning* `MANIFEST.json` — with no such file
anywhere in the tree — reads as a receipt. Separately, a manifest that parses and hashes
correctly but declares `entries: []` and a fabricated `bundle_sha256` also reads as a
receipt, because the check never re-derives the hash or looks for the entries on disk.
Both are `FALSE_SUCCESS`: a `COMPLETED` claim with no verified output behind it.

**Extended, not duplicated:**
`workstreams/so02/control-plane/operating-environment/l1-cursor-baseline/
proposed-cursor-config/dot-cursor/hooks/verify_hooks.py`, new cases inside the file's
existing `gate_claim_state.py — stop` section.

**Mechanism change:** `strong_receipt_health` (lane-d namespace, inlined directly into
`gate_claim_state_fixed.py` rather than kept in a separate module — an earlier
`receipt_health.py` was found to duplicate this logic and was deleted). Requires, in
order: the artifact parses as JSON; it has at least one entry; every entry's path exists
on disk at read-back time; the manifest's own `bundle_sha256` recomputes correctly over
the entries it claims.

**Pre-fix failure → passing rerun (`DIRECTLY_REPRODUCED`, full transcript at
`evidence/DEFECT-3-TRANSCRIPT.txt`):**
```
PASS  PRE-FIX TRIPWIRE (DEF-SCP-D-03): a prose MENTION of MANIFEST.json with no such
      file anywhere in the tree is wrongly accepted as a receipt for COMPLETED
PASS  PRE-FIX TRIPWIRE (DEF-SCP-D-03), ... entries=[] and an unverifying bundle_sha256
      of all zeros: FALSE_SUCCESS accepted as a receipt
PASS  lane D fix: a mentioned-but-absent manifest is correctly refused
PASS  lane D fix: a zero-entry, non-verifying manifest is correctly refused
PASS  lane D fix does not regress a manifest that actually parses, covers a real entry,
      binds its own bundle_sha256, and reads back true from disk
```

---

## Defect 4 — the new defect this cohort observed: DEF-SCP-01 (assigned), plus one bonus

**Class:** `EARNED`, `DEF-SCP-01` — assigned by the coordinator directly to this lane on
`workstreams/so02/control-plane/operating-environment/scp-si-01/
DEFECT-SCP-01-SUPERSESSION-READS-AS-TAMPERING.json`, published on the integration branch
mid-run. Not invented: the coordinator observed it, named it, and routed it here; this
lane found the mechanism and built the regression.

**Mechanism found broken:** `currentctl.py`'s `check_reproducibility` compares a recorded
`sha256` against the current *working tree* only. That single comparison cannot
distinguish an integrity incident (the hash was never right) from routine drift (the hash
was right when recorded, the file has since legitimately moved on) — both report the
identical `EVIDENCE_HASH_MISMATCH`. This is the exact DEF-05/DEF-16 gap named by the
commission: "verify each artifact at its own commit, then compare against branch tip to
flag supersession; neither root alone is correct."

**Extended, not duplicated:**
`workstreams/so02/control-plane/operating-environment/l4-currentness-recovery/tests/test_currentctl.py`,
new class `DefSCP01SupersessionVsTamperingTests`, added beside the file's existing
`ReproducibilityTests`.

**Mechanism change:** `currentctl_supersession_split.py` (lane-d namespace) —
`check_artifact_hash_with_supersession` reads the artifact **at its own recorded commit**
first (`_artifact_at_commit`, reused from `evidence_gate_wiring.py`'s git-scoped read); if
that hash is wrong, reports `EVIDENCE_HASH_MISMATCH` (tampering, `ERROR`) without ever
consulting the tip. If it is right, only then compares against branch tip
(`compare_to_branch_tip`): a tip that has moved reports `EVIDENCE_SUPERSEDED` (`INFO`, new
severity level, not a failure); a tip that matches reports nothing. Entries with no
`artifact_commit` fall back unchanged to the pre-existing working-tree check — this keeps
every entry recorded before this field existed passing exactly as before
(`EVIDENCE_ANCHOR_MISSING` is available but not forced, for full backward compatibility).

**Pre-fix failure → passing rerun (`DIRECTLY_REPRODUCED`, full transcript at
`evidence/DEFECT-4-TRANSCRIPT.txt`):**
```
test_case_2_and_case_3_are_indistinguishable_in_the_unmodified_checker ... ok   (tripwire: confirmed conflated)
test_the_lane_d_mechanism_correctly_splits_all_four_cases ... ok               (clean / superseded / tampered / anchor-missing, all four correctly split)
test_the_fix_does_not_regress_the_real_estate_reproducibility_checks ... ok
```
Full file: 74/74 tests pass.

**Canonical patch proposed, not applied in place:**
`workstreams/so02/control-plane/operating-environment/scp-si-01/lane-d/patches/currentctl.py.patch`
— backward compatible: the three-way split activates only when an entry carries
`artifact_commit`; entries without it keep prior behaviour unchanged, verified directly
against the file's own pre-existing `ReproducibilityTests` (still 100% passing with the
patch's logic exercised via the lane-d module).

**Bonus regression found and fixed in the same hook while working Defect 3 — same "one
finding code silently covers two different cases" shape:** `gate_claim_state.py`'s
`PROJECTION_WORDS` regex required the completion word to follow the projection phrase, so
`"COMPLETED ... a pull request"` (completion word **first**) was never matched — the exact
word order the hook's own docstring names as the failure to catch. Fixed by matching both
orders. Pre-fix tripwire and passing rerun are in `evidence/DEFECT-4-TRANSCRIPT.txt`, Part
B. Folded into the same canonical patch:
`workstreams/so02/control-plane/operating-environment/scp-si-01/lane-d/patches/gate_claim_state.py.patch`.

---

## Provenance ledger for this document

- Defect framing 1-3 (user-role/authorship, hash-valid/unparsable, FALSE_SUCCESS):
  `DOCUMENTED` — the commission's own prose description of each, directly reproduced by
  this lane rather than invented.
- DEF-SCP-01 (Defect 4's primary content): `DOCUMENTED` — the coordinator's own published
  defect record, routed to this lane by name.
- Every mechanism-broken diagnosis, every mechanism-change design, and every transcript
  cited above: `EARNED`, named against the defect it fixes, `DIRECTLY_REPRODUCED` this
  session (raw transcripts retained under `evidence/`).
- DEF-05/DEF-16 and DEF-21 framing: `DOCUMENTED` (`SCP-SI-01-SYSTEM-MAP.md:46-47`); DEF-21's
  applicability to this delivery's four mechanisms is audited separately in
  `DEF-21-APPLICABILITY-AUDIT.md`.
