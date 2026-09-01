# Deliverable 2 — the 117 portability findings, triaged, and the sys.path.insert ruling

**Author:** Lane D, SCP-SI-01. **Provenance of this document:** `EARNED` where it states a
finding by name, `DOCUMENTED` where it reports another writer's artifact, `HYPOTHESIS`
where marked. Every claim carries `DIRECTLY_REPRODUCED`, `DOCUMENTED`, or `HYPOTHESIS`.

## 0. Where the 117 number comes from, and why it is not in this branch's tree

The commission (`workstreams/so02/control-plane/operating-environment/scp-si-01/SCP-SI-01-SYSTEM-MAP.md:45`)
reports **868 tests / 19 failures and 117 portability findings across 210 files** for "the
integrated tree" — `DOCUMENTED`, taken from the frozen system map, not independently
re-run here, because that integrated tree is `po03`'s, and `po03` is not present in
`origin/cursor/operating-environment-return-20260822-v001` (the ref this lane's worktree
was created from) or in any ancestor of this lane's `HEAD`. `git merge-base --is-ancestor`
confirms this directly — `DIRECTLY_REPRODUCED`.

The 117 figure traces to one authored artifact: `workstreams/po03/runtime/finding-triage.json`,
written by `po03-worker-a3` at commit `2779185a` on branch `cursor/po03-a3-portable-runtime-ed20`,
pinned to observation commit `0b91b697525e` on `cursor/po03-wave-a-transactional-factory-ed20`.
That document states the identical accounting the system map reports (117 hermeticity findings)
and is the authoritative source for the per-file triage. This is `DOCUMENTED`: found by
inspecting `po03`'s own branch history, not authored here, and not on this lane's branch.

To audit rather than merely cite it, I built a disposable scratch worktree (`/tmp/scratch-merge`,
outside this lane's branch and not part of this delivery), fetched and merged
`origin/cursor/po03-a3-portable-runtime-ed20` into it, and ran the actual prober,
`workstreams/po03/runtime/hermeticity.py`, myself. Output is attached in full at
`triage/hermeticity-reproduction-run.json` in this same directory — `DIRECTLY_REPRODUCED`.
That merged tree is **not** a3's exact pin (it also carries later `po03` merges — a11, a12,
a13 — that a3 never scanned), so the raw counts differ from her 117/17/32/68 split; the
per-file judgements below are what I checked line by line against her reasoning, not a
recomputation of her exact pinned totals.

## 1. a3's triage, as published (DOCUMENTED, commit `2779185a`)

| Bucket | Count | Meaning |
|---|---|---|
| `GENUINE`, reportable | 6 | Real portability defects, routed to the owning cohort |
| `FALSE_POSITIVE`, kept reportable | 2 | Residual imprecision named rather than hidden (see §4) |
| `FALSE_POSITIVE`, `EXEMPT_BY_ROLE` | 9 (other files, individually justified) | Detector caught a syntactic role, not a location |
| Reportable subtotal | **17** | 6 genuine + 2 residual + 9 exempt-with-individual-entries |
| `SYS_PATH_ANCHORED`, advisory | 68 | Accepted pattern, downgraded — see §2 |
| `EXEMPT_BY_ROLE`, remaining | 32 | Not individually itemised below the file level in her document |
| **Total** | **117** | 17 reportable + 68 advisory + 32 exempt, per her own summary |

Note on the arithmetic, stated rather than smoothed over: a3's own summary reports
`reportable_after: 17`, `exempt_by_role_after: 32`, `advisory_after: 68`, and states
`17 + 32 + 68 = 117`. Her `per_finding` array — the individually-justified rows — lists
23 entries (8 `REPORTED`, 15 `EXEMPT_BY_ROLE`), not 49 (17 + 32). Some of the 32
`EXEMPT_BY_ROLE` total is therefore accounted for at the **class/role** level in her document
(the eight named roles in `role_verdicts`) rather than as one row per file. This is
`DOCUMENTED` exactly as she left it — I have not renumbered it — and it is named here rather
than silently reconciled, in the same spirit her own document names its own residual
imprecision in §4 below.

## 2. The sys.path.insert ruling — answering as the gate owner

**Verdict: `ACCEPTED_PATTERN`. Not a real defect when the argument is anchored to `__file__`.
Downgraded to the advisory class `SYS_PATH_ANCHORED`, which does not fail the gate.**

Reasoning, independently checked rather than taken on faith:

1. **No package exists to import instead.** `EARNED` — verified directly: there is no
   `pyproject.toml`, no `setup.py`, no `__init__.py` anywhere under `workstreams/po03`, and
   the engineering standard forbids third-party packages. A cohort cannot be faulted for not
   using an installable package that does not exist and may not be created.

2. **`python3 -I` removes the one alternative that would make this unnecessary.** I built a
   minimal fixture (`sibling.py` next to `main.py`) and ran it: under `python3 -I`,
   `sys.path[0]` is `/usr/lib/python312.zip` — never the script's own directory — and
   `import sibling` fails with `ModuleNotFoundError`. `DIRECTLY_REPRODUCED` (this run, this
   session; the same result was independently reproduced in an earlier session of this
   task). Exactly two mechanisms remain available to a test that needs a module beside it:
   mutate `sys.path`, or load by location with `importlib.util.spec_from_file_location`.
   Flagging the first of two available, portable mechanisms is a style preference, not a
   portability judgement.

3. **The failure mode the rule exists to catch is a directory a clean clone might not have** —
   an absolute path, a vendored sibling, a path read from the environment. My own
   reproduction run confirms every anchored case in the current tree derives its argument
   from `__file__` (`SYS_PATH_ANCHORED`, 68 findings, `advisory_count: 68` in
   `hermeticity-reproduction-run.json`), which is inside the clone by construction — the
   exact property the rule protects. Recall is not lost: I scanned
   `workstreams/po03/runtime/fixtures/non_portable/import_path_mutation.py` (planted,
   unanchored `sys.path.insert(0, "vendor")`) directly and it still reports as
   `SYS_PATH_MUTATION` at full severity — `DIRECTLY_REPRODUCED`, output below.

   ```
   FINDING SYS_PATH_MUTATION workstreams/po03/runtime/fixtures/non_portable/import_path_mutation.py 11
   FINDING SYS_PATH_MUTATION workstreams/po03/runtime/fixtures/non_portable/import_path_mutation.py 12
   ADVISORY SYS_PATH_ANCHORED workstreams/po03/runtime/fixtures/non_portable/anchored_import_path.py 30
   ADVISORY SYS_PATH_ANCHORED workstreams/po03/runtime/fixtures/non_portable/anchored_import_path.py 34
   ADVISORY SYS_PATH_ANCHORED workstreams/po03/runtime/fixtures/non_portable/anchored_import_path.py 38
   ```

4. **Do not route 19 no-op fixes.** Editing 19 (a3 measured 66, this run's broader tree
   measures more) files to change zero observable behaviour teaches every future cohort that
   obeying the gate accomplishes nothing. That cost is real and larger than the residual risk.

5. **What the downgrade does not dismiss, and what I checked beyond a3's own writeup:**
   `sys.path` is process-global. A position-0 insert can shadow a same-named stdlib module and
   change import resolution for every later test in the same `unittest discover` run. That
   stays visible as `SYS_PATH_ANCHORED` rather than being mistaken for the defect it is not.
   I additionally checked one case a3's own tree did not yet contain:
   `workstreams/po03/holdout/generation_adapter.py:142` inserts
   `sys.path.insert(0, str(source_root))`, where `source_root` is **not** `__file__`-derived —
   it is a directory populated at run time by extracting a git archive of a historical
   commit into a caller-supplied `workdir`. My reproduction run correctly reports this as a
   full-severity `SYS_PATH_MUTATION` finding, not an advisory (`hermeticity-reproduction-run.json`,
   `findings[0]`) — `DIRECTLY_REPRODUCED`. This is exactly the shape a3's own "how this could
   be wrong" caveat anticipated (an inserted path that is not present in a clean clone), and
   the mechanism already gets it right without any change from me. It falls outside the
   pinned 117 (it postdates a3's observation pin) so it is not part of that count, but it is
   reported here as new information and routed in §5.

## 3. The two named literals — assessed on their merits

**A literal `/tmp/` in one cohort's tests.** Located at
`workstreams/po03/tests/test_a1_support.py` (`assertNotUnderTmp`, comparing a resolved path
against `/tmp/` in order to *refuse* it) and `workstreams/po03/tests/test_a8_scores.py`
(the right operand of an `in` test hunting for `/tmp` inside a score document). Both are the
detector's own invariant, restated inside a test that enforces the same property. **Verdict:
`FALSE_POSITIVE`, role `COMPARISON_OPERAND`.** `DOCUMENTED` (a3, same verdict, same
reasoning) and `DIRECTLY_REPRODUCED`: my own run of the live prober against the merged tree
places both lines in `exempt`, not `findings` — the exemption is already mechanically in
force, not merely argued for.

**A `~` home-path literal in the strengthened seeded validator itself.** `EARNED` naming: the
commission's own language ("seeded validator") matches
`workstreams/po03/tools/validate_contracts.py`, and I confirmed by `git log` that this exact
file was the subject of commits titled "harden transactional result gate" (`e15f95cf`) and
"strengthen transactional result schema validation" (`7e224c36`) — `DIRECTLY_REPRODUCED`, this
is the file the commission means. The literal is at line 227, inside `_resolve_local_ref`:
`raw_part.replace("~1", "/").replace("~0", "~")` — the RFC 6901 JSON Pointer escape
characters, decoding a document pointer, not resolving a home directory. **Verdict:
`FALSE_POSITIVE`, role `JSON_POINTER`.** I found a second instance of the identical pattern
while auditing the broader tree, `workstreams/po03/tests/test_a13_holdout_freeze.py:119`
(same `~1`/`~0` unescape, over a mutated JSON-pointer path in a test) — same reasoning, same
verdict, reported here as corroboration, not as part of the pinned 117.

a3's own document makes the sharper point I adopt rather than restate: this exact literal was
routed to a12/a5 as `GENUINE` *before* the precision work — the clearest evidence available
that an imprecise gate is not merely ignored, it is *believed*, and sends a writer to fix
something that was never broken.

## 4. What is still genuinely wrong, and where it is routed

Six findings are `GENUINE` per a3's triage and remain **unfixed** at the tree state I audited
(`DIRECTLY_REPRODUCED` — `grep` of the current file content on the merged tree still shows
every one of them; see §5 for the exact routing). Two more are named `FALSE_POSITIVE` but kept
visible on purpose ("residual imprecision") rather than silently suppressed:

- `workstreams/po03/packverify/boundary_run.py:34` — `ENV_READ` reading `PATH`, ruled
  `FALSE_POSITIVE` because the read is how the module builds a fully-enumerated child
  environment (hermeticity work, not ambient dependence), but kept reported because no
  structural rule distinguishes a fencing read from a leaking one — only a value allowlist
  would, and a3 declined to add one.
- `workstreams/po03/successor/g2/successor.py:204,207` — `ABS_PATH_LITERAL` on `/anchor`, a
  synthetic prefix stripped before any filesystem access, ruled `FALSE_POSITIVE` for the same
  reason: correctly not a sink, but not distinguishable from a real absolute path without
  following the value through the call graph.

I did not add either suppression myself: doing so would mean writing a value allowlist into
`po03`'s own prober from outside `po03`'s namespace, which is exactly the boundary this lane
must not cross, and it is exactly the "forgiven-value list" a3's own document rejects as what
"ends" a gate's credibility. Both stay named, not hidden.

## 5. Routing table — genuine findings, to the owning cohort

Ownership is read from `workstreams/po03/control/path-ownership.json` (as it stood at the
merge I audited), never asserted from memory:

| Finding | File | Rule | Owner | Status at audit |
|---|---|---|---|---|
| Socket import for telemetry probing | `workstreams/po03/metrics/probe_telemetry.py:16` | `NETWORK_IMPORT` | `po03-worker-a7` | **unfixed** |
| Socket connect, host-dependent result | `workstreams/po03/metrics/probe_telemetry.py:89` | `NETWORK_CALL` | `po03-worker-a7` | **unfixed** |
| `CANDIDATE_USAGE_PATHS`, 7 hand-written absolute host paths | `workstreams/po03/metrics/probe_telemetry.py:33-39` | `ABS_PATH_LITERAL` | `po03-worker-a7` | **unfixed** |
| Two of those seven are under `/tmp` | `workstreams/po03/metrics/probe_telemetry.py:37-38` | `TEMP_PATH_LITERAL` | `po03-worker-a7` | **unfixed** |
| Ambient env reads for provider discovery | `workstreams/po03/metrics/probe_telemetry.py:79,117` | `ENV_READ` | `po03-worker-a7` | **unfixed** |
| Hand-written `/usr/bin:/bin` PATH default | `workstreams/po03/packverify/boundary_run.py:34` | `ABS_PATH_LITERAL` | `po03-worker-a4` | **unfixed** |
| Unanchored `sys.path.insert` into a run-time git-archive extraction dir (new, postdates a3's pin) | `workstreams/po03/holdout/generation_adapter.py:142` | `SYS_PATH_MUTATION` | `po03-worker-a13` (owns `workstreams/po03/holdout/`) | **unfixed**, newly observed by this lane |

`po03-worker-a7`'s minimal fix, per a3 (`DOCUMENTED`, adopted, not reinvented): record
`NOT_OBSERVABLE` when the socket/paths/env are absent, so the recorded evidence is identical
on every host instead of varying with what happens to be listening — the probe may keep
running, but its committed output must stop depending on the host that ran it.
`po03-worker-a4`'s minimal fix, per a3: `os.environ.get("PATH", os.defpath)` — identical
behaviour on POSIX, correct on any platform. `po03-worker-a13`'s fix (mine, since a3 never
saw this file): anchor `source_root`'s insertion point, or scope the inserted path's lifetime
so it cannot leak into a later test's import resolution in the same `discover` run — named
here, not fixed here, since `workstreams/po03/holdout/` is `po03-worker-a13`'s namespace, not
this lane's.

This lane holds no write access to `workstreams/po03/**`, so no fix above is applied by this
delivery. Routing is a citation, not a patch.

## 6. Suite status

**Reported FAILING until the six genuine findings above are fixed.** This is not a
qualification of the `so02` control-plane suite this lane extends (§ tested separately, see
`SUITE-STATUS.md`) — it is the `po03` portability gate the commission asked this lane to
triage. Six real defects remain open in another cohort's namespace; the gate that catches them
is precise (§2-§3 show it no longer flags the two literals or the 68 anchored insertions), but
precision does not manufacture a fix this lane cannot write.

## 7. Provenance ledger for this document

- The 117 count, the system-map framing, and the 868/19/210 figures: `DOCUMENTED`
  (`SCP-SI-01-SYSTEM-MAP.md:45`).
- a3's full triage document, its reasoning, and its residual-imprecision note: `DOCUMENTED`
  (`workstreams/po03/runtime/finding-triage.json` @ `2779185a`).
- The `python3 -I` sys.path behaviour, the planted-fixture recall check, the exempt-list
  membership of the two named literals, the `validate_contracts.py` git-log confirmation, and
  the new `generation_adapter.py` finding: `DIRECTLY_REPRODUCED` (this lane, this run;
  raw output retained at `triage/hermeticity-reproduction-run.json`).
- The routing table's owner column: `DOCUMENTED` (`workstreams/po03/control/path-ownership.json`).
- The sys.path.insert verdict and the sole judgement about whether the residual imprecision in
  §4 should be suppressed: `EARNED` (named against DEF-05/DEF-16's "verify what you can, do
  not manufacture certainty you were not given the means to check" spirit) where it goes beyond
  restating a3, `ASSISTANT_AUTHORED` and inert unless ratified where it is this lane's own
  judgement call rather than a citation.
