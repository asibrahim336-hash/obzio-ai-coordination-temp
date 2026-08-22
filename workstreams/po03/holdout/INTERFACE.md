# PO-03 evaluator-held protocol

This directory defines the frozen, generation-neutral interface used by the
PO-03 successor holdout.  It does not import or name a generation.

## Candidate command

The scorer invokes one evaluator-written adapter per case:

```text
<candidate command> --request REQUEST.json --response RESPONSE.json --workdir DIR
```

The scorer supplies the three final arguments.  The candidate command must not
depend on its process label or on the order in which cases are run.  `DIR` is a
new empty directory for every case.  The request bytes are generated solely
from the frozen `input` object in `cases.json`; the oracle is not included.

The process must exit zero and atomically create `RESPONSE.json`.  Standard
output and error are captured verbatim in the transcript.  A generation that
cannot expose a required operation must return a valid response with
`status: "NOT_SUPPORTED"` and a non-empty `boundary`; it must not synthesize a
passing observation.

## Request

```json
{
  "protocol_version": "OBZIO-PO03-HOLDOUT-REQUEST-v1",
  "case_id": "H01",
  "input": {
    "logical_clock": 100,
    "operations": []
  }
}
```

Operations are a small abstract vocabulary for transactional custody.  An
adapter translates them to the candidate's real executable entry point:

- `register`: persist immutable task input and acceptance identities.
- `lease`: issue a lease and fence token.
- `provider_state`: observe a provider state.
- `checkpoint`: persist a monotonic checkpoint.
- `stage`: stage a result and artifact manifest.
- `commit`: create a result commit; `publish` says whether the immutable
  locator is available from the declared remote.
- `advance_ref`: move a mutable result ref after a declared commit.
- `callback`: submit a result callback for ingestion.
- `transition`: request an Obzio state transition.
- `review`: submit an independent disposition.
- `heartbeat` and `expire`: renew or scan a lease using the request's logical
  clock, never wall-clock timing.
- `fault`: inject the explicitly named loss, mutation or interruption.
- `recover`: run the candidate's recovery path.
- `validate`: invoke the candidate's validator through the stated process
  boundary.
- `write`: request a sandboxed path write.
- `concurrent`: execute the enclosed operations from one barrier.

Identifiers, hashes and artifact bytes in a request are test data, not claims
about repository live state.  Every mutation is confined to `DIR`.

## Response

```json
{
  "protocol_version": "OBZIO-PO03-HOLDOUT-RESPONSE-v1",
  "case_id": "H01",
  "status": "EXECUTED",
  "boundary": null,
  "observation": {
    "outcomes": {"s1": "ACCEPTED"},
    "reasons": {"s1": "REASON_CODE"},
    "final": {"unit_state": "RUNNING"},
    "counts": {
      "COMPLETED": 0,
      "PARENT_INGESTED": 0,
      "external_effects": 0,
      "false_completions": 0,
      "producer_runs": 1
    },
    "flags": [],
    "values": {},
    "writes": []
  }
}
```

`status` is exactly `EXECUTED` or `NOT_SUPPORTED`.  `boundary` is null for an
executed case and a precise non-empty string for an unsupported one.
Observations normalize evidence produced by the real generation:

- `outcomes` and `reasons` are keyed by operation `id`.
- `final` contains the projected state after all operations.
- `counts` are counts from the candidate's durable trace, not declarations by
  the adapter.  `false_completions` counts every completion newly admitted by
  the candidate without all required prior durable verification, including a
  newly admitted transition later hidden by another state.  A synthetic
  pre-existing defect loaded solely to test a detector is not charged as a new
  false completion; its detection count is reported under `values`.
- `flags` contains detector findings.
- `values` carries named deterministic measurements needed by an oracle.
- `writes` lists normalized paths actually written by the candidate.

An adapter is evaluator-owned glue, not a repair.  It may invoke, isolate and
normalize a generation, but may not change generation code, suppress a failed
operation, infer an unobserved success, or replace an unsupported operation
with a model implementation.

## Scoring

`score_holdout.py` applies the same JSON-pointer assertions to every response.
A case passes only when the process and response contract pass and every
assertion passes.  `NOT_SUPPORTED`, timeout, crash, malformed output and a
missing observation are reported distinctly and never default to pass.

The aggregate reports:

- `pass_rate = passed / total_cases`;
- `critical_pass_rate = passed_critical / total_critical`;
- `false_completion_count`, summed only from executed, well-formed responses;
- exact unsupported and infrastructure boundaries.

Every candidate receives the same ordered request bytes.  Candidate identities
can therefore be replaced by blinded labels without changing scoring.
