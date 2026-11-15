# Voice-Starter

A reusable hackathon foundation: **Next.js at the repository root**, one separate
Python LiveKit Agents worker in `backend/`, and replaceable native STT → LLM → TTS
plugins. Browser and worker join the same **LiveKit server** (including local self-hosting); the browser
does not call the Python worker over HTTP.

For laptop-only self-hosted development (no LiveKit Cloud), see
[Local LiveKit on Windows](docs/local-livekit-windows.md), including three-terminal
startup and the distinction between local transport and external model APIs.

This is a development starter, not a publicly deployable product. The existing
unauthenticated `/api/token` endpoint **works only in `next dev`** and returns 403
in production/preview. Do not remove that guard to get a public demo working.

## Implemented capabilities

- LiveKit session integration, native streaming providers, partial/final transcripts,
  voice/text input, interruption, microphone controls and reconnection handling.
- Reusable mobile/desktop Voice Workbench, light/dark themes, separate microphone
  and agent-track visualization; aura, bar, grid, radial and wave options.
- Configuration-driven provider registry, bounded retries and opt-in native fallback.
- Typed tools, permissions, allowlists, confirmation, timeouts and session-local
  idempotency. Harmless clock/calculator tools and a sequential workflow.
- Optional approved MCP stdio/Streamable HTTP tools, never blindly trusted discovery.
- Opt-in PostgreSQL metadata/transcripts/tool history with SQLAlchemy/Alembic;
  optional disposable Redis cache/rate limiter. No raw-audio storage path.
- JSON logs, per-turn measurements, OpenTelemetry, optional Sentry/Prometheus,
  readiness checks and opt-in real-audio scenarios.
- Isolated use-case modules: general assistant, an education tool/service/card
  example, and clearly limited healthcare/finance/business scaffolds.

Implemented does not mean verified against paid services. See the
[engineering audit](docs/engineering-audit.md) for evidence and limitations.
No real voice call, acoustic benchmark, paid-provider fallback or deployment is
claimed verified without credentials and an actual test.

## Windows PowerShell quick start

For the verified local Groq/NVIDIA configuration, select `VOICE_PROFILE=groq_nvidia`
instead of manually specifying models, endpoints and speech flags. See
[provider profiles and offline/live doctor](docs/provider-profiles.md).

Requirements: Node **24**, Corepack/pnpm **9.15.9**, uv, Python **3.13** (uv can
install it), the local LiveKit binary and provider accounts. Docker Desktop's Linux engine
is needed only for containers. No execution-policy change is necessary.

```powershell
git clone https://github.com/Koushikroyal2005/Voice-Starter.git
cd Voice-Starter
node --version
# If Corepack is missing: npm.cmd install --global corepack
corepack pnpm install --frozen-lockfile
# If uv is missing: winget install --id astral-sh.uv --exact
if (!(Test-Path -LiteralPath .env.local)) { Copy-Item .env.example .env.local }
if (!(Test-Path -LiteralPath backend/.env)) { Copy-Item backend/.env.example backend/.env }
notepad .env.local
notepad backend/.env
```

Set these **same** server values in both files:

```dotenv
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
AGENT_NAME=
```

Only `backend/.env` also needs the selected providers' credentials:

```dotenv
VOICE_PROFILE=groq_nvidia
GROQ_API_KEY=YOUR_GROQ_KEY
NVIDIA_API_KEY=YOUR_NVIDIA_KEY
USE_CASE=general_assistant
```

These are placeholders. Never use `NEXT_PUBLIC_` for secrets. Shell environment
overrides `.env` files; restart processes after changes. Automatic dispatch requires
blank `AGENT_NAME` in **both** files; named dispatch must match exactly. Assistant
display names are separate from dispatch registration.

Install the native server using [Local LiveKit on Windows](docs/local-livekit-windows.md).
Terminal 1, from the repository root:

```powershell
.\.local\livekit\livekit-server.exe --dev --config livekit.local.yaml
```

Terminal 2:

```powershell
cd backend
uv python install 3.13
uv sync --locked --extra mcp --extra telemetry
uv run python -m app.cli providers doctor --offline
uv run python -m app.main download-files
uv run --extra mcp --extra telemetry python -m app.main dev
```

Keep the worker running. In Terminal 3, from the cloned repository root:

```powershell
corepack pnpm dev
```

Open <http://localhost:3000>. Start a session, allow microphone access, verify worker
job receipt, user transcript, LLM answer and **audible** TTS. Try barge-in, explicit
interrupt, mute, text input, disconnect and a fresh reconnect. A transcript alone
does not prove audio playback. `Start Audio` handles browser autoplay restrictions.

## Optional containers

See [Docker setup](docs/docker.md) and [persistence](docs/persistence.md).
PostgreSQL, Redis and Docker are optional for basic local voice development.

## Verification commands

For repeatable offline checks, opt-in provider calls and manual browser tests, use
[the local smoke checklist](docs/local-smoke-tests.md). See also
[stabilization findings and limitations](docs/main-stabilization.md).

The smoke checklist contains all offline commands. CI makes no real provider
calls. Skips are not successful integration tests. Speaker audibility requires
actual confirmation; advanced audio work stays on voice-optimization.

## Documentation and reusable parts

- [Architecture diagram and boundaries](docs/architecture.md)
- [Backend development](docs/backend-development.md)
- [Provider integration](docs/provider-integration.md)
- [MCP integration](docs/mcp-integration.md)
- [Creating a new use case](docs/creating-a-new-usecase.md)
- [Tool orchestration](docs/tool-orchestration.md)
- [Shared v1 workbench contracts and generation](contracts/voice-workbench/v1/README.md)
- [Voice UI and audio sources](docs/voice-workbench.md)
- [Persistence and Redis](docs/persistence.md)
- [Observability/debugging latency](docs/observability.md)
- [Voice evaluation](docs/voice-evaluation.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Engineering audit](docs/engineering-audit.md)

Reuse the voice shell/Agents UI, provider factory, deterministic tool executor,
approved MCP layer, ownership-scoped persistence, telemetry and scenario harness.
Put business services/tables/cards in use-case modules, not common code.
`USE_CASE=education` demonstrates this separation.

## Before public production deployment

Replace the dev issuer with authenticated and tenant-authorized token issuance,
stable server-derived participant identity, room/tool permissions, CSRF/origin
controls, quotas and abuse protection. Keep secrets in a secret manager; configure
TLS, restricted DB roles, migrations, backups, consent/retention, endpoint access,
provider data residency, durable business idempotency and operational monitoring.
Dockerfiles are packaging, not deployment verification or a security certification.
The dependency audit still reports two low KaTeX paths; see the audit report before
public deployment. Next 15.5.28 and scoped dependency patches address the detected
critical/high findings without migrating to Next 16.

The root license is MIT, but an aura shader has a different upstream notice. Read
[third-party notices](THIRD_PARTY_NOTICES.md) before redistribution/commercial reuse.
Healthcare/finance examples are not validated or compliant products.
