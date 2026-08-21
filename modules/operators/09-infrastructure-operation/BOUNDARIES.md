# BOUNDARIES — pack 09 · infrastructure-operation

**MACHINE_ENFORCED** — code raises on violation; a test proves it.
**BEHAVIOURAL_ONLY** — prose. Nothing stops you.

## Permitted

- Apply any operation, any number of times, under a stable `op_id`.
- Retry after any failure, including one you cannot diagnose.
- Consolidate in as many bounded batches as it takes.
- Refuse to proceed.

## Prohibited

- Reading whole state.
- Advancing a cursor outside the transaction that applied its batch.
- Deleting or editing `applied_ops`.
- Reusing an `op_id` for a different operation.
- Raising a ceiling so an oversized request fits.

## Control table

| # | Control | Status | Mechanism | Proof |
|---|---|---|---|---|
| 1 | The effect and its idempotency record commit together or not at all | **MACHINE_ENFORCED** | one `BEGIN IMMEDIATE` … `COMMIT`; the key is INSERTed first, the effect follows, the result is stored under the same key, all inside the transaction. | `t03` — four kill points, `mid` state asserts effect-present ⟺ key-present |
| 2 | A kill at any point cannot double an effect | **MACHINE_ENFORCED** | pre-commit kill → WAL rollback; post-commit kill → retry finds the key and returns the stored result. | `t03` (apply), `t04` (consolidate) — real `os._exit(9)` in real subprocesses |
| 3 | Replay returns the stored result and changes nothing | **MACHINE_ENFORCED** | key lookup before any write; `ApplyResult.applied=False`. | `t02` (3 applies → balance 250, 1 key) |
| 4 | Same key, different payload is refused | **MACHINE_ENFORCED** | `payload_digest` compared → `IdempotencyKeyConflict`. | `t07` |
| 5 | Duplicate `op_id`s inside one admitted batch are refused | **MACHINE_ENFORCED** | `admit_ops` scans before execution. | `t08` |
| 6 | There is no whole-state read | **MACHINE_ENFORCED (by construction)** | `BoundedStateReader.read_all()` raises `UnboundedReadRefused`. No other method returns unbounded rows. | `t05` |
| 7 | Every request is bounded twice — rows and bytes | **MACHINE_ENFORCED** | `LIMIT max_rows` in SQL, then byte accumulation stops at `max_bytes`; `checks.py` re-verifies every batch in the report. | `t05` (2000 rows → 6 batches, max 65 529B of 65 536B), `t10` |
| 8 | The watermark advances in the same transaction as its batch | **MACHINE_ENFORCED** | the `cursors` upsert is between the effect and the `COMMIT`. | `t04` — `cursor_moved` matches `effect_applied` at both kill points |
| 9 | Request size tracks new work, not history | **MACHINE_ENFORCED (consequence of 8)** | the watermark means run *n+1* reads only what arrived since run *n*. | `t05`: run1 2000 rows, run2 **0 rows / 0 B**, run3 10 rows / 1 878 B |
| 10 | A row that can never fit is named, not spun on | **MACHINE_ENFORCED** | `RowTooLarge` when a single row exceeds the ceiling. | `t06` |
| 11 | The growth pre-mortem runs every time and is recorded | **MACHINE_ENFORCED** | `guard_request_growth()` sizes whole state via SQL `LENGTH()` without materialising it, and writes the result into the `CURRENT_STATE_RECOVERED` ledger entry; `checks.py` fails a run without it. | `t05` (`whole_state_read_would_exceed_ceiling is True`) |
| 12 | Recovery is derived from committed state, not from memory | **MACHINE_ENFORCED** | `recover_state()` reads the watermark and `applied_ops` from the DB. | `t03`, `t04` (retry after kill) |
| 13 | No idempotency key appears applied twice in the log | **MACHINE_ENFORCED** | `checks.py`, over `op_log.jsonl`, covering point ops **and** consolidation batches. | `t10` |
| 14 | Watermark contiguity is auditable | **MACHINE_ENFORCED** | `checks.py` walks batch `from`/`to` and requires contiguity from `start_position` to `end_position`. | `t10` |
| 15 | Producer cannot advance past `MACHINE_CHECKS_PASSED` | **MACHINE_ENFORCED** | `SelfAcceptanceRefused`. | `t09` |
| 16 | Acceptance re-derived from disk | **MACHINE_ENFORCED** | acceptor re-runs `checks.run_checks`. | `t11` |
| 17 | Run ledger append-only; pack code unmodified | **MACHINE_ENFORCED** | hash chain; manifest re-hash. | every run |
| 18 | `op_id` is derived from the business fact | **BEHAVIOURAL_ONLY** | The pack guarantees exactly-once **per key**. A caller passing `uuid4()` per attempt gets exactly-once per attempt, which is at-least-once overall. **Largest residual risk in this pack, by a wide margin.** | none |
| 19 | Durability of the commit | **PARTIAL** | `journal_mode=WAL`, `synchronous=FULL`, `fsync` on log writes. Survives process kill — proven. Survives host power loss only as far as the disk's write cache is honest, which is not testable here. | process kill proven; power loss not |
| 20 | Ceilings are below the real platform limit | **BEHAVIOURAL_ONLY** | 65 536 B and 500 rows are constants in this file. Nothing checks them against the actual downstream limit. Set them deliberately. | none |
| 21 | Concurrent writers | **PARTIAL** | `BEGIN IMMEDIATE` + `busy_timeout=5000` serialises writers on one SQLite file. Two concurrent *consolidators* on the same cursor are safe (second blocks, then finds the key applied). Multi-host coordination is out of scope. | not tested |
| 22 | No out-of-band writer moves the cursor | **BEHAVIOURAL_ONLY** | Any process with the DB file can `UPDATE cursors`. Control 8 binds *this pack's* writes only. | none |
| 23 | Acceptance key unreadable by producer | **BEHAVIOURAL_ONLY here** | single uid. | not proven |

## The two specific defects

### 1. Double effect on retry

Blocked by controls 1–3. The proof is not a mock: `t03` runs
`state_machine.py apply` as a child process with `OBZIO_CRASH_AT` set, and the
child calls `os._exit(9)` — no unwinding, no `atexit`, no flush. Four points
are exercised, including the nastiest one (`after_commit_before_return`, where
the effect is durable but the caller never learned it). Every case ends at
balance=100 with one key after two retries.

The intermediate assertion matters as much as the final one:

```python
expect((mid["balances"].get("a", 0) == 100) == (mid["applied_ops"] == 1),
       f"{pt}: effect and key disagree")
```

There is no observable state in which the effect happened and the record did
not, or vice versa. That is what makes the retry safe to perform blindly.

### 2. The consolidation job that outgrew its ceiling

> re-read whole state every run until its request outgrew a per-request ceiling

Three controls, and the third is the one that actually fixes it:

- control 6 removes the unbounded path, so the defect cannot be written
- control 7 bounds each request, so a large backlog is drained rather than refused
- **control 8/9 is the cure**: because the watermark commits with its batch,
  run *n+1* reads only new rows. `t05` proves the shape of the curve directly —
  2 000 rows in run 1, then **0 rows and 0 bytes** in run 2 over the same
  state, then 10 rows and 1 878 bytes in run 3 after 10 new events arrive.
  Under the original design run 2 would have re-read all 2 000 and run 3 would
  have read 2 010, growing forever.

Control 11 is the early-warning: every run records what a whole-state read
*would* have cost. In `t05` that is 308 000 B against a 65 536 B ceiling — the
incident condition, visible in the ledger before it becomes an outage.


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

It **redoes the arithmetic**: reads the immutable `events` table and the ops
declared in the objective, computes what every balance must be if each effect
landed exactly once, and compares that to the actual `balances`. It does not
read `consolidation_report.json`, `op_log.jsonl` or `db_state.json` to form its
expectation.

`t14` applies a double effect out of band, after every machine check has
passed, and the acceptor catches it because 500 ≠ 1000 in arithmetic it did
itself.

Basis: `INDEPENDENT_SOURCE` (the event log and the live balances).

Residual: if the `events` table itself is corrupted, both parties are deceived
identically. Commit-first does not create a second source of truth.
