# Voice-Starter

A reusable hackathon foundation: **Next.js at the repository root**, one separate
Python LiveKit Agents worker in `backend/`, and replaceable native STT → LLM → TTS
plugins. Browser and worker join the same **external LiveKit project**; the browser
does not call the Python worker over HTTP.

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

Requirements: Node **24**, Corepack/pnpm **9.15.9**, uv, Python **3.13** (uv can
install it), a LiveKit project and provider accounts. Docker Desktop's Linux engine
is needed only for containers. No execution-policy change is necessary.

```powershell
cd 'E:\voice agent starter\voice-agent-starter'
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
LIVEKIT_URL=wss://YOUR_PROJECT.livekit.cloud
LIVEKIT_API_KEY=YOUR_LIVEKIT_API_KEY
LIVEKIT_API_SECRET=YOUR_LIVEKIT_API_SECRET
AGENT_NAME=voice-starter
```

Only `backend/.env` also needs the selected providers' credentials:

```dotenv
STT_PROVIDER=deepgram
LLM_PROVIDER=openai_compatible
TTS_PROVIDER=cartesia
DEEPGRAM_API_KEY=YOUR_DEEPGRAM_KEY
LLM_API_KEY=YOUR_OPENAI_OR_COMPATIBLE_KEY
CARTESIA_API_KEY=YOUR_CARTESIA_KEY
USE_CASE=general_assistant
```

These are placeholders. Never use `NEXT_PUBLIC_` for secrets. Shell environment
overrides `.env` files; restart processes after changes. Automatic dispatch requires
blank `AGENT_NAME` in **both** files; named dispatch must match exactly. Assistant
display names are separate from dispatch registration.

```powershell
cd backend
uv python install 3.13
uv sync --locked --extra mcp --extra telemetry
uv run python -m app.check_setup
uv run python -m app.main download-files
uv run --extra mcp --extra telemetry python -m app.main dev
```

Keep the worker running. In a second PowerShell window:

```powershell
cd 'E:\voice agent starter\voice-agent-starter'
corepack pnpm dev
```

Open <http://localhost:3000>. Start a session, allow microphone access, verify worker
job receipt, user transcript, LLM answer and **audible** TTS. Try barge-in, explicit
interrupt, mute, text input, disconnect and a fresh reconnect. A transcript alone
does not prove audio playback. `Start Audio` handles browser autoplay restrictions.

## Local containers

LiveKit Cloud/SFU is **not** included. Continue using your external project URL and
credentials. Dockerfiles exclude `.env` files and run application processes as
non-root users. Never pass provider secrets as build arguments.

```powershell
cd 'E:\voice agent starter\voice-agent-starter'
if (!(Test-Path -LiteralPath .env.compose)) { Copy-Item .env.compose.example .env.compose }
notepad .env.compose
# Set a strong persistent POSTGRES_PASSWORD; REDIS_PASSWORD only if using Redis.
# Fill .env.local and backend/.env as above.
docker compose --env-file .env.compose config --quiet
docker compose --env-file .env.compose --profile app up --build -d
docker compose --env-file .env.compose --profile app logs -f worker frontend
# Optional Redis; enable REDIS_ENABLED in backend/.env only if using it:
docker compose --env-file .env.compose --profile redis up -d --wait redis
```

The default frontend target is **development**, bound to host loopback, so the dev
token issuer works locally. A production target is also provided, but its token
route remains blocked. See [Docker and deployment](docs/docker.md) for migration
commands, container DNS, service profiles and production requirements.

Native voice-only development requires no PostgreSQL or Redis. When persistence is
enabled, PostgreSQL and migrations become mandatory. Transcript storage is separately
opt-in. Redis is never the permanent source of truth. See [persistence](docs/persistence.md).

## Verification commands

```powershell
# Repository root
corepack pnpm install --frozen-lockfile
corepack pnpm lint
corepack pnpm typecheck
corepack pnpm test
corepack pnpm build
corepack pnpm security:secrets
node scripts/check-secrets.mjs --history

cd backend
uv sync --locked --extra mcp --extra telemetry
uv run ruff check app tests
uv run ruff format --check app tests
uv run pytest -q
```

Real PostgreSQL/Redis contracts require dedicated `TEST_DATABASE_URL` and
`TEST_REDIS_URL`. Real voice replay requires `RUN_REAL_VOICE_EVAL=true` plus consented
WAV fixtures/provider credentials. Missing prerequisites are skipped, not successful
benchmarks. Local MCP tests start actual harmless stdio/HTTP servers when its extra
is installed. Clean builds need internet for packages, the Google font and worker
model assets. CI uses Node 24 and locked Python/frontend dependencies.

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
