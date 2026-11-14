# Engineering audit — 14 November 2026

Scope: current checked-out Next.js/React application, Python worker, dependencies,
configuration, tests, infrastructure and documentation. This is a source review
and explicitly bounded local verification, not a production security certification.
The pre-audit use-case changes were committed and pushed as `d09d63d`. This audit's
changes are a separate working-tree change set.

## Findings and corrections

1. **Duplicate tool cancellation:** a cancelled duplicate waiter could cancel a
   shared read operation. Track the creating caller, shield shared execution and
   avoid publishing a false cancellation for the original call. Regression tested.
2. **Shutdown race:** LiveKit job shutdown callbacks execute concurrently. Flush
   native session history before closing tool/MCP/persistence resources; stop the
   telemetry exporter after cleanup. Add an explicit completion event and budgets.
   A concurrent-callback regression test asserts the shutdown order.
3. **Ignored TTS language:** provider selection validated language, but constructors
   did not receive it. Forward language to Cartesia/ElevenLabs; validate and pass a
   full supported Murf locale. Real plugin construction is tested without API calls.
4. **Build/CI drift:** align CI with Node 24, use direct ESLint, add explicit
   TypeScript/frontend/backend tests and current lockfile installs. Remove two
   unused dependency/variable warnings without changing visualizer behavior.
5. **Packaging/documentation:** add standalone frontend and unprivileged worker
   images, profile-gated app/Redis Compose services, ignored private runtime env
   files and current entrypoint commands. Preserve the production token guard.
   Standalone output is Docker-only: an initial Windows build compiled but failed
   packaging on denied symlink creation. Native builds do not require standalone.
6. **Transport test reliability:** bootstrap's local MCP test used a five-second
   subprocess cold-start allowance unlike the other Windows transport tests.
   Use their bounded 20-second allowance and an explicit 30-second assertion
   deadline. Production defaults remain unchanged. The initial full run exposed
   this failure rather than proving an external MCP service unavailable.
7. **Dependency security:** npm's production audit initially reported one critical,
   12 high, 12 moderate and nine low findings (advisories, not proven exploits).
   Update Next/eslint-config-next from 15.5.27 to 15.5.28, preserving Next 15 and
   React 19. Patch nanoid and same-major PostCSS/DOMPurify/source-map-js,
   Mermaid and provider-utils dependencies; explicitly select the patched Zod 4
   peer already required by the AI SDK. Use the Next advisory's explicit Sharp
   >=0.35.5 workaround through a scoped override: upgrading Next alone retained
   the old optional Sharp version in the lockfile.
   The Next security fixes are documented in
   [GHSA-2464-fhr4-w9xw](https://github.com/advisories/GHSA-2464-fhr4-w9xw) and
   [GHSA-p3m5-59mp-jv5r](https://github.com/advisories/GHSA-p3m5-59mp-jv5r).
   Remaining audit findings must be reviewed before production; no blanket
   vulnerability-free claim is made and no incompatible forced upgrades are used.
   Final `pnpm audit --prod --json`: **0 critical, 0 high, 0 moderate, 2 low**
   vulnerable dependency paths for the same
   [KaTeX advisory](https://github.com/advisories/GHSA-238p-pmpm-9mq7).
   Its fix crosses the current 0.16 to 0.18 renderer dependency line and is left
   for an explicit math-renderer compatibility review rather than an untested
   global override. `provider-utils` is deliberately pinned to patched 3.0.28;
   newer 3.0.46 introduced vulnerable Undici 5 dependencies during this audit.

No application relocation, UI replacement, fake STT/TTS or new business framework
was introduced. Third-party license notices were retained and documented.

## Architecture and working implementation

“Implemented” below means present and reviewed in code; it is not a claim of a
verified live paid-provider call.

- **Frontend/backend integration and sessions:** Next 15.5.28 / React 19 at the
  root; LiveKit React session/track hooks and one Python LiveKit Agents 1.8.12
  `AgentSession`. Development-only server token generation uses fresh room/user
  IDs, short-lived tokens and server-side dispatch settings. Matching blank agent
  names use automatic dispatch; matching nonempty names use explicit dispatch.
  Disconnect closes the native session; reconnect obtains a fresh session.
- **STT/LLM/TTS:** native plugin instances preserve SDK events and streaming.
  Deepgram/AssemblyAI provide streaming STT; OpenAI Whisper is explicitly batch-only
  with a VAD adapter and cannot promise interim transcription. OpenAI-compatible
  and Gemini LLMs, Cartesia/ElevenLabs/Murf TTS are configured through factories.
  Model/language/endpoint capability differs; provider selection is not runtime
  hot switching. NVIDIA NIM/vLLM are endpoint configurations, not separately
  verified services. See [provider guide](provider-integration.md).
- **Barge-in:** native LiveKit turn handling, VAD and speech interruption manage
  audio playback. Browser RPC invokes actual session interruption; mute is a
  separate operation. Safe tools can be cancelled; non-cancellable side effects
  must not be represented as rolled back. Acoustic interruption remains untested.
- **Tools/workflows:** typed schemas, exact allowlists, deterministic business
  functions, permissions, deadlines, human confirmations, structured results and
  a bounded per-session idempotency ledger. Time/arithmetic tools and a sequential
  workflow are real implementations; arithmetic never uses `eval`. LLMs do not
  receive direct database mutation access. A ledger is not durable across workers.
- **MCP:** optional official SDK + LiveKit integration; stdio and Streamable HTTP,
  multiple servers, reviewed schemas, explicit tool selection, permission and
  confirmation rules, output disclosure limits and bounded calls. Reconnection
  does not replay side effects. Local subprocess commands are trusted executable
  configuration, not sandboxed code. External maps/database/business examples are
  disabled illustrative configuration, not proven integrations.
- **PostgreSQL:** optional SQLAlchemy 2 async repositories/services, Alembic common
  infrastructure tables, transactions and ownership checks. Final transcripts are
  separately opt-in; raw audio is not stored. Metadata/tool history intentionally
  omit arbitrary private arguments/results. Sensitive-data redaction is heuristic.
- **Redis:** optional TTL session cache and atomic quota counter. Disabled mode
  needs no Redis. Cache is fail-open, configured rate limiting fail-closed. Redis
  is never permanent truth. Compose Redis is password-protected and disposable.
- **Errors/retries:** safe user-facing worker errors, bounded native provider retry
  and opt-in capability-constrained fallback, with no replay after partial LLM
  output. Deterministic tool actions are not blindly retried. MCP monitoring
  reconnects with bounded request deadlines until normal worker shutdown; it is
  not an unbounded retry loop inside an action. No extra circuit-breaker framework.
- **Observability:** safe structured logs, correlated IDs, SDK/native and custom
  OTel observations, per-turn stage metrics, optional Sentry and per-job
  Prometheus. Cloud recording is disabled. Measurements are SDK-observed timing,
  not true browser mouth-to-ear latency. Missing events remain missing, not zero;
  a multi-step response can generate more than one assistant-item observation.
- **Reusable UI:** separate microphone and agent tracks feed actual audio
  visualizers (aura/bar/grid/radial/wave), partial/final transcript hooks, native
  session-state mapping, text fallback, interruption/mute, connection failures,
  confirmation/tool/result cards, themes and responsive shell. Domain card
  renderers and public configuration remain outside the generic voice shell.
- **Use cases:** general assistant remains default; education demonstrates prompt,
  deterministic service, tool and custom result card. Healthcare/finance/business
  modules are examples, not safety-validated complete products.

## Verification record

Performed locally on Windows with Node 24, pnpm 9.15.9, Python 3.13 and uv 0.11.26:

- Frozen frontend install and locked backend install with MCP/telemetry extras.
- ESLint, TypeScript checks and 27 frontend contract tests passed again after
  security dependency changes. Next 15.5.28 production build passed, including
  prerender/type/lint stages; `/` reports about 600 kB first-load JS. That is a
  substantial reusable-UI bundle, not a performance optimization claim.
- Ruff checks and formatting checks passed (83 Python files). Final full backend
  run: **184 passed, 10 skipped** in 100.67 seconds, including actual harmless
  local MCP stdio and Streamable HTTP transport tests. The skipped cases are two
  PostgreSQL/Redis service contracts and eight opt-in real audio scenarios.
  An initial run was 183 passed, one MCP cold-start timeout and 10 skipped before
  the test-fixture correction; the successful rerun is not an external-server test.
- Browser initial/disconnected page rendered at 320, 768 and 1440 px without
  horizontal document overflow. Missing-config development token request returned
  503. This does not test connected transcripts, real device input or every control.
  The final built production server also rendered the workbench and an actual
  browser POST to `/api/token` returned the expected 403 with the development-only
  security message. Both temporary local Next processes were stopped afterward.
- Compose configuration parsed successfully with app + Redis profiles for both
  development and production frontend targets, using synthetic validation values.
- Known-pattern tracked-file/reachable-history scan covered 369 commits with no
  matches or non-example tracked env files. This is not exhaustive secret detection.

Docker CLI is installed but the Docker Desktop Linux engine is unavailable; container builds,
image health/startup, PostgreSQL and Redis service contracts were not executed.

## Required external verification and known limitations

- No real LiveKit room call, browser microphone/STT/LLM/TTS loop, paid-provider
  fallback, multilingual quality, noisy speech or deployed application was verified.
  Supply LiveKit + selected provider credentials and consented WAV fixtures for
  opt-in replay; run an actual browser call separately. Scenario definitions and
  mocked fault tests are not benchmark results or target achievements.
- Real PostgreSQL and Redis tests require dedicated `TEST_DATABASE_URL` and
  `TEST_REDIS_URL`. SQLite migrations/repository tests do not prove PostgreSQL
  behavior. Start Docker and run both service contracts before relying on storage.
- Local MCP transport tests do not prove any external MCP vendor integration.
  External services require reviewed configuration, connectivity and credentials.
- No application authentication, durable business idempotency, durable persistence
  queue, production token issuer, backups or retention automation is supplied.
  The bounded asynchronous persistence queue can drop records on saturation or
  process death. Do not use it as an auditable transaction ledger.
- Dev participant identities are ephemeral; persistent cross-session ownership
  requires authenticated server-derived identity. Production token issuance is
  intentionally blocked until implemented. Optional infrastructure is not an
  authorization substitute.
- Worker readiness does not verify provider credentials or quota. Metrics endpoints
  and telemetry collectors need private-network access controls. Python/Next/font
  and model downloads need network availability. CI changes were not run on GitHub.
- The install still reports the existing TypeScript 5.9.2 versus older
  typescript-eslint `<5.9` peer-range warning. Lint/type checks must remain part of
  upgrades; this audit does not silently replace the lint stack. A dedicated
  Python dependency vulnerability scanner was not run. The production npm audit
  retains the two low KaTeX paths above; do not interpret passing tests as proof
  that dependency security or exploitability has been exhaustively established.
- The aura visualizer includes an upstream Polyform NonResale notice despite the
  root MIT license. Review [third-party notices](../THIRD_PARTY_NOTICES.md) before
  redistribution/commercial use; this audit does not give legal clearance.

## Running and reusing the starter

Follow the exact PowerShell commands in the [root README](../README.md),
[backend guide](backend-development.md) and [Docker guide](docker.md). Required
voice credentials are `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` on both
servers, matching optional `AGENT_NAME`, plus default `DEEPGRAM_API_KEY`,
`LLM_API_KEY` and `CARTESIA_API_KEY` in the backend. `LLM_MODEL` / `LLM_BASE_URL`
select a compatible alternative endpoint; provider-specific configuration remains
backend-only. Examples contain placeholders, never working credentials.

Reuse the domain-neutral voice shell, native provider factory/capability registry,
typed tool executor and workflow, reviewed MCP layer, common storage repositories,
optional caches, correlated telemetry and deterministic scenario harness. Add a
business module using [creating a new use case](creating-a-new-usecase.md), without
changing the engine. Apply production controls listed in the README before public
exposure; these containers are local packaging, not a verified deployment.
