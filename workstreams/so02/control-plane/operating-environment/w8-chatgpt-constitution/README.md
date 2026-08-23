# OE-W8 — the constitution of ChatGPT's functions

Lane `OE-W8-CHATGPT-CONSTITUTION` under commission `COM-CUR-ENV-01-20260822-v001`.
Branch `cursor/oe-w8-chatgpt-constitution-696d` · base `5a8923ab`.
Terminal state: `READY_TO_COMMIT`. `decision_changed: []`.

A proposal for admission, not a self-declared binding. It binds no company
strategy, names no model, tool or architecture as bound, creates no obligation
or spend, and imposes no fixed number of projects, agents or functions.

One deliverable, in four parts: what the founder's recorded ChatGPT advisory
proposal gets right and wrong, where each function lives, how provenance
survives a recovered thread, and what Ahmed must personally do.

## Read in this order

| File | What it is |
|---|---|
| `CHATGPT-CONSTITUTION-20260822-v001.md` | The deliverable, readable. Parts A–D. |
| `FUNCTION-ADJUDICATION-20260822-v001.json` | Part A, structured. Twelve functions, one verdict and its evidence each. Governs where it differs from the prose. |
| `ledger/admission-rule.json` | Part B, structured. The standing lattice, the derivation table, the caps, the resolution order. |
| `ledger/utterances/*.json` | Part B, live. Four real utterances transcribed from committed files with pinned commits. |
| `TRIAGE-PROGRAMME-20260822-v001.json` | Part C, structured. Five corrections to the prior design and the replaced exit condition. |
| `FOUNDER-ACTIONS-20260822-v001.json` | Part D, structured. Eight actions, all ten required fields each. |

## Run it

```bash
cd workstreams/so02/control-plane/operating-environment/w8-chatgpt-constitution

python3 tools/intentctl.py validate                  # PASS: schema and locator discipline hold
python3 tools/intentctl.py conflicts                 # PASS: no contested class unresolved
python3 tools/negative_tests_intentctl.py            # PASS: all 16 failure modes rejected

python3 tools/triagectl.py plan --tolerance 0.01 --strata ledger/fixtures/strata-founder-reported.json
python3 tools/triagectl.py exit-check --history ledger/fixtures/yield-history.json --consecutive 3   # exit 1 BY DESIGN

python3 tools/verify_function_claims.py --out /tmp/docs --log /tmp/log.json   # re-derives the documentary evidence
python3 tools/build_manifest.py --repo-root "$(git rev-parse --show-toplevel)" --check
```

Two of those exit non-zero on purpose. `exit-check` exits 1 because the
illustrative yield series has a non-zero last three sweeps — it is a check, not
a report. And `intentctl conflicts` will exit 1 the moment two conflicting
claims of equal standing are added with no way to order them, which is the
behaviour the rule exists for.

## The three things worth knowing before reading

**The unit of admission is the utterance, not the thread.** A thread holds
utterances of mixed standing, and treating it as the atom forces one standing
onto all of them. That is exactly how a persuasive old thread becomes current
intent: persuasiveness is a property of prose, standing is a property of a
speaker and a speech act, and they are independent. The estate proves it —
`FOUNDER-STANDING-INSTRUCTION-20260822.md` holds a controlling instruction, a
decision and a quoted advisory proposal in one commit, and the checker derives
`S1` for the proposal from speaker class alone.

**ChatGPT does not hold acceptance, and the reason is not the one the prior
lane gave.** The prior decomposition of independence is sound but incomplete: its
six properties are all properties of the verdict process, none is a property of
the criteria's origin, and every Cursor lane shares instruction lineage with its
producer. So the advisory proposal is pointing at something real. It attached it
to the wrong function. What ChatGPT can uniquely contribute is a
differently-sourced *question*, not a *verdict* — and those need completely
different transport, context hygiene and blocking power.

**The constitution's central custody route is untested and labelled so.**
`FA-W8-01` proposes attaching a local clone as a folder in a ChatGPT desktop
project. The feature is documented; its behaviour on this account is a
`HYPOTHESIS` with a ten-minute test and a written fallback. No lane authenticated
to ChatGPT to find out.

## Evidence discipline

`DIRECTLY_REPRODUCED` — this lane ran the command or fetched the URL; receipt
under `receipts/so02/2026-08-22/oe-w8-chatgpt-constitution/raw/`.
`DOCUMENTED` — an official source cited by URL and fetch date, **or** a prior
lane's reproduction cited by repository path; prior-lane reproductions are never
relabelled as this lane's own.
`HYPOTHESIS` — untested inference, never used to establish that a route works,
always carrying the test that would settle it and the fallback if it fails.

Ten of eleven claim sources fetched at HTTP 200 on 2026-08-23. The eleventh,
`help.openai.com`, returned 403 to an unauthenticated fetch, so the owner data
export could not be evidenced — which is recorded as a gap rather than assumed
away, and which a prior lane hit identically.

Every input under `ledger/fixtures/` is illustrative and says so. No real sweep
has been run and no chat has been read.

## Boundaries kept

Wrote only on `cursor/oe-w8-chatgpt-constitution-696d`, only under
`workstreams/so02/control-plane/operating-environment/w8-chatgpt-constitution/**`
and `receipts/so02/2026-08-22/oe-w8-chatgpt-constitution/**`, from an isolated
worktree, with every push confirmed by `git ls-remote`.

Did not authenticate to ChatGPT or attempt to acquire any credential. Did not
print or store a credential value. Did not build the route evidence table, which
is a sibling lane's deliverable. Did not open, comment on, merge or modify any
pull request. Did not message or configure SW. Did not touch PO-01, PO-03,
MANUS, `main`, the SO-02 source branch, the return branch, or another lane's
namespace.
