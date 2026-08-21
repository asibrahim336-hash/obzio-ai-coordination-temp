# BOUNDARIES — pack 07 · capability-manufacture

**MACHINE_ENFORCED** — code here raises on violation; a test proves it.
**BEHAVIOURAL_ONLY** — prose. Nothing stops you.

## Permitted

- Commission any capability, provided the acceptance spec is pinned first.
- Execute vendor artefacts inside quarantine to obtain evidence.
- Refuse a return for any reason in the verdict table.
- Re-commission as many times as the budget allows.

## Prohibited

- Treating the vendor's own status file, README, or results.json as evidence.
- Editing the spec after the return has been inspected.
- Advancing or promoting anything short of `MATERIAL`.
- Promoting on a `MATERIAL` verdict alone, without independent acceptance.
- Importing vendor code into the validating process.

## Control table

| # | Control | Status | Mechanism | Proof |
|---|---|---|---|---|
| 1 | Acceptance spec is pinned and hashed before the return is judged | **MACHINE_ENFORCED** | `dispatch()` writes `commission.json` with `spec_digest`; `validate()` compares and raises `SpecMutated`. | `t05` |
| 2 | Dispatch precedes receipt | **MACHINE_ENFORCED** | `checks.py` compares `dispatched_at <= return_received_at`. | every run |
| 3 | MATERIAL requires output **we** produced by running **their** artefact | **MACHINE_ENFORCED** | verdict arm requires `probes_passed == probes_defined >= min_probes_passed`; `checks.py` re-derives the count from `probe_log.jsonl`. | `t01`, `t09` |
| 4 | Vendor self-reports are never evidence | **MACHINE_ENFORCED** | undeclared files contribute 0 material bytes; name-matched status files are catalogued in `self_attestation_ignored`. | `t02` |
| 5 | Undeclared files earn no credit at all | **MACHINE_ENFORCED** | `material_bytes` accrues only for declared, type-conforming deliverables. | `t02`, `t03` |
| 6 | A module that parses but does not run is not a capability | **MACHINE_ENFORCED** | typecheck (`ast.parse` + `must_define`) and probe are separate gates; passing the first does not satisfy the second. | `t02` (asserts `type_ok` **and** `probe_passed is False`) |
| 7 | Loud-and-empty is distinguished from quiet-and-empty | **MACHINE_ENFORCED** | verdict precedence puts `NARRATIVE_RETURN` ahead of `EMPTY`; the prose-ratio arm is gated on `material_bytes > 0`. | `t02` vs `t03` |
| 8 | Only MATERIAL advances | **MACHINE_ENFORCED** | `artefacts_present()` raises `ReturnRejected`. | `t02`, `t03`, `t04` |
| 9 | Promotion requires independent acceptance, not just MATERIAL | **MACHINE_ENFORCED** | `promote()` raises `PromotionRefused` when `not self.accepted`. | `t07` |
| 10 | Declared paths cannot escape quarantine | **MACHINE_ENFORCED** | `_resolve_inside()` raises `QuarantineEscape` on traversal. | `t06` |
| 11 | Vendor code is never imported into the validator | **MACHINE_ENFORCED** | typecheck uses `ast.parse` on source text; execution is always `subprocess.run`. | read `_typecheck` / `_run_probe` |
| 12 | Vendor code executes under containment | **PARTIAL — see below** | cwd confined to quarantine, env stripped to `PATH`/two `PYTHON*` vars, wall-clock timeout, 16 KiB output cap. **No seccomp, no namespace, no container, no network block, no filesystem jail.** A malicious return can read and write outside quarantine and reach the network. | timeout/cap exercised; containment **not** proven |
| 13 | Producer cannot advance past `MACHINE_CHECKS_PASSED` | **MACHINE_ENFORCED** | `Run.advance` → `SelfAcceptanceRefused`. | `t08` |
| 14 | Acceptance is re-derived from disk | **MACHINE_ENFORCED** | acceptor receives only `workdir`; re-runs `checks.run_checks`. | `t10` |
| 15 | Run ledger append-only and tamper-evident | **MACHINE_ENFORCED** | hash chain. | every run |
| 16 | Pack code unmodified | **MACHINE_ENFORCED** | `check_pack_manifest`. | every run |
| 17 | Completion-claim detection is complete | **BEHAVIOURAL_ONLY** | Nine regexes over nine phrasings of "it works". A vendor writing "the artefact behaves as specified" trips none of them. **This is a reporting signal only** — see below. | none |
| 18 | The commissioned spec describes the capability actually needed | **BEHAVIOURAL_ONLY** | The pack proves the return matches the spec. It cannot know the spec was right. | none |
| 19 | Probes are strong enough to be worth passing | **BEHAVIOURAL_ONLY** | A probe asserting `exit == 0` on a script that does nothing passes. Probe quality is entirely on the author. **Second-largest residual risk after control 12.** | none |
| 20 | Acceptance key unreadable by producer | **BEHAVIOURAL_ONLY here** | Single uid, single process. Deployment needs uid or host separation. | not proven |

## Why control 17 being weak does not sink the pack

Claim regexes never cause a rejection. The rejection is caused by
`probes_passed < min_probes_passed`, which is measured by running the code.
A silent vendor that ships a broken module is refused exactly as hard as a
loud one — it just gets classified `PARTIAL` or `EMPTY` instead of
`NARRATIVE_RETURN`. The regexes only choose the label and the follow-up
action, so a missed phrase costs a nicer error message, not a false accept.

The inverse failure — regexes firing on prose that is merely *enthusiastic*
about a return that genuinely works — cannot cause a false reject either,
because the `MATERIAL` arm is evaluated first and does not consult claims at all.

## The specific failure this pack is built against

A return that looks complete from every angle except execution:

```
README.md      "successfully implemented ... production-ready"
STATUS.md      "# Status: COMPLETE"
results.json   {"status":"success","tests_passed":12,"coverage":"100%"}
solver.py      parses cleanly, defines solve() and main(), raises on call
cases.jsonl    valid, well-formed, real
```

Four of five signals are green. `t02` asserts that `solver.py` **passes** the
type check — that is the trap working as designed — and that the verdict is
still `NARRATIVE_RETURN`, because the only signal this pack lets be decisive is
the one it produced itself by running the code.


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

It **runs the probes itself**, against the same quarantine, in its own scratch
directory, and commits its own verdict. Quarantine is vendor input that both
parties observe; `assessment.json` is the producer's claim and is not an input
to the expectation. `t13` forges a MATERIAL assessment over a narrative return
and the acceptor rejects it, having already written down `NARRATIVE_RETURN`.

Basis: `INDEPENDENT_SOURCE` (the vendor artefacts, executed by us).

Residual: the acceptor executes vendor code, so control 12's containment caveat
applies to the acceptor's process too — now in two processes rather than one.
