[![PyPI](https://img.shields.io/pypi/v/pipecat-ai)](https://pypi.org/project/pipecat-ai) ![Tests](https://github.com/pipecat-ai/pipecat/actions/workflows/tests.yaml/badge.svg) [![codecov](https://codecov.io/gh/pipecat-ai/pipecat/graph/badge.svg?token=LNVUIVO4Y9)](https://codecov.io/gh/pipecat-ai/pipecat) [![Docs](https://img.shields.io/badge/Documentation-blue)](https://docs.pipecat.ai) [![Discord](https://img.shields.io/discord/1239284677165056021)](https://discord.gg/pipecat) [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/pipecat-ai/pipecat)

# 🎙️ Pipecat: Real-Time Voice & Multimodal AI Agents

**Pipecat** is an open-source Python framework for building real-time voice and multimodal conversational agents. Build a single voice agent or a full multi-agent system where specialists hand off, fan out in parallel, and coordinate over a shared bus, locally or distributed across processes and machines. Orchestrate audio and video, AI services, transports, and conversation pipelines effortlessly, so you can focus on what makes your agents unique.

> Want to dive right in? Run `pipecat init quickstart` or follow the [quickstart guide](https://docs.pipecat.ai/getting-started/quickstart).

## 🚀 What you can build

- **Voice Assistants** – natural, streaming conversations with AI
- **Multi-Agent Systems** – specialists that hand off, fan out in parallel, or run as sidecars over a shared bus
- **AI Companions** – coaches, meeting assistants, characters
- **Multimodal Interfaces** – voice, video, images, and more
- **Interactive Storytelling** – creative tools with generative media
- **Business Agents** – customer intake, support bots, guided flows
- **Complex Dialog Systems** – design logic with structured conversations

## 🧠 Why Pipecat?

- **Voice-first**: Integrates speech recognition, text-to-speech, and conversation handling
- **Pluggable**: Supports many AI services and tools
- **Composable Pipelines**: Build complex behavior from modular components
- **Multi-Agent Ready**: Each pipeline is an agent. Compose them with handoff, parallel fan-out, sidecar workers, or distributed deployments
- **Real-Time**: Ultra-low latency interaction with different transports (e.g. WebSockets or WebRTC)

## 🌐 Pipecat ecosystem

### 📱 Client SDKs

Building client applications? You can connect to Pipecat from any platform using our official SDKs:

JavaScript | React | React Native |
Swift | Kotlin | C++ | ESP32

### 🧭 Structured conversations

Need predefined or dynamic conversation paths with state management? [Pipecat Flows](https://docs.pipecat.ai/guides/features/pipecat-flows) is built into Pipecat. Browse the [examples](https://github.com/pipecat-ai/pipecat/tree/main/examples/flows) to see it in action.

### 🪄 Beautiful UIs

Want to build beautiful and engaging experiences? Checkout the [Voice UI Kit](https://github.com/pipecat-ai/voice-ui-kit), a collection of components, hooks and templates for building voice AI applications quickly.

### 🛠️ Create and deploy projects

The [Pipecat CLI](https://docs.pipecat.ai/api-reference/cli/overview) ships with `pipecat-ai` — install it with `uv tool install "pipecat-ai[cli]"`. Run `pipecat init` to start a project: it sets you up so an AI coding assistant (Claude Code, Codex) builds it for you, and can scaffold a runnable bot in under a minute. Then use the CLI to monitor and deploy your agent to production.

### 🔍 Debugging

Looking for help debugging your pipeline and processors? Check out [Whisker](https://github.com/pipecat-ai/whisker), a real-time Pipecat debugger.

### 🖥️ Terminal

Love terminal applications? Check out [Tail](https://github.com/pipecat-ai/tail), a terminal dashboard for Pipecat.

### 🤖 Claude Code skills

Use [Pipecat Skills](https://github.com/pipecat-ai/skills) with [Claude Code](https://claude.ai/code) to scaffold projects, deploy to Pipecat Cloud, and more. Install the marketplace with:

```
claude plugin marketplace add pipecat-ai/skills
```

and install any of the available plugins.

### 🧩 Community integrations

Build and share your own Pipecat service integrations! Browse existing [community integrations](https://docs.pipecat.ai/api-reference/server/services/supported-services) or check out our [guide](COMMUNITY_INTEGRATIONS.md) to create your own.

### 📺️ Pipecat TV channel

Catch new features, interviews, and how-tos on our [Pipecat TV](https://www.youtube.com/playlist?list=PLzU2zoMTQIHjqC3v4q2XVSR3hGSzwKFwH) channel.

## 🎬 See it in action

## 🧩 Available services

| Category | Services |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Speech-to-Text | [AssemblyAI](https://docs.pipecat.ai/api-reference/server/services/stt/assemblyai), [AWS](https://docs.pipecat.ai/api-reference/server/services/stt/aws), [Azure](https://docs.pipecat.ai/api-reference/server/services/stt/azure), [Cartesia](https://docs.pipecat.ai/api-reference/server/services/stt/cartesia), [Deepgram](https://docs.pipecat.ai/api-reference/server/services/stt/deepgram), [ElevenLabs](https://docs.pipecat.ai/api-reference/server/services/stt/elevenlabs), [Fal Wizper](https://docs.pipecat.ai/api-reference/server/services/stt/fal), [FunASR](https://docs.pipecat.ai/api-reference/server/services/stt/funasr), [Gladia](https://docs.pipecat.ai/api-reference/server/services/stt/gladia), [Google](https://docs.pipecat.ai/api-reference/server/services/stt/google), [Gradium](https://docs.pipecat.ai/api-reference/server/services/stt/gradium), [Groq (Whisper)](https://docs.pipecat.ai/api-reference/server/services/stt/groq), [Mistral](https://docs.pipecat.ai/api-reference/server/services/stt/mistral), [Moonshine](https://docs.pipecat.ai/api-reference/server/services/stt/moonshine), [NVIDIA](https://docs.pipecat.ai/api-reference/server/services/stt/nvidia), [OpenAI (Whisper)](https://docs.pipecat.ai/api-reference/server/services/stt/openai), [Sarvam](https://docs.pipecat.ai/api-reference/server/services/stt/sarvam), [Soniox](https://docs.pipecat.ai/api-reference/server/services/stt/soniox), [Speechmatics](https://docs.pipecat.ai/api-reference/server/services/stt/speechmatics), [Together](https://docs.pipecat.ai/api-reference/server/services/stt/together), [Whisper](https://docs.pipecat.ai/api-reference/server/services/stt/whisper), [xAI](https://docs.pipecat.ai/api-reference/server/services/stt/xai) |
| LLMs | [Anthropic](https://docs.pipecat.ai/api-reference/server/services/llm/anthropic), [AWS](https://docs.pipecat.ai/api-reference/server/services/llm/aws), [Azure](https://docs.pipecat.ai/api-reference/server/services/llm/azure), [Baseten](https://docs.pipecat.ai/api-reference/server/services/llm/baseten), [Cerebras](https://docs.pipecat.ai/api-reference/server/services/llm/cerebras), [Crusoe](https://docs.pipecat.ai/api-reference/server/services/llm/crusoe), [DeepSeek](https://docs.pipecat.ai/api-reference/server/services/llm/deepseek), [Fireworks AI](https://docs.pipecat.ai/api-reference/server/services/llm/fireworks), [Gemini](https://docs.pipecat.ai/api-reference/server/services/llm/gemini), [Grok](https://docs.pipecat.ai/api-reference/server/services/llm/grok), [Groq](https://docs.pipecat.ai/api-reference/server/services/llm/groq), [Inception](https://docs.pipecat.ai/api-reference/server/services/llm/inception), [Mistral](https://docs.pipecat.ai/api-reference/server/services/llm/mistral), [Nebius](https://docs.pipecat.ai/api-reference/server/services/llm/nebius), [Novita](https://docs.pipecat.ai/api-reference/server/services/llm/novita), [NVIDIA NIM](https://docs.pipecat.ai/api-reference/server/services/llm/nvidia), [Ollama](https://docs.pipecat.ai/api-reference/server/services/llm/ollama), [OpenAI](https://docs.pipecat.ai/api-reference/server/services/llm/openai), [OpenAI Responses](https://docs.pipecat.ai/api-reference/server/services/llm/openai-responses), [OpenRouter](https://docs.pipecat.ai/api-reference/server/services/llm/openrouter), [Perplexity](https://docs.pipecat.ai/api-reference/server/services/llm/perplexity), [Qwen](https://docs.pipecat.ai/api-reference/server/services/llm/qwen), [SambaNova](https://docs.pipecat.ai/api-reference/server/services/llm/sambanova), [Sarvam](https://docs.pipecat.ai/api-reference/server/services/llm/sarvam), [Together AI](https://docs.pipecat.ai/api-reference/server/services/llm/together) |
| Text-to-Speech | [Async](https://docs.pipecat.ai/api-reference/server/services/tts/asyncai), [AWS](https://docs.pipecat.ai/api-reference/server/services/tts/aws), [Azure](https://docs.pipecat.ai/api-reference/server/services/tts/azure), [Bland](https://docs.pipecat.ai/api-reference/server/services/tts/bland), [Camb AI](https://docs.pipecat.ai/api-reference/server/services/tts/camb), [Cartesia](https://docs.pipecat.ai/api-reference/server/services/tts/cartesia), [Deepgram](https://docs.pipecat.ai/api-reference/server/services/tts/deepgram), [ElevenLabs](https://docs.pipecat.ai/api-reference/server/services/tts/elevenlabs), [Fish](https://docs.pipecat.ai/api-reference/server/services/tts/fish), [Google](https://docs.pipecat.ai/api-reference/server/services/tts/google), [Gradium](https://docs.pipecat.ai/api-reference/server/services/tts/gradium), [Groq](https://docs.pipecat.ai/api-reference/server/services/tts/groq), [Hume](https://docs.pipecat.ai/api-reference/server/services/tts/hume), [Inworld](https://docs.pipecat.ai/api-reference/server/services/tts/inworld), [Kokoro](https://docs.pipecat.ai/api-reference/server/services/tts/kokoro), [LMNT](https://docs.pipecat.ai/api-reference/server/services/tts/lmnt), [MiniMax](https://docs.pipecat.ai/api-reference/server/services/tts/minimax), [Mistral](https://docs.pipecat.ai/api-reference/server/services/tts/mistral), [Neuphonic](https://docs.pipecat.ai/api-reference/server/services/tts/neuphonic), [NVIDIA](https://docs.pipecat.ai/api-reference/server/services/tts/nvidia), [OpenAI](https://docs.pipecat.ai/api-reference/server/services/tts/openai), [Piper](https://docs.pipecat.ai/api-reference/server/services/tts/piper), [Resemble](https://docs.pipecat.ai/api-reference/server/services/tts/resemble), [Rime](https://docs.pipecat.ai/api-reference/server/services/tts/rime), [Sarvam](https://docs.pipecat.ai/api-reference/server/services/tts/sarvam), [Smallest](https://docs.pipecat.ai/api-reference/server/services/tts/smallest), [Soniox](https://docs.pipecat.ai/api-reference/server/services/tts/soniox), [Speechify](https://docs.pipecat.ai/api-reference/server/services/tts/speechify), [Speechmatics](https://docs.pipecat.ai/api-reference/server/services/tts/speechmatics), [Together](https://docs.pipecat.ai/api-reference/server/services/tts/together), [xAI](https://docs.pipecat.ai/api-reference/server/services/tts/xai), [XTTS](https://docs.pipecat.ai/api-reference/server/services/tts/xtts) |
| Speech-to-Speech | [AWS Nova Sonic](https://docs.pipecat.ai/api-reference/server/services/s2s/aws), [Gemini Multimodal Live](https://docs.pipecat.ai/api-reference/server/services/s2s/gemini), [Grok Voice Agent](https://docs.pipecat.ai/api-reference/server/services/s2s/grok), [OpenAI Realtime](https://docs.pipecat.ai/api-reference/server/services/s2s/openai), [Ultravox](https://docs.pipecat.ai/api-reference/server/services/s2s/ultravox), |
| Transport | [Daily (WebRTC)](https://docs.pipecat.ai/api-reference/server/services/transport/daily), [FastAPI Websocket](https://docs.pipecat.ai/api-reference/server/services/transport/fastapi-websocket), [LiveKit (WebRTC)](https://docs.pipecat.ai/api-reference/server/services/transport/livekit), [SmallWebRTCTransport](https://docs.pipecat.ai/api-reference/server/services/transport/small-webrtc), [Vonage (WebRTC)](https://docs.pipecat.ai/api-reference/server/services/transport/vonage),