# OpenAI route activation programme

**Lane:** OE-L5-CHATGPT-SCALE · **Commission:** COM-CUR-ENV-01-20260822-v001
**State:** READY_TO_COMMIT · **Every action below is an owner action. This lane executed none of them.**

Companion artifacts: `OPENAI-API-SURFACE-FINDINGS-20260822-v001.md` (what the
surface actually is) and `OPENAI-SURFACE-EVIDENCE-20260822-v001.json` (62 claims
with URL, sha256 and verbatim excerpt). Claim ids like `C-SPEND-429` below refer
to that register.

---

## 0. How to read this, and the one sequencing rule that matters

Each action below carries all ten required fields:

| # | Field |
|---|---|
| 1 | exact capability unlocked |
| 2 | why it benefits the whole operation |
| 3 | exact account and settings location |
| 4 | minimum appropriate scope |
| 5 | secret-storage location |
| 6 | exact test command |
| 7 | expected result |
| 8 | verification and revocation |
| 9 | cost, privacy and retention |
| 10 | activate now or later |

**The sequencing rule: containment before capability.** The spend cap is set
*before* the key exists, not after. This is not caution theatre. A hard spend
limit returns HTTP 429 at the cap, and the documentation states plainly that
enforcement is not instantaneous, so recorded spend can slightly exceed the
configured amount (`C-SPEND-429`). A cap set after the key means the first
mistake is unbounded; a cap set before means the worst case is a known number
plus a small overshoot. That difference is the entire risk profile of this
activation.

**Never paste a secret into a chat.** Every action stores its secret in the
Cursor Dashboard under **Cloud Agents → Secrets**, repository-scoped. Secrets
are injected as environment variables into new agent VMs, so a value added
during a run is not visible to that run: **a new agent run must be started
after the secret is saved.** Every test command below reads from the
environment by variable name and prints no credential material.

### The credential-safe curl pattern used throughout

Passing a key with `-H "Authorization: Bearer $KEY"` puts the expanded value in
curl's argv, where `ps` and process accounting can see it. Every command below
instead feeds the header to curl on stdin, so the value never reaches an
argument vector:

```bash
printf 'header = "Authorization: Bearer %s"\nurl = "%s"\n' "$SOME_KEY_ENV" "$URL" \
  | curl -sS --config - -o /tmp/body.json -w 'http_status=%{http_code}\n'
```

`DIRECTLY_REPRODUCED`: this pattern was exercised on 2026-08-22 against
`https://api.openai.com/v1/models` with a deliberately invalid synthetic key and
returned `http_status=401` with an `invalid_request_error`, proving the header
is transmitted correctly by this mechanism.

One further precaution appears in the commands: **the error body is never
printed verbatim.** On an invalid key the provider echoes a masked fragment of
the key back in the message. Masked is not absent. The commands print the error
*type* and *code* and withhold the message.

**These commands were executed, not merely written.** `DIRECTLY_REPRODUCED`
2026-08-22: the OA-3 command run with a synthetic invalid key printed
`http_status=401` then `result: FAILED  error_type: invalid_request_error
code: invalid_api_key`, and no key material appeared in the output. With the
variable unset, the `:?` guard aborted the shell before curl was reached. The
receipt is at
`receipts/so02/2026-08-22/oe-l5-chatgpt-scale/raw/activation-command-tests.txt`.

---

## OA-0 — Establish which ChatGPT plan the account holds

*No credential. This is a fact-finding action, and it gates OA-7 and OA-8.*

1. **Capability unlocked.** None directly. It determines whether the two routes
   that touch the ChatGPT UI exist for this account at all.
2. **Why it benefits the operation.** Everything in the operating programme that
   depends on reaching the 11 projects, the 61 project chats or the 121 sidebar
   chats branches on this single fact. Workspace Agents requires a workspace
   with admin controls (`C-WA-TOKEN-LOCATION`); the Compliance Platform guide is
   titled for Enterprise, Edu and ChatGPT for Teachers (`C-COMPLIANCE-PLAN-GATE`).
   Designing return routes without knowing this is designing in the dark, and
   it is cheap to resolve.
3. **Location.** `https://chatgpt.com/admin/settings` if an admin workspace
   exists; otherwise ChatGPT → Settings → the plan indicator. The presence or
   absence of an `Admin` section is itself the answer.
4. **Minimum scope.** Read-only observation by the account owner.
5. **Secret storage.** None. Record the answer as a fact in the repository, not
   a credential.
6. **Test command.** None — this is an observation. Record the result as:
   plan name; whether an `Admin` section is present; whether
   **Admin → Access tokens** is present; whether **Scheduled** appears in the
   sidebar.
7. **Expected result.** One of: a personal plan with no Admin section (OA-7 and
   OA-8 are unavailable); or a workspace plan with Admin (both become
   candidates).
8. **Verification and revocation.** Not applicable; nothing is granted.
9. **Cost, privacy, retention.** None.
10. **Now or later.** **Now, and first.** It is free, it takes a minute, and two
    later actions are unspecifiable without it.

---

## OA-1 — Create an isolated API project

1. **Capability unlocked.** A blast-radius boundary. A project is the unit that
   both API keys and spend limits attach to, so an isolated project makes every
   subsequent control scoped rather than organisation-wide.
2. **Why it benefits the operation.** Independent acceptance requires
   independently attributable actors. Usage, spend and rate limits are readable
   per project, so an operation running in its own project can answer "what did
   this cost and who spent it" without disentangling it from unrelated
   activity. It also makes revocation surgical: deleting one project's key stops
   this operation and nothing else.
3. **Location.** `https://platform.openai.com/settings/organization/general`
   → Projects → **Create project**. Suggested name: `obzio-so02-control-plane`.
4. **Minimum scope.** A project with no members other than the owner. Do not
   add users at creation; add them only when a second actor genuinely needs
   independent attribution.
5. **Secret storage.** None — a project id is not a secret. Record it in the
   repository as a locator.
6. **Test command.** None; creation is visually confirmed. The project id
   becomes visible in project settings and is confirmed indirectly by OA-3.
7. **Expected result.** A project exists, with zero keys and zero spend.
8. **Verification and revocation.** Verification: the project appears in the
   organisation's project list. Revocation: archive the project, which
   invalidates its keys.
9. **Cost, privacy, retention.** No cost. No data.
10. **Now or later.** **Now.** It is a prerequisite for OA-2 and OA-3.

---

## OA-2 — Set a hard spend limit and a spend alert, before any key exists

1. **Capability unlocked.** A hard monthly ceiling that returns HTTP 429 and
   stops traffic at a configured amount, plus a notification threshold below it
   (`C-SPEND-HARD-LIMIT`, `C-SPEND-429`).
2. **Why it benefits the operation.** It converts "we trust the automation" into
   an arithmetic bound. This programme proposes many functions, background work
   and bulk sweeps; the honest way to authorise that is a number the founder
   chooses rather than an assurance the lane offers. It also makes the failure
   mode legible: at the cap, requests fail with a named code, which a function
   can detect and report rather than silently degrading.
3. **Location.** `https://platform.openai.com/settings/organization/limits`
   (`C-SPEND-LOCATION`). Under **Spend**, select **Edit spend limit**, enter the
   monthly amount, and turn on **Enforce a hard limit**. Set the project-level
   limit on the OA-1 project as well, so the operation cannot consume the whole
   organisation's allowance.
4. **Minimum scope.** Requires permission to manage organisation or project
   settings. Set the alert well below the hard limit so notification precedes
   interruption; alerts remain active alongside a hard limit.
5. **Secret storage.** None.
6. **Test command.** None before a key exists. After OA-3, current usage is
   readable at `https://platform.openai.com/settings/organization/usage`.
7. **Expected result.** A hard limit is displayed as enforced on both the
   organisation and the OA-1 project.
8. **Verification and revocation.** Verification: the limit shows as enforced,
   and after the canary, usage is a small non-zero number well under it.
   Revocation: lower the limit to a token amount to halt spend immediately —
   a faster brake than key rotation, because it needs no coordination with the
   agent runtime.
9. **Cost, privacy, retention.** This is the cost control. Note the documented
   caveat that enforcement is not instantaneous and recorded spend can slightly
   exceed the cap, so the limit should be set to an amount tolerable to overshoot
   a little, not to the exact maximum acceptable loss.
10. **Now or later.** **Now, and strictly before OA-3.** This is the sequencing
    rule in §0.

---

## OA-3 — Create the project API key and store it as `OPENAI_API_KEY`

*This is the action that unblocks the route. Everything else is optional.*

1. **Capability unlocked.** Authenticated access to `api.openai.com`: the
   Responses API, the Conversations API, structured outputs, tool calling,
   background mode and batch. Concretely, it turns the five 401s reproduced in
   the findings into working routes.
2. **Why it benefits the operation.** It is the difference between a designed
   programme and an operating one. Without it, every function that needs a model
   call is a specification. With it, work can be dispatched, given a durable
   addressable identifier, retrieved later by that identifier, and reconciled
   into repository custody without a human carrying the result between systems.
   That last property — retrieval by identifier from a different process — is
   what the canary tests, and it is the property the operation actually needs.
3. **Location.** `https://platform.openai.com/settings/organization/api-keys`
   (`C-LOC-API-KEYS`) → **Create new secret key**. Scope the key to the OA-1
   project, not to "all projects". Name it for its purpose, e.g.
   `so02-control-plane-agent`, so that a later audit can tell what it was for
   without asking anyone.
4. **Minimum appropriate scope.** Start from least privilege, which is the
   provider's own instruction (`C-RBAC-LEAST-PRIV`). For the canary and the first
   wave, the needed permissions are:

   | Permission area | Level | Why |
   |---|---|---|
   | List models | Read | the liveness probe and runtime model discovery (`C-RBAC-MODELS-PERM`) |
   | Responses API | Read + Write | create and retrieve responses (`C-RBAC-RESPONSES-PERM`) |
   | Model capabilities | Request | make generation requests |

   Do **not** grant Files, Vector Stores, Fine-tuning, Batch, Assistants,
   Webhooks or Agent Builder yet. Batch in particular grants a wide implied set:
   its Write permission additionally confers Files read/write, model listing and
   model-capability request across many endpoints (`guide-rbac`, harvested).
   Grant it when a sweep is actually authorised, not in advance.

   **A known gap, stated rather than papered over:** the RBAC table publishes no
   row named Conversations. Whether conversation operations ride with the
   Responses API permission is not stated on the fetched page. This is a
   `HYPOTHESIS`. The canary settles it empirically: if conversation creation
   returns 401 or 403 while `/v1/models` succeeds, the answer is that
   Conversations needs a permission not in the list above, and the key needs one
   more grant. That is a two-minute correction, and finding out this way costs
   one API call.

   Note also that a project key's effective rights are the **intersection** of
   the key's permissions and the owning user's project role (`C-RBAC-DOUBLE-CHECK`).
   If a correctly scoped key returns 403, check the user's role before
   re-issuing the key.
5. **Secret storage.** Cursor Dashboard → **Cloud Agents → Secrets**,
   **repository-scoped** to this repository, variable name exactly
   `OPENAI_API_KEY`. Nowhere else. Not in a chat message, not in a file, not in
   a commit, not in a branch name. Secrets are injected into **new** agent VMs,
   so after saving, a new agent run must be started before the key is visible.
6. **Exact test command.** Paste-ready. Reads the key from the environment,
   keeps it out of argv, and prints no credential material:

```bash
: "${OPENAI_API_KEY:?OPENAI_API_KEY is not set in this environment. Add it in the Cursor Dashboard under Cloud Agents -> Secrets (repository-scoped), then start a NEW agent run.}"
printf 'header = "Authorization: Bearer %s"\nurl = "https://api.openai.com/v1/models"\n' "$OPENAI_API_KEY" \
  | curl -sS --config - -o /tmp/oa3.json -w 'http_status=%{http_code}\n'
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("/tmp/oa3.json")
d = json.loads(p.read_text())
if "error" in d:
    # The provider echoes a masked key fragment in error messages, so the
    # message body is deliberately withheld. The type is enough to diagnose.
    print("result: FAILED  error_type:", d["error"].get("type"),
          " code:", d["error"].get("code"))
else:
    ids = sorted(m["id"] for m in d.get("data", []))
    print("result: OK  models_visible:", len(ids))
    print("sample_ids:", ids[:5])
p.unlink()
PY
```

7. **Expected result.** `http_status=200` followed by
   `result: OK  models_visible: <N>` with `N` greater than zero, and a sample of
   model ids. Interpreting other outcomes:

   | Outcome | Meaning |
   |---|---|
   | `http_status=401` | key wrong, revoked, or not injected — did a new run start after saving? |
   | `http_status=403` | key authenticated but lacks List models, or the user's project role does not include it |
   | `http_status=429` with a spend-limit code | the OA-2 cap is already reached |
   | shell aborts before curl | the secret is not in this environment; the `:?` guard fired |

8. **Verification and revocation.**
   **Verify** by running the test above, then the canary in §OA-4, then
   confirming that the conversation id recorded by the canary is retrievable in
   a *later, separate* process. A key that works once in one process has
   demonstrated far less than a key whose artifacts are addressable afterwards.
   **Revoke** by deleting the key at
   `https://platform.openai.com/settings/organization/api-keys`, then removing
   `OPENAI_API_KEY` from Cursor Dashboard → Cloud Agents → Secrets, then proving
   the revocation rather than assuming it:

```bash
bash scripts/probe_openai_routes.sh
```

   Revocation is confirmed when the probe reports `OPENAI_API_KEY present: no`
   and every route returns 401. Deleting the key in one place and not the other
   is the common failure: a deleted-upstream key still sitting in Secrets will
   produce confusing 401s in later runs that look like network faults.
9. **Cost, privacy, retention.** Cost is bounded by OA-2. Privacy is where care
   is needed: `/v1/responses` retains no application state by default and is
   Zero Data Retention eligible, but **`/v1/conversations` and
   `/v1/conversations/items` retain application state *until deleted* and are
   *not* ZDR eligible** (`C-RET-CONVERSATIONS`). Default abuse-monitoring
   retention elsewhere is 30 days (`C-RET-ABUSE-DEFAULT`); for conversations it
   is until deletion. Using Conversations for durable custody therefore means
   accepting indefinite provider-side retention of whatever is placed in them.
   That is a founder decision, restated as OA-9 below. Retention controls, where
   an organisation is approved for them, live at
   `https://platform.openai.com/settings/organization/data-controls/data-retention`
   (`C-RET-CONTROLS-LOCATION`).
10. **Now or later.** **Now**, immediately after OA-1 and OA-2, provided the
    founder accepts the retention position in field 9 or defers Conversations
    use until OA-9 is decided. The canary can be run against Responses alone if
    Conversations is deferred, at the cost of not testing durable addressability
    — which is most of the point, so deciding OA-9 first is the better path.

---

## OA-4 — Run the bounded first canary

*Agent action, not an owner action, listed here because it is the verification
step for OA-3 and because it should run before anything else uses the key.*

The script is `scripts/openai_canary.py`, written and tested now so that it runs
the moment the key exists.

**Validate it today, with no key, no network call and no spend:**

```bash
python3 scripts/openai_canary.py --dry-run
```

`DIRECTLY_REPRODUCED` 2026-08-22: exits 0, reports `"calls_made_now": 0`,
`"spend_now": 0`, and lists the five calls it would make. With no key present it
exits 2 with an instruction to use the Cursor Dashboard, and it never prompts
for a credential.

**Run it once the key is present:**

```bash
python3 scripts/openai_canary.py
```

What it does, in order: discovers an available model from `/v1/models`; creates
**one** conversation whose metadata holds only pointers back to repository
custody; executes **one** bounded response against that conversation with
`store: true`, a strict `json_schema` output format, `max_output_tokens` capped
at 256 and no tools; then — the actual test — issues **separate** requests to
`GET /conversations/{id}` and `GET /conversations/{id}/items` to prove the work
is retrievable *by identifier* rather than merely returned inline; and finally
writes a locator record into repository custody.

Three deliberate properties worth naming:

- **No model is hardcoded.** The script discovers one at runtime and accepts
  `--model` or `OPENAI_CANARY_MODEL` as an override. Model identifiers are
  exactly the fact that goes stale between writing and running, and binding one
  is outside this lane's authority in any case.
- **`store: true` is explicit, not omitted.** Under some retention
  configurations an omitted `store` behaves as `store=false` and a background
  result is deleted after roughly ten minutes (`C-BG-RETENTION-TRAP`). Omission
  is not a neutral default.
- **It deletes nothing.** Conversations persist until deleted, and deleting a
  conversation does not delete its items (`C-CONV-DELETE-ORPHANS`). Disposal is
  a separate owned decision, not a test's side effect.

**Exit codes.** `0` pass · `2` credential absent · `3` a safety check refused to
proceed · `4` an API call failed · `5` **the result was created but was not
retrievable by identifier**. Code 5 is the interesting failure: it would mean
the route generates but does not durably address, which disqualifies it as
custody and invalidates a load-bearing assumption of the operating programme.

**Credential-safety, tested rather than asserted.** `scripts/negative_tests_canary.py`
attempts each leak path and requires the guard to fire.
`DIRECTLY_REPRODUCED` 2026-08-22, all ten checks pass: writing a record
containing the live key is refused; writing credential-shaped text is refused
even when the guard is not told the key; a captured `Authorization: Bearer`
header is refused; a clean record still writes (a guard that blocks everything
gets disabled by the first person it annoys); passing a key on the command line
exits 3 without echoing it; and `--dry-run` with a key present makes zero calls
and prints no credential.

**Reconciliation into repository custody.** The canary writes
`locators/openai-canary-locator.json` containing the conversation id, the
response id, the addressability result, token usage, the model that ran and how
it was chosen — and explicitly `"credential_value_recorded": false`. The record
also carries the retention note, so anyone reading the locator later learns that
the conversation persists until someone deletes it without having to re-derive
that from the documentation.

---

## OA-5 — Narrow the key with a custom role

1. **Capability unlocked.** A role granting exactly the permissions the first
   wave needs, instead of a preset role that grants more.
2. **Why it benefits the operation.** After the canary, the permission set is no
   longer a guess — it is a measured fact, including the Conversations question
   left open in OA-3. Encoding that measured set as a custom role makes least
   privilege durable rather than a one-time intention, and gives later functions
   a named role to be granted rather than an ad-hoc key.
3. **Location.** Organisation settings → Roles → create a role; or the OA-1
   project's settings for a project-scoped role. Custom-role eligibility is
   marked per area in the RBAC table (`C-RBAC-RESPONSES-PERM`,
   `C-RBAC-MODELS-PERM`).
4. **Minimum scope.** Exactly the permissions the canary proved necessary and no
   others. Note that Batch is **not** custom-role eligible per the table, so a
   sweep needs a different grant path — worth knowing before a sweep is planned
   around it.
5. **Secret storage.** None; a role is not a secret.
6. **Test command.** Re-run OA-3's test and the canary under the narrowed role.
   The negative test matters more than the positive one — confirm that a
   capability deliberately *not* granted is actually refused:

```bash
: "${OPENAI_API_KEY:?not set}"
printf 'header = "Authorization: Bearer %s"\nurl = "https://api.openai.com/v1/files"\n' "$OPENAI_API_KEY" \
  | curl -sS --config - -o /tmp/oa5.json -w 'http_status=%{http_code}\n'
python3 -c "import json;d=json.load(open('/tmp/oa5.json'));print('error_type:', d.get('error',{}).get('type','NONE - ACCESS WAS GRANTED'))"
rm -f /tmp/oa5.json
```

7. **Expected result.** The canary still passes; the Files probe returns 403 (or
   401) with an error type. If the Files probe returns 200, the role is wider
   than intended and the narrowing did not take effect.
8. **Verification and revocation.** Verification is the paired positive/negative
   test above. Revocation: unassign the role, or delete it, which affects every
   key relying on it — so check what else uses it first.
9. **Cost, privacy, retention.** No direct cost. Reduces the blast radius of a
   leaked key, which is the point.
10. **Now or later.** **Later**, immediately after the canary passes. Doing it
    before means guessing the permission set; doing it after means encoding a
    measured one.

---

## OA-6 — Register a webhook endpoint and store `OPENAI_WEBHOOK_SECRET`

1. **Capability unlocked.** Push notification when work completes:
   `response.completed`, `response.failed`, `response.cancelled`,
   `response.incomplete` and the `batch.*` family (`C-WH-EVENTS`,
   `C-WH-EVENT-NAME`).
2. **Why it benefits the operation.** This is the mechanism that most directly
   serves the directive that the founder must not be the relay. "Notice that
   work finished" is otherwise a job for a poller, and a poller that is a person
   is the failure mode being designed out. With webhooks, completion announces
   itself and a return route can fire without anyone watching.
3. **Location.** `https://platform.openai.com/settings/project/webhooks`
   (`C-LOC-WEBHOOKS`). Webhooks are configured per project, so this attaches to
   the OA-1 project. The page can also send test events with sample data, which
   allows the receiver to be validated before any real work depends on it.
4. **Minimum scope.** Subscribe to the smallest set of events the first wave
   consumes — `response.completed` and `response.failed` — not the full catalogue.
   Add `batch.*` when a sweep is actually authorised.
5. **Secret storage.** Cursor Dashboard → Cloud Agents → Secrets,
   repository-scoped, variable name exactly `OPENAI_WEBHOOK_SECRET`. This is a
   **second, distinct secret** from `OPENAI_API_KEY` (`C-WH-SECRET-ENV`); it
   verifies that an inbound payload really came from OpenAI. Conflating the two
   is a real mistake with a real consequence: an unverified webhook receiver
   will accept forged completions, and a forged completion is a forged claim
   that work is done.
6. **Test command.** Trigger a test event from the settings page, then confirm
   the receiver validated the signature. Locally, confirm only that the secret
   is present and correctly named, without printing it:

```bash
python3 - <<'PY'
import os
name = "OPENAI_WEBHOOK_SECRET"
v = os.environ.get(name)
print(f"{name}: {'present' if v else 'ABSENT'}"
      + (f" (length {len(v)}, value never printed)" if v else ""))
PY
```

7. **Expected result.** The secret reports present; the test event from the
   dashboard reaches the receiver; signature validation succeeds; an invalid
   signature is rejected.
8. **Verification and revocation.** Verification: send a dashboard test event
   and confirm both a valid payload is accepted and a tampered one is rejected —
   only the second proves verification is real. Revocation: delete the webhook
   endpoint in project settings and remove the secret from the Cursor Dashboard.
9. **Cost, privacy, retention.** No direct cost. Privacy consideration: payloads
   are delivered to an endpoint the operation controls, so whatever that endpoint
   logs becomes a new copy of the data outside both the provider and the
   repository. Decide the receiver's logging posture before it starts receiving.
10. **Now or later.** **Later, and honestly blocked on infrastructure, not on
    the founder.** A webhook needs a durable, publicly reachable HTTPS endpoint.
    A cloud agent VM is not one; it disappears with the run. Until such an
    endpoint exists, the working substitute is background mode plus scheduled
    polling from a durable runner, and the founder-load ledger should record the
    push route as a known deficiency rather than reporting it as live.

---

## OA-7 — Admin API key

1. **Capability unlocked.** Administration endpoints: programmatic management of
   projects, users, keys and rate limits.
2. **Why it benefits the operation.** It would let the operation provision and
   revoke its own scoped credentials, and read usage per project without a human
   opening a dashboard. That serves both founder-load reduction and the
   accounting the register requires.
3. **Location.** `https://platform.openai.com/settings/organization/admin-keys`
   (`C-LOC-ADMIN-KEYS`). Admin API keys cannot be used for non-administration
   endpoints, which is a useful separation: an admin key cannot generate text and
   a project key cannot create projects.
4. **Minimum scope.** Organisation-level administrative access. There is no
   smaller version of this, which is precisely why it is deferred.
5. **Secret storage.** Cursor Dashboard → Cloud Agents → Secrets,
   repository-scoped, under a **distinct** variable name, e.g.
   `OPENAI_ADMIN_KEY`. Never reuse `OPENAI_API_KEY`; the whole value of the
   separation is lost if one variable carries both.
6. **Test command.**

```bash
: "${OPENAI_ADMIN_KEY:?OPENAI_ADMIN_KEY is not set}"
printf 'header = "Authorization: Bearer %s"\nurl = "https://api.openai.com/v1/organization/projects?limit=1"\n' "$OPENAI_ADMIN_KEY" \
  | curl -sS --config - -o /tmp/oa7.json -w 'http_status=%{http_code}\n'
python3 -c "import json;d=json.load(open('/tmp/oa7.json'));print('result:', 'OK' if 'data' in d else 'FAILED '+str(d.get('error',{}).get('type')))"
rm -f /tmp/oa7.json
```

7. **Expected result.** `http_status=200` and `result: OK`. A 401 means the key
   is wrong or not injected; a 403 means it is not an admin key.
8. **Verification and revocation.** Verify with the command above. Revoke by
   deleting the key on the admin-keys page and removing it from the Cursor
   Dashboard, then re-running the command and requiring a 401.
9. **Cost, privacy, retention.** No direct usage cost. The risk is not cost but
   authority: this credential can create and delete projects and keys. It should
   have the shortest life and the narrowest justification of anything here.
10. **Now or later.** **Later, and only against a specific need.** Nothing in
    the first wave requires it. Issuing an organisation-wide administrative
    credential to enable convenience is the wrong trade; issuing it to enable a
    named, accepted function is a decision the founder can actually weigh.

---

## OA-8 — Workspace Agents access token *(conditional on OA-0)*

1. **Capability unlocked.** Triggering a published ChatGPT workspace agent from
   outside the UI: `POST https://api.chatgpt.com/v1/workspace_agents/{id}/trigger`
   (`C-WA-TRIGGER-ROUTE`), returning `202 Accepted` with a `conversation_url`
   (`C-WA-ACCEPTED`), with optional beta run-status polling.
2. **Why it benefits the operation — and the limit stated up front.** It is the
   only documented way to start work *inside* the ChatGPT account
   programmatically, which makes scheduled and event-driven dispatch possible
   without the founder opening a chat. But the documentation is explicit
   (`C-WA-NO-RETURN`): *"The agent's response cannot currently be retrieved
   through the API."* Beta polling returns status only, never content
   (`C-WA-RUN-STATUS`). So this route dispatches and reports completion; it does
   not return results. **A workflow that ends in "the founder opens
   `conversation_url` and reads it" is the founder-as-relay pattern the
   directives prohibit, wearing the costume of automation.** Activate it for
   dispatch. Do not build a return route on it.
3. **Location.** Two steps, both in ChatGPT, both requiring workspace admin
   (`C-WA-TOKEN-LOCATION`): first, **Admin → Permissions & roles**, enable
   Workspace agents and turn on *Allow users to create personal access tokens*;
   then **Admin → Access tokens** (`https://chatgpt.com/admin/access-tokens`),
   create a token and select the **Workspace Agents** scope. The live 401
   reproduced in the findings independently names that same page.
4. **Minimum scope.** The **Workspace Agents** scope only. The token is scoped to
   Workspace Agents operations and nothing else (`C-WA-TOKEN-SCOPE`) — a
   genuinely narrow credential, which is a point in its favour.
5. **Secret storage.** Cursor Dashboard → Cloud Agents → Secrets,
   repository-scoped, variable name e.g. `CHATGPT_WORKSPACE_AGENT_TOKEN`.
   **Not** `OPENAI_API_KEY`: different host, different credential, different
   capability set. Storing it under the API key's name would produce failures
   that look like an outage.
6. **Test command.** A read-only status probe against a non-existent run, which
   distinguishes "token invalid" from "token valid, run not found" without
   triggering an agent or spending anything:

```bash
: "${CHATGPT_WORKSPACE_AGENT_TOKEN:?CHATGPT_WORKSPACE_AGENT_TOKEN is not set}"
printf 'header = "Authorization: Bearer %s"\nurl = "https://api.chatgpt.com/v1/workspace_agents/agtch_probe/runs/apirun_probe"\n' "$CHATGPT_WORKSPACE_AGENT_TOKEN" \
  | curl -sS --config - -o /tmp/oa8.json -w 'http_status=%{http_code}\n'
python3 -c "import json;d=json.load(open('/tmp/oa8.json'));e=d.get('error',{});print('error_code:', e.get('code'), '| type:', e.get('type'))"
rm -f /tmp/oa8.json
```

7. **Expected result.** **Not** 200 — the identifiers are deliberately fake.
   Three outcomes, two of which were reproduced on 2026-08-22:

   | Outcome | Meaning | Status |
   |---|---|---|
   | `401` / `error_code: missing_api_key` | no credential was sent at all | `DIRECTLY_REPRODUCED` (no header) |
   | `401` / `error_code: invalid_api_key` | a credential was sent and rejected | `DIRECTLY_REPRODUCED` (synthetic token) |
   | `404` or a not-found error code | **authentication succeeded**; the fake run simply does not exist | `HYPOTHESIS` — cannot be reproduced without a real token |

   The distinction between the two 401s is what makes this probe worth running:
   `missing_api_key` means the secret was never injected, `invalid_api_key`
   means it was injected and is wrong. Those have different fixes, and without
   the distinction both look like "it doesn't work". This is also a cleaner test
   than triggering a real agent, because it proves the credential without
   starting work or consuming plan usage.
8. **Verification and revocation.** Verify with the probe above. Revoke at
   **Admin → Access tokens** and remove the secret from the Cursor Dashboard,
   then re-run the probe and require 401.
9. **Cost, privacy, retention.** Triggering an agent consumes the ChatGPT plan's
   usage, not API credits, so OA-2's spend cap does **not** bound it. That is
   worth stating plainly: this route's cost control is the plan's own limits, and
   they are a different budget with a different ceiling.
10. **Now or later.** **Later, and conditional on OA-0** showing an admin
    workspace. Even then, activate it only alongside a decision about how results
    return, because on its own it terminates in a URL for a human.

---

## OA-9 — Decide the retention posture for Conversations

*A founder decision, not a credential.*

1. **Capability unlocked.** None. It authorises, or declines, a data placement.
2. **Why it benefits the operation.** `/v1/conversations` and
   `/v1/conversations/items` retain application state **until deleted** and are
   **not** Zero Data Retention eligible (`C-RET-CONVERSATIONS`), whereas
   `/v1/responses` retains none by default and is ZDR eligible
   (`C-RET-RESPONSES`). Durable addressability is exactly what makes
   Conversations valuable for custody, and indefinite provider-side retention is
   exactly its cost. These are the same property viewed from two sides; there is
   no configuration that gives one without the other.
3. **Location.** `https://platform.openai.com/settings/organization/data-controls/data-retention`,
   visible once an organisation is approved for retention controls
   (`C-RET-CONTROLS-LOCATION`). Approval itself is requested from OpenAI.
4. **Minimum scope.** Decide per material class, not globally. A plausible
   split: operational scaffolding may use Conversations; founder-intent
   material, strategy and anything commercially sensitive may not, until a
   retention control exists.
5. **Secret storage.** None.
6. **Test command.** None. This is a judgment. What can be checked is
   compliance with it afterwards: the register can require every function that
   uses Conversations to declare the material class it places there, and that
   declaration can be validated.
7. **Expected result.** A recorded decision naming which material classes may
   enter Conversations.
8. **Verification and revocation.** Verification: audit conversation metadata
   against declared classes. Revocation: delete the conversations — remembering
   that deleting a conversation does **not** delete its items
   (`C-CONV-DELETE-ORPHANS`), so disposal needs both steps to be real.
9. **Cost, privacy, retention.** This action *is* the privacy and retention
   decision.
10. **Now or later.** **Now, before the canary if founder-intent material would
    be involved.** The canary itself places only a synthetic connectivity string
    and four pointer-shaped metadata values into a conversation, so it can
    proceed ahead of this decision. Nothing carrying real content should.

---

## OA-10 — IP allowlist

1. **Capability unlocked.** Network-level restriction so the key is only usable
   from approved addresses or CIDR ranges (`C-LOC-IP-ALLOWLIST`).
2. **Why it benefits the operation.** It converts a leaked key from an immediate
   compromise into a mostly-inert string. It is the cheapest available
   defence-in-depth for a long-lived credential.
3. **Location.** `https://platform.openai.com/settings/organization/security/ip-allowlist`.
   The page includes a **Check** tool to confirm a specific address is covered.
4. **Minimum scope.** Only the egress addresses that genuinely need access.
5. **Secret storage.** None.
6. **Test command.** Use the **Check** tool with the runner's egress address,
   then re-run OA-3's test from that runner and require 200.
7. **Expected result.** Approved addresses succeed; others are refused.
8. **Verification and revocation.** Verify from both an allowed and a
   non-allowed source if one is available. Revocation: remove the entries.
   Note the documented behaviour that a configuration change can take up to
   fifteen minutes, so an immediate failure after editing is not necessarily a
   misconfiguration.
9. **Cost, privacy, retention.** No cost. One real operational risk: cloud agent
   VMs do not have stable egress addresses. An allowlist that does not account
   for that will lock out the operation itself, and the symptom will look like
   an authentication failure rather than a network policy.
10. **Now or later.** **Later**, and only once egress addressing is known to be
    stable. Applying it to an environment with rotating egress creates outages
    that will be misdiagnosed as key problems.

---

## 11. What is deliberately not requested

Stated so that the absence reads as a decision rather than an oversight.

- **No Compliance API activation.** It is the only documented route that reads
  ChatGPT conversation records, but the public page does not publish routes,
  schemas or filters, deferring to an authenticated Admin API reference
  (`C-COMPLIANCE-UNDOCUMENTED`), and it is plan-gated
  (`C-COMPLIANCE-PLAN-GATE`). Specifying an owner action for an interface whose
  contract cannot be read would mean inventing it. OA-0 determines whether the
  question is even live; if it is, the correct next step is for an admin to open
  `https://chatgpt.com/admin/api-reference` and report what is actually offered.
- **No ChatGPT authentication, credential acquisition or sign-up.** Out of
  bounds for this lane, and nothing here required it.
- **No model, plan, architecture or stack bound as a decision.** The canary
  discovers a model at runtime precisely so that running it does not
  accidentally constitute a binding choice.
- **No spend.** Every command in this document either sends no credential, or is
  gated on a credential that does not exist in this runtime. The only calls made
  by this lane were unauthenticated probes and public documentation fetches.

---

## 12. The activation sequence, in order

| Step | Action | Gate |
|---|---|---|
| 1 | OA-0 establish the plan | free; gates OA-8 and the Compliance question |
| 2 | OA-1 create the isolated project | prerequisite for scoping |
| 3 | OA-2 set the hard spend limit | **before** any key exists |
| 4 | OA-9 decide the Conversations retention posture | before real content, not before the canary |
| 5 | OA-3 create and store `OPENAI_API_KEY` | unblocks the route |
| 6 | OA-4 run the canary | verifies OA-3 and settles the Conversations-permission question |
| 7 | OA-5 narrow the key with a measured custom role | after the canary, not before |
| 8 | OA-6 / OA-7 / OA-8 / OA-10 | each against a named need, never speculatively |

Steps 1 to 6 are the whole of the first wave. Everything after step 6 should be
justified by something the first wave learned, which is the same standard this
programme applies to every function it admits.
