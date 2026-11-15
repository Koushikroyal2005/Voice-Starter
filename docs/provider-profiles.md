# Voice profiles and provider doctor

Configure keys once, then select a named voice pipeline. Everything runs with the
existing local Next.js frontend, Python worker and LiveKit server. Hosted model
APIs are still external inference services, not offline laptop models.

## Quick start (Windows PowerShell)

Keep LiveKit running locally on port 7880 and Next.js on port 3000. Do not start
duplicates. From the repository root:

```powershell
cd backend
uv sync --locked --all-extras
# Only copy if you do not already have a private env file:
if (!(Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
uv run python -m app.cli providers doctor --offline
uv run python -m app.main dev
```

The minimum backend configuration is:

```dotenv
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
AGENT_NAME=
GROQ_API_KEY=YOUR_GROQ_KEY
GOOGLE_API_KEY=YOUR_GOOGLE_AI_STUDIO_KEY
NVIDIA_API_KEY=
VOICE_PROFILE=groq_gemini
```

The frontend's root `.env.local` contains only the four matching LiveKit settings.
Never put provider keys in frontend files, `NEXT_PUBLIC_*`, catalogs or profiles.
The development token endpoint is unchanged and remains development-only.

Your existing private file may reuse previously entered keys through dotenv
aliases: `GROQ_API_KEY=${LLM_API_KEY}` after `LLM_API_KEY`, and
`NVIDIA_API_KEY=${LLM_FALLBACK_API_KEY}` after that definition. These aliases do
not enable automatic fallback. Do not delete an alias's source key until replacing
the alias privately. No real credentials are copied into examples.

## Available profiles

- `groq_gemini`: Groq Whisper `whisper-large-v3-turbo`, Groq LLM
  `openai/gpt-oss-20b`, Gemini TTS `gemini-3.8-flash-tts`, Kore voice.
  Batch STT with VAD; final-only transcription. This is the previously
  real-provider-tested roomless pipeline, not a claim of completed browser testing.
- `gemini_only`: Gemini streaming STT `gemini-3.5-transcribe-live`, Gemini LLM
  `gemini-3.5-flash`, the same Gemini TTS. Native STT interim results are required.
  Full profile inference has **not** been verified. Earlier STT testing established
  handshake access only, not transcription quality.
- `nvidia_gemini`: Groq Whisper, NVIDIA `meta/llama-3.3-70b-instruct` through the
  existing OpenAI-compatible LLM adapter, the same Gemini TTS. Needs all three
  provider keys. NVIDIA inference/tool compatibility is **not tested** here.
  Tool capability is unknown, not promised. No NVIDIA STT/TTS is registered.

Restart the worker after editing a profile or its selected name. No model listing,
account probe, infrastructure enablement or automatic fallback occurs on startup.

## Resolution and conflicts

Precedence is explicit environment overrides, selected profile, provider/model
catalog defaults, then application/use-case defaults where applicable. Shell
environment still takes precedence over the ignored `.env` file.

Without `VOICE_PROFILE`, legacy behavior stays intact, including blank-value reset
semantics, existing defaults, custom endpoints and use-case provider restrictions.
With a profile, blank provider/model/endpoint overrides mean "use the profile".
Nonblank conflicting overrides **fail closed**, listing variable names without
their values. This prevents old `STT_*`, `LLM_*`, `TTS_*` settings silently changing
a newly selected pipeline. Remove stale settings, or acknowledge intentional edits:

```dotenv
VOICE_PROFILE=groq_gemini
VOICE_PROFILE_ALLOW_OVERRIDES=true
TTS_MODEL=gemini-3.1-flash-tts-preview
TTS_VOICE=Puck
```

Acknowledged override names appear in startup warnings and offline doctor output.
Acknowledgement does not disable validation: requesting interim words from Groq
Whisper, disabling its batch opt-in or selecting an invalid model/voice still fails.
Use-case tool/language/provider restrictions also still apply.

Each vendor alias uses its declared credential: `groq` uses `GROQ_API_KEY`,
`gemini` uses `GOOGLE_API_KEY`, `nvidia` uses `NVIDIA_API_KEY`. An old generic
`LLM_API_KEY` is not silently reused for NVIDIA. The legacy `openai_compatible`
selection still uses `LLM_API_KEY` or `OPENAI_API_KEY` and supports custom
`LLM_BASE_URL` plus explicit `LLM_MODEL`, including local vLLM.

Model requirements are separate from provider selection. Google profiles derive
`GOOGLE_GENAI_API_VERSION=v1beta`; `load_settings()` applies that supported SDK
environment setting at the process boundary. Pure resolution does not mutate the
environment or construct clients. The native Google TTS plugin still manages
incremental PCM audio; its `streaming=False` means no streaming **text input**.
LiveKit continues to own sentence adaptation, interruptions and cancellation.

## Catalogs, adapters and capabilities

`backend/config/providers/*.yaml` is the single source of configurable model
metadata. It populates the **existing** `ProviderRegistry` at import. Python retains
only supported adapter wiring, not another model list. Existing Deepgram,
AssemblyAI, OpenAI Whisper, generic OpenAI-compatible, Cartesia, ElevenLabs and
Murf defaults were migrated unchanged alongside Groq, Gemini and NVIDIA catalogs.

Each category declares an adapter, `api_key_env`, defaults, optional LLM endpoint,
and model entries with their own capabilities and voice/language/API requirements.
Provider-wide unknown capabilities remain unknown. Model-specific declarations
win during validation; catalogued support does not establish account access.
STT/TTS transport endpoints remain owned by their existing adapters. Generic LLM
catalog entries preserve explicitly configured non-catalogued model support;
their capabilities are conservative and inference must be verified separately.

YAML is local, reviewed application configuration: no remote loading, executable
tags, arbitrary imports, duplicate keys, aliases or secret fields. Profiles only
configure STT/LLM/TTS and turn detection; they cannot enable MCP, databases, Redis
or add tools. Files are size-limited and errors omit raw YAML validation inputs.

Legacy `LLM_FALLBACK_*` (and STT/TTS equivalents) remain independent. A backup
requires its own explicit key, compatible language and operator acknowledgement
via `*_FALLBACK_COMPATIBLE=true`. Batch-only providers are still rejected as
realtime fallbacks. Doctor inference checks test primary stages, not failover.

## Diagnostics: offline first, live only when you opt in

```powershell
# No network; checks YAML, keys, endpoint syntax and model/capability compatibility:
uv run python -m app.cli providers doctor --offline

# OPTIONAL: billable requests; only run when you want to test real provider access:
uv run python -m app.cli providers doctor --live

# OPTIONAL: use your own consented <=15-second mono 16-bit PCM, 16 kHz WAV for STT:
uv run python -m app.cli providers doctor --live --wav 'C:\audio\sample.wav'
```

Offline mode is the default. It reports `configuration_valid_inference_not_tested`,
never a successful authentication/inference claim. Exit status is nonzero when
configuration or credentials are invalid/missing. Placeholder keys are not treated
as configured credentials by the doctor.

Live mode bounds each stage to 15 seconds with zero LiveKit retries and closes
clients. It tests TTS first, then LLM streaming, then STT using either your supplied
WAV or the generated non-private diagnostic speech. It does not save audio, print
transcripts, echo error bodies, log keys, test tools or create browser sessions.
Native vendor retries can occur within the outer deadline. A TTS failure without
`--wav` means STT is `not_tested_no_audio`, not a fabricated pass. `--wav` is validated
before billable requests. Results identify the exact successful/failed stage;
`ready_for_browser_testing` is deliberately **not** a completed voice-call claim.

Failure codes include missing/invalid credentials, access denied, unsupported
model/options, model unavailable, `model_terms_required`, quota exceeded,
unsupported request format, timeout, network failure and capability mismatch.
HTTP 400 alone never means "invalid key". Groq Orpheus terms must be reviewed by
your organization admin; neither the doctor nor startup accepts legal terms.
Model listing alone is not an inference/access test.

## Add models, providers or hackathon profiles

1. To add a model to an existing supported provider, edit that category's catalog
   `models` mapping. Record only officially documented capabilities; use `null`
   for unknown properties. Declare voice/language restrictions and API version
   where required. Change `default_model` only deliberately, then run tests/doctor.
2. To add a vendor that really implements an existing API, add a catalog using
   that native adapter, its own credential environment reference and verified URL.
   Do not label every vendor OpenAI-compatible. New transports require a focused
   native adapter and addition to the category adapter allowlist—not a new registry.
3. Copy `config/profiles/groq_gemini.yaml` to e.g. `config/profiles/my_hackathon.yaml`,
   set `name: my_hackathon`, select providers and optional model/voice/language
   overrides, then set `VOICE_PROFILE=my_hackathon`. Keep domain rules in a use-case
   module; do not edit the orchestrator or voice UI to select models.
4. Run `uv run pytest -q`, Ruff, and offline doctor. Explicitly opt in to live
   diagnostics before claiming new account/model access or speech quality.

## Evidence and reference design

This change ran offline diagnostics and mocked inference tests only—no paid API
calls or browser acceptance test. Historical real checks for Groq Whisper,
GPT-OSS streaming/tool selection and Gemini 3.8 TTS/roomless AgentSession are in
[the first voice guide](first-voice-conversation.md). Gemini-only and NVIDIA
profiles are documented candidates, not newly verified working integrations.

The relevant PentAGI patterns were a single constructor/credential registry,
separate model catalogs, per-role defaults layered over provider defaults, and
validation before construction. Those map here to STT/LLM/TTS profiles, not
PentAGI's multiple agent roles, pricing system, UI or database-backed settings.
Sources inspected: [registry](https://github.com/vxcontrol/pentagi/blob/master/backend/pkg/providers/registry.go),
[Gemini defaults](https://github.com/vxcontrol/pentagi/blob/master/backend/pkg/providers/gemini/config.yml),
[model catalog](https://github.com/vxcontrol/pentagi/blob/master/backend/pkg/providers/gemini/models.yml),
[typed configuration](https://github.com/vxcontrol/pentagi/blob/master/backend/pkg/providers/pconfig/config.go),
and [configuration guide](https://github.com/vxcontrol/pentagi/blob/master/backend/docs/config.md).

Official provider references: [Groq STT](https://console.groq.com/docs/speech-to-text),
[Groq GPT-OSS](https://console.groq.com/docs/model/openai/gpt-oss-20b),
[Gemini speech](https://ai.google.dev/gemini-api/docs/speech-generation),
[LiveKit Gemini STT](https://docs.livekit.io/agents/models/stt/gemini/),
[NVIDIA Llama API](https://docs.api.nvidia.com/nim/reference/meta-llama-3_3-70b-instruct-infer).
