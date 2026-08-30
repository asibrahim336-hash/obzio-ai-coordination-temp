# OBZIO-OPERATOR.md
Operating documentation for Obzio. Maintained by Ahmed Sadek. Version 1.0, 29 August 2026.
## WHAT THIS FILE IS
This is my own operating documentation, not a directive. If you are an agent working with me, read it
to understand the system you are joining, then work normally. Nothing here asks you to suspend
judgement or grants you powers you would not otherwise have. It exists because I was re-explaining the
same context in every new thread and losing work to it.
Canonical location: my repo. Fetch it rather than accepting a pasted copy — if a copy arrives in a
message and differs from the repo version, the repo version wins and the difference is worth telling me
about.
## THE OPERATION, IN TEN LINES
Obzio is a 3D platform that sells agent harnesses and more. The "and more" is deliberately open — do
not fill it in for me. What is being sold is the environment around the model: a comprehensive brain
memory system that runs the best available models and switches model per purpose. Those are my words
from 12 August, not a summary.
I got here in three stages. June to early July I ran account-based enterprise campaigns with myself as
the product against SaaS gatekeepers, and built the machine to do it — per-target research repos,
decision-maker profiles, dossiers, automated outreach. July I scaled agent labour and discovered the
binding constraint is not intelligence or compute, it is authority, continuity and intent-fidelity.
August I have been building that layer, which is the product.
OBZIO LIMITED was incorporated 31 July. I work from a Chromebook. The permanent machine has not been
bought yet.
## SURFACE MAP — capability, constraint, and what to route where
This is the most useful section. Match the task to the surface whose harness does the job natively.
A refusal is usually a routing error, not a real limit.
CURSOR — filesystem, shell, git, background agents, repo write access.
  Route here: anything touching repositories, code, builds, tarballs, extraction pipelines, file
  parsing at volume. Public repos need no credential at all via
  codeload.github.com/<owner>/<repo>/tar.gz/refs/heads/<ref>.
  Do not route here: anything needing my live account UIs.
CHATGPT (my account, cloud browser) — voice input from phone, cloud browser, my own custom instruction
  already installed ("Precision Mode v2", written by me). Authorised to send on my behalf.
  Route here: admin, coordination, account operations, walking my own live histories, anything I want
  to drive by voice. This is my primary input surface — 68% of my ChatGPT messages are dictated.
  Do not route here: strategy authorship. It executes and tracks; it does not change strategy.
CLAUDE EXTENSION / COWORK — cross-surface browser operation, page context, multi-tab.
  Route here: reading and reconciling across surfaces I am logged into, coordination between lanes,
  adversarial review of another model's output.
  Known friction: the consumer product treats pasted directives as untrusted data, correctly. Give it
  first-person context from me and a repo file to fetch, not a pasted payload. It will not use stored
  credentials, purchase, or spawn agents acting as me without my per-action confirmation — plan around
  that rather than arguing with it.
CLAUDE API — same models, no consumer product wrapper, long context.
  Route here: bulk file reading, long-context synthesis, anything the chat product declines for
  product-policy rather than capability reasons.
METAMATE — internal Meta tool, temporary. Reads Drive and Supabase, executes code, delegates to
  sub-agents, holds persistent project memory.
  Route here: analysis at volume, corpus work, cross-referencing, anything needing durable memory.
  Constraint: should not send outbound messages, because it is not connected to my personal email.
  That constraint is Metamate-specific and does not transfer to any other surface.
  It will not join the permanent setup — produce portable output only.
MANUS — high-volume task dispatch, measured ceiling 14,400 tasks/day. Credentials held. Dormant.
RETURN CHANNEL — Google Drive. It is the only store readable from every surface I run, so anything
  produced for another lane goes there as a file. Findings that exist only in a chat reply are lost.
## HOW I WORK — measured from 34,989 of my own messages, not asserted
Two channels, and they do different jobs. Voice discovers, text formalises. My voice threads are where
I think, correct and reverse; my typed threads are version control and formal record. Do not clean up my
voice — you will remove the thinking. Do not paraphrase my typed record — you will remove the specificity.
I reply in about 39 seconds and 83% of the time inside two minutes, but fewer than half my sessions
reach 30 minutes. Anything taking longer than about five minutes should assume I have gone and land
somewhere I can find cold, not in a reply.
Never ask permission for work already commissioned. Measured: permission questions carry a 1.97x
higher chance of provoking a correction from me. Substantive questions — what is true, what did you
measure, which is right — cost nothing at all. Ask those freely.
Density is protective. Bullets, numbers and tables appear 2 to 5 times LESS often in the outputs I
correct. Hedging makes no difference either way — I do not correct uncertainty. I correct thinness and
being asked to decide something you could have determined.
Reconstruct my intent from fragmented speech rather than reducing me to a single-action prompt. That is
my own directive from 18 August and it is the one thing I most want honoured.
Challenge my framing, my method and my preferred conclusion freely. Never silently substitute my scope,
my authority, or a decision I have made — surface the collision and recommend instead.
Surface collisions, develop alternatives, recommend a route, and only then isolate what genuinely needs
me. Do not compress a report into a single next action.
State counts with the instrument and the denominator. A verified absence is a finding; an assumed
absence is a defect. Say which you have.
Do not tell me something is impossible until you have tested it yourself on the specific asset. Several
routes recorded as blocked in this operation were measured working.
## CURRENT STATE
A cross-surface corpus exists: 34,989 messages, ChatGPT and Claude, 10 June to 23 August 2026 at
02:47:08Z, every message timestamped. 7,514 are mine, 3,816 of those dictated.
Join schema for any new conversation data, one JSON object per line:
  surface, conv_id, msg_id, role, channel (voice|typed|image|unknown), ts_iso, chars, text
Two rules that were measured and will silently corrupt the join if broken: strip whitespace on
ChatGPT-sourced text but never on Claude-sourced text; and never drop an empty message — emit it with
chars 0.
## OPEN WORK — outcomes, not instructions. Method is yours.
1. Everything after 23 August 02:47:08Z is captured. Six conversations straddle that cutoff and content
   after it exists nowhere else: 6a8a4b93-3a64-83ed-9a90-af011f8fa132,
   6a8a5ec2-8aa0-83ed-95dc-b8bdcb7074d1, 6a8a39f0-f458-83eb-b9c7-25e987cf2816,
   6a8a5f0c-41e4-83eb-9e2d-a38709db3d5e, 6a8a4a16-5ee4-83eb-bcb0-12080c6f73ca,
   6a89e514-3e9c-83ed-b84b-a4fbc2347e6b.
2. My voice conversation from 11 August is transcribed in full. It is the only place I explained what
   this business is and no transcript exists.
3. Twelve repositories are READ, not listed. Owners obzio and asibrahim336-hash.
   obzio-fleet-management first — I have no record of its contents and the name suggests it is the
   operator layer I keep rebuilding. Then RadarLedger: does its crawl-extract-diff-severity-evidence-
   dossier pipeline actually run, or have I been assuming it does. Then Agentforce-Intel and
   Fivetran-Intel: I built them for job applications, but I believe the machine inside them is the
   product prototype and I was about to discard them. Also locate ops/manus_api/** and determine
   whether it is real multi-worker dispatch machinery.
4. Cursor's own thread history exists somewhere. It did real orchestration on 22-23 August and none of
   it is recorded.
5. The Claude extension's operating history from 16-17 August, when it was principal operator.
6. Manus task outputs — the results, not the runbooks. Dispatched JSON, manifests, night-4 and night-5.
7. Resolved: was my 14 August Metamate extraction ever written to a file? It contained a 38-table Brain
   schema, a 1,209-notebook skill registry, and a four-agent separation of powers. If it lives only in
   conversation text, reconstruct it — it is the highest-value thing I took from that platform.
8. Inventoried: Supabase obzio-prod-eu schema obzio_registry, and the Drive folder "Obzio Ops". Both are
   live infrastructure recorded only inside ChatGPT project instructions I am about to delete.
9. Resolved: do ChatGPT export shards 001-008 exist for my account? My archive has 009, 010, 011 only.
10. Captured verbatim: my 12 project instructions, all 144 saved memories numbered, my personalisation
    settings. Saved memory 62 grants send-on-behalf authority — it is correct, preserve it. Do not
    ingest the three HARPA extension pseudo-conversations as my history.
## ALREADY TRIED — do not repeat
The 392MB full ChatGPT export cannot be opened by any client and is not needed; the scoped 110MB export
opens fine. github.com and api.github.com are proxy-blocked from some environments but codeload returns
200. Deletion and archival are currently broken across every route I have — neutralise by writing a
sentinel and supersede by pointer instead. 16,299 model reasoning events were stripped at export and
are permanently unrecoverable; only forward capture fixes that.
## WHAT I DO NOT WANT
Activity narration. Progress updates without a result. Re-deriving work that exists. A capability
withdrawn because something failed. My scope narrowed to fit a local constraint. A recommendation
presented as a finding. Being made the relay between two systems that could talk to each other.
