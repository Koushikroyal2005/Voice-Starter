# Python voice worker

Python 3.13, LiveKit Agents 1.8.12 (locked), one replaceable STT → LLM → TTS pipeline.
Next.js stays at the repository root. The worker connects to the same external
LiveKit project; it is not FastAPI and does not issue browser tokens.

```powershell
cd 'E:\voice agent starter\voice-agent-starter\backend'
uv python install 3.13
uv sync --locked --extra mcp --extra telemetry
if (!(Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
notepad .env
uv run python -m app.cli providers doctor --offline
uv run python -m app.main download-files
uv run --extra mcp --extra telemetry python -m app.main dev
```

Fill backend environment credentials; never commit `.env`. Base `uv sync --locked`
omits optional MCP/Sentry extras if not needed. `download-files` and `--help` work
before credentials are set. `start` is the SDK's production worker mode, not proof
that the frontend token issuer is production-ready.

See [backend development](../docs/backend-development.md),
[providers](../docs/provider-integration.md), [MCP](../docs/mcp-integration.md),
[use cases](../docs/creating-a-new-usecase.md), [persistence](../docs/persistence.md),
[observability](../docs/observability.md) and [containers](../docs/docker.md).

```powershell
uv run ruff check app tests
uv run ruff format --check app tests
uv run pytest -q
```

Offline tests do not prove cloud access or a voice call. See
[evaluation](../docs/voice-evaluation.md) and [audit evidence](../docs/engineering-audit.md).
