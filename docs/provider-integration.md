# Provider integration guide

Constructors return native LiveKit interfaces, preserving streams/events rather
than wrapping them in a text-only API. Offline constructor tests do not establish
account access or acoustic quality. Exact defaults are in `app/providers/registry.py`.

## Supported selections

- STT: `deepgram` (`DEEPGRAM_API_KEY`), `assemblyai` (`ASSEMBLYAI_API_KEY`), REST
  `whisper` (`OPENAI_API_KEY`). Deepgram enables interim results. AssemblyAI Pro uses
  a language hint; legacy language behavior follows model selection. Whisper here
  is **batch**: `STT_ALLOW_BATCH=true` enables native VAD segmentation, not real
  streaming or interim text.
- LLM: `openai_compatible` (`LLM_API_KEY`, legacy `OPENAI_API_KEY` fallback) and
  `gemini` (`GOOGLE_API_KEY`). Actual model/tool behavior depends on the endpoint.
- TTS: `cartesia` (`CARTESIA_API_KEY`), `elevenlabs` (`ELEVEN_API_KEY`), `murf`
  (`MURF_API_KEY`) through installed official streaming plugins.

```dotenv
STT_PROVIDER=deepgram
LLM_PROVIDER=openai_compatible
TTS_PROVIDER=cartesia
STT_LANGUAGE=en
TTS_LANGUAGE=en
```

`STT_MODEL`, `LLM_MODEL`, `TTS_MODEL`, `TTS_VOICE` override defaults; clear stale
overrides when switching vendors. Cartesia/ElevenLabs receive `TTS_LANGUAGE`
explicitly. Murf maps default `en` to `en-US`; other languages require a supported
full locale such as `es-ES` and compatible voice. Constructor forwarding is tested;
non-English speech is not claimed verified. Use-case language lists do not certify
provider/model/voice coverage.

## OpenAI-compatible NIM/vLLM and other services

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://YOUR_VERIFIED_ENDPOINT/v1
LLM_API_KEY=YOUR_BACKEND_ONLY_KEY
LLM_MODEL=YOUR_AVAILABLE_MODEL
```

Custom URLs require an explicit model. Verify streaming, tool schemas, cancellation,
error formats, quota and TLS. Local vLLM can use trusted-local HTTP. Docker Desktop
host services use `host.docker.internal`, not container `localhost`. Never put a
key in a URL or a `NEXT_PUBLIC_*` variable.

## Capabilities, fallback, retries

Registry metadata records streaming, interim text, turn detection, multilingual
support, cancellation and tools where known. `None` means model-dependent or not
guaranteed. Batch STT cannot satisfy `STT_REQUIRE_INTERIM=true`.
`TURN_DETECTION=stt` requires endpointing support; default VAD is vendor-independent.

Fallback is explicit via `*_FALLBACK_PROVIDER/API_KEY/MODEL/BASE_URL/LANGUAGE/VOICE`
and `*_FALLBACK_COMPATIBLE=true` after compatibility/residency review. Same-language,
streaming and use-case restrictions remain. Native guards prevent LLM switching
after partial text/tool output. Fallback disables outer retries and uses zero
per-provider retries to avoid multiplication. Non-fallback attempts use bounded
`PROVIDER_MAX_RETRIES` / `PROVIDER_TIMEOUT_SECONDS`. Mocked native-stream tests
verify bounds/guards; **paid-provider failover needs an actual credentialed test**.
See [observability](observability.md).

## Add another provider

1. Verify a maintained official plugin and installed-version constructor against
   official [STT](https://docs.livekit.io/agents/models/stt/),
   [LLM](https://docs.livekit.io/agents/models/llm/) or
   [TTS](https://docs.livekit.io/agents/models/tts/) docs.
2. Add its dependency/extra, lock it, and add a thin constructor in `providers/`.
3. Register accurate capabilities/key-name metadata. Keep batch distinctions and
   remote-cancellation caveats; do not mark every feature supported.
4. Test configuration, actual offline construction, deterministic streaming/fault
   behavior, then opt-in real audio before claiming support.
5. Update docs and any use-case allowlist intentionally. Normal provider additions
   must not rewrite the agent, deterministic tools, services or frontend.
