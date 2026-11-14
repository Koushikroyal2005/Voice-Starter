# Voice reliability and observability

## Quick start (PowerShell)

```powershell
cd 'E:\voice agent starter\voice-agent-starter\backend'
uv sync --extra mcp --extra telemetry
# Optional: OTLP HTTP collector. Omit to keep custom logs without remote export.
$env:VOICE_OTLP_ENDPOINT = 'http://localhost:4318/v1/traces'
# Optional; prints a loopback-only per-job metrics port in JSON logs:
$env:PROMETHEUS_ENABLED = 'true'
# Optional backend secret, from your own Sentry project (never commit it):
# $env:SENTRY_DSN = 'your-private-project-dsn'
uv run python -m app.observability.health
uv run python -m app.main dev
```

`uv sync` alone supports JSON logs and OpenTelemetry; `--extra telemetry` installs
Prometheus and Sentry clients. Neither collector, Prometheus nor Sentry is required
for voice startup. Exports use bounded queues/timeouts; telemetry is not a durable
audit log. Keep exporters/collectors on trusted networks and configure access/TLS.
Exporter authentication uses standard OTLP environment settings, not browser code.

`session_id` is the orchestrator's conversation UUID, shared with persistence.
`request_id` is the LiveKit job ID (or session ID when no job ID is available),
not an HTTP token-request ID. `turn_id` is a generated voice-turn UUID;
`tool_call_id` is LiveKit's native function call ID. JSON logs and custom spans use
these identifiers. Native LiveKit spans receive session metadata, preserving the
SDK's real provider/turn timeline. Custom spans are **observation records**, with
`duration_seconds` attributes, not reconstructed timeline bars.

Application logs allowlist metadata fields and omit exception dumps. Custom events
never export transcript, prompt, tool arguments/results, credentials or user identity.
LiveKit's custom tracer provider is installed before session start with
`allow_pii=False`; cloud session recording is explicitly `record=False`. Review
project-level LiveKit and provider retention/logging separately. The JSON formatter
is for `voice-starter.*` logs, not a claim to sanitize every third-party logger.
Do not enable SDK/provider debug payload logging in a private deployment.

## Timing definitions (seconds)

- `user_speech_start`: receipt of LiveKit's VAD/user-speaking event. This is not
  the physical microphone onset before capture/network/VAD processing.
- `stt_interim`: first interim transcript event minus observed VAD speech start.
- `stt_final_from_speech_start`: first final STT segment minus observed speech start.
  A segment can finalize before a long utterance ends; this is not endpointing.
- `stt_final`: SDK `ChatMessage.metrics.transcription_delay`, measured after end
  of user speech. This is the final-turn transcription delay.
- `end_of_turn`: SDK `end_of_turn_delay`, last speech to endpointing decision.
- `llm_ttft`: SDK `llm_node_ttft`, node start to first text token.
- `tts_first_audio`: SDK `tts_node_ttfb`, first text delivered to TTS to first audio.
- `tool_execution`: monotonic running-to-terminal duration; excludes human approval
  waiting. Denied/replayed calls without a running stage have no duration.
- `response_first_audio`: SDK `e2e_latency`, end of user speech to agent output start.
- `full_turn`: SDK assistant output end minus corresponding user speech end;
  interrupted turns are labeled separately.
- `interruption_stop`: observed user barge-in to agent leaving speaking state.
  `interruption_rpc` is explicit interrupt request to SDK interrupt completion.

SDK turn metrics arrive when history items are committed, not necessarily at the
instant audio first arrives. Native traces show in-flight work. Assistant turns
are matched using the SDK's end-of-user-speech anchor; ambiguous/missing matches
are session-correlated only rather than assigned to the latest user by guesswork.
No transcript or provider request payload is needed for this matching. Text-only
input, unvoiced output and failures may legitimately lack audio-stage metrics.
Missing/negative metrics are not silently recorded as zero.

Default room output timing does **not** include browser network/jitter buffer/device
playout. Do not call these measurements microphone-to-ear latency. Browser-side
clock synchronization and playback acknowledgements would be a separate addition.

## Reliability and fallback

`PROVIDER_MAX_RETRIES` is 0–3 (default 2); `PROVIDER_TIMEOUT_SECONDS` is 1–60
(default 10). LiveKit `APIConnectOptions` bounds each provider connection/request
attempt, with the SDK's native retry interval. It is not a deadline on an entire
streaming conversation. Tool deadlines and confirmation timeouts remain enforced.
Explicit interruption has a five-second completion timeout.

No retry wrapper surrounds business tools. Existing idempotency protects only the
current process/session; do not replay non-idempotent writes after uncertain results.
Idempotent dependency probes use at most three attempts, individual three-second
timeouts and capped exponential full-jitter backoff. Cancellation is never retried.
These policies are intentionally separate to avoid multiplying nested retries.

Native STT/LLM/TTS `FallbackAdapter` is opt-in, one backup per category. Configure:

```dotenv
LLM_FALLBACK_PROVIDER=openai_compatible
LLM_FALLBACK_API_KEY=YOUR_BACKUP_KEY
LLM_FALLBACK_BASE_URL=https://your-supported-endpoint.example/v1
LLM_FALLBACK_MODEL=YOUR_VERIFIED_TOOL_CAPABLE_MODEL
LLM_FALLBACK_LANGUAGE=en
LLM_FALLBACK_COMPATIBLE=true
```

Use analogous `STT_FALLBACK_*` / `TTS_FALLBACK_*` keys, including `VOICE` where
needed. Primary/fallback language must match; batch-only STT is rejected. Existing
STT interim/turn-detection validation also applies. Native adapters retain streaming
and cancellation; TTS checks compatible channels/resamples through LiveKit. Model
tool-calling support, actual language coverage, voice consent, residency and semantic
equivalence cannot be inferred from an OpenAI-compatible URL. The explicit
`*_FALLBACK_COMPATIBLE=true` is your attestation after testing those properties,
not an SDK guarantee. Unknown providers and missing keys fail configuration.

Fallback has zero per-provider internal retries and disables outer SDK retries for
that category. LLM does not switch after partial text/tool calls have been sent;
TTS uses LiveKit's partial-audio guard. Native adapters manage provider availability
and recovery probes while a session is active, and close with the session. Those
probes are not unbounded retries of a user's failed action. No extra application
circuit breaker is layered over the same availability state. Side-effecting tool
replay is never part of fallback. Fallback is not required for normal conversations.

Provider errors emit safe text feedback through the existing authenticated workbench
data channel; it does not call the failing TTS again to announce its own failure.
Unknown internal error messages are not forwarded to the browser. SDK consecutive
unrecoverable errors are capped at two; disconnected sessions can be restarted.

## Health, readiness and metrics

LiveKit's existing worker HTTP `GET /` checks worker registration/connection and
inference-process health (503 until ready; reconnect grace applies). Use the port
logged by the SDK; it chooses an ephemeral port in development and defaults to 8081
in production. Restrict network access: `/worker` also exposes operational metadata.
Do not replace this with a permanently-green application endpoint.

`python -m app.observability.health` performs bounded dependency readiness checks,
validates configuration and PostgreSQL migration revision, and checks Redis when
enabled. Disabled services require no connection. Optional-cache failure is degraded;
Redis rate-limit failure is unready. It makes no billable inference call, so a green
probe does not prove model access, available quota or speech quality. Run it as a
deployment preflight; it is not a live per-session provider health guarantee.

Prometheus exposes `voice_stage_seconds` histograms and `voice_events_total`
counters, with bounded stage/status labels only. Session/turn/call IDs belong in logs
and traces, **not** metric labels. Each Windows-spawned job binds an ephemeral
loopback port with an independent registry; the endpoint lives only for that job.
Scrape/discover the logged `metric_port` while the call runs. This is not an
aggregate worker endpoint and short calls can finish before a scrape; use OTLP/log
collection for durable cross-process aggregation. No multiprocess registry or fixed
port collision is hidden behind this option.

Sentry is opt-in and gets only explicit safe error events with correlation IDs and
stage/category tags. Automatic integrations, breadcrumbs, PII, stack dumps and
transaction tracing are disabled. Validate delivery in your Sentry project yourself.

## Debugging a slow voice turn

1. Find `session_id` and `turn_id` in JSON logs, then the same session in your trace
   backend. Filter a tool by `tool_call_id`. For ambiguous late events, inspect the
   native SDK timeline rather than assigning the event to a guessed turn.
2. Slow interim/final STT: check capture, network, language/model support and noise.
   Slow endpointing with fast STT: inspect pauses, VAD and end-of-turn configuration.
3. Slow `llm_ttft`: inspect native request attempts, provider availability and model
   configuration. Slow tool spans: examine deterministic service/dependency timeouts,
   approval waiting and denied/unknown outcomes without exposing private arguments.
4. Slow TTS first audio: inspect synthesis provider, text segmentation and fallback.
   Fast server first audio but slow listening experience points toward browser/network
   playback, which these server metrics do not measure.
5. Count failed/cancelled/unknown outcomes, not just successful latency samples.
   Compare equivalent languages/models/scenarios and sample sizes. Do not add
   overlapping stage delays together as if they were a purely sequential pipeline.

See [repeatable evaluation](voice-evaluation.md) for fixtures, fault tests and limits.
Official references: [LiveKit events](https://docs.livekit.io/reference/agents/events/),
[data hooks](https://docs.livekit.io/testing/observability/data/),
[OpenTelemetry](https://docs.livekit.io/testing/observability/tracing/),
[fallback behaviour](https://docs.livekit.io/agents/logic/fallback-strategies/).
