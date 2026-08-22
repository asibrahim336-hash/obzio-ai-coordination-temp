# OE-L5-CHATGPT-SCALE — lane index

**Commission:** COM-CUR-ENV-01-20260822-v001
**Branch:** `cursor/oe-l5-chatgpt-scale-696d` · **Base:** `fe0a595206e5986de7eaac6cabc619215a1eb81b`
**State:** `READY_TO_COMMIT`

Two deliverables: how to operate the founder's ChatGPT account at scale as a
differentiated agent platform, and how to activate the OpenAI route.

---

## Deliverable A — the scaled ChatGPT-account operating programme

| File | What it is |
|---|---|
| `CHATGPT-SCALE-OPERATING-PROGRAMME-20260822-v001.md` | The programme. Diagnosis, admission method, the functions, anti-overlap, visibility, lifecycles, return routes, the 121 sidebar chats, the `CANNOT_ASSESS` surfaces, the project mapping, cost and wave learning. |
| `FUNCTION-TOPOLOGY-REGISTER-20260822-v001.json` | The machine-checked register: 31 functions over a partition of 32 internal decision classes, 8 external classes, 12 project slots. |
| `scripts/check_function_register.py` | Validates 12 invariants over the register. The anti-overlap mechanism is code, not advice. |
| `scripts/negative_tests_register.py` | Mutates the register into six known failure modes and requires the validator to reject each. |

```bash
python3 scripts/check_function_register.py     # PASS: all 12 invariants hold
python3 scripts/negative_tests_register.py     # PASS: all 6 failure modes rejected
```

## Deliverable B — the OpenAI route activation programme

| File | What it is |
|---|---|
| `OPENAI-API-SURFACE-FINDINGS-20260822-v001.md` | What the surface actually is, matched against this operation's needs, and what it cannot reach. |
| `OPENAI-SURFACE-EVIDENCE-20260822-v001.json` | 62 claims, each with source URL, sha256 of the fetched body, fetch time and a verbatim excerpt. |
| `OPENAI-ROUTE-ACTIVATION-PROGRAMME-20260822-v001.md` | Eleven owner actions, each with all ten required fields, in sequence. |
| `scripts/openai_canary.py` | The bounded first canary. Runs the moment `OPENAI_API_KEY` exists. |
| `scripts/negative_tests_canary.py` | Attempts every credential-leak path and requires the guard to fire. |
| `scripts/harvest_openai_docs.py` | Fetches 59 official documentation sources and records provenance. |
| `scripts/build_surface_evidence.py` | Cuts each excerpt out of the fetched body at build time, so a claim cannot drift from its source. |
| `scripts/probe_openai_routes.sh` | Unauthenticated probe distinguishing credential-blocked from unsupported. |

```bash
python3 scripts/openai_canary.py --dry-run     # no key, no call, no spend
python3 scripts/negative_tests_canary.py       # PASS: every leak path refused
bash    scripts/probe_openai_routes.sh         # 401 everywhere: gated, not missing
python3 scripts/harvest_openai_docs.py --out DOCS --log LOG
python3 scripts/build_surface_evidence.py --docs DOCS --log LOG --out EVIDENCE.json
```

---

## Evidence labels

| Label | Meaning |
|---|---|
| `DIRECTLY_REPRODUCED` | This lane ran the command or fetched the URL. Command, URL and date recorded. |
| `DOCUMENTED` | Official source, cited by URL, but not the basis of an endpoint-shape claim. |
| `HYPOTHESIS` | Untested inference. Never used for an API surface claim. |

Every API surface claim is `DIRECTLY_REPRODUCED` from a fetched document whose
sha256 is recorded. Re-running the two harvest scripts re-derives the evidence;
a changed hash means the documentation moved and the claim needs re-reading.

## Receipts

`receipts/so02/2026-08-22/oe-l5-chatgpt-scale/` — `MANIFEST.json` plus raw
outputs under `raw/`: the documentation fetch log, the unauthenticated route
probe, the register validation, the canary safety tests, and the activation
command tests.

## What this lane did not do

Did not authenticate to ChatGPT, obtain a credential, or sign up for anything.
Did not spend money. Did not create, rename, freeze or archive any project or
chat. Did not bind a model, plan, architecture or stack. Did not touch SW,
PO-01, PO-03, MANUS, any protected branch, or any pull request. No authenticated
API call was made: every status code recorded came from a request carrying no
credential, or from a synthetic invalid one.
