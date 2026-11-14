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

## Configuration precedence (characterized before extraction)

`load_settings()` loads `backend/.env` without overriding process environment.
`Settings.from_env(mapping)` uses that mapping alone (not process environment),
selects the use case, then overlays supplied values on its public provider defaults.
An explicit blank overrides a profile value; stripped blank provider/model/URL/
language/voice values then use the application/registry default, not the profile
value they replaced. The default providers are Deepgram, OpenAI-compatible and
Cartesia. Other provider defaults come from the registry, not this guide.

Only the selected provider's key is needed. For OpenAI-compatible LLMs, stripped
`LLM_API_KEY` wins over `OPENAI_API_KEY`; a blank generic key permits that legacy
fallback. All credential values stay backend-only and are hidden from config repr.
Missing LiveKit and primary provider credentials are aggregated in category order;
invalid provider/model/endpoint selections can fail first. Other validation errors
remain fail-fast, not one combined list of every possible configuration error.

Fallbacks are optional, one per category, evaluated in STT/LLM/TTS order. Their
provider names are case-sensitive (primary names are lowercased). A blank fallback
provider disables that fallback and ignores its other fields. Each selected fallback
requires its own nonblank `*_FALLBACK_API_KEY`; primary/vendor credentials are never
borrowed. `*_FALLBACK_COMPATIBLE` must be exactly `true`, not `TRUE` or a padded value.
Fallback model/URL/voice/language fields are independent: blank or omitted values
reset to registry/application defaults, not primary or profile values. In particular,
language defaults to `en`, so a non-English primary needs an explicit matching
fallback language. The language comparison is exact. Batch fallbacks are rejected;
STT fallbacks must also satisfy the selected interim/turn-detection requirements.
Use-case provider/language and tool/storage policies apply to primaries and fallbacks.
An explicitly empty `TOOL_ALLOWLIST` remains empty; omission selects profile defaults.

Before Opportunity 4 the flow was application configuration -> primary providers ->
infrastructure/telemetry -> each fallback overlay -> recursive `Settings.from_env()`
(including another use-case selection, all three providers and infrastructure).
Characterization tests capture the rules above before removing that recursion.

## Independent configuration Modules

The new flow keeps `Settings.from_env()` as the application assembly entry point:
select/merge the use case once -> resolve primary provider fields -> aggregate
missing primary/LiveKit credentials -> validate LiveKit URL and STT requirements ->
resolve infrastructure/telemetry once -> resolve independent fallbacks -> apply
application/use-case policies -> return Settings. No fallback calls `Settings.from_env()`.

`backend/app/config/providers.py` is a focused Module with small Interfaces:

- `resolve_provider(category, values, provider_registry=registry)` resolves one
  category's fields/credentials using registry metadata. It does not read process
  environment or require LiveKit credentials. Application assembly can supply a
  missing-key collector to preserve the existing aggregated error order.
- `resolve_stt_requirements(values, config, provider_registry=registry)` checks the
  selected STT's batch/interim/turn requirements. It is separate from field resolution
  to preserve application validation precedence, and is also used for STT fallbacks.
- `resolve_fallbacks(values, primary_providers, provider_registry=registry)` resolves
  only enabled backup categories, through that same field resolver. A standalone
  LLM backup requires only its own fields and the resolved primary LLM's language,
  not PostgreSQL, Redis, telemetry, LiveKit, STT or a use-case registry.

`config/validation.py` holds shared scalar validation/error formatting so this
Module does not import `settings.py` and reintroduce a dependency cycle. This is
a concrete Seam for isolated tests, not a generic configuration framework.
The provider registry remains the sole owner of models/capability metadata; native
LiveKit Adapters and the fallback runtime are unchanged.

Existing imports of `ProviderConfig`, `ConfigurationError`, `validate_url` and
`boolean` from `config.settings` remain valid through imports/re-exports. The
`Settings.parse_fallbacks()` compatibility method is now only a delegate.
Standalone resolution does not apply application authorization policies: normal
worker startup must still use `Settings.from_env()`/`load_settings()`.

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

For an operator-provided NVIDIA NIM-compatible endpoint (illustrative placeholders,
not a verified deployment or an assertion of support for every NIM model):

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://YOUR_NIM_HOST/v1
LLM_API_KEY=YOUR_NIM_BACKEND_KEY
LLM_MODEL=YOUR_SERVED_NIM_MODEL_ID
```

For a separately reviewed OpenAI-compatible backup:

```dotenv
LLM_FALLBACK_PROVIDER=openai_compatible
LLM_FALLBACK_API_KEY=YOUR_BACKUP_BACKEND_KEY
LLM_FALLBACK_BASE_URL=https://YOUR_BACKUP_HOST/v1
LLM_FALLBACK_MODEL=YOUR_BACKUP_MODEL_ID
LLM_FALLBACK_LANGUAGE=en
# Set only after actually reviewing this endpoint/model for the application.
LLM_FALLBACK_COMPATIBLE=true
```

These settings pass through the existing OpenAI-compatible Adapter. They do not
prove that an arbitrary server supports streaming, tool calling, cancellation,
language coverage or safe fallback. Verify those features with the exact served
model and account. Registry `None` capability values remain explicitly unknown.

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
   Add provider-specific configuration checks in `config/providers.py` only when
   genuinely needed; do not copy the application assembly or fallback parser.

## Configuration errors and verification

Missing selected primary keys use the existing aggregate message with variable
names only. Selected backup keys are mandatory even if a vendor or primary key
is present, and backup key/compatibility errors remain fail-fast in category order.
Invalid model and endpoint messages do not echo the configured value. Unsupported
provider messages now omit the untrusted selection value too, while listing the
registry's supported names. This diagnostic redaction is the only intentional
message change; primary failures remain `ConfigurationError`, unsupported fallback
lookups retain `ProviderError`. Never log the input environment or serialized
configuration containing secrets; `repr=False` does not sanitize `asdict()`.

Configuration tests use synthetic credentials and injected registry metadata.
They check primary/backup field equivalence, blank values, profile overrides,
dedicated keys, capability/language gates, aggregation and secret-safe diagnostics.
Isolation checks make application parsers fail if called by a fallback, assert
one use-case/infrastructure/telemetry resolution even with three backups, and
import the provider Module in a fresh Python process without LiveKit/SQLAlchemy/
Redis/application settings being imported.

```powershell
cd backend
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
```

The existing mocked native-stream tests still cover retry bounds and the prohibition
on fallback after partial LLM output. No new real-provider compatibility or paid
failover claims are made by this configuration-only refactoring.

Retained limitations: primary/fallback provider-name case handling and the exact
compatibility acknowledgement syntax intentionally remain asymmetric. There is
one fallback slot per category, not an arbitrary chain. Registry model lists are
validated where present; other model IDs and real endpoint features still need
account-specific verification. These are not broadened in Opportunity 4.

Opportunity 4 verification (15 November 2026): 126 focused characterization tests
passed before extraction. The completed backend suite passed **313 tests, 10 skipped**,
including 54 new configuration cases. Skips were the PostgreSQL/Redis service checks
and opt-in voice integration cases. Ruff lint and format checks passed (91 files);
both root contract generation/fixture agreement checks and `git diff --check` passed.
The frontend, provider runtime and registry metadata were not modified. Real provider
requests and paid failover were not performed.
