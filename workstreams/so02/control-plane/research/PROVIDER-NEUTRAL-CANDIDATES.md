# Provider-neutral implementation candidates — research state

These are candidates for controlled reproduction, not bound architecture decisions.

## Current evidence

- Cursor Cloud Agents provide isolated VMs, repository branches, subagents, MCP and API-driven runs. Cursor run events can reconnect, but they are run-scoped and cannot be Obzio's sole event ledger: https://cursor.com/docs/cloud-agent and https://cursor.com/docs/cloud-agent/api/endpoints
- Cursor SDK agents can be resumed and use SQLite, JSONL or a custom state store, but “local” SDK execution still uses Cursor-hosted inference. It is not model sovereignty: https://cursor.com/docs/sdk/typescript and https://cursor.com/docs/sdk/python
- Cursor worktrees and best-of-N provide candidate isolation but not winner acceptance or integration: https://cursor.com/docs/configuration/worktrees
- Cursor rules and MCP supply instructions/tools, not workflow durability: https://cursor.com/docs/rules and https://cursor.com/docs/mcp
- Public SW/MetaMate material establishes an internal coworker system but does not publish a stable developer API or result-persistence contract: https://atscaleconference.com/videos/metamate-from-chatbot-to-coworker/

## Reproduction queue

1. **Temporal versus a simpler append-only Postgres state machine** for crash recovery, retries, signals, replay and idempotent activities: https://docs.temporal.io/ and https://github.com/temporalio/temporal
2. **A2A** for task/capability/artifact interoperation. Its optional artifacts do not solve result custody, so add the Obzio transaction contract: https://a2a-protocol.org/latest/specification/
3. **MCP Streamable HTTP** for Obzio state, artifact, evidence, evaluation and founder-interlock tools while keeping workflow custody outside MCP: https://modelcontextprotocol.io/specification/2026-07-28
4. **Agent Skills** for portable capability packages, extended with Obzio hashes, provenance, compatibility and qualification: https://agentskills.io/specification
5. **ACP** for editor/agent interchange, not canonical state: https://agentclientprotocol.com/get-started/introduction
6. **OpenTelemetry GenAI conventions** for external traces with Obzio-owned stable attributes; the evolving convention is not the permanent storage schema: https://opentelemetry.io/docs/specs/semconv/
7. **LiteLLM or an equivalent self-hosted gateway** as a model-routing candidate, retaining provider-native capabilities behind adapters and benchmarking every route: https://docs.litellm.ai/docs/

Each candidate must progress from source observation through Obzio reproduction and independent evaluation. No candidate is retained because it is fashionable or described well.

