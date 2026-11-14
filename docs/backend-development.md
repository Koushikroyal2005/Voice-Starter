# Backend development guide

Use Python 3.13 and committed `uv.lock`. API compatibility is checked against the
installed LiveKit Agents 1.8.12. Upgrades must rerun plugin construction, streaming/
fallback, MCP, Windows serialization and session-lifecycle tests.

## Windows setup

```powershell
cd 'E:\voice agent starter\voice-agent-starter\backend'
uv python install 3.13
uv sync --locked --extra mcp --extra telemetry
if (!(Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
notepad .env
uv run python -m app.check_setup
uv run python -m app.main download-files
uv run --extra mcp --extra telemetry python -m app.main dev
```

Match URL/key/secret/dispatch name with root `.env.local`. Provider keys exist only
in backend environment. Process environment wins over dotenv. Base `uv sync --locked`
omits optional extras; neither MCP nor telemetry services are required when disabled.
No venv activation or execution-policy change is needed. Use the **app entrypoint**
for model downloads, not `python -m livekit.agents download-files`.

## Layer boundaries

- `config/`: environment validation and secret-safe errors.
- `providers/`: native plugin constructors/capabilities; do not buffer streamed
  output into strings or duplicate LiveKit audio processing.
- `agents/`: one orchestrator and bounded session-local operation state.
- `tools/`: typed inputs/outputs, allowlists, permissions, approval and deadlines.
- `usecases/`: prompts/domain services/config; see [creation guide](creating-a-new-usecase.md).
- `mcp/`: approved external transports and schema/disclosure checks, not providers.
- `database/`, `services/`: ownership-scoped repositories/transaction boundaries.
- `cache/`: optional disposable Redis TTL status/quotas.
- `observability/`: metadata-only stages/trace correlation, not private content dumps.

Accurately declare tool side effects and cancellation safety. Sensitive operations
require reviewed summaries and human approval. Session-local idempotency is not
enough for production writes/payments: implement durable domain-transaction
idempotency. Never replay an unknown non-idempotent operation automatically.

## Tests and migrations

```powershell
uv run ruff check app tests
uv run ruff format --check app tests
uv run pytest -q
uv run python -m app.observability.health
```

Readiness requires valid configuration and enabled dependencies, not paid inference.
MCP transport tests run harmless real local servers. Dedicated PostgreSQL/Redis
contracts need `TEST_DATABASE_URL` / `TEST_REDIS_URL`; real audio needs explicit
opt-in and WAV fixtures. See [persistence](persistence.md) and [evaluation](voice-evaluation.md).

With an appropriately configured database:

```powershell
uv run alembic upgrade head
uv run alembic check
uv run alembic revision --autogenerate -m 'describe your schema change'
```

Review migrations; do not automatically create schemas in workers. Use separate
migration and runtime DML identities in production. Downgrade/re-upgrade tests must
only target dedicated test databases.

## Shutdown and debugging

SDK shutdown callbacks run concurrently. Workbench cleanup awaits native close/final
history, then bounded tools/MCP cleanup, then persistence flush. Telemetry waits for
that barrier before ending exporters. Worker drain is 30 seconds, process cleanup
budget is 140 seconds; Compose allows 180. Crashes/forced termination can still lose
queued events or leave writes unknown: these are bounded budgets, not exactly-once
guarantees. Keep callbacks at module scope where Windows multiprocessing requires it.

Use correlated logs/native traces, not full conversation dumps. See
[observability](observability.md) and [troubleshooting](troubleshooting.md).
