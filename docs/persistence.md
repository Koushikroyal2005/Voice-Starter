# Persistence and temporary infrastructure

The frontend is unchanged. Normal voice sessions require neither PostgreSQL nor
Redis. `PERSISTENCE_ENABLED=true` makes PostgreSQL mandatory for that worker job;
startup checks connectivity and the migration revision. Redis is independently
optional. Its cache is disposable and is never a fallback permanent database.

## Layout and responsibilities

```text
compose.yaml                              local PostgreSQL + opt-in Redis profile
backend/
  alembic.ini                             migration entrypoint
  app/
    config/infrastructure.py              validated backend-only settings
    database/
      connection.py                       async engine and transaction scope
      models/__init__.py                  common voice tables, no business domain
      repositories/voice.py               ownership-scoped database operations
      migrations/
        env.py                            async migration runner
        script.py.mako                    future revision template
        versions/0001_voice.py            reversible initial schema
    cache/
      redis_client.py                     optional bounded Redis connection pool
      session_cache.py                    owner-scoped status cache with TTL
      rate_limiter.py                     atomic fixed-window tool quota
    services/
      conversation_service.py             transactions and storage policy
      transcript_service.py               redaction and owner pseudonymization
      infrastructure.py                   SDK events, bounded writer and cleanup
  tests/
    test_persistence.py                   repositories, migrations, privacy, cache
    test_infrastructure_lifecycle.py       event wiring and shutdown flush
```

## Windows setup

Start Docker Desktop's Linux engine first. In a PowerShell terminal at the repo root:

```powershell
cd 'E:\voice agent starter\voice-agent-starter'
# Generates local credentials in this shell, not in tracked files.
$env:POSTGRES_PASSWORD = [guid]::NewGuid().ToString('N')
$env:REDIS_PASSWORD = [guid]::NewGuid().ToString('N')
docker compose up -d --wait postgres
# Optional; omit when Redis is disabled:
docker compose --profile redis up -d --wait redis

cd backend
uv sync --extra mcp
# Use `uv sync` instead if MCP is not needed.
$env:DATABASE_URL = "postgresql+asyncpg://voice_starter:$($env:POSTGRES_PASSWORD)@localhost:5432/voice_starter"
$env:REDIS_URL = "redis://:$($env:REDIS_PASSWORD)@localhost:6379/0"
$env:DATA_REDACTION_KEY = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$env:PERSISTENCE_OWNER_NAMESPACE = 'local-demo'
$env:PERSISTENCE_ENABLED = 'true'
$env:PERSIST_TRANSCRIPTS = 'false'
$env:REDIS_ENABLED = 'false'
uv run alembic upgrade head
uv run python -m app.main dev
```

Keep the generated passwords and redaction key in a local secret manager or ignored
`backend/.env` for subsequent runs. Do not regenerate the database password on every
start: the named volume retains its original credentials. Changing Compose's
password does not change an initialized database password. Rotating the redaction
key changes ownership hashes and prevents access to old records without an explicit
key/ownership migration. Never commit credentials. `.env` is already Git-ignored.

To enable Redis, set `REDIS_ENABLED=true`. To enable tool quotas, set
`TOOL_RATE_LIMIT=30` and `RATE_LIMIT_WINDOW_SECONDS=60`. Zero disables quotas.
`SESSION_CACHE_TTL_SECONDS=300` controls status TTL. Quotas apply per pseudonymous
owner across sessions and include sequential workflow child tools; duplicate
waiters for the same in-memory operation are not charged again. Cache failures
act as misses. Enabled quota failures deny tool execution; they do not silently
remove the limit. Voice-only conversation does not consume this tool quota.

Both containers bind only to loopback. PostgreSQL uses a named persistent volume;
Redis disables persistence. `docker compose stop` stops services without deleting
data. This is development infrastructure, not a production deployment: configure
TLS (`rediss://` and PostgreSQL TLS options), network isolation, restricted DB roles,
backups, retention, secret management and monitoring for production. Workers need
DML rights; only the migration/deployment identity should have schema-change rights.

## Storage and authorization

- `voice_conversations`: session UUID, HMAC owner key, timestamps and status.
- `voice_turns`: optional final user/assistant text/transcripts from LiveKit's
  `conversation_item_added` event. Interim speech is not written. Text input and
  STT share this event. An interrupted assistant item reflects SDK history, not a
  word-perfect guarantee of what the listener heard.
- `voice_tool_executions`: one row per call, updated with lifecycle status and safe
  human title. No arguments, results, confirmation tokens or API keys.

Transcripts are disabled by default and must be explicitly enabled with
`PERSIST_TRANSCRIPTS=true`. There is deliberately no raw-audio recording path or
audio blob column; enabling audio storage would require separate consent, retention
and implementation work. Existing provider/LiveKit logging and telemetry policies
also need deployment review; this layer does not log conversation text or driver
exception details. Known environment secrets, email, phone and common credential
patterns are redacted. This is basic best-effort redaction, not complete PII
detection or a healthcare/finance compliance guarantee. Do not put secrets in speech.

Ownership is derived server-side from the linked LiveKit participant identity and
`PERSISTENCE_OWNER_NAMESPACE`, HMACed with `DATA_REDACTION_KEY`. It is never accepted
from LLM arguments or browser-supplied record IDs. Every repository read/update
checks that owner, returning the same unavailable error for missing/unauthorized
records. Participant replacement never transfers ownership. No database API or
database tool is exposed to the agent. Future HTTP APIs must authenticate users and
derive this ownership context themselves, not trust caller-supplied hashes.

**The existing development token endpoint is not production authentication.** It
generates local-development identities, so records are session-scoped, not a stable
account history. Before production, issue tokens only after application login,
bind stable identities to authorized tenant/user principals, and configure a trusted
tenant namespace (or inject a trusted tenant resolver). Never derive tenant ownership
from unverified room/participant metadata. No cross-tenant administrator API exists.

Services own transactions; repositories do not commit. A new async SQLAlchemy
session is used per operation. Row locking serializes per-conversation writes on
PostgreSQL, and unique constraints deduplicate final transcript IDs and tool calls.
Business models should live in a separate application/domain package with their
own reviewed migrations and deterministic services, not inside these common tables.
Do not expose SQL or arbitrary database writes to an LLM.

The writer is bounded (256 events), serialized and flushed on orderly shutdown
(10-second deadline). After startup, write errors/overflow are logged without data;
voice continues, and failed events are not retried or durably spooled. A process
crash can lose queued events and leave a conversation marked active. This is not an
audit-grade delivery guarantee. Add reconciliation/metrics and an explicit durable
outbox if a product needs that guarantee. Tool history is **not** a durable
idempotency ledger; existing side-effect idempotency remains session-local. Business
side effects need transactional domain-specific idempotency before production use.

No automatic deletion schedule is assumed. Each product must define consent and
retention/deletion policies before enabling transcript storage. Cascading foreign
keys support application-controlled deletion; there is no unauthenticated delete
endpoint. Redis expiry is not a PostgreSQL retention policy.

## Tests and migrations

```powershell
cd 'E:\voice agent starter\voice-agent-starter\backend'
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
uv run alembic check
# After changing models, review the generated migration before applying it:
uv run alembic revision --autogenerate -m 'describe schema change'
```

Portable tests use SQLite only as a test harness: upgrade/downgrade/re-upgrade,
model parity, authorization, transactions/rollback, redaction and transcript
opt-in. Redis unit tests use mocks, not a claim of server compatibility.

For real service contract tests, use a **dedicated test database**, never production:

```powershell
# With the local Compose PostgreSQL already running in the same shell:
docker compose -f ..\compose.yaml exec postgres createdb -U voice_starter voice_starter_test
$env:DATABASE_URL = "postgresql+asyncpg://voice_starter:$($env:POSTGRES_PASSWORD)@localhost:5432/voice_starter_test"
uv run alembic upgrade head
$env:TEST_DATABASE_URL = $env:DATABASE_URL
$env:TEST_REDIS_URL = $env:REDIS_URL
uv run pytest tests/test_persistence.py -q
# Restore the normal database URL before starting a worker.
```

The PostgreSQL contract deletes only records it creates. Redis contracts verify
atomic quota concurrency and real expiration with isolated random keys. These tests
skip explicitly if their URLs are absent. No cloud voice credentials are needed for
these database/cache tests. Live voice-session verification still needs existing
LiveKit/STT/LLM/TTS credentials.

Implementation references: [SQLAlchemy async sessions](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html),
[Alembic async migrations](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic),
[redis-py asyncio lifecycle](https://redis.io/docs/latest/develop/clients/redis-py/async/).
