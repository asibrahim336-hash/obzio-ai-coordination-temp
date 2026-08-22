# Founder operating environment — candidate topology comparison and recommendation

**Artifact** `OE-L2-TOPOLOGY-COMPARISON-20260822-v001`
**Lane** `OE-L2-CAPABILITY-RESEARCH` · **Commission** `COM-CUR-ENV-01-20260822-v001`
**Fence token** `d5e76252f0ea259d` · **Immutable start SHA** `fe0a595206e5986de7eaac6cabc619215a1eb81b`
**Lifecycle state** `READY_TO_COMMIT`
**Binding status** `NON_BINDING_RESEARCH_NO_TOOL_MODEL_OR_ARCHITECTURE_SELECTED`

Companion artifacts: `CAPABILITY-MAP.json` (32 requirements across the ten commissioned
areas), `CANDIDATE-REGISTER.json` (73 candidates, 65 with live GitHub signals),
`NAME-RESOLUTION.json` (ambiguous seeds). Raw evidence with fetch dates and body
hashes is under `receipts/so02/2026-08-22/oe-l2-capability-research/raw/`.

Every claim below is labelled `DIRECTLY_REPRODUCED` (this lane ran the command),
`DOCUMENTED` (official source this lane fetched) or `HYPOTHESIS` (untested
inference). The recommendation rests only on the first two.

---

## 1. What the evidence changed

Five findings from live sources moved the answer away from what recall alone would
have produced. They are stated first because they are the reason the comparison
comes out as it does.

**Open weights and local operation are different properties, and they come apart at
the top.** `DIRECTLY_REPRODUCED`: the Hugging Face API reports `moonshotai/Kimi-K3`
at **2,779,931,837,184 parameters** — about 2.78 trillion. The weights are published
and ungated. No laptop will ever run it. Meanwhile `Qwen/Qwen3.8-27B` is 27.8B under
Apache-2.0 with an `mlx` 4-bit build already published by `mlx-community`,
`openai/gpt-oss-20b` is 21.5B under Apache-2.0, and `zai-org/GLM-4.7-Flash` is 31.2B
under **MIT**. Naming an open-weight coordinating base is therefore not one decision
but two: which family, and whether the requirement is "weights are published" or
"I can run it myself".

**Two named seeds are not maintained, and one is not what its name implies.**
`DIRECTLY_REPRODUCED`: `BrowserMCP/mcp` was last pushed **2025-04-24** with no
published release ever, and npm `@browsermcp/mcp` sits at 0.1.3 from 2025-04-11 with
no licence field — roughly sixteen months of stillness in a component that has to
track Chrome. Nanobrowser's extension is alive (pushed 2026-08-18) but its last
release is from 2025-11-22 and its integration point,
`nanobrowser/nanobrowser-mcp-host`, has 19 stars and stopped in May 2025. And
`MoonshotAI/Kimi-K2`, the repo the name "Kimi" points at, was last pushed 2026-01-21
and documents a superseded generation while the live product is K3.

**The Playwright maintainers no longer recommend MCP as the default interface.**
`DOCUMENTED`: the `playwright-mcp` README now says coding agents "increasingly favor
CLI-based workflows exposed as SKILLs over MCP because CLI invocations are more
token-efficient", reserving MCP for "specialized agentic loops that benefit from
persistent state". An MCP-only interface policy would contradict the maintainer of
the strongest browser-control candidate. `microsoft/playwright-cli` is real and
active: `DIRECTLY_REPRODUCED`, 12,744 stars, pushed 2026-08-19.

**Telemetry and data handling differ sharply between candidates that look alike.**
`DOCUMENTED`: `chrome-devtools-mcp` collects Google usage statistics **by default**
and may send trace URLs to the Google CrUX API, both with documented opt-outs.
`DIRECTLY_REPRODUCED` from Chrome Web Store listings: Sider (5,000,000 users)
declares it handles **personally identifiable information and website content**,
while HARPA (300,000 users) and the Playwright Extension (90,000 users) both declare
no data collection. These are not equivalent components with different logos.

**Several widely-cited projects have moved, and one memory project's headline
numbers are not its open-source numbers.** `DIRECTLY_REPRODUCED`: fifteen slug
redirects were observed, including `block/goose` → `aaif-goose/goose` (now a Linux
Foundation project), `invariantlabs-ai/mcp-scan` → `snyk/agent-scan`,
`microsoft/presidio` → `data-privacy-stack/presidio`, and `iterative/dvc` →
`treeverse/dvc`. `kuzudb/kuzu` and `huggingface/text-generation-inference` are
**archived**. `DOCUMENTED`: mem0's own README states its LoCoMo and LongMemEval
figures "reflect Mem0's managed platform, which includes proprietary optimizations
not available in the open-source SDK". Creditable disclosure, and disqualifying for a
sovereignty-first choice.

---

## 2. The constraint that shapes every topology

State it plainly, because it determines the whole design:

> On a Chromebook, **cloud reachability and authenticated-session operation are
> mutually exclusive** unless a third party is admitted into the trust boundary.

A cloud agent runs in an isolated VM with no route to the founder's logged-in browser
or microphone. A controller that *can* reach them must run on the founder's device.
Closing that gap has exactly three shapes, and each is a disclosure decision rather
than a technical preference:

| Shape | Mechanism | Who holds the session | Evidence |
|---|---|---|---|
| Local controller | Crostini-hosted controller attaches to the existing Chrome profile under a per-connection approval | The founder's device | `DOCUMENTED` — Playwright Extension docs: existing profile, per-client tab groups, approval dialog |
| Cloud relay to local node | A vendor cloud dispatches instructions to a node on the founder's machine | The founder's device, but a vendor cloud commands it | `DOCUMENTED` — HARPA GRID docs: "GRID orchestrates your machine to run the tasks for you, thus handling data behind logins" |
| Cloud browser | Credentials move into a vendor vault; sessions run on vendor machines | The vendor | `DIRECTLY_REPRODUCED` — Airtop site: authenticated cloud browsing, password vault, up to 100 sessions |

This is founder question **FQ-02**, and no amount of further research settles it.

---

## 3. Candidate topologies

Five are compared. T1 is what runs today; T5 is the recommendation.

### T1 — Cloud-agent-centric with Git as canonical state *(the incumbent)*

Cloud agents in isolated VMs operate the repository. GitHub is transport, canonical
store and result custody. Models are provider-hosted.

- **Delivers:** provenance and knowledge flow (C3); cross-model continuity from
  repository state (C4); durable state, manifests and replay (C8); model routing and
  qualification against API routes (C6 except local inference); everything that does
  not need the founder's device (C9-R1).
- **Cannot deliver, structurally:** authenticated-session operation (C1-R1), evidence
  capture from the founder's own logged-in surfaces (C2 on those surfaces), voice
  intake (C7 — no microphone), desktop control (C1-R4), local inference (C6-R4).
  These are not maturity gaps. A VM in someone else's data centre has no path to
  them.
- **Local vs cloud control:** all execution is in the provider's environment; the
  founder's device is a viewport.
- **Open vs proprietary:** the runtime is proprietary, the state is open. That split
  is the reason the topology is survivable.
- **Chromebook / MacBook:** excellent now; the MacBook adds nothing.
- **Privacy and disclosure:** repository contents and prompts are disclosed to the
  runtime and its model provider. Notably, it has *no* access to authenticated
  sessions — a real privacy advantage, not only a limitation.
- **Authentication burden:** lowest of the five. One repository grant.
- **Maintenance burden:** near zero; the provider maintains the runtime.
- **Cost shape:** subscription plus metered model usage; no capex.
- **Lock-in and portability:** medium. Mitigated by Git-canonical state and by ACP
  (`DOCUMENTED`: Cursor documents an ACP surface for its CLI). Would rise sharply if
  canonical state moved to a provider-hosted repository product.
- **Failure recovery:** state survives anything; execution stops when the provider
  stops. No offline mode.
- **Independent verifiability:** high for artifacts (commits, hashes, manifests), low
  for the run itself — provider completion is a status, not acceptance.

### T2 — Chromebook browser-extension-centric

A proprietary extension (HARPA, Sider, or Nanobrowser as the open variant) does the
work inside the founder's browser with bring-your-own model keys.

- **Delivers:** authenticated-session operation natively and with zero setup (C1-R1);
  some extraction (C2); model choice via BYO keys (C6 partially).
- **Cannot deliver:** structured machine-checkable read-back, replay, provenance,
  durable versioned state, result custody independent of the tool, or independent
  verification — effectively all of C3 and C8, and the evidence half of C2.
  Automations live in a vendor's format.
- **Local vs cloud control:** nominally local, but the vendor cloud is in the loop for
  most products, and explicitly so for HARPA GRID.
- **Open vs proprietary:** closed engines that cannot be audited or forked. The one
  open member, Nanobrowser, has an abandoned integration point.
- **Chromebook / MacBook:** excellent now, identical later — no upgrade path.
- **Privacy and disclosure:** the weakest. `DIRECTLY_REPRODUCED`: Sider declares it
  handles PII and website content. Even where no collection is declared, a closed
  engine operating inside authenticated sessions cannot be verified.
- **Authentication burden:** lowest — which is precisely the risk.
- **Maintenance burden:** none for the founder, and no ability to repair.
- **Cost shape:** small subscription; cheapest of the five.
- **Lock-in and portability:** high in workflow terms.
- **Failure recovery:** poor; no replay, no substitution path.
- **Independent verifiability:** poor. **This is the disqualifier**, not the price and
  not the privacy policy.

### T3 — Chromebook Crostini local-controller

Crostini hosts a controller (Playwright CLI or MCP, plus `chrome-devtools-mcp`) and a
local agent runtime (goose) calling API models. The Playwright Extension bridges into
the authenticated ChromeOS browser under per-connection approval. Git stays canonical.

- **Delivers:** authenticated operation with a real owner gate (C1-R1, C1-R2);
  explicit failure semantics (C1-R3); the full evidence surface — accessibility tree,
  DOM, console, network, performance traces (C2); open interfaces (C5); API model
  routing (C6 except local); durable state (C8); secret discipline (C10).
- **Cannot deliver:** local inference (C6-R4 — no accelerator), desktop control
  (C1-R4 — ChromeOS is not a general desktop target), and **it is not reachable from a
  cloud agent**, so it does not replace T1, it complements it.
- **Local vs cloud control:** control is local; only prompts and observations leave.
- **Open vs proprietary:** entirely open components (Apache-2.0 and MIT) except the
  hosted model API behind an adapter.
- **Chromebook fit:** workable with real friction. `DOCUMENTED` from the ChromeOS
  developer docs: all apps in the Linux container **share one sandbox** and can affect
  each other, and permissions such as USB and **microphone are not shared by
  default**. That last point directly constrains voice.
- **MacBook fit:** upgrades cleanly — the same controller, without the extension
  dependency.
- **Privacy and disclosure:** strong. Sessions never leave the device. Requires
  deliberately disabling `chrome-devtools-mcp` usage statistics and CrUX reporting.
- **Authentication burden:** moderate, and the burden *is* the safety feature — an
  approval per connection. `DOCUMENTED`: `PLAYWRIGHT_MCP_EXTENSION_TOKEN` exists to
  remove that prompt; adopting it removes the gate.
- **Maintenance burden:** the highest of the five for the founder personally — Node,
  npm, a Rust binary and browser-version drift, all maintained by hand on a
  Chromebook.
- **Cost shape:** software near zero; metered model usage only.
- **Lock-in and portability:** lowest of the browser topologies.
- **Failure recovery:** good; components are individually replaceable.
- **Independent verifiability:** highest of the browser topologies — network, console
  and accessibility artifacts are checkable by someone who was not there.

### T4 — MacBook local-first with cloud fallback

Local models (MLX, llama.cpp, Ollama), local transcription (whisper.cpp, Handy), a
controller-owned browser profile, local graph and vector stores, Git canonical, and
frontier API calls only where justified.

- **Delivers:** everything in the capability map, including local inference (C6-R4),
  fully-local voice (C7-R1) and desktop control (C1-R4).
- **Cannot deliver:** frontier-scale reasoning locally. `DIRECTLY_REPRODUCED`: Kimi K3
  at 2.78T parameters and gpt-oss-120b at 116.8B set the ceiling; gpt-oss-20b at 21.5B
  and Qwen3.8-27B at 27.8B set the accessible floor. Which rung is reachable is a
  function of unified memory — **FQ-01**, a procurement decision.
- **Local vs cloud control:** maximal local control; cloud used deliberately.
- **Open vs proprietary:** the most open of the five. MLX, llama.cpp, Ollama,
  whisper.cpp and Handy are all MIT.
- **Chromebook fit:** none. This is the future state, not a current option.
- **Privacy and disclosure:** the best available. Voice, the most sensitive artifact
  in the system, never leaves the device.
- **Authentication burden:** low once established.
- **Maintenance burden:** moderate and self-inflicted — model updates, quantisation
  choices, runtime upgrades.
- **Cost shape:** capital expenditure, then near-zero marginal inference, with cloud
  burst. Inverts T1's shape.
- **Lock-in and portability:** lowest overall.
- **Failure recovery:** best — it works with no network at all. Its new risk is a
  single machine as a single point of failure, which needs a mirror.
- **Independent verifiability:** high, and uniquely, model behaviour becomes
  reproducible because the weights are pinned by hash rather than by a vendor's alias.

### T5 — One Git-canonical control plane, three swappable execution planes *(recommended)*

Not a compromise between the others; a structure that makes them stages of one
system rather than competing designs.

- **Control plane (always):** the Git repository is canonical — state, provenance,
  manifests, evaluation results, decisions and recovery points. Every plane writes
  here and nothing is authoritative anywhere else.
- **Plane A — cloud execution (today):** repository work, research, knowledge flow,
  long-running agents. **Holds no authenticated session and no microphone**, by design
  rather than by limitation.
- **Plane B — device-local browser (today, Chromebook; better later, MacBook):**
  authenticated operation under per-connection approval, emitting structured evidence
  into the control plane. On the Chromebook via Crostini plus the extension bridge; on
  the MacBook via a controller-owned profile.
- **Plane C — device-local compute (empty today, fills on the MacBook):** local
  inference, local transcription, desktop control.
- **One adapter boundary** in front of models, tools and voice, so a plane's backend
  changes without touching call sites. **One evaluation suite** every plane must pass,
  so substitution is qualified rather than asserted.

- **Delivers:** every capability in the map, with each one attributed to a plane and
  each plane separately disclosed.
- **Cannot deliver:** nothing the individual topologies deliver — but it costs more
  discipline than any of them, because the adapter boundary and the evaluation suite
  have to exist before the second plane is worth having.
- **Chromebook / MacBook:** Plane C is simply empty today. The MacBook fills it
  without migrating state, interfaces or evidence.
- **Privacy and disclosure:** each plane has its own disclosure class, so the cloud
  plane never sees authenticated-session content and the browser plane never sees the
  whole strategic frame.
- **Cost shape:** T1's subscription today, T4's capex later, and routing choice
  dominating both — see §5.
- **Lock-in and portability:** every plane is individually replaceable; the control
  plane is plain Git.
- **Failure recovery:** a plane failing degrades capability without stopping
  operation, which none of T1–T4 achieves alone.
- **Independent verifiability:** highest, because verification lives in the control
  plane rather than in any execution runtime.

---

## 4. Comparison at a glance

| | T1 cloud-agent | T2 extension | T3 Crostini-local | T4 MacBook-local | T5 hybrid |
|---|---|---|---|---|---|
| Authenticated sessions | **no (structural)** | yes | yes | yes | yes (Plane B) |
| Runtime/network evidence | n/a | weak | **strong** | strong | strong |
| Provenance + durable state | strong | **absent** | strong | strong | strong |
| Voice intake | **no** | no | gated by Crostini mic sharing | **fully local** | staged |
| Local inference | no | no | no | **yes** | Plane C |
| Works today on Chromebook | **yes** | yes | yes, with friction | **no** | yes |
| Survives provider outage | no | no | partly | **yes** | partly, then yes |
| Independently verifiable | artifacts only | **no** | yes | yes | **yes** |
| Founder maintenance | **lowest** | none | **highest** | moderate | moderate |
| Disclosure surface | repo + prompts | **widest** | narrow | **narrowest** | per-plane |
| Cost shape | subscription | small sub | metered only | **capex then ~0** | staged |
| Lock-in | medium | **high** | low | **lowest** | low |

---

## 5. Cost shape is set by routing, not by model choice

`DIRECTLY_REPRODUCED` from the OpenRouter catalogue on 2026-08-22 (421 models live):

| Route | Weights published | Context | USD / M input | USD / M output |
|---|---|---|---|---|
| `moonshotai/kimi-k3` | yes | 1,048,576 | 3.00 | 15.00 |
| `qwen/qwen3.8-27b` | yes | 1,000,000 | 0.45 | 3.20 |
| `z-ai/glm-4.7-flash` | yes | 202,752 | 0.06 | 0.40 |
| `deepseek/deepseek-v4-flash` | yes | 1,048,576 | 0.0601 | 0.1201 |
| `openai/gpt-oss-120b` | yes | 131,072 | 0.037 | 0.17 |

The spread between the cheapest capable open route and the frontier open route is
roughly **50× on input and 88× on output**. `HYPOTHESIS`: for a founder estate, the
routing policy will dominate total spend by more than any single model selection —
which is an argument for the adapter boundary on economic grounds alone, before any
sovereignty argument.

Two further substitution facts, both `DIRECTLY_REPRODUCED` or `DOCUMENTED`: the
catalogue exposes a dated `canonical_slug` beside every moving `id` (for example
`moonshotai/kimi-k3` → `moonshotai/kimi-k3-20260715`), so exact-model pinning is
mechanically available; and the DeepSeek API publishes **both** an OpenAI-compatible
and an Anthropic-compatible base URL, so it can substitute behind either SDK shape
without a rewrite.

---

## 6. Recommendation

**Adopt T5 — one Git-canonical control plane with three swappable execution planes.**

The reasoning is not that T5 scores highest on a table. It is that the two strongest
single alternatives fail in opposite and non-overlapping ways:

- **T1 cannot acquire what it lacks.** Its gaps — authenticated sessions, voice,
  desktop control, local inference — are not immaturity. A cloud VM has no route to
  the founder's browser or microphone, and the only ways to build one are the three
  trust-boundary shapes in §2, each of which admits a third party. Waiting does not
  fix T1.
- **T4 cannot be acquired now.** Its gap is temporal and procurement-bound. Every
  component is verified live and permissively licensed; the machine does not exist
  yet, and which rung of the local model ladder it reaches is a purchasing decision
  (FQ-01) rather than an engineering one.

**The decisive trade-off between them is that T1's deficit is permanent and T4's is
scheduled.** T5 is the structure that follows from that asymmetry: keep T1 as the
plane that runs today, treat T4 as a plane that fills on arrival rather than a
platform to migrate to, and use T3 as the bridge that supplies — today, on the
Chromebook — the one capability class neither T1 nor T4 can supply right now.

What makes this cheap rather than grandiose is that the control plane already exists.
This lane's own outputs were produced, hashed, manifested and pushed through it. The
work is the adapter boundary and the evaluation suite, not a new platform.

### Components the evidence supports, per plane

Recorded as evidence-supported candidates. **None is selected**; the commission
reserves that to the founder.

- **Control plane:** Git plus sha256 manifests (already in use); W3C PROV-O for
  provenance vocabulary (`DOCUMENTED`, W3C Recommendation, unchanged since 2013 —
  its age is the argument for it); in-toto attestation predicates for signed
  acceptance verdicts.
- **Plane A:** the incumbent cloud agent; ACP as the standing escape hatch
  (`DIRECTLY_REPRODUCED`: `agentclientprotocol/agent-client-protocol`, schema-v1.21.0
  released 2026-08-20, and documented on both Cursor's CLI and goose).
- **Plane B:** Playwright for deterministic control — with the interface (CLI plus
  Skills, or MCP) left open per the maintainer's own guidance — plus
  `chrome-devtools-mcp` for runtime evidence with telemetry explicitly disabled, and
  goose as a provider-agnostic local runtime (`DIRECTLY_REPRODUCED`: Apache-2.0,
  v1.47.0 released 2026-08-21, now a Linux Foundation project).
- **Plane C:** MLX and llama.cpp for inference, Ollama for management, whisper.cpp
  and Handy for voice — all MIT, all pushed within the last four days.
- **Across planes:** a self-hosted LiteLLM gateway or OpenRouter behind Obzio's own
  adapter; Inspect AI or promptfoo as the substitution regression suite; age plus
  SOPS for secrets, with gitleaks enforcing the never-commit rule.

### On the halted batch

Independent evidence gathered by this lane happens to support two components the
halted SO-02 batch named — Playwright and goose. **That is a coincidence of
conclusions, not a revival.** This lane issues no founder action, no install step and
no configuration change, and the components arrived here through a capability-first
route with maintenance and disclosure signals attached, which the batch did not have.
Two other components the batch named do **not** survive: BrowserMCP fails on
maintenance and Nanobrowser's integration point is abandoned. The batch remains
halted.

---

## 7. Questions that require founder judgement, not more research

Ordered by how much they change the route.

**FQ-01 — MacBook unified memory.** This single number sets which local model rung is
reachable and therefore how much sovereignty the MacBook actually buys.
`DIRECTLY_REPRODUCED`: gpt-oss-20b is 21.5B parameters and Qwen3.8-27B is 27.8B, both
comfortable on a mid-memory machine; gpt-oss-120b is 116.8B and needs a large one;
Kimi K3 at 2.78T is unreachable at any configuration. Research cannot pick a budget.

**FQ-02 — May any third party hold or drive an authenticated session?** The three
shapes in §2 are a disclosure decision. HARPA GRID gives a vendor cloud standing
authority over the founder's logged-in browser; Airtop moves the credentials into a
vendor vault; the local controller keeps both on the device at the cost of cloud
unreachability and higher maintenance. Nothing about this is technical.

**FQ-03 — Is the requirement "open weights" or "runnable by us"?** The prior founder
directive names Qwen as the coordinating open-weight base with Kimi and DeepSeek
alongside. The evidence says Qwen is the only named family that spans both the
Chromebook-era API rung and the MacBook-era local rung under a permissive licence,
while Kimi is an API route wearing open-weight clothing. If the answer is "runnable by
us", the directive already holds and should be reaffirmed with that reason attached.
If the answer is "published weights", Kimi qualifies and the sovereignty claim needs
rewording.

**FQ-04 — Default telemetry posture.** `DOCUMENTED`: `chrome-devtools-mcp` collects
usage statistics by default and may send trace URLs to Google's CrUX API. Both are
disableable. The question is the standing rule — is third-party telemetry off by
default across the estate, with exceptions recorded, or on unless someone objects?

**FQ-05 — Is GitHub acceptable as the sole host of canonical state?** Git is
portable; GitHub is one vendor holding the hosting, the API and the permissions.
A second remote is cheap. This is a resilience decision the founder should make
knowingly rather than inherit.

**FQ-06 — Cost shape.** T1 is subscription plus metered, T4 is capital expenditure
then near zero. The 50× to 88× routing spread in §5 means the routing policy matters
more than the model choice, and the founder should set the ceiling before the
adapter enforces one.

**FQ-07 — May voice audio leave the device?** Raw audio carries unfiltered intent and
is the most sensitive artifact in the system. `DOCUMENTED`: browser on-device
recognition is gated by the `on-device-speech-recognition` permissions policy, and
Crostini does not share the microphone with the Linux container by default. Both
paths are viable; they disclose very differently.

**FQ-08 — Is AGPL-3.0 acceptable in Obzio's IP posture?** It is the deciding factor
for Skyvern, Basic Memory, Firecrawl and TruffleHog. Given the strategy of packaging
proven mechanisms as portable principal-owned IP, this needs a standing answer rather
than a per-component argument.

**FQ-09 — What was "Aircrift/Aircraft"?** `UNRESOLVED` after probing GitHub
repositories, users and organisations, the Chrome Web Store, npm, PyPI and DNS; no
web search engine was reachable. One sentence from the founder resolves in minutes
what unbounded search cannot: was it (a) a browser sidebar assistant like HARPA or
Sider, (b) a cloud browser service that holds logins like Airtop, (c) a voice or
dictation tool, or (d) something else? Full probe record in `NAME-RESOLUTION.json`.

It is worth noting what this seed demonstrates. An unconfirmed transcription entered
a work order and survived several hands unchallenged. That is precisely the failure
mode requirement **C7-R2** exists to prevent: read back consequential interpretation
before it becomes a durable instruction. The environment being designed here would
have caught it.
