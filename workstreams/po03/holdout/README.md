# PO-03 evaluator-held holdout

This is the independently authored holdout for commission
`COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001` revision
v002.  It is a continuation of the existing appointment.  It does not change
any founder decision (`decision_changed: []`).

## Blind-authorship statement

`po03-worker-a13` authored and executed the suite from the commission,
transactional contracts, frozen a13 dispatches, recorded custody defects and
the snapshot-coupling rule.  Before the freeze commit, the evaluator did not
read, fetch or inspect any source, harness, scorer or generation under
`workstreams/po03/successor/` or on
`cursor/po03-a8-successor-generations-ed20`.

No direct comparison to the public suite was possible before freeze without
breaking independence.  The cases are independently devised compound,
concurrent, restart, boundary and metamorphic constructions, not knowingly
restatements of a public case.  After freeze, novelty is checked against the
public suite and any exact restatement is reported rather than silently
removed or rewritten.

## Frozen material

- `INTERFACE.md` defines the candidate adapter protocol.
- `cases/cases.json` contains 32 ordered cases and their preregistered oracles.
- `score_holdout.py` is the only scorer.
- `FREEZE_MANIFEST.json` records byte hashes of the suite and evaluator tests.
- `AUTHORSHIP_FREEZE.md` records the final freeze commit after it exists.

The scorer never sends assertions, requirement text or novelty notes to a
candidate.  It sends only the protocol version, case ID and frozen `input`.

## Run

```bash
python3 -I workstreams/po03/holdout/score_holdout.py \
  --candidate-command 'python3 -I /absolute/path/to/evaluator_adapter.py' \
  --candidate-label BLINDED-01 \
  --transcript workstreams/po03/holdout/transcripts/BLINDED-01.json
```

The adapter is invoked once in a clean empty work directory per case.  The same
command template and exact request hashes are used for every generation.  An
unsupported operation is returned as `NOT_SUPPORTED` with its exact boundary.

## Case catalogue and commission citations

| Case | Commission requirement tested |
|---|---|
| H01 | Transactional custody: provider completion without a verified durable commit is never Obzio completion. |
| H02 | Transactional custody: every artifact and manifest is read back at the declared immutable commit. |
| H03 | Transactional custody: verify declared bytes while flagging an attestation superseded at the mutable result ref. |
| H04 | Transactional custody: an identical callback replay remains harmless across controller restart. |
| H05 | Transactional custody: a non-identical terminal resubmission is refused. |
| H06 | Transactional custody: terminal state cannot regress and a unit cannot complete twice. |
| H07 | Transactional custody: stale fenced ownership cannot be revived with a fresh idempotency key. |
| H08 | Transactional custody: a higher fence that was never issued cannot commit. |
| H09 | Transactional custody: result input and acceptance identities remain bound to the dispatched attempt. |
| H10 | Transactional custody: lost acknowledgement plus concurrent duplicate callbacks produce one durable ingestion. |
| H11 | Transactional custody: equal idempotency key with unequal bytes is a collision, not a duplicate. |
| H12 | Transactional custody: fencing and append serialization hold at a true race barrier. |
| H13 | Transactional custody: a sealed ledger detects truncation followed by a valid-looking suffix. |
| H14 | Transactional custody: an external seal detects historical mutation followed by cascade rehash. |
| H15 | Transactional custody: reconciliation detects two valid forks from one ledger predecessor. |
| H16 | Transactional custody: display-name changes cannot bypass producer/reviewer separation. |
| H17 | Transactional custody: independent acceptance is ordered after coordinator completion. |
| H18 | Transactional custody: a real diagnostic commit cannot promote an honest failed result. |
| H19 | Successor clean runtime: missing validator schema is a controlled failure, not an import crash. |
| H20 | Transactional custody: a committed result is recovered after total provider loss without rerun. |
| H21 | Transactional custody: an uncommitted task reruns from immutable input with no duplicate external effect. |
| H22 | Transactional custody: checkpoints remain monotonic across process loss. |
| H23 | Transactional custody: heartbeat renewal cannot be erased by a concurrent expiry scan. |
| H24 | Successor guardrail: normalized traversal and symlink targets cannot escape the allowlist. |
| H25 | Collision boundary: the exact PO-03 workflow pattern accepts a valid dot-prefixed path and rejects a lookalike. |
| H26 | Successor clean runtime: a fresh clone ignores poisoned matching `/tmp` state and warm-only refs. |
| H27 | Transactional custody: corrupt-artifact rejection is durable and leads to recovery after restart. |
| H28 | Transactional custody: result attempt metadata must match durable lease and checkpoint state. |
| H29 | Transactional custody: a real commit on an undeclared remote is not a durable result-slot commit. |
| H30 | Transactional custody: worker completion is refused without blocking one later coordinator completion. |
| H31 | Transactional custody: artifact mutation between verification and commit is detected. |
| H32 | OS measurement: false-completion scanning examines history, not only the current projection. |

All fixture values are synthetic and immutable.  Tests assert invariants over
those values; none recomputes a committed observation from live shared state or
asserts that a repository defect still exists.
