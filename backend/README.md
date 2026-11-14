# Configurable LiveKit voice backend

Python 3.13 / LiveKit Agents 1.8.12. One agent, one configured STT → LLM → TTS
pipeline. All provider credentials stay in `backend/.env` or process environment.
The existing Next.js frontend uses the worker's real tool events and confirmation RPC.

See [tool orchestration](../docs/tool-orchestration.md) for tool definitions, permissions,
confirmation, idempotency, cancellation, workflows and the use-case extension guide.

Optional MCP uses the official SDK and LiveKit integration; see [MCP setup](../docs/mcp.md).
It is disabled by default and is not a speech or LLM provider. Install with
`uv sync --locked --extra mcp --group dev` and use `uv run --extra mcp` when enabled.

## Windows setup

From the repository root in PowerShell:

```powershell
winget install --id astral-sh.uv --exact
# Reopen PowerShell if uv was newly installed.
cd backend
uv python install 3.13
uv sync --locked
Copy-Item .env.example .env  # Only when .env does not already exist.
notepad .env
# Fill credentials, save, and prepare local model assets:
uv run python -m livekit.agents download-files
uv run python -m app.main dev
```

No environment activation or execution-policy change is needed. Production SDK
startup is `uv run python -m app.main start`.

## Configuration

Configuration uses environment variables (no YAML loader is needed). Process
variables override `backend/.env`. Optional blank values use provider defaults.
Restart the worker after changes. Never use NEXT*PUBLIC* for credentials.
`backend/.env` and environment variants are ignored by Git.

Always required: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.
Default selection:

```dotenv
STT_PROVIDER=deepgram
LLM_PROVIDER=openai_compatible
TTS_PROVIDER=cartesia
DEEPGRAM_API_KEY=your-key
LLM_API_KEY=your-key
CARTESIA_API_KEY=your-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4.1-mini
```

Only selected provider credentials are required:

- STT `deepgram`: `DEEPGRAM_API_KEY`; default `nova-3`.
- STT `assemblyai`: `ASSEMBLYAI_API_KEY`; default `universal-3-6-pro`.
- STT `whisper`: `OPENAI_API_KEY`; model `whisper-1` via OpenAI's REST API.
- LLM `openai_compatible`: `LLM_API_KEY`; legacy `OPENAI_API_KEY` fallback.
- LLM `gemini`: `GOOGLE_API_KEY`; default `gemini-3.5-flash` via Google API.
- TTS `cartesia`: `CARTESIA_API_KEY`; default `sonic-3`.
- TTS `elevenlabs`: `ELEVEN_API_KEY`; default `eleven_multilingual_v2`.
- TTS `murf`: `MURF_API_KEY`; default `FALCON` using the official streaming plugin.

`STT_MODEL`, `LLM_MODEL`, `TTS_MODEL`, and `TTS_VOICE` override the registry's
defaults. Clear old model and voice overrides when switching vendors. Voice IDs
must be accessible to your account. `STT_LANGUAGE` defaults to `en`; AssemblyAI
Universal-3 Pro receives it as a language hint. Other AssemblyAI streaming models
infer language from their model selection. `STT_BASE_URL` is supported only for
the batch Whisper REST integration; compatibility of other Whisper servers must
be tested. Gemini uses its native plugin, so clear `LLM_BASE_URL` when selecting it.
These adapters do not expose TTS_BASE_URL; unsupported URL settings raise errors.

`AGENT_INSTRUCTIONS` overrides `app/agents/instructions.py`. `AGENT_NAME` controls
dispatch. Blank uses automatic dispatch; for named dispatch, use the same name in
the frontend's root `.env.local` and backend `.env`.

## NVIDIA NIM, vLLM, and compatible LLM endpoints

Use the existing `openai_compatible` provider, with no changes to the agent:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://localhost:8000/v1
LLM_API_KEY=your-endpoint-key
LLM_MODEL=your-served-model-name
```

For hosted NIM, use the base URL, API key, and exact model ID supplied by your
deployment. A custom base URL requires an explicit model; there is no assumption
that it serves the default OpenAI model. A local endpoint that has authentication
disabled still needs a nonempty client key (for example `not-used`) because the
OpenAI client expects one. Set this deliberately; no key is fabricated by code.

The endpoint must implement streaming Chat Completions. Model names, chat
templates, tool parsers, tool calling, languages, usage chunks, and cancellation
semantics depend on the deployed server/model. Merely sharing the OpenAI API
format does not guarantee all of these. Other compatible services can use the
same path after their endpoint behavior is verified.

## Capabilities and batch STT

`app/providers/registry.py` records native streaming, interim transcription,
provider turn detection, multilingual support, local cancellation, and tool
calling. `None` means model/endpoint dependent or not applicable, never a promise
of support. The metadata describes these adapters, not every product from a vendor.
`registry.require(category, provider, capability)` rejects false or unknown
capabilities. Native SDK capabilities are checked when an interim requirement is set.

- Deepgram Nova and AssemblyAI use native streaming STT and interim results.
- AssemblyAI exposes provider end-of-turn detection; set `TURN_DETECTION=stt`
  to use it. Universal-3 Pro's silence setting is explicitly set to 1000 ms, and
  the session avoids additive minimum endpointing delay in STT mode.
- The current Nova adapter uses `TURN_DETECTION=vad`; it does not claim semantic
  turn detection from Deepgram Flux. Flux would need a separate verified adapter.
- Whisper is **batch-only**. Set `STT_ALLOW_BATCH=true` to permit LiveKit's
  `StreamAdapter` with Silero VAD. It sends completed utterances for recognition,
  with no interim transcripts and added utterance latency. The registry continues
  to report native `streaming=False`; the adapter does not change that fact.
- `STT_REQUIRE_INTERIM=true` rejects Whisper. `TURN_DETECTION=stt` also rejects
  providers that do not guarantee it. Default turn detection is `vad`.
- Cartesia, ElevenLabs, and Murf use native streaming TTS. Multilingual behavior
  depends on the selected model, voice, and language; it is not a universal flag.
- Native LLM objects retain tool-call chunks. Whether a selected model/endpoint
  can correctly generate them remains model dependent. No tools are registered yet.
- Cancellation means local stream/task cancellation via LiveKit APIs. It does
  not promise that remote inference or billing immediately stops.

The SDK's own STT/LLM/TTS interfaces, event emitters, retries, metrics, and stream
lifecycles are preserved. There is no custom buffering or text-only wrapper.

## Frontend connection

Use the same LiveKit project in frontend and backend. Root `.env.local` needs
`LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET`. The frontend always
uses its existing development-only `/api/token`; it does not use
`LIVEKIT_TOKEN_SERVER_ID` or fall back to the public demo. Missing configuration
returns 503; token issuance outside development returns 403. The server sets
named dispatch from its own `AGENT_NAME`. Restart both after configuration.
Run `uv run python -m app.check_setup` from backend to compare local configuration
without printing secrets. See the root README for the full two-process checklist.

In a second PowerShell window, from the repository root:

```powershell
# Frontend requires Node 24 and pnpm 9.15.9.
pnpm install --frozen-lockfile
pnpm dev
```

Open http://localhost:3000, start a call, allow the microphone, ask a short
question, and check worker dispatch, transcription, a relevant spoken answer,
interruption behavior, and disconnect. Provider credentials and network access
are required; actual inference can incur charges.

## Checks

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Tests cover registration, duplicate/unsupported selection, defaults, credentials,
URL validation, capabilities, real plugin construction, native event interfaces,
session composition, and Windows callback serialization. They use synthetic keys
and never make inference requests. End-to-end voice and provider account access
must be verified separately with real credentials.

## Structure and extension pattern

`app/providers/stt/`, `llm/`, and `tts/` contain thin native-plugin constructors.
`registry.py` is the explicit supported-provider catalog, with defaults,
credential variable names, capability metadata, builder paths, and official links.
`factory.py` resolves that catalog, validates the interface, and constructs the
selected plugin. `pipeline.py` composes vendor-independent objects in AgentSession.
`config/settings.py` resolves environment settings before accepting a job.
`agents/` holds behavior; `main.py` registers the single worker. The reserved
`tools/` and `services/` packages still start no extra components.

To add a completely new provider:

1. Verify an official maintained LiveKit plugin's installed signatures, supported
   models, native streaming/events and limitations. Add and pin its plugin dependency,
   regenerate `uv.lock` with `uv sync`, and test installation on Windows.
2. Add a constructor to the appropriate category package (or a dedicated module).
   Accept `ProviderConfig` and return the native `STT`, `LLM`, or `TTS` interface.
   If no plugin exists, implement the LiveKit base class and its stream protocol,
   including close/cancellation, metrics and event behavior, with focused tests.
3. Register a `ProviderSpec` with a unique category/name, builder import path,
   backend credential variable, defaults and honest capabilities. No config-supplied
   arbitrary Python import paths are accepted.
4. Add explicit validation for provider-specific restrictions. Do not silently
   ignore unsupported settings or convert batch recognition into a streaming claim.
5. Add selection, missing-credential, capability, constructor and stream lifecycle
   tests. Add an opt-in real-provider smoke test where credentials are available.
6. Document configuration and limitations here and in `.env.example`. Agent and
   business logic should require no changes.

This uses a registry and factory with dependency injection into LiveKit's session,
and thin adapters around existing plugins. It deliberately avoids inventing a
parallel provider SDK or replacing LiveKit's event and transport abstractions.

## Official references

- [LiveKit Python starter](https://github.com/livekit-examples/agent-starter-python)
- [Deepgram](https://docs.livekit.io/agents/models/stt/deepgram/)
- [AssemblyAI](https://docs.livekit.io/agents/models/stt/assemblyai/)
- [OpenAI STT / Whisper](https://docs.livekit.io/agents/models/stt/openai/)
- [OpenAI-compatible LLM plugin](https://docs.livekit.io/agents/models/llm/openai/)
- [Gemini](https://docs.livekit.io/agents/models/llm/gemini/)
- [Cartesia](https://docs.livekit.io/agents/models/tts/cartesia/)
- [ElevenLabs](https://docs.livekit.io/agents/models/tts/elevenlabs/)
- [Murf](https://docs.livekit.io/agents/models/tts/murf/)
- [NIM Chat Completions](https://docs.nvidia.com/nim/large-language-models/1.12.0/api-reference.html)
- [vLLM serving](https://docs.vllm.ai/en/stable/serving/online_serving/)

## Optional persistence and infrastructure

See [PostgreSQL, migrations, Redis and Windows setup](../docs/persistence.md).
Persistence and transcripts default off; Redis is independently optional.
