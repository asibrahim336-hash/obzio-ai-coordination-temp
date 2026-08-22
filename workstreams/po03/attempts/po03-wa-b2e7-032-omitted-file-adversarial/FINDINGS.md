# po03-wa-b2e7-032-omitted-file-adversarial

Hypothesis: *A manifest that omits a real file must fail verification rather than
report success.*

**Verdict: PASS**, with two omissions that escape by never reaching a verifier,
both reproduced and both closed by a check shipped here.

Every manifest put in front of a verifier while omitting a real file was refused:
16 declared scenarios, 12 of them expecting a non-zero exit, all behaving exactly
as declared (`fixture_output.txt`). The two controls passed, which is what makes
the refusals mean anything — a verifier that refused everything would satisfy the
attacks and fail the controls.

## The attack that matters

Omission is the hardest manifest corruption to catch because the result can be
flawless on its own terms. Drop an entry, decrement `artifact_count`, subtract
that entry's byte count from `total_bytes`, and every internal cross-check agrees:

```
entry-omitted-manifest-fully-self-consistent   expected_exit=1 actual_exit=1 marker=UNCOVERED_FILE
line-omitted-trailer-adjusted-to-match         expected_exit=1 actual_exit=1 marker=MANIFEST_VIOLATION
```

A checker that recomputed totals from the entries handed to it would pass those
forever. Both refusals come from enumerating the source instead: the unit 029
auditor lists the artifact commit, and the unit 025 verifier re-enumerates its
declared source. `test_the_self_consistent_mutation_leaves_no_internal_contradiction`
asserts that the mutated manifest really is internally consistent, so the attack
cannot quietly degrade into an easier one.

The weaker forms are refused earlier and by different checks, which is worth
recording because it shows the refusal is not one lucky assertion:
`COUNT_DISAGREEMENT` for stale totals, `TOTAL_BYTES_DISAGREEMENT` once the count
is adjusted, `UNCOVERED_FILE` once the arithmetic is repaired, and `NO_ARTIFACTS`
for a manifest claiming the slot holds nothing.

## Gap one: the emitter omits payloads named like a generated document

`workstreams/po03/tools/emit_result.py` selects artifacts with
`Path(path).name not in GENERATED`, a basename test applied at any depth. A file
committed at `<slot>/nested/manifest.json` is therefore real, durable and never
counted, and the emitter reports `RESULT_COMMITTED` over it.

Reproduced against the live tool: five real files committed under the slot, the
manifest covered three, `nested/manifest.json` and `nested/result.json` omitted,
emitter exit 0.

This is a generation-time hole, not a verification failure, and the distinction
matters for the verdict. Handed the same commit, the unit 029 auditor refuses it
and names both files (`UNCOVERED_FILE x2`). Verification still fails closed; what
failed is the generator's idea of what to count.

Adjacent behaviour worth recording as sound: the emitter does *not* silently omit
an empty file or an empty slot. It refuses both outright, with
`refusing to count empty artifact` and `contains no artifacts`.

## Gap two: a file committed after the artifact commit escapes per-manifest audit

A manifest declares "at commit X the artifacts are these", and that claim stays
true forever. The unit 029 auditor enumerates the commit the manifest names, so it
is asking the right question and answering it correctly. But a slot accumulates
commits, and a file added after the artifact commit is present at the branch tip
while every manifest in the slot remains perfectly faithful.

Recorded honestly as a gap rather than dressed up as a refusal: the scenario
declares `expected_exit=0`, and the test suite requires that anything labelled a
gap declares it was not refused, so a gap can never be counted as a rejection.

## What this unit ships to close both gaps

`residual_coverage.py` asks the other question: what does a slot hold *now* that
no manifest in it ever claimed? It enumerates the slot at a chosen commit and
subtracts every claim from every manifest in that slot's history, matching by
content hash as well as by path so a manifested file that was later moved is not a
false positive. It excludes `manifest.json` and `result.json` at the slot root
only, which is precisely what makes gap one visible.

Both gaps are caught: `residual-check-catches-the-smuggled-payloads`
(`RESIDUAL_FILE x2`) and `residual-check-catches-the-late-artifact`.

Run against this repository's own slots at `d5417ec`, every manifested slot is
clean: 7 slots, 40 files, 0 residual bytes (`residual_audit.txt`). That is a real
result about this cohort's own work, not a synthetic one.

One fail-open was found in this tool while testing it and fixed rather than
tested around: an explicitly named slot that does not exist originally reported a
clean pass, so a mistyped task id in a CI loop would have turned a gate green
having audited nothing. It now exits 2 with `nothing was audited`.

## Exact commands and real outcomes

```
python3 -I workstreams/po03/attempts/po03-wa-b2e7-032-omitted-file-adversarial/omission_fixture.py
  -> PO03_OMISSION_PASS scenarios=16 rejecting=12 controls=2 generation_gaps=2   (exit 0)

python3 -I workstreams/po03/attempts/po03-wa-b2e7-032-omitted-file-adversarial/residual_coverage.py \
  --repo-root . --commit HEAD
  -> PO03_RESIDUAL_PASS slots=7 files_accounted_for=40 commit=d5417ec...          (exit 0)

python3 -I -m unittest discover -s <this subtree> -t <this subtree> -p 'test_*.py'
  -> Ran 24 tests ... OK                                                          (exit 0)
```

## Observed limitations

- **Coverage is only ever relative to a stated frame.** This unit adds a second
  frame, the slot at a commit, and does not eliminate the need to choose one. A
  file outside any `workstreams/po03/attempts/<slot>/` is invisible to
  `residual_coverage.py` by construction; the path-scope guard, not this tool, is
  what bounds where files may appear.
- **The emitter is unchanged.** `workstreams/po03/tools/**` is immutable to this
  producer, so gap one is demonstrated and compensated for downstream, not fixed
  at its source. Anything that consumes an emitted manifest without also running
  a residual check remains exposed to it.
- **Hash-matching relocated files trades one error for another.** A file whose
  bytes match a manifested entry is treated as covered even under a new path. That
  suppresses false positives on renames, and it also means an attacker who
  duplicates already-manifested bytes under a new name is not reported.
- **The synthetic capsule is not the real capsule.** The emitter needs a task
  capsule, and `workstreams/po03/control/**` is immutable, so the fixture builds a
  synthetic one inside a scratch repository. The tool under attack is the real
  file, copied byte-for-byte, but its input is constructed.
- **Scratch repositories are not durable evidence.** They exist for the duration
  of a run under a temporary directory. The durable evidence is the captured
  output committed in this subtree, not the repositories that produced it.
- **Only two verifiers and one generator were attacked.** Any other consumer of
  these manifests is unmeasured here.
