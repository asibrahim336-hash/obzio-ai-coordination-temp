# LAUNCH — founder-intent-processing

## Entry point

```bash
cd /tmp/packs/founder-intent-processing
python3 test_pack.py
python3 checks.py <run_dir>
```

```python
from state_machine import build_machine, make_acceptor
from obzio_spine.expectation import AcceptanceReturn

acceptor = make_acceptor("reviewer-01", correction_text, surface_registry)
m = build_machine(run_dir, producer_id, commitments, correction_text,
                  surface_registry, received_at="2026-08-20T09:14:00Z",
                  acceptor=acceptor)
for _ in range(6): m.advance()
m.advance(acceptance=AcceptanceReturn(True, acceptance_reveal, acceptor.reveal()))
m.advance()
```

`surface_registry` maps surface name -> `{"kind":…, "path":…, "tags":[…]}`.
Tags drive routing: `policy`, `prompt`, `checklist`, `reference`, `published`,
`instance`, `clarification`.

## Acceptance independence: `PARTIAL_ORACLE`

Acceptance is **commit-first**. The acceptor derives and hash-commits its own
expected result from the declared inputs *before any artefact exists*; the
machine refuses the commitment if one already does. At the gate the artefacts
are compared against that commitment and **divergence defaults to REJECT**.
The channel back to the producer is **one bit** — no rationale, no diff, no
rubric. See BOUNDARIES.md for exactly what this oracle does and does not
cover.

## Mandate

Ingest one founder correction. Separate what was **said** from what it
**implies**, and emit the surfaces affected plus the changes required.

The literal claim is the founder's. The system implication is the operator's.
This pack exists because those two get fused, and once fused nobody can tell
a founder's instruction from an operator's guess.

## Maximum delegated authority

| Act | Authority |
|---|---|
| Extract literal claims with byte spans | **GRANTED** |
| Infer system implications and label them INFERRED | **GRANTED** |
| Map implications onto registered surfaces | **GRANTED** |
| Emit change orders describing required changes | **GRANTED** |
| **Apply** a change order to a real surface | **DENIED** — this pack emits orders; it never edits the surface |
| Normalise, tidy, or paraphrase the correction text | **DENIED** — destroys verbatim spans (`CHK-FI-01`) |
| Promote a ONE_OFF claim to standing policy | **DENIED** — `CHK-FI-08` |
| Act unilaterally on a LOW-confidence implication | **DENIED** — requires founder confirmation (`CHK-FI-07`) |
| Resolve an AMBIGUOUS scope by picking one | **DENIED** — must route to a clarification surface |
| Accept its own interpretation | **DENIED** — machine-enforced at the gate |

## Required artefacts

`correction.json` · `interpretation.json` · `surface_impact.json` ·
`change_orders.json` — plus `check_report.json`, `journal.json`,
`return_state.json`.

## Definition of done

Every claim verifies verbatim against `correction.json["source_text"]`, every
implication traces to a claim and reaches at least one surface, every affected
surface has an order, and the reviewer returned ACCEPT.
