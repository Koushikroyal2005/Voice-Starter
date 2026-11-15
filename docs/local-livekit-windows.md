# Local LiveKit on Windows (no hosted application services)

The existing Next.js UI and Python worker stay unchanged. Run both natively on
Windows and run LiveKit locally. Neither LiveKit Cloud, Cloudflare tunnels, AWS,
PostgreSQL nor Redis is needed for this transport setup. Hosted Groq/Google/NVIDIA
model APIs are still external inference services, not offline laptop inference.
Selecting fully offline speech/models would be a different task.

## Configuration

Root `.env.local` and `backend/.env` must both contain:

```dotenv
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
AGENT_NAME=
```

Those are LiveKit's public **development-only** defaults, not production secrets.
Keep them in the ignored env files. Never expose either API secret in `NEXT_PUBLIC_*`.
Leave `AGENT_NAME` blank on both sides for automatic dispatch. For explicit dispatch,
set the same nonblank name in both files and restart both processes. The token
endpoint already adds the named dispatch configuration; do not manually redesign it.

The configured LLM uses the existing OpenAI-compatible Adapter:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-20b
LLM_API_KEY=YOUR_GROQ_KEY
```

The base URL ends at `/v1`, not `/chat/completions`. The selected model is listed
as a production Groq model with local tool-calling support. Actual streaming,
tool calling and account quotas still require an inference test. Do not add keys
to this document or to tracked examples. Google AI Studio/NVIDIA keys are not
interchangeable with a Groq key; only the selected LLM key is required.

### Current voice prerequisite

The provider registry also supports Gemini and Groq speech adapters.
See [first voice conversation](first-voice-conversation.md) for the current
Groq Whisper → Groq LLM → Groq Orpheus profile, its terms-acceptance blocker,
separate streaming Gemini profile and actual diagnostic results.
Groq's Whisper model IDs differ from the existing `whisper-1`
allowlist; merely substituting a URL/key is not supported. Do not bypass validation
or send fake speech data to claim a working pipeline.

With the current default selections, replace these placeholders before starting
an actual voice job:

```dotenv
STT_PROVIDER=deepgram
STT_MODEL=nova-3
DEEPGRAM_API_KEY=YOUR_DEEPGRAM_KEY
TTS_PROVIDER=cartesia
TTS_MODEL=sonic-3
CARTESIA_API_KEY=YOUR_CARTESIA_KEY
```

These remain the defaults unless you select Gemini as documented in the linked guide.
Google/Groq/NVIDIA keys alone do not guarantee speech model access or quota.
Text-only UI mode skips microphone acquisition; it does not remove the worker's
STT/TTS configuration requirements or its spoken greeting.

## One-time setup

Open PowerShell in the repository root:

```powershell
cd 'E:\voice agent starter\voice-agent-starter'
corepack pnpm install --frozen-lockfile
cd backend
uv sync --locked --group dev
uv run python -m app.main download-files
cd ..
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-local-livekit.ps1
```

The installer downloads the pinned official Windows v1.13.11 release from GitHub,
checks SHA-256 against its release checksums and extracts into ignored `.local/`.
The command-specific execution-policy option does not change your system policy.
Alternatively, manually download the matching Windows archive and checksums from
the [official releases](https://github.com/livekit/livekit/releases/tag/v1.13.11).
No administrator installation or Docker engine is required for this native option.
Stop an already-running binary before reinstalling it.

## Terminal 1: local LiveKit server

From the repository root:

```powershell
.\.local\livekit\livekit-server.exe --dev --bind 127.0.0.1 --node-ip 127.0.0.1
```

Loopback binding and an explicit advertised loopback IP avoid Docker/WSL virtual
adapters being selected for this laptop-only setup. Signaling uses TCP 7880;
development RTC uses TCP 7881 and UDP 7882. Do not expose dev mode to a LAN or the
internet. A Windows "CPU monitoring unsupported/capacity management disabled"
message does not by itself mean signaling failed; check the subsequent server
startup line and room API/connectivity. This is a development setup, not capacity
validation for production.

### Docker Desktop alternative (not needed with the native binary)

Start Docker Desktop with its Linux engine; `docker version` must show a Server.
Stop the native LiveKit process first to avoid a port conflict. Then:

```powershell
docker run --rm --name voice-starter-livekit `
  -p 127.0.0.1:7880:7880 `
  -p 127.0.0.1:7881:7881 `
  -p 127.0.0.1:7882:7882/udp `
  livekit/livekit-server:v1.13.11 `
  --dev --bind 0.0.0.0 --node-ip 127.0.0.1
```

The bind inside the container differs from the loopback-only host port publishing.
Docker Desktop UDP forwarding/firewall behavior must be verified on your machine;
the native binary is preferred here. Do not start the root infrastructure Compose
stack just for LiveKit: that stack includes optional database/application services,
not a required local LiveKit server.

## Terminal 2: existing Python worker

Only after selecting supported STT/TTS credentials, from the repository root:

```powershell
cd backend
uv run python -m app.check_setup
uv run python -m app.main dev
```

Look for a registered worker connected to `localhost:7880`. Environment variables
already set in your shell override the env file: remove stale cloud `LIVEKIT_*`
overrides or use a clean PowerShell terminal. A placeholder string is not a working
provider key, even if a presence-only configuration check accepts it.
The installed SDK currently accepts `python -m app.main dev`, but warns that this
CLI mode is deprecated in favor of `lk agent dev` for future hot reload. This task
does not change the pinned SDK, add the LiveKit CLI or redesign worker startup.

## Terminal 3: existing Next.js frontend

From the repository root:

```powershell
corepack pnpm dev --hostname 127.0.0.1 --port 3000
```

Open `http://localhost:3000`. Use `pnpm dev`, not `pnpm start`: the existing
unauthenticated `/api/token` endpoint intentionally returns 403 outside development.
Do not remove this restriction. `localhost` is a browser secure-context exception
for microphone permission; plain HTTP at a different LAN IP is not equivalent.

## Manual verification (separate transport from voice)

1. Terminal 1 must report a listening local server. In a spare PowerShell:

   ```powershell
   Test-NetConnection localhost -Port 7880
   $details = Invoke-RestMethod -Method Post -Uri http://localhost:3000/api/token `
     -ContentType application/json -Body '{}'
   $details.serverUrl -eq 'ws://localhost:7880'
   # Do not print or share $details.participantToken.
   ```

   A token response alone does not prove a room joined or an agent was dispatched.

2. With only LiveKit/Next.js running, select **Connect with text**. Confirm the
   header changes to connected, then End session. An absent worker can leave Agent
   Status waiting/connecting and eventually report an unavailable-agent timeout;
   this is not evidence of an active voice agent, even when the header is connected.
   Check the local LiveKit logs for that participant joining/leaving its fresh room.
3. After supported speech keys are configured, run the real worker and connect
   again. Confirm its registration first and then `Voice job received` for the
   new room. With automatic dispatch, the worker must register under a blank name.
   With named dispatch, both env files must match exactly. An accepted dispatch
   API record with no worker/job is not dispatch-delivery verification.
4. Allow the microphone, speak a short question and check interim/final user text,
   generated response, audible TTS, separate input/output meters and Interrupt.
   Check actual provider errors rather than inferring success from an animation.
5. End the session, verify participant disconnection and worker session cleanup,
   then reconnect: the token endpoint should issue a fresh room. Check listener/
   track recovery rather than refreshing to hide an error.

If connecting hangs, check localhost ports, stale shell configuration, browser
network errors, worker registration, Windows firewall and the advertised node IP.
Do not start a cloud tunnel or replace the UI as a workaround.

Official references: [local LiveKit development](https://docs.livekit.io/transport/self-hosting/local/),
[ports](https://docs.livekit.io/transport/self-hosting/ports-firewall/),
[Groq model](https://console.groq.com/docs/model/openai/gpt-oss-20b),
[Groq compatibility](https://console.groq.com/docs/openai).

## Initial transport verification performed in this workspace

On 15 November 2026:

- Official Windows LiveKit v1.13.11 archive downloaded, SHA-256 checked, and binary
  started with loopback bind/advertised IP. Docker Desktop's engine was stopped;
  the Docker alternative above was not tested.
- Local room creation, listing and deletion succeeded with the installed server SDK.
- Real Next.js development `/api/token` returned HTTP 200 with `no-store`. Its JWT
  signature/issuer, room-join grant, automatic dispatch configuration and matching
  `ws://localhost:7880` URL were checked without printing the token.
- The unchanged browser UI joined through **Connect with text**, displayed a connected
  header, and End session disconnected it. The room API confirmed one real browser
  participant and one automatic-dispatch record. With no worker active there were
  zero dispatched jobs, and Agent Status eventually reported no available agent.
- The unchanged `uv run python -m app.main dev` worker subsequently registered with
  blank `agent_name` at the local server. No rooms were active during this check.
  It was stopped cleanly before any speech/provider job, because STT/TTS keys remain
  placeholders. Registration is not a completed agent-job or voice-pipeline test.
- The configured Groq key successfully listed models and included
  `openai/gpt-oss-20b`. No chat completion, tool call or provider audio request was made.
- Backend tests: **346 passed, 10 skipped** (external PostgreSQL/Redis checks and
  opt-in voice scenarios). Ruff lint and format checks passed. All **99 frontend
  tests**, TypeScript, ESLint, shared-contract generation and actual Python fixture
  agreement checks passed. `git diff --check` and installer PowerShell syntax
  checks also passed. No production build was needed for this configuration-only task.

The following reflects the initial transport task, before Gemini integration.
Local LiveKit/Next.js were started as background processes for these checks; do not
start duplicate copies on ports 7880/3000. The worker is intentionally stopped until
supported speech credentials are supplied. Fully verified agent dispatch delivery,
STT/LLM/TTS generation and audible speech still require the steps above; no successful
voice session is claimed. No application/runtime/UI/provider architecture was changed.
