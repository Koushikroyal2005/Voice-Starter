# Voice-Starter

Reusable voice AI starter: the existing Next.js / React LiveKit frontend at the
repository root and a separate Python LiveKit Agents worker in `backend/`.

The browser connects to LiveKit, and LiveKit dispatches a Python worker job into
the room. The browser does not call the Python process over HTTP. STT, LLM, and
TTS run through backend provider plugins; their keys never enter browser code.

## Local Windows setup

Requirements: Node.js 24, Python 3.13 (installed by uv below), uv, and a LiveKit
project plus provider accounts. PowerShell commands use Corepack and `.cmd` where
needed so no execution-policy change is required. If Corepack is unavailable,
install it with `npm.cmd install --global corepack`.

From the repository root:

```powershell
node --version
corepack pnpm install --frozen-lockfile
winget install --id astral-sh.uv --exact
# Reopen PowerShell if uv was newly installed.
Copy-Item .env.example .env.local  # Only if .env.local does not already exist.
notepad .env.local
```

Fill the root `.env.local` with real values:

```dotenv
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your-livekit-key
LIVEKIT_API_SECRET=your-livekit-secret
AGENT_NAME=voice-starter
```

Then prepare the backend:

```powershell
cd backend
uv python install 3.13
uv sync --locked
Copy-Item .env.example .env  # Only if .env does not already exist.
notepad .env
```

In `backend/.env`, use the **same four values** as the frontend, plus provider keys:

```dotenv
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your-livekit-key
LIVEKIT_API_SECRET=your-livekit-secret
AGENT_NAME=voice-starter
STT_PROVIDER=deepgram
LLM_PROVIDER=openai_compatible
TTS_PROVIDER=cartesia
DEEPGRAM_API_KEY=your-deepgram-key
LLM_API_KEY=your-openai-or-compatible-key
CARTESIA_API_KEY=your-cartesia-key
```

The example values above are placeholders. Do not commit actual credentials.
`.env.local` and `backend/.env` are ignored. Never use `NEXT_PUBLIC_` for secrets.
Process environment variables take precedence over files; check for stale values
if the files appear correct but configuration differs.

Before starting, from `backend/`:

```powershell
uv run python -m app.check_setup
uv run python -m livekit.agents download-files
```

The setup check compares local development environment settings without printing
credentials. It checks URL, key, secret and dispatch-name equality, and selected
provider configuration. It cannot validate account access or compare environment
variables set only in a different running shell.

## Run two separate processes

PowerShell window 1 — from the repository root:

```powershell
corepack pnpm dev
```

PowerShell window 2 — from the repository root:

```powershell
cd backend
uv run python -m app.main dev
```

Keep both running, then open http://localhost:3000. Restart both after changing
environment values. No FastAPI or extra HTTP backend is required for voice calls.

## Dispatch and development token endpoint

Named dispatch is recommended for this local setup: set `AGENT_NAME=voice-starter`
in both files. The Python worker registers that name; the frontend Session API
requests it; `/api/token` puts the server-configured name into the participant JWT.

Automatic dispatch also works: leave `AGENT_NAME` blank in **both** files. The
token contains no named dispatch, and an unnamed worker is dispatched automatically.
Use a project without competing unnamed workers for a predictable demo.

The frontend always uses its existing `/api/token` route. It no longer falls back
to the public homepage agent or uses `LIVEKIT_TOKEN_SERVER_ID`. Missing configuration
returns an actionable 503 response instead of connecting to someone else's demo.
The route returns only the server URL, room/participant details and a short-lived
participant JWT; it never returns `LIVEKIT_API_SECRET` or provider keys.

**This token endpoint is unauthenticated and development-only.** It returns 403
outside `next dev`, including preview deployments. A production build can compile,
but `next start` intentionally cannot issue tokens. Production requires a separate
authenticated, authorized token-issuance implementation.

Every token refresh generates a new room and participant identity. LiveKit's
existing Session API manages transient network reconnection and refreshes tokens
for later calls. Failed starts show a toast and restore the Start call button;
duplicate clicks are blocked while connecting. Unexpected disconnects return to
the welcome screen. The existing agent-failure handler ends failed sessions.

This worker accepts audio and text. Camera and screen-share inputs are hidden
because this backend does not currently process visual input. Visualizers, media
controls, transcript components and the existing design are retained.

## Verify a real voice session

With real credentials and both processes running:

1. Open http://localhost:3000 and click **Start call**. Allow microphone access.
2. Confirm Python logs show worker registration, an accepted job, and **Voice job
   received**. If no job arrives, check the LiveKit project and dispatch name.
3. Hear the greeting. If autoplay is blocked, click the existing **Start Audio** button.
4. Speak a short question. Open the existing transcript panel and verify your
   words appear. With streaming STT, partial transcripts may update before final text.
5. Confirm the agent moves through thinking/speaking, produces a relevant answer,
   and its response transcript appears. A visible transcript alone does not prove audio.
6. Listen for audible TTS playback and try interrupting the answer.
7. Click **End call**. Confirm microphone capture stops and the welcome screen
   returns. Python should log **Voice session closed** and shut down that job;
   the worker process stays available for the next call.
8. Start another call without refreshing. Confirm a fresh room/job and no old
   transcript. For failure recovery, stop the worker, try a call, then restart it
   and retry after the session reports the missing agent.

Without valid credentials, job dispatch, STT, LLM generation, TTS playback, and
live disconnect/reconnect behavior remain unverified. Configuration checks and
offline tests do not establish that a voice conversation works.

## Automated checks

From the repository root:

```powershell
corepack pnpm test:token
corepack pnpm build
```

From `backend/`:

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Token tests use synthetic credentials entirely offline: development-only issuance,
missing configuration, server-controlled dispatch, unique rooms, JWT grants and
absence of returned secrets. Backend tests cover provider construction, configuration
matching, dispatch names, capabilities and Windows serialization. The frontend's
existing Google font requires network access during a clean build.

## Project layout

- `app/page.tsx`: server-side composition of the existing voice app.
- `app/api/token/route.ts`: development-only JWT issuer and dispatch configuration.
- `components/app/`: existing welcome/session views and connection controls.
- `components/agents-ui/`: existing reusable LiveKit controls, visualizers and transcript.
- `components/ui/`, `styles/`: existing local UI primitives and design tokens.
- `backend/`: independent Python agent process, provider registry/factory and tests.
- `tests/token-route.test.cjs`: offline tests of the actual Next.js token route.

See [backend/README.md](backend/README.md) for provider selection, batch Whisper
limitations, compatible NIM/vLLM endpoints, and adding new providers.

See [Voice Workbench](docs/voice-workbench.md) for the reusable UI components,
state/event model, real audio sources, interruption bridge and verification checklist.

See [Tool orchestration](docs/tool-orchestration.md) for the single-agent tool engine,
safe demo tools/workflow, permission/confirmation policies and use-case extension guide.
