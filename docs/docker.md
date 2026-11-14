# Local Docker setup

LiveKit remains an external service. These containers do not run a LiveKit server.
Use Docker Desktop with Linux containers and a current Compose v2 supporting
optional `env_file` entries and optional health dependencies. Node 24 and Python
3.13 images match local development. The worker waits for Redis health when its
profile is selected, but Redis is not a mandatory dependency when disabled.
The worker build also uses Compose `additional_contexts` / BuildKit named contexts
to copy the single shared contract directory outside its backend build context.
For a standalone image build from the repository root use:

```powershell
docker build --build-context contracts=./contracts -f backend/Dockerfile backend
```

Compose supplies that named context automatically. Do not copy schema files into
backend source or maintain a second schema set.

## PowerShell

Run from the repository root. Copy examples only if the destination does not exist:

```powershell
if (!(Test-Path .env.local)) { Copy-Item .env.example .env.local }
if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
if (!(Test-Path .env.compose)) { Copy-Item .env.compose.example .env.compose }
notepad .env.local
notepad backend/.env
notepad .env.compose
```

Set the same LiveKit URL, key, secret and agent name in frontend and backend files.
Set provider credentials in the backend only. Set a strong `POSTGRES_PASSWORD` in
`.env.compose`; set `REDIS_PASSWORD` only when using Redis. URL-encode non-URL-safe
passwords in explicit `WORKER_DATABASE_URL` / `WORKER_REDIS_URL` overrides.
All these files are ignored by Git and excluded from image build contexts.

```powershell
# Validate without contacting the Docker daemon (does not verify images/services).
docker compose --env-file .env.compose --profile app config --quiet
# Build and start PostgreSQL, the development frontend and registered worker.
docker compose --env-file .env.compose --profile app up --build -d
docker compose --env-file .env.compose logs -f worker frontend
```

Open <http://localhost:3000>. The worker uses container DNS `postgres`, not
`localhost`. Enable persistence explicitly in backend/.env when desired, then run:

```powershell
docker compose --env-file .env.compose --profile app run --rm worker python -m alembic upgrade head
```

Database migrations are explicit, not run concurrently by every worker. Migrate
before sending sessions to a persistence-enabled worker. PostgreSQL starts in this
full-stack Compose setup even if application persistence is disabled. Native
voice-only development needs neither PostgreSQL nor Redis.

## Optional Redis

Set `REDIS_ENABLED=true` in backend/.env and a Redis password in .env.compose:

```powershell
docker compose --env-file .env.compose --profile app --profile redis up --build -d
```

When disabled, Redis is not required. When enabled, status caching is best-effort,
but a configured rate limiter fails closed on Redis errors. Redis has no persistent
volume and must never hold the only copy of important data.

## Images and production boundary

The root Dockerfile has `development` (default Compose) and `production` targets.
The production target enables `NEXT_OUTPUT_STANDALONE=true` at build time and
serves Next's standalone output as an unprivileged user. Normal native Windows
builds leave this unset, avoiding standalone pnpm symlink privilege requirements.
Set `FRONTEND_TARGET=production` in .env.compose to build it. Its existing
`/api/token` deliberately returns 403: implement an authenticated, authorized,
rate-limited token issuer before public deployment. Do not weaken that guard or
use development mode as a public production deployment.

The worker image installs locked dependencies and downloads VAD/model assets at
build time; this requires network access but not provider credentials. It runs
`python -m app.main start` as an unprivileged user, with native health on 8081.
Its 180-second stop grace covers the configured drain/process budgets. Neither
image receives credentials as build arguments. Runtime environment variables are
visible to Docker administrators; use a deployment secret manager in production.

Ports are bound to loopback for local use. A health check is not proof that a paid
provider works. Worker HTTP health/readiness is described in [observability](observability.md).
Review TLS, authentication, quotas, storage retention, ownership, telemetry export,
resource limits and licenses before deployment. Builds may download Google fonts;
an offline/restricted build environment needs an approved local-font strategy.

```powershell
# Stop without deleting the PostgreSQL volume.
docker compose --env-file .env.compose --profile app --profile redis down
```

Do not add `--volumes` unless you deliberately want to erase local database data.
This audit validated Compose configuration only; container builds and service
startup require a running Docker engine and were not verified here.
