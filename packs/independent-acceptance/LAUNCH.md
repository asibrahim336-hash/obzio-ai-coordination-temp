# LAUNCH — independent-acceptance

## Entry point

```bash
cd /tmp/packs/independent-acceptance
python3 test_pack.py     # produces a real subject run, then reviews it
python3 checks.py <review_run_dir>
```

```python
from state_machine import build_machine, make_acceptor
from obzio_spine.expectation import AcceptanceReturn

# COMMIT FIRST. The acceptor MAY read the subject (its input); it may not read
# this review's verdict or findings before committing.
acceptor = make_acceptor("review-acceptor-01", "/path/to/subject/run",
                         [...], "reviewer-01")

m = build_machine(review_run_dir,
                  reviewer_id="reviewer-01",
                  commitments=third_party_commitments,   # NOT the subject's
                  subject_root="/path/to/subject/run",
                  subject_required_artefacts=[...],
                  subject_pack_dir="/path/to/subject/pack",
                  acceptor=acceptor)
for _ in range(6): m.advance()
m.advance(acceptance=AcceptanceReturn(True, acceptance_reveal, acceptor.reveal()))
m.advance()
```

Three distinct principals are involved and none may collapse into another:

| Role | Who |
|---|---|
| Subject producer | wrote the work under review |
| Reviewer | **this pack's producer** — writes the review |
| Acceptor of the review | a third principal who holds the commitments |

This pack is itself a producing operator: it produces a review, and that
review must in turn be accepted by someone else. The gate is not special-cased
for reviewers. A review that signs itself off is the same defect one level up.

## Acceptance independence: `PARTIAL_ORACLE (one-sided)`

Acceptance is **commit-first**. The acceptor derives and hash-commits its own
expected result from the declared inputs *before any artefact exists*; the
machine refuses the commitment if one already does. At the gate the artefacts
are compared against that commitment and **divergence defaults to REJECT**.
The channel back to the producer is **one bit** — no rationale, no diff, no
rubric. See BOUNDARIES.md for exactly what this oracle does and does not
cover.

## Mandate

Adversarially review another operator's output and issue ACCEPT or REJECT with
evidence. Treat the subject's own reports as claims, not evidence: re-run its
checks, re-verify its manifest, re-derive its digests.

## Maximum delegated authority

| Act | Authority |
|---|---|
| Read every file in the subject | **GRANTED** |
| Re-run the subject's `checks.py` against its artefacts | **GRANTED** |
| Re-verify the subject's manifest and digests | **GRANTED** |
| Record findings with evidence pointers | **GRANTED** |
| Issue ACCEPT or REJECT | **GRANTED** — the only two values |
| **Write anything inside the subject** | **DENIED** — `WriteFence`, machine-enforced |
| Fix a defect it finds | **DENIED** — report it; fixing erases the record |
| Review work it produced itself | **DENIED** — refused at admission |
| ACCEPT while holding a blocking finding | **DENIED** — `CHK-IA-04` |
| Issue a verdict with no probes run | **DENIED** — `CHK-IA-06` |
| Accept the subject's `check_report.json` at face value | **DENIED** — `CHK-IA-07` |
| Accept its own review | **DENIED** — machine-enforced at the gate |

## Probes

| Probe | Question |
|---|---|
| `P-01_required_artefacts` | Do the owed artefacts exist and carry bytes? |
| `P-02_return_state` | Is the completion claim internally coherent? Did the subject self-review? |
| `P-03_check_report` | Does the report contradict itself (`passed` with failures)? |
| `P-04_recomputed_checks` | Do the subject's checks still pass when **we** run them? |
| `P-05_manifest` | Does the pack manifest match the bytes on disk? |
| `P-06_journal` | Is the journal contiguous, and did an acceptance actually occur? |
| `P-07_digest_binding` | Does `accepted_run_digest` bind the artefacts that are present? |

## Required artefacts

`review_scope.json` · `findings.json` · `verdict.json` ·
`independence_proof.json` — plus `check_report.json`, `journal.json`,
`return_state.json`.

## Definition of done

`independence_proof.unchanged` is true, every mandatory probe ran, the verdict
follows from the findings, and a third principal accepted the review.
