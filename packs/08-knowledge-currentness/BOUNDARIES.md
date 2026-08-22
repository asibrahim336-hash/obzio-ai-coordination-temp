# BOUNDARIES — pack 08 · knowledge-currentness

**MACHINE_ENFORCED** — code raises on violation; a test proves it.
**BEHAVIOURAL_ONLY** — prose. Nothing stops you.

## Permitted

- Read any pinned path, as often as needed, in full.
- Report `DRIFT`, `MISSING`, `UNKNOWN`, `INCOMPLETE`, `DEGRADED` freely.
- Refuse to publish.

## Prohibited

- Reporting `MATCH` on anything not read during this run.
- Carrying a verdict forward from a previous run.
- Deciding currentness from mtime, size, or any other proxy for content.
- Reporting `CURRENT` while any pin went uncompared.
- Writing to a pinned path.
- Re-pinning to make drift go away.

## Control table

| # | Control | Status | Mechanism | Proof |
|---|---|---|---|---|
| 1 | `MATCH` requires a comparison performed in this run | **MACHINE_ENFORCED** | verdicts are minted only inside `DriftAuditor.compare()`, which performs the read itself and takes no `Evidence` argument. There is no setter. | `t01`, `t04` |
| 2 | A carried-forward row is refused | **MACHINE_ENFORCED** | `_verify_row` checks an auth MAC minted with this auditor's per-run key, **and independently** checks `run_nonce`. Both fire. | `t03` (asserts both arms) |
| 3 | A hand-constructed `MATCH` is refused | **MACHINE_ENFORCED** | auth MAC does not verify → `UnbackedVerdictRefused`. | `t04` |
| 4 | A `MATCH` citing evidence this run never read is refused | **MACHINE_ENFORCED** | evidence id must be in `reader.registry` for this run. | `t05` |
| 5 | No mtime/size shortcut exists in the read path | **MACHINE_ENFORCED** | `LiveReader.read()` has one branch: read all bytes, hash them. `full_read` is a recorded field, and `checks.py` fails a `MATCH` backed by `full_read=False`. | `t02` proves the shortcut lies; `t03` proves we don't take it |
| 6 | Content change under a preserved mtime is still caught | **MACHINE_ENFORCED** | digest comparison, plus an `mtime_shortcut_disagreements` tripwire that records when the defective comparator would have disagreed. | `t03` (`disagreements == ["schema"]`) |
| 7 | Evidence that aged past the ceiling cannot be published as `MATCH` | **MACHINE_ENFORCED** | staleness recomputed at **publication** time from a monotonic clock; over-ceiling `MATCH` is demoted to `UNKNOWN` and status becomes `DEGRADED`. | `t06` |
| 8 | Partial coverage cannot read as healthy | **MACHINE_ENFORCED** | the report is scored against the **whole pinboard**, not the audited subset → `INCOMPLETE`. | `t07` |
| 9 | A vanished target is `MISSING`, with evidence of the attempt | **MACHINE_ENFORCED** | `TargetMissing` carries an `Evidence` record with `outcome="MISSING"`; `checks.py` requires every `MISSING` row to cite one. | `t08` |
| 10 | Zero comparisons cannot be published | **MACHINE_ENFORCED** | `NoComparisonPerformed`. | `t09` |
| 11 | `exit_code == 0` only for `CURRENT` | **MACHINE_ENFORCED** | computed in `report()`; cross-checked by `exit_code_consistent_with_status`. | `t01` vs `t06`/`t07`/`t08` |
| 12 | Prior reports never supply verdicts | **MACHINE_ENFORCED** | `recover_state()` reads the prior report for context and records `prior_verdicts_discarded`; the auditor starts with an empty row list and a new nonce. | `t03` |
| 13 | The published report is re-derivable from the evidence log | **MACHINE_ENFORCED** | `every_match_row_has_this_run_evidence` re-checks each `MATCH` against `evidence_log.jsonl` on disk. | `t10`, `t12` |
| 14 | Producer cannot advance past `MACHINE_CHECKS_PASSED` | **MACHINE_ENFORCED** | `SelfAcceptanceRefused`. | `t11` |
| 15 | Run ledger append-only, pack code unmodified | **MACHINE_ENFORCED** | hash chain; manifest re-hash. | every run |
| 16 | Re-pinning is not reachable from a run | **MACHINE_ENFORCED (by construction)** | no run method calls `Pinboard.pin()`. It is a separate, human-invoked call requiring `by=`. | inspect `state_machine.py` |
| 17 | The right things are pinned | **BEHAVIOURAL_ONLY** | The pack proves the pins it has are current. It has no opinion about the pins it does not have. An unpinned config drifts invisibly and silently. **Largest residual risk in this pack.** | none |
| 18 | The pin was correct when taken | **BEHAVIOURAL_ONLY** | `pin()` records whatever is there at pin time. Pinning a broken file makes broken the expectation. | none |
| 19 | The audit actually gets run on a schedule | **BEHAVIOURAL_ONLY** | Nothing here schedules anything. A control that stops executing reports nothing at all — which is exactly as bad as a false MATCH and much easier to overlook. Monitor `comparisons_performed` externally. | none |
| 20 | `max_staleness_s` is set sensibly | **BEHAVIOURAL_ONLY** | A large ceiling makes control 7 inert. | none |
| 21 | Reads are atomic w.r.t. concurrent writers | **BEHAVIOURAL_ONLY** | `read_bytes()` on a file being rewritten can observe a torn state and report spurious `DRIFT`. Fails safe (noisy, not silent), but it is a false-positive source. | none |
| 22 | Acceptance key unreadable by producer | **BEHAVIOURAL_ONLY here** | single uid, single process. | not proven |

## The specific defect this pack is built against

> A drift row read `MATCH` while the underlying file had changed.

That single sentence covers four distinct mechanisms, and the pack blocks each
by a different control:

| Mechanism | Blocked by |
|---|---|
| (a) the row was carried forward from an earlier run | control 2 (auth MAC + run nonce) |
| (b) the "live" side came from a cache that outlived the change | control 4 (evidence must be in *this* run's registry); `LiveReader` holds no cross-run cache |
| (c) the comparator short-circuited on mtime and never hashed content | control 5 (single read path, `full_read` recorded and checked) |
| (d) a row was simply constructed with `verdict="MATCH"` | control 3 (unminted MAC refused) |

`t02` exists to keep the pack honest about (c): it takes the real file, changes
its content, restores its mtime with `os.utime`, and asserts that the mtime
comparator **still says MATCH**. If that test ever fails, the trap has stopped
being reproducible and controls 5 and 6 need re-justifying, not deleting.

## Known gap

Controls 1–16 make a *false* `MATCH` very hard to produce. They do nothing
about a *missing* one. If nobody schedules the audit, `drift_report.json` keeps
its last contents forever and every downstream reader sees the last known
status. This pack cannot fix that from the inside — see control 19. Whatever
schedules this run must alert on the run's *absence*, not only on its verdict.


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

## What this pack's acceptor derives independently

It **reads the pinned paths itself** and computes its own per-key verdict before
opening `drift_report.json`.

This is the cleanest fit of the five, and it changes the character of the
pack's central defence. Under the anchored design, a carried-forward MATCH had
to be *caught by a rule* — the auditor re-ran the producer's checks over the
producer's evidence log, and `every_match_row_has_this_run_evidence` was the
rule that caught it. Under commit-first the acceptor has already written DRIFT
from its own read before it ever sees the claim. No rule is consulted. The two
answers simply differ, and divergence defaults REJECT. `t15` proves exactly
that sequence.

Basis: `INDEPENDENT_SOURCE` (the pinned files).

Residual: the acceptor reads at commit time, the producer read at audit time.
A file that changes in between produces a spurious REJECT. That is a
false-positive source, and it fails in the safe direction.
