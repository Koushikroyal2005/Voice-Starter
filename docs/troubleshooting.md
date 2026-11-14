# Troubleshooting

## Session will not connect

- Development `/api/token` 503: configure root `.env.local` with `LIVEKIT_URL`,
  `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`; restart Next. No fallback credentials exist.
- Production `/api/token` 403 is intentional. Supply an authenticated production
  token service; do not remove the development-only guard.
- Match all three LiveKit settings and `AGENT_NAME` between root `.env.local` and
  backend `.env`. Do not use `NEXT_PUBLIC_` for secrets.
- Named dispatch requires the worker to register the exact name. Blank names on
  both sides select automatic dispatch. Check worker registration/job logs.
- Run frontend and worker in separate terminals. Starting Next does not start Python.
- A connected browser without an agent usually indicates dispatch, worker startup,
  credentials or provider failures. Inspect worker logs before changing the UI.

## Microphone, interruption and transcripts

Use HTTPS or localhost. Allow microphone access in the browser and OS; check the
selected device and whether another application holds it. Text connection is a
fallback, not an STT test. Real input and output tracks drive the visualizers;
silence/disconnection should not generate fake activity. Browser autoplay may
require a user gesture. Use headphones when testing interruption to reduce echo.

Partial transcripts depend on the selected STT provider. Whisper is batch-only
and uses LiveKit's VAD adapter; it cannot supply genuine streaming interim text.
Language support differs between models. `TTS_LANGUAGE` is passed to plugins;
Murf requires a supported full locale such as `en-US`. Switching a text-language
setting does not prove a provider correctly transcribes code switching.

## Provider errors

Check the selected provider, its required API key, model, endpoint, voice and
language. An OpenAI-compatible API is not automatically compatible with streaming
tools. Check the [provider guide](provider-integration.md). Never print credentials
to debug. Quotas, regional availability and invalid voice IDs require provider-side
verification. Fallback is opt-in and capability constrained, not an unlimited retry.

## Tools and MCP

Check use-case tool selection, global allowlist and permissions. Sensitive actions
need human confirmation and an idempotency key. A duplicate waiter must not cancel
the original operation. A non-cancellable action may continue after interruption.

MCP is disabled by default. A configured server is not automatically trusted:
verify transport, startup command, tool allowlist, pinned input/output schemas and
permissions. Container stdio servers must exist inside the worker image; HTTP
`localhost` means the worker container, not Windows. Use the
[MCP guide](mcp-integration.md), never expose private server configuration in public UI.

## Database and Redis

Run Alembic migrations with the same database URL as the worker. Native Windows
uses `localhost`; Compose worker uses `postgres` / `redis`. Check passwords and URL
encoding. Ownership is linked to the LiveKit participant; the development token
endpoint creates new identities, not a persistent authenticated account.

Persistence and transcript storage are opt-in; no raw audio is stored. The bounded
writer is best-effort, not a durable queue. Redis can be disabled entirely. If
enabled, cache failure is tolerated but rate-limit failure rejects guarded work.
Docker CLI availability does not imply Docker Desktop's engine is running.

## Slow voice turn

Follow `session_id`, `turn_id`, `tool_call_id` through structured logs and traces.
Compare speech/STT final/end-of-turn, LLM first token, tool duration, TTS first audio
and total response measurements. Missing measurements are unknown, not zero.
SDK timestamps are not browser microphone-to-speaker latency. See the
[observability guide](observability.md) for safe logging and exporters, and the
[evaluation guide](voice-evaluation.md) for opt-in real-provider scenarios.

## Build or install problems

Use Node 24, pnpm 9.15.9, uv and Python 3.13. Install using lockfiles, not ad-hoc
upgrades. Stop the development server before building to avoid competing `.next`
writers. The first development compile can be slow; a successful initial page load
does not verify a voice call. Restricted networks can prevent font/model downloads.
If standalone tracing reports Windows `EPERM` symlink errors, leave
`NEXT_OUTPUT_STANDALONE` unset for native builds; the Linux Docker builder enables
it explicitly. This does not require changing Windows privileges or system policy.
On Windows use the documented `.venv\Scripts\python.exe` commands if activation is
blocked; changing machine-wide execution policy is unnecessary.
