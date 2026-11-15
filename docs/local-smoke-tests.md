# Repeatable local verification (Windows PowerShell)

Install locked dependencies using README. Run these offline checks from root:

```powershell
corepack pnpm test
corepack pnpm typecheck
corepack pnpm lint
corepack pnpm contracts:check
corepack pnpm contracts:fixtures:check
corepack pnpm security:secrets
corepack pnpm build
cd backend
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
cd ..
git diff --check
```

No real provider calls are made by these tests or CI. Database/Redis and real voice
scenario tests need isolated services/opt-in settings; skips are not successes.

Stop the Next.js development server before `pnpm build`. Both commands use
`.next`; do not run them concurrently. Wait for the production route summary
before restarting development. On this laptop the isolated build compiled in
91 seconds, then needed additional time for lint, types and build tracing.
Production `/api/token` deliberately returns 403; voice testing uses `pnpm dev`.

## Configuration and opt-in provider calls

From backend, with ignored `.env` keys configured:

```powershell
uv run python -m app.cli providers doctor --offline
# Explicit opt-in; uses provider allowance, never run in CI:
uv run python -m app.cli providers doctor --live
```

Doctor checks TTS audio, LLM streaming and STT using synthetic diagnostic audio.
It does not prove worker registration, room startup, tool execution or audibility.
Default profile is groq_nvidia. Gemini and other profiles remain available.

## Browser and local services

1. Start exactly the three README processes. Confirm worker registration and
   matching local server/AGENT_NAME. Run offline doctor without stale overrides.
2. Open localhost:3000, start voice and allow microphone permission. Confirm a job
   reaches the worker and an agent joins. Registration alone is not a media test.
3. If several microphones exist, select each. Verify real input levels, mute,
   unmute, and accessible Mute/Unmute labels. Deny permission separately; check
   the safe error and Connect with text alternative.
4. Ask “Use the calculator to calculate two plus three.” Confirm final STT text,
   tool selected/running/completed, agent text and actually hear five. Whisper is
   batch STT; no interim words are promised. Do not record private audio.
5. Ask a second question. Interrupt during a long answer by speaking; separately
   test Interrupt and Escape. Confirm old playback stops and safe tool work cancels.
   Non-cancellable writes must not be falsely reported as cancelled or repeated.
6. End, reconnect and verify a fresh room, no stale confirmation/tool state, and
   old job closure. Temporarily interrupt transport to observe reconnecting UI.
7. Test text-only without microphone access. At mobile width, verify wrapping,
   keyboard controls and all five real audio visualizers.
8. Close the tab and check the old session shuts down. No pending tools, MCP
   processes or optional infrastructure tasks should remain for that job.

Record date/profile/model IDs, pass/fail/skipped and sanitized error categories.
Never share JWTs, keys, headers or private conversations. Physical speaker output,
microphone quality and spoken barge-in require a human when devices are unavailable.
