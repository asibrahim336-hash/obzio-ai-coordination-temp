# OBZIO — INTEROP EVIDENCE LOG (17 Aug 2026)
TEMPORARY — NON-CANONICAL — REPLACEABLE — NO SECRETS
Purpose: actual cross-surface transfer routes and failures, as evidence for Ultra's eventual communication/state architecture. Compact, additive. Not the information-plane decision.

## Successful routes (exercised this operation)
- ChatGPT web <-> ChatGPT web (same account): browser extension + backend-api. Verbatim source fetch via GET /backend-api/conversation/{id} (node content.parts join); delivery via synthetic ClipboardEvent paste -> pasted-text attachment. Proven at 35,690 B and 65,419 B with no composer freeze. Primary internal relay route; removes founder re-upload for any source already in the ChatGPT estate.
- GitHub (Zapier connector, CLOUD — browser-independent): file CRUD via put_file_b64, read via get_file_contents; account asibrahim336-hash. Durable coordination artefacts (this file, state/*, commissions/*, templates/*).
- Google Drive (Claude connector, CLOUD): search/read/create. Interim handoff bus (Obzio Ops).
- Claude memory (native): cross-surface continuity, incl. successor boot.
- Claude scheduled tasks (claude-code-remote, CLOUD): daily 08:30 / weekly Sun 17:00 Irish cadence.

## Failures / boundaries (observed)
- BROWSER BRIDGE DISCONNECT (17 Aug, immediately after Checkpoint 02): the claude-in-chrome MCP server dropped and did NOT auto-reconnect; server absent from the session's connected-server list (confirmed via server refresh — only cloud servers remain). EFFECT: ALL ChatGPT-web and Metamate-web operation is blocked from the Claude operator until the owner reopens the side panel / extension. This is the top operational reliability risk: a single point of failure for the entire browser-operator lane. Cloud connectors (GitHub/Drive/Gmail/Calendar/memory/scheduled) are unaffected.
- ChatGPT OpenAI API (Zapier) != chatgpt.com web account: the API estate cannot post into web conversations. Therefore there is NO non-browser fallback to relay into a ChatGPT web lane. Any web-lane relay (incl. packet 008 -> Ultra Prompt Control) hard-depends on the extension.
- metamate.meta.com: EARLIER browser state could not attach extension tools (site-access). SUPERSEDED by current owner report that Metamate is reachable + a founder clarification sent re: a policy concern. The operative Metamate blocker is now a policy question under founder clarification, NOT a site-access boundary. Recorded so the two are not conflated (per the distinguish-current-boundary-from-inherited-memory rule).
- claude.ai: extension cannot operate Anthropic's own surface (platform rule). Unchanged.
- SPA navigation race (ChatGPT web): new-chat composer can rebind to the most recent conversation between paste and send; caused one misrouted seed (6b3372c1, voided in-lane). Mitigation now standard: single JS call route-check -> paste -> chip-check -> route-recheck -> send.

## Architecture implications for Ultra (communication/state)
- The browser-operator lane needs one of: (a) a resilient/auto-reconnecting bridge; (b) a non-browser path into the ChatGPT-web estate; or (c) migration of relay-bearing state onto a surface reachable by cloud connectors. Until one exists, the extension is a hard single point of failure and every web-lane relay is founder-attention-bound whenever it drops.
- Immutable transfer artefacts (repo files, Drive docs) are the correct fallback when live connectivity is absent: they let a returning operator resume without re-fetching from a live surface. Prefer AI-lane direct retrieval when the surface is live; fall back to immutable artefact when it is not.
- Cost/latency note: browser relays cost real wall-clock (multi-step UI + backend-api verification per send) and carry the disconnect risk; cloud-connector writes are cheaper and more reliable but only reach connector-visible surfaces. Route selection should weigh both.
