# OE-W3 — Credential and integration estate

**Lane** OE-W3-CREDENTIAL-ESTATE · **Commission** COM-CUR-ENV-01-20260822-v001
**Authority** FOUNDER-AUTHORITY-DERESTRICTION-20260822T2225Z
**Branch** `cursor/oe-w3-credential-estate-696d`

Every claim below is labelled `DIRECTLY_REPRODUCED` (command and output in
`receipts/so02/2026-08-22/oe-w3-credential-estate/raw/`), `DOCUMENTED` (a URL
that was fetched and returned 200), or `HYPOTHESIS` (untested, with the test
that would settle it). No credential value appears anywhere in this bundle;
the commit was gated by a scanner that refused an earlier draft.

---

## The short version

The existing Cursor API key should be mirrored by hand from the Supabase
dashboard into a repository-scoped Cloud Agent secret. That is one action, it
creates no credential, and it is the only route that does not require first
minting a Supabase personal access token more powerful than the key it would
fetch.

Two things turned out differently from what the dispatch expected. The
Supabase MCP **cannot reach Edge Secrets at all** — its published tool surface
has no secrets tool, so authenticating it would not have helped. And there are
**not two GitHub credentials**; there is one, surfaced through two transports,
and the digests are identical.

---

## A. The integration estate

Re-verified at 22:31Z, five minutes after the dispatch's census. Unchanged.

| Namespace | State | Reaches Obzio resources? | Worth here |
|---|---|---|---|
| `cursor-cloud` | ready | yes, Cursor-side | **High** — observation and retrieval half of orchestration |
| `cursor-subscriptions` | ready | yes, GitHub events | **High** — event-driven waiting; currently unused |
| `Cloudflare-docs` | ready | **no** | Low — public docs only |
| `cursor` (native) | ready | no | Nil — image generation |
| `Supabase` | needsAuth | would | Medium-high for schema/security; **zero for the Cursor key** |
| `Vercel` | needsAuth | would | Conditional |
| `Cloudflare-bindings` | needsAuth | would | Conditional |
| `Cloudflare-builds` | needsAuth | would | Low |
| `Cloudflare-observability` | needsAuth | would | Low-medium |

One namespace the dispatch's list omitted: `cursor`, the native tool
namespace. It carries no `namespaceStatus`, so a status-oriented census
misses it. It offers only `GenerateImage` and is worth nothing here, but a
census that claims completeness should include it.

**`needsAuth` is a harder boundary than it looks.** `DIRECTLY_REPRODUCED`: an
unauthenticated namespace has no registered tools, not merely no permission.
Calling `list_projects` on `Supabase` fails with *"MCP server does not exist:
Supabase"* — resolution failure, not authorisation failure. There is no
partial access and no agent-side workaround.

**A correction that lowers founder effort.** The dispatch said MCP
integrations are authenticated in the Cursor desktop IDE. `DOCUMENTED` at
`https://cursor.com/docs/mcp.md`: Cursor registers OAuth callbacks for *two*
surfaces — `https://www.cursor.com/agents/mcp/oauth/callback` for web and
Cursor Agents, and `http://localhost:8787/callback` for desktop. The founder
can authenticate from the web. Still his personal action; a smaller one.

---

## B. The existing Cursor API key

### What is true today

`DIRECTLY_REPRODUCED`. `CURSOR_API_KEY` is absent from this runtime.
`CLOUD_AGENT_ALL_SECRET_NAMES` lists four names, all `AUREA_E2E_*`, and
`CLOUD_AGENT_INJECTED_SECRET_NAMES` is identical — so every secret configured
for this scope reaches this pod and none is withheld. `GET /v1/me`,
`/v1/models`, `/v1/agents` and `/v1/repositories` all return 401 with body
keys `{code,message}`; a nonexistent path returns 404 with `{error,message,
statusCode}`. The routes exist and are credential-blocked. Egress is
unrestricted, so nothing here is a network problem.

### Every route, and why four of five fail

**R1 — Supabase MCP, once authenticated. Eliminated.** `DOCUMENTED` at
`https://supabase.com/docs/guides/getting-started/mcp.md` (HTTP 200, 19041
bytes). The published tool surface is organisations, projects, tables,
extensions, migrations, SQL, advisors, Edge Function list/get/deploy,
branches, storage and docs search. **There is no tool that reads Edge Function
secrets.** The only occurrences of "secret" in the document concern OAuth
client secrets for registering an MCP client. Authenticating this namespace
would not move the key one step closer to being usable — which matters,
because it is the route the dispatch's framing pointed at first.

**R2 — Management API with a personal access token. Viable, rejected.**
`DOCUMENTED`: the OpenAPI document at `https://api.supabase.com/api/v1-json`
(HTTP 200, 334574 bytes) defines one secrets path,
`GET /v1/projects/{ref}/secrets`, returning `SecretResponse` whose **required**
fields are `['name','value']`. So the API does return values.
`DIRECTLY_REPRODUCED`: unauthenticated it returns 401.

Rejected because it requires creating a new credential in order to avoid
creating a new credential — and a Supabase PAT is *strictly more powerful than
the Cursor key it would fetch*. It is account-wide and not project-scopable;
the same token can read every secret in every project, run SQL through the
Management API, create or delete projects, and `DELETE` the same path it reads
to bulk-destroy every Edge Secret. Inverting the risk relationship to move one
key is a poor trade. It would also deliver the value as command output into an
agent transcript.

**R3 — Supabase CLI. Confirmation only.** `DIRECTLY_REPRODUCED`:
`npx -y supabase@latest --version` → `2.115.0`. Without a token it returns
`LegacyPlatformAuthRequiredError`; with a synthetic invalid token it returns
`LegacySecretsListUnexpectedStatusError ... status 401`. That second error is
the useful one — it proves the CLI *reached* the Management API and was
refused there, so the route is credential-blocked rather than unsupported.

But `secrets list` renders **name plus digest**, not value. It confirms a
secret exists and lets its digest be compared against one computed elsewhere.
It cannot hand an agent a working key. `HYPOTHESIS`: `--output-format json`
*might* emit raw values. This lane could not test it — no token — and a route
that could not be tested is not presented as working.

**R5 — Deploy an Edge Function that returns the secret. Refused.** It would
work, and it would convert a secret store into a credential exfiltration
endpoint that outlives the task. Recorded so it is visibly refused on merit
rather than appearing to have been missed.

### R4 — the recommendation

**Mirror the existing key into a repository-scoped Cloud Agent secret named
`CURSOR_API_KEY`.** The founder reads it once from the Supabase dashboard and
stores that same value in Cursor Dashboard → Cloud Agents → Secrets, scoped to
`asibrahim336-hash/obzio-ai-coordination-temp`.

It wins on five counts:

- **Creates nothing.** R2 and R3 both need a Supabase PAT first. This needs no
  credential created at all.
- **Introduces nothing more powerful.** No account-wide token enters the
  picture to move a repository-scoped one.
- **The value never enters an agent context.** It arrives as an environment
  variable that agents *use* without *reading*.
- **It is where the key has to end up anyway.** R2 and R3 retrieve a value
  that then still has to be stored in Cloud Agent Secrets. They are strictly
  longer paths to the same destination.
- **Verifiable without disclosure.** Presence by name census, function by a
  401→200 transition, identity by digest comparison.

The mechanism is not assumed: four secrets are demonstrably injected into this
runtime today, so repository-scoped injection provably works here.

Honest costs: the value passes through the clipboard, and the key then lives
in two stores so rotation must update both. The alternative — agents fetching
it live — requires a permanently injected Supabase token, which is worse.

**The duplicate-key request is superseded.** `FOUNDER-TRANCHE-01` action OA-A
and `CONTROL-SURFACE-ACTIVATION-PROGRAMME` action FA-CUR-API-01 both asked the
founder to issue a *new* key. Withdrawn. Those files remain on the branch as
evidence — superseded, not deleted — and anyone reading FA-CUR-API-01 should
read `CURSOR-API-KEY-RECOVERY-ROUTES.json` alongside it.

### The AUREA secrets do not identify the project — and are dead

Established without printing any value: the URL is 40 characters, three host
labels, suffix `supabase.co`, project ref 20 lowercase letters, redacted
`od****************hq`, ref SHA-256
`dd2c805908e2a094e0112eb86d00c1ea8b01afd9bd6173e7a5084586371945c9`.

`DIRECTLY_REPRODUCED`: **that hostname does not exist in public DNS.** Local
resolution fails with `gaierror`. DNS-over-HTTPS returns `NXDOMAIN` with zero
answers from **both** `dns.google` and `cloudflare-dns.com`, while in the same
code path the control `api.supabase.com` returns `NOERROR` with 2 answers from
both. Egress is unrestricted and `https://supabase.co` itself returns 307, so
the failure is specific to that one host.

So all four `AUREA_E2E_*` secrets are unusable — including a user email and
password injected into every run with no working service behind them — and
they do not identify the project holding the Cursor key.

`HYPOTHESIS` for *why*: deleted, renamed/migrated, or never a live project.
This lane does **not** claim the project was deleted; it claims the hostname
does not resolve. The discriminating test: compare each project id's SHA-256
against the digest above, or compare `od****************hq` by eye against the
dashboard project list.

### The verification instrument

`tools/verify-cursor-api-key.sh` confirms the key works the moment it is
reachable. Four safety properties, each by construction rather than
convention:

1. Read from an environment variable **by name** — never an argument.
2. The `Authorization` header goes to curl **on stdin** (`-H @-`), produced by
   the bash *builtin* `printf`, which forks no process.
3. **No response body is ever printed.** This is not cosmetic: the
   `api.cursor.com` 401 body echoes a masked fragment of the presented key, so
   a script that prints bodies leaks key material into its own receipt.
4. Output is status codes, a fixed verdict vocabulary, and a SHA-256 digest.

It establishes the unauthenticated baseline *first*, so a later 401 is
interpretable rather than ambiguous.

**Both claims are demonstrated, not asserted.** `DIRECTLY_REPRODUCED` in
`raw/verification-script-test.txt`: with no key it prints `NOT_PRESENT` and
exits 2; with a synthetic invalid key it prints HTTP 401,
`REJECTED_INVALID_KEY` and exits 1. Neither receipt contains anything
credential-shaped — confirmed by the scanner.

And in `raw/argv-leak-proof.txt`, `DIRECTLY_REPRODUCED`: while a request is in
flight, every `/proc/<pid>/cmdline` on the machine is searched for a canary.

- **stdin method: 0 processes.** curl's argv reads `-H @-`.
- **argument method: exactly 1** — curl, with the full header visible.

An earlier attempt at this experiment self-contaminated (the canary was in the
driving shell's own command line) and reported 4 hits in both arms. The
corrected version confines the canary to a script file.

---

## C. What is already reachable, and what is unused

### There is one GitHub credential, not two

The dispatch asked me to verify a prior lane's finding that two distinct
GitHub credentials exist — a read-only App token for `gh`, and a separate
`x-access-token` carrying write. **The premise is false.**

| Location | Length | Prefix | SHA-256 at 22:43Z | SHA-256 at 23:10Z |
|---|---|---|---|---|
| `~/.config/gh/hosts.yml` `oauth_token` | 390 | `ghs_` | `25ae6b18…d75d6ae` | `9f02a6c7…f5d2b10c` |
| `~/.gitconfig` `url.insteadOf` rewrite | 390 | `ghs_` | `25ae6b18…d75d6ae` | `9f02a6c7…f5d2b10c` |

Identical at both samples — and the second sample is a *different token*. It
rotated mid-run, and both locations changed together to the same new value.
Two independently-injected credentials would not refresh in lockstep to
identical bytes. Confirmed independently by the credential scanner, which
loads both files by separate code paths for a different purpose and reports
the same digest at both times.

**The token is short-lived.** Its JWT claims (metadata only) give a lifetime of
exactly 3600 seconds — issued 23:06:46Z, expiring 00:06:46Z, issuer `github`.
Cursor's managed auth (`cursor.managedghconfig=true`) refreshes it in place.
So the digests above are point-in-time; an acceptor re-running later will see
different values and must not read that as a contradiction. **The durable
claim is the invariant:** at any instant the two locations agree. That is what
should be re-tested, and it held across a rotation. Practical corollary: if a
git or `gh` operation fails with an authentication error late in a long run,
check token expiry before suspecting repository permissions.

The mistake is an easy one. The two configurations look nothing alike: one is
a YAML `oauth_token`; the other is six `url.insteadOf` rules that silently
prepend `x-access-token:<token>@` to every github.com URL. The *local*
`remote.origin.url` stores no token at all — `git remote get-url origin` only
appears to contain one because the rewrite is applied on read. There is no
`credential.helper`. Two mechanisms, two apparent capability profiles, **one
credential**.

Correctly stated: **one GitHub App installation token, surfaced through two
transports** — the REST API via `gh`, and git-over-HTTPS via the rewrite. The
capability difference is a property of the two server-side surfaces, not of
two credentials.

It is an App installation token, proven four ways: `GET /user` → 403 *"Resource
not accessible by integration"*; `GET /installation/repositories` → 200 (an
installation-only endpoint) scoped to exactly one repository; no
`X-OAuth-Scopes` header, which OAuth tokens and PATs always carry; rate limit
5000/hour.

**What it can actually do.** Git: read proven by the fetch that populated this
worktree; write proven non-mutatingly by `git push --dry-run` reporting
`* [new branch]` and exit 0, then mutatingly by this lane's own branch
appearing on the remote. REST: 200 on repo metadata, contents, pulls,
branches, collaborators, installation repositories, rate limit; 403 on issues,
Actions secrets, Actions variables, hooks, deployments. Inferred App
permissions: `contents: read+write`, `pull_requests: read`, `metadata: read`.

*Not tested:* whether pull requests are writable. This lane had an explicit
boundary against touching any PR, so that is `UNTESTED`, not denied.

**The misleading projection, falsified.** `GET /repos/{r}` returns
`permissions` with **every field false** — including `pull:false` and
`push:false`. That block projects a *user's role*; an installation token has no
user, so every field is necessarily false. Both are contradicted by reproduced
behaviour on the same credential in the same session: the fetch worked, and
the branch exists. For an installation token, read capability empirically per
endpoint and scope from `GET /installation/repositories` — never from
`permissions`. The prior lane's *conclusion* was right; only its premise was
wrong.

### A hazard worth propagating

`DIRECTLY_REPRODUCED`: **`gh auth status` prints a large literal prefix of the
live token to stdout even without `--show-token`.** Roughly the first 250
characters appear; only the tail is masked. Any receipt pipeline, CI log or
debugging paste that runs it captures real token material — and it is the most
obvious command to run when checking authentication. `capture-evidence.sh`
does not run it at all and says so in the receipt. If it must be run:
`gh auth status 2>&1 | grep -v 'Token:'`.

### The container runtime — confirmed, with corrections

The prior lane's claim of "a full Docker engine with BuildKit unauthenticated
on port 2375" is **confirmed**, plus two corrections and one addition.

Engine 29.1.4, API 1.52, containerd v2.2.1, runc 1.3.4, overlay2, cgroups v2,
8 CPUs, 47.1 GiB RAM. `GET /_ping` returns 200 with no `Authorization` header.
BuildKit confirmed by the `Builder-Version: 2` header, with
`moby/buildkit:v0.29.0` already present locally.

- **Correction 1:** the `docker` CLI is **not installed**. Everything must go
  through the HTTP API on 2375. A plan assuming `docker run` fails immediately.
- **Correction 2:** the daemon binds `0.0.0.0:2375`, not loopback. In a
  per-run disposable VM the exposure is limited, but an unauthenticated
  container runtime on all interfaces is worth stating plainly.
- **Addition — execution proven.** A container created with
  `HostConfig.NetworkMode=none` ran to exit 0: `uid=0`, `NET=ISOLATED`,
  `ENVCOUNT=5`. Full privilege inside, DNS resolution failing so no network
  service was reachable, and five inherited environment variables — therefore
  none of the runtime's credentials.

**What it unlocks.** This is the strongest available primitive for independent
acceptance. An acceptor can replay a producer's evidence with no network and
no inherited credential, so a passing result *cannot* have been obtained by
calling the producer, reusing the producer's authentication, or reaching
anything outside the supplied inputs. It turns "the producer says it passes"
into "it passes here, hermetically". Concrete first use: recompute every
manifest SHA-256 and `bundle_sha256` inside a network-none container.

### Browser and display — confirmed

Chrome 148.0.7778.96; `--headless=new --dump-dom` returned expected DOM
content, so it renders and serialises rather than merely launching.
`DISPLAY=:1` live, one screen at 1920x1200, `Xtigervnc` on `127.0.0.1:5901`
(loopback only).

It unlocks surfaces with no API — reading a rendered dashboard, capturing a
screenshot as evidence. It does **not** unlock anything requiring the
founder's authenticated session; there are no browser credentials here. It is
a rendering capability, not an access capability, and confusing the two would
be the natural error.

### Present and unused

- A hermetic container runtime with BuildKit — the strongest acceptance
  primitive available, adopted by no lane.
- A working headed and headless browser — no API-less surface has needed it.
- `cursor-subscriptions` — event-driven waiting, while lanes poll or idle.
- The Supabase CLI, installable on demand via `npx`.
- 47 GiB RAM and 8 CPUs, essentially idle.

Also absent from PATH: `docker`, `supabase`, `vercel`, `wrangler`, `psql`.
`curl` 8.5.0 supports `-H @-` and `-K -` but **not** the `%{errno}` write-out
variable — worth knowing before writing diagnostics that depend on it.

---

## D. The plan

Full ten-point specification per action in `FOUNDER-ALIGNMENT-PLAN.json`.
Ordered by leverage per founder minute, with a hard preference for actions
that create no credential.

1. **FA-W3-01 — mirror the existing Cursor API key. NOW.**
   ***The single action that unlocks the most.*** Two dashboard visits, one
   copy-paste, nothing created. It is the only item that removes the founder
   from the critical path of every future dispatch: with it, a controller
   creates its own lanes and chooses each lane's model — including a different
   family for the acceptor, which is what makes acceptance independent rather
   than nominal.
2. **FA-W3-02 — retire the four dead `AUREA_E2E_*` secrets. NOW**, subject to
   confirming the tests are not returning. Near-zero effort; stops a live email
   and password reaching every run for no benefit.
3. **FA-W3-03 — authenticate the Supabase MCP. LATER.** Worth having for
   `get_advisors` against the unresolved Supabase security boundary, and for
   observing real schema state. Creates no secret. Must not be scheduled as
   though it reaches the Cursor key.
4. **FA-W3-04 — Cloudflare and Vercel as one bundled decision. ON DEMAND.**
   Connect when a lane has an actual deployment question, not before.
5. **FA-W3-05 — service account instead of a personal key. DEFERRED DECISION.**
   Decouples continuity from one person, but *would* create a credential — so
   it is justified only if the existing key is then retired from programme use.
   Explicitly not a reason to delay FA-W3-01.

**Recommended against:** issuing a new Cursor key (superseded); creating a
Supabase PAT to fetch the key (a more powerful credential to move a lesser
one); an Edge Function that returns the secret (an exfiltration endpoint);
broader GitHub permissions (the App's permissions are set by the App, not the
installer — coordination already runs on git, where write is proven).

Nothing in this bundle asks the founder to paste a secret into chat.
