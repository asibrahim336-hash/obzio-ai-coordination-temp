# BOUNDARIES — pack 06 · browser-execution

Legend:
**MACHINE_ENFORCED** — code in this pack raises on violation; there is a test.
**BEHAVIOURAL_ONLY** — nothing here can stop you. Prose. Treat as a promise, not a control.

## Permitted

- Observe the surface as often as you like. Observation is free and unlogged-cost.
- Send a message into a conversation whose observed routing triple matches the
  intended `Target`, at send time, under a live token.
- Refuse. Refusal is always permitted and always cheaper than a misroute.
- Re-navigate and re-verify after a refusal, up to the bounded retry count.

## Prohibited

- Sending without a `SendToken` from `RouteGuard.verify`.
- Sending after the surface has moved since verification.
- Sending to a handle outside the allowlist.
- Exceeding `max_sends`.
- Editing, truncating or rotating `route_ledger.jsonl` during a run.
- Accepting your own run.
- Widening the allowlist or the send cap to make a refusal go away.

## Control table

| # | Control | Status | Mechanism | Proof |
|---|---|---|---|---|
| 1 | A send requires a token issued by `verify()` | **MACHINE_ENFORCED** | `send()` re-computes the HMAC over the token fields with a per-guard key; mismatch → `TokenForged`. Unknown nonce → `UnverifiedSend`. | `t07` |
| 2 | Routing is re-derived at send time, not trusted from verify | **MACHINE_ENFORCED** | `send()` calls `surface.observe()` again and compares `surface_digest`; mismatch → `RouteChanged`. | `t03` (with `t02` proving the trap is real) |
| 3 | Any surface mutation between verify and send voids the token | **MACHINE_ENFORCED** | `mutation_seq` compared at send; mismatch → `SurfaceMutated`. | `t03` path |
| 4 | Verify refuses when the surface is not on the intended target | **MACHINE_ENFORCED** | three-field digest comparison; mismatch → `Misroute` naming the differing fields. | `t04` |
| 5 | Exactly one compose surface, and it is focused | **MACHINE_ENFORCED** | `compose_open_count != 1` or falsy `focused_compose_id` → `AmbiguousSurface`. | `t05` |
| 6 | Recipient allowlist | **MACHINE_ENFORCED** | membership test at both `admit_input` and `verify` → `RecipientNotAllowed`. | `t06` |
| 7 | Send cap | **MACHINE_ENFORCED** | counter checked in `send()` → `MandateExceeded`; independently re-checked from the ledger by `checks.py`. | `t06` |
| 8 | Tokens are single-use | **MACHINE_ENFORCED** | spent-nonce set → `TokenReplay`. | `t07` |
| 9 | Producer cannot advance past `MACHINE_CHECKS_PASSED` | **MACHINE_ENFORCED** | `Run.advance` raises `SelfAcceptanceRefused` without a token whose `acceptor_id != producer_id`. | `t08` |
| 10 | Acceptance cannot be pre-minted | **MACHINE_ENFORCED** | token binds the ledger head; any later ledger write invalidates it → `TokenInvalid`. | `t08` |
| 11 | Acceptance is re-derived from disk, not from the producer's claim | **MACHINE_ENFORCED** | `IndependentAcceptor` is handed only `workdir` and re-runs `checks.run_checks`. | `t10` |
| 12 | Every attempt, including refusals, is on the record before the effect | **MACHINE_ENFORCED** | `_record()` writes and `fsync`s the route-ledger row before `do_send` is called. | inspect `route_ledger.jsonl` in `t03` |
| 13 | Refusal vocabulary is closed | **MACHINE_ENFORCED** | `checks.py` fails any verdict outside `REFUSAL_CODES ∪ {OK}`. | `t09` |
| 14 | Run ledger is append-only and tamper-evident | **MACHINE_ENFORCED** | hash chain; `verify_chain()` raises `LedgerTampered`. | `check_run_ledger` in every run |
| 15 | Transcript agrees with the route ledger | **MACHINE_ENFORCED** | `checks.py` compares claimed sends to logged sends. | `t09`, `t10` |
| 16 | The pack's own code is unmodified | **MACHINE_ENFORCED** | `check_pack_manifest` re-hashes every file against `MANIFEST.json`. | every run |
| 17 | `observe()` reports the DOM honestly | **BEHAVIOURAL_ONLY** | Nothing can check this. An adapter that hard-codes the expected conversation id passes every control above and misroutes anyway. **This is the pack's single largest residual risk.** | none |
| 18 | The intended `Target` is the right one | **BEHAVIOURAL_ONLY** | The pack proves delivery matched intent. It cannot know intent was correct. Garbage target in, faithfully-delivered garbage out. | none |
| 19 | Message text is appropriate to send | **BEHAVIOURAL_ONLY** | Only the text digest and length are recorded. | none |
| 20 | The acceptance key is unreadable by the producer | **BEHAVIOURAL_ONLY here / machine-enforceable in deployment** | `generate_keyfile` chmods `0400`, but producer and acceptor share a uid in a single-process run, so in-process the key object is reachable by reflection. Real enforcement is a separate uid or a separate host. | not proven in-sandbox |
| 21 | Allowlist/cap not widened between runs | **BEHAVIOURAL_ONLY** | Construction-time values. A new run may legally be built with a wider mandate. Governance lives above this pack. | none |

## The specific failure this pack is built against

A message composed for conversation X delivered into conversation Y.

The naive control — read the header, then click send — does not prevent it,
because the surface can move in between. `t02` demonstrates exactly that: it
observes conversation alpha, the SPA silently re-renders to beta, and the send
lands in beta. No exception, no error, wrong recipient.

Control 2 closes it by re-deriving the routing digest inside `send()` and
refusing on any difference. The token is not a permission slip; it is a
commitment to a specific observed surface state, and it dies the moment that
state changes.

Note what is deliberately **not** in the digest: unread counts, timestamps,
scroll position, avatar URLs. Including them would make every send fail closed
on ordinary UI churn, and a control that fires constantly gets switched off.
Only `conversation_id`, `recipient_handle` and `thread_title` are bound.


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

It reads **every conversation on the surface**, not only the target, and records
which delivered message digests it found where, plus its own pass/fail. A
transcript claiming delivery to `conv-alpha` cannot survive an acceptor that has
already written down what it saw in `conv-beta`.

Basis: `INDEPENDENT_SOURCE` (the live surface).

Residual: this inherits control 17 of the main table. If `inbox_digests()` lies
the same way `observe()` could, the acceptor is deceived along with everyone
else. Commit-first removes anchoring, not a dishonest adapter.
