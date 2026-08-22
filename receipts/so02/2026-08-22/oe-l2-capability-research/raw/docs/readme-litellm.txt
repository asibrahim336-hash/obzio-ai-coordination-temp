🚅 LiteLLM

LiteLLM AI Gateway

Open Source AI Gateway for 100+ LLMs. Self-hosted. Enterprise-ready. Call any LLM in OpenAI format.

LiteLLM Proxy Server (AI Gateway) | Hosted Proxy | Enterprise Tier | Website

---

## What is LiteLLM

LiteLLM is an open source AI Gateway that gives you a single, unified interface to call 100+ LLM providers — OpenAI, Anthropic, Gemini, Bedrock, Azure, and more — using the OpenAI format.

Use it as a **Python SDK** for direct library integration, or deploy the **AI Gateway (Proxy Server)** as a centralized service for your team or organization.

[**Jump to LiteLLM Proxy (LLM Gateway) Docs**](https://docs.litellm.ai/docs/simple_proxy)

[**Jump to Supported LLM Providers**](https://docs.litellm.ai/docs/providers)

---

## Why LiteLLM

Managing LLM calls across providers gets complicated fast — different SDKs, auth patterns, request formats, and error types for every model. LiteLLM removes that friction:

- **Unified API** — one interface for 100+ LLMs, no provider-specific SDK juggling
- **Drop-in OpenAI compatibility** — swap providers without rewriting your code
- **Production-ready gateway** — virtual keys, spend tracking, guardrails, load balancing, and an admin dashboard out of the box
- **8ms P95 latency** at 1k RPS ([benchmarks](https://docs.litellm.ai/docs/benchmarks))

### OSS Adopters

Netflix

---

## Features

LLMs - Call 100+ LLMs (Python SDK + AI Gateway)

[**All Supported Endpoints**](https://docs.litellm.ai/docs/supported_endpoints) - `/chat/completions`, `/responses`, `/embeddings`, `/images`, `/audio`, `/batches`, `/rerank`, `/a2a`, `/messages` and more.

### Python SDK

```shell
uv add litellm
```

```python
from litellm import completion
import os

os.environ["OPENAI_API_KEY"] = "your-openai-key"
os.environ["ANTHROPIC_API_KEY"] = "your-anthropic-key"

# OpenAI
response = completion(model="openai/gpt-4o", messages=[{"role": "user", "content": "Hello!"}])

# Anthropic
response = completion(model="anthropic/claude-sonnet-4-20250514", messages=[{"role": "user", "content": "Hello!"}])
```

### AI Gateway (Proxy Server)

[**Getting Started - E2E Tutorial**](https://docs.litellm.ai/docs/proxy/docker_quick_start) - Setup virtual keys, make your first request

```shell
uv tool install 'litellm[proxy]'
litellm --model gpt-4o
```

```python
import openai

client = openai.OpenAI(api_key="anything", base_url="http://0.0.0.0:4000")
response = client.chat.completions.create(
model="gpt-4o",
messages=[{"role": "user", "content": "Hello!"}]
)
```

[**Docs: LLM Providers**](https://docs.litellm.ai/docs/providers)

Agents - Invoke A2A Agents (Python SDK + AI Gateway)

[**Supported Providers**](https://docs.litellm.ai/docs/a2a#add-a2a-agents) - LangGraph, Vertex AI Agent Engine, Azure AI Foundry, Bedrock AgentCore, Pydantic AI

### Python SDK - A2A Protocol

```python
from litellm.a2a_protocol import A2AClient
from a2a.types import SendMessageRequest, MessageSendParams
from uuid import uuid4

client = A2AClient(base_url="http://localhost:10001")

request = SendMessageRequest(
id=str(uuid4()),
params=MessageSendParams(
message={
"role": "user",
"parts": [{"kind": "text", "text": "Hello!"}],
"messageId": uuid4().hex,
}
)
)
response = await client.send_message(request)
```

### AI Gateway (Proxy Server)

**Step 1.** [Add your Agent to the AI Gateway](https://docs.litellm.ai/docs/a2a#adding-your-agent) — set `protocolVersion` to `1.0` or `0.3` per agent

**Step 2.** Call Agent via A2A SDK (requires `a2a-sdk>=1.1.0`)

```python
import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, SendMessageRequest
from a2a.utils.constants import TransportProtocol
from uuid import uuid4

base_url = "http://localhost:4000/a2a/my-agent" # LiteLLM proxy + agent name
headers = {"Authorization": "Bearer sk-1234"} # LiteLLM Virtual Key

async with httpx.AsyncClient(headers=headers, timeout=60.0) as http_client:
resolver = A2ACardResolver(httpx_client=http_client, base_url=base_url)
agent_card = await resolver.get_agent_card()
config = ClientConfig(
httpx_client=http_client,
streaming=False,
supported_protocol_bindings=[TransportProtocol.JSONRPC, TransportProtocol.HTTP_JSON],
)
client = ClientFactory(config).create(agent_card)

request = SendMessageRequest(
message=Message(
message_id=uuid4().hex,
role=Role.ROLE_USER,
parts=[Part(text="Hello!")],
)
)
async for event in client.send_message(request):
populated = event.ListFields()
if populated and populated[0][0].name in ("message", "msg"):
print("".join(getattr(p, "text", "") or "" for p in populated[0][1].parts))
```

[**Docs: A2A Agent Gateway**](https://docs.litellm.ai/docs/a2a)

MCP Tools - Connect MCP servers to any LLM (Python SDK + AI Gateway)

### Python SDK - MCP Bridge

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from litellm import experimental_mcp_client
import litellm

server_params = StdioServerParameters(command="python", args=["mcp_server.py"])

async with stdio_client(server_params) as (read, write):
async with ClientSession(read, write) as session:
await session.initialize()

# Load MCP tools in OpenAI format
tools = await experimental_mcp_client.load_mcp_tools(session=session, format="openai")

# Use with any LiteLLM model
response = await litellm.acompletion(
model="gpt-4o",
messages=[{"role": "user", "content": "What's 3 + 5?"}],
tools=tools
)
```

### AI Gateway - MCP Gateway

**Step 1.** [Add your MCP Server to the AI Gateway](https://docs.litellm.ai/docs/mcp#adding-your-mcp)

**Step 2.** Call MCP tools via `/chat/completions`

```bash
curl -X POST 'http://0.0.0.0:4000/v1/chat/completions' \
-H 'Authorization: Bearer sk-1234' \
-H 'Content-Type: application/json' \
-d '{
"model": "gpt-4o",
"messages": [{"role": "user", "content": "Summarize the latest open PR"}],
"tools": [{
"type": "mcp",
"server_url": "litellm_proxy/mcp/github",
"server_label": "github_mcp",
"require_approval": "never"
}]
}'
```

### Use with Cursor IDE

```json
{
"mcpServers": {
"LiteLLM": {
"url": "http://localhost:4000/mcp/",
"headers": {
"x-litellm-api-key": "Bearer sk-1234"
}
}
}
}
```

[**Docs: MCP Gateway**](https://docs.litellm.ai/docs/mcp)

### Supported Providers ([Website Supported Models](https://models.litellm.ai/) | [Docs](https://docs.litellm.ai/docs/providers))

| Provider | `/chat/completions` | `/messages` | `/responses` | `/embeddings` | `/image/generations` | `/audio/transcriptions` | `/audio/speech` | `/moderations` | `/batches` | `/rerank` |
|-------------------------------------------------------------------------------------|---------------------|-------------|--------------|---------------|----------------------|-------------------------|-----------------|----------------|-----------|-----------|
| [Abliteration (`abliteration`)](https://docs.litellm.ai/docs/providers/abliteration) | ✅ | | | | | | | | | |
| [AI/ML API (`aiml`)](https://docs.litellm.ai/docs/providers/aiml) | ✅ | ✅ | ✅ | ✅ | ✅ | | | | | |
| [AI21 (`ai21`)](https://docs.litellm.ai/docs/providers/ai21) | ✅ | ✅ | ✅ | | | | | | | |
| [AI21 Chat (`ai21_chat`)](https://docs.litellm.ai/docs/providers/ai21) | ✅ | ✅ | ✅ | | | | | | | |
| [Aleph Alpha](https://docs.litellm.ai/docs/providers/aleph_alpha) | ✅ | ✅ | ✅ | | | | | | | |
| [Amazon Nova](https://docs.litellm.ai/docs/providers/amazon_nova) | ✅ | ✅ | ✅ | | | | | | | |
| [Anthropic (`anthropic`)](https://docs.litellm.ai/docs/providers/anthropic) | ✅ | ✅ | ✅ | | | | | | ✅ | |
| [Anthropic Text (`anthropic_text`)](https://docs.litellm.ai/docs/providers/anthropic) | ✅ | ✅ | ✅ | | | | | | ✅ | |
| [Anyscale](https://docs.litellm.ai/docs/providers/anyscale) | ✅ | ✅ | ✅ | | | | | | | |
| [AssemblyAI (`assemblyai`)](https://docs.litellm.ai/docs/pass_through/assembly_ai) | ✅ | ✅ | ✅ | | | ✅ | | | | |
| [Auto Router (`auto_router`)](https://docs.litellm.ai/docs/proxy/auto_routing) | ✅ | ✅ | ✅ | | | | | | | |
| [AWS - Bedrock (`bedrock`)](https://docs.litellm.ai/docs/providers/bedrock) | ✅ | ✅ | ✅ | ✅ | | | | | | ✅ |
| [AWS - Sagemaker (`sagemaker`)](https://docs.litellm.ai/docs/providers/aws_sagemaker) | ✅ | ✅ | ✅ | ✅ | | | | | | |
| [Azure (`azure`)](https://docs.litellm.ai/docs/providers/azure) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | |
| [Azure AI (`azure_ai`)](https://docs.litellm.ai/docs/providers/azure_ai) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | |
| [Azure Text (`azure_text`)](https://docs.litellm.ai/docs/providers/azure) | ✅ | ✅ | ✅ | | | ✅ | ✅ | ✅ | ✅ | |
| [Baseten (`baseten`)](https://docs.litellm.ai/docs/providers/baseten) | ✅ | ✅ | ✅ | | | | | | | |
| [Bytez (`bytez`)](https://docs.litellm.ai/docs/providers/bytez) | ✅ | ✅ | ✅ | | | | | | | |
| [Cerebras (`cerebras`)](https://docs.litellm.ai/docs/providers/cerebras) | ✅ | ✅ | ✅ | | | | | | | |
| [Clarifai (`clarifai`)](https://docs.litellm.ai/docs/providers/clarifai) | ✅ | ✅ | ✅ | | | | | | | |
| [Cloudflare AI Workers (`cloudflare`)](https://docs.litellm.ai/docs/providers/cloudflare_workers) | ✅ | ✅ | ✅ | | | | | | | |
| [Codestral (`codestral`)](https://docs.litellm.ai/docs/providers/codestral) | ✅ | ✅ | ✅ | | | | | | | |
| [Cognition (`cognition`)](https://docs.litellm.ai/docs/providers/cognition) | ✅ | ✅ | ✅ | | | | | | | |
| [Cohere (`cohere`)](https://docs.litellm.ai/docs/providers/cohere) | ✅ | ✅ | ✅ | ✅ | | | | | | ✅ |
| [Cohere Chat (`cohere_chat`)](https://docs.litellm.ai/docs/providers/cohere) | ✅ | ✅ | ✅ | | | | | | | |
| [CometAPI (`cometapi`)](https://docs.litellm.ai/docs/providers/cometapi) | ✅ | ✅ | ✅ | ✅ | | | | | | |
| [CompactifAI (`compactifai`)](https://docs.litellm.ai/docs/providers/compactifai) | ✅ | ✅ | ✅ | | | | | | | |
| [Custom (`custom`)](https://docs.litellm.ai/docs/providers/custom_llm_server) | ✅ | ✅ | ✅ | | | | | | | |
| [Custom OpenAI (`custom_openai`)](https://docs.litellm.ai/docs/providers/openai_compatible) | ✅ | ✅ | ✅ | | | ✅ | ✅ | ✅ | ✅ | |
| [Dashscope (`dashscope`)](https://docs.litellm.ai/docs/providers/dashscope) | ✅ | ✅ | ✅ | ✅ | | | | | | ✅ |
| [Databricks (`databricks`)](https://docs.litellm.ai/docs/providers/databricks) | ✅ | ✅ | ✅ | | | | | | | |
| [DataRobot (`datarobot`)](https://docs.litellm.ai/docs/providers/datarobot) | ✅ | ✅ | ✅ | | | | | | | |
| [Deepgram (`deepgram`)](https://docs.litellm.ai/docs/providers/deepgram) | ✅ | ✅ | ✅ | | | ✅ | | | | |
| [DeepInfra (`deepinfra`)](https://docs.litellm.ai/docs/providers/deepinfra) | ✅ | ✅ | ✅ | | | | | | | |
| [Deepseek (`deepseek`)](https://docs.litellm.ai/docs/providers/deepseek) | ✅ | ✅ | ✅ | | | | | | | |
| [ElevenLabs (`elevenlabs`)](https://docs.litellm.ai/docs/providers/elevenlabs) | ✅ | ✅ | ✅ | | | ✅ | ✅ | | | |
| [Empower (`empower`)](https://docs.litellm.ai/docs/providers/empower) | ✅ | ✅ | ✅ | | | | | | | |
| [Fal AI (`fal_ai`)](https://docs.litellm.ai/docs/providers/fal_ai) | ✅ | ✅ | ✅ | | ✅ | | | | | |
| [Featherless AI (`featherless_ai`)](https://docs.litellm.ai/docs/providers/featherless_ai) | ✅ | ✅ | ✅ | | | | | | | |
| [Fireworks AI (`fireworks_ai`)](https://docs.litellm.ai/docs/providers/fireworks_ai) | ✅ | ✅ | ✅ | | | | | | | |
| [FriendliAI (`friendliai`)](https://docs.litellm.ai/docs/providers/friendliai) | ✅ | ✅ | ✅ | | | | | | | |
| [Galadriel (`galadriel`)](https://docs.litellm.ai/docs/providers/galadriel) | ✅ | ✅ | ✅ | | | | | | | |
| [GitHub Copilot (`github_copilot`)](https://docs.litellm.ai/docs/providers/github_copilot) | ✅ | ✅ | ✅ | ✅ | | | | | | |
| [GitHub Models (`github`)](https://docs.litellm.ai/docs/providers/github) | ✅ | ✅ | ✅ | | | | | | | |
| [Google - PaLM](https://docs.litellm.ai/docs/providers/palm) | ✅ | ✅ | ✅ | | | | | | | |
| [Google - Vertex AI (`vertex_ai`)](https://docs.litellm.ai/docs/providers/vertex) | ✅ | ✅ | ✅ | ✅ | ✅ | | | | | |
| [Google AI Studio - Gemini (`gemini`)](https://docs.litellm.ai/docs/providers/gemini) | ✅ | ✅ | ✅ | | | | | | | |
| [GradientAI (`gradient_ai`)](https://docs.litellm.ai/docs/providers/gradient_ai) | ✅ | ✅ | ✅ | | | | | | | |
| [Groq AI (`groq`)](https://docs.litellm.ai/docs/providers/groq) | ✅ | ✅ | ✅ | | | | | | | |
| [Heroku (`heroku`)](https://docs.litellm.ai/docs/providers/heroku) | ✅ | ✅ | ✅ | | | | | | | |
| [Hosted VLLM (`hosted_vllm`)](https://docs.litellm.ai/docs/providers/vllm) | ✅ | ✅ | ✅ | | | | | | | |
| [Huggingface (`huggingface`)](https://docs.litellm.ai/docs/providers/huggingface) | ✅ | ✅ | ✅ | ✅ | | | | | | ✅ |
| [Hyperbolic (`hyperbolic`)](https://docs.litellm.ai/docs/providers/hyperbolic) | ✅ | ✅ | ✅ | | | | | | | |
| [IBM - Watsonx.ai (`watsonx`)](https://docs.litellm.ai/docs/providers/watsonx) | ✅ | ✅ | ✅ | ✅ | | | | | | |
| [Infinity (`infinity`)](https://docs.litellm.ai/docs/providers/infinity) | | | | ✅ | | | | | | |
| [Jina AI (`jina_ai`)](https://docs.litellm.ai/docs/providers/jina_ai) | | | | ✅ | | | | | | |
| [Lambda AI (`lambda_ai`)](https://docs.litellm.ai/docs/providers/lambda_ai) | ✅ | ✅ | ✅ | | | | | | | |
| [Lemonade (`lemonade`)](https://docs.litellm.ai/docs/providers/lemonade) | ✅ | ✅ | ✅ | | | | | | | |
| [LiteLLM Proxy (`litellm_proxy`)](https://docs.litellm.ai/docs/providers/litellm_proxy) | ✅ | ✅ | ✅ | ✅ | ✅ | | | | | |
| [Llamafile (`llamafile`)](https://docs.litellm.ai/docs/providers/llamafile) | ✅ | ✅ | ✅ | | | | | | | |
| [LM Studio (`lm_studio`)](https://docs.litellm.ai/docs/providers/lm_studio) | ✅ | ✅ | ✅ | | | | | | | |
| [Maritalk (`maritalk`)](https://docs.litellm.ai/docs/providers/maritalk) | ✅ | ✅ | ✅ | | | | | | | |
| [Meta - Llama API (`meta_llama`)](https://docs.litellm.ai/docs/providers/meta_llama) | ✅ | ✅ | ✅ | | | | | | | |
| [Mistral AI API (`mistral`)](https://docs.litellm.ai/docs/providers/mistral) | ✅ | ✅ | ✅ | ✅ | | | | | | |
| [ModelScope (`modelscope`)](https://docs.litellm.ai/docs/providers/modelscope) | ✅ | ✅ | ✅ | | ✅ | | | | | |
| [Moonshot (`moonshot`)](https://docs.litellm.ai/docs/providers/moonshot) | ✅ | ✅ | ✅ | | | | | | | |
| [Morph (`morph`)](https://docs.litellm.ai/docs/providers/morph) | ✅ | ✅ | ✅ | | | | | | | |
| [Nebius AI