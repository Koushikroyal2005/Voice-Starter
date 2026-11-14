# Python voice backend

Single LiveKit agent using real provider plugins: Deepgram Nova-3 STT →
OpenAI-compatible Chat Completions LLM (default `gpt-4.1-mini`) → Cartesia Sonic-3
TTS. Silero VAD supplies local speech boundaries and interruption detection.
Python 3.13 is pinned for Windows; `uv.lock` records resolved dependencies.

## Windows PowerShell

From the repository root:

```powershell
winget install --id astral-sh.uv --exact
# Reopen PowerShell after installation if uv is not on PATH.
cd backend
uv python install 3.13
uv sync --locked
Copy-Item .env.example .env
notepad .env
# Fill in real credentials, save, then download the local speech model:
uv run python -m livekit.agents download-files
uv run python -m app.main dev
```

No virtual-environment activation or PowerShell execution-policy change is needed.
`uv sync --locked` installs runtime and development dependencies into `.venv`.
The SDK module's `download-files` command prepares local model assets; it does not
require provider credentials. Run `uv run python -m app.main start` for the
SDK's production startup mode (deployment hardening is separate).

## Environment

Copy `.env.example` to **backend/.env**. The loader uses that exact path regardless
of the current directory. Process environment variables override the file.
Secrets are never placed in source or printed by configuration validation.
`.env`, environment variants, `.venv`, and caches are ignored by Git.

Required: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`,
`DEEPGRAM_API_KEY`, `OPENAI_API_KEY`, `CARTESIA_API_KEY`.
`OPENAI_API_KEY` may hold the key for a compatible provider when `LLM_BASE_URL`
and `LLM_MODEL` are set accordingly. Compatibility of a third-party endpoint
must be verified with that endpoint; the initial documented combination uses OpenAI.

Optional: `AGENT_NAME` (blank for automatic dispatch), `STT_MODEL`,
`STT_LANGUAGE`, `LLM_MODEL`, `LLM_BASE_URL`, `TTS_MODEL`, `TTS_VOICE`,
`AGENT_INSTRUCTIONS`. Defaults are shown in `.env.example`. Blank optional values
use defaults. Customize the demo instructions in `app/agents/instructions.py`
or set `AGENT_INSTRUCTIONS` in the environment.

## Connect the existing frontend

Use the same LiveKit project for the frontend and backend. In the repository's
existing root `.env.local`, configure `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and
`LIVEKIT_API_SECRET`; leave `LIVEKIT_TOKEN_SERVER_ID` blank to use `/api/token`.
The frontend otherwise prioritizes its development token server or falls back to
the LiveKit homepage demo, which will not connect to this worker.

Leave `AGENT_NAME` blank in both environments for automatic dispatch. For explicit
dispatch, set the same nonempty name (for example `voice-starter`) in both files
and restart both processes. The frontend's Session API already sends `room_config`
and its token route preserves it. Do not run competing automatic-dispatch workers
for this demo in the same project.

In a second PowerShell window, use the frontend's existing setup:

```powershell
# From the repository root; pnpm 9.15.9 and Node 24 are the frontend requirements.
pnpm install --frozen-lockfile
pnpm dev
```

Open http://localhost:3000, click Start call, allow microphone access, and say a
short question. Check that the worker accepts the job, the agent greets you,
speech receives a relevant spoken response, the transcript updates, interruptions
work, and leaving ends the session. This is a manual, billable integration check
requiring valid accounts and microphone/network access. Unit tests do not prove
STT, LLM, TTS, room dispatch, or audible playback work end to end.

## Checks

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Tests use synthetic credentials and never call provider APIs. They cover missing
credentials, URL validation, defaults, overrides, secret-safe representation,
and loading the backend environment file without overriding process variables.
The SDK wiring tests additionally construct the real provider objects, load Silero,
and verify callback serialization. These are local checks, not voice-call tests.

Implementation verification on Windows with Python 3.13.14 and Agents 1.8.12:
configuration tests passed (20); Ruff lint and formatting passed; CLI help,
missing-credential errors, SDK constructor signatures, and model preparation
were checked. An initial full run reached 21 passed with one test-cleanup error
(calling a nonexistent Silero VAD `aclose` method). That cleanup was corrected;
the final full rerun was not completed because permission for running native SDK
tests outside the sandbox was declined. Run the commands above locally to confirm.
No real provider credentials were available, so end-to-end voice is unverified.

## Files

- `app/main.py`: SDK CLI entrypoint, worker registration and session lifecycle.
- `app/agents/demo.py`: single Agent subclass.
- `app/agents/instructions.py`: safe, concise demo prompt.
- `app/config/settings.py`: dotenv loading, environment parsing and validation.
- `app/providers/pipeline.py`: STT, LLM, TTS and VAD construction.
- `app/tools/__init__.py`, `app/services/__init__.py`: reserved namespaces only.
- `tests/test_settings.py`: credential-free configuration tests.
- `tests/test_sdk_wiring.py`: real SDK construction and Windows callback
  serialization checks, without calling provider APIs.
- Package `__init__.py` files: Python package markers and module descriptions.
- `.env.example`: placeholders and optional settings.
- `.gitignore`: backend-specific secrets, environments and caches.
- `.python-version`: Python 3.13 selection.
- `pyproject.toml`: dependencies, development tools and check configuration.
- `uv.lock`: reproducible dependency resolution; generated by uv.

## Official references

- [Python starter](https://github.com/livekit-examples/agent-starter-python)
- [Deepgram plugin](https://docs.livekit.io/agents/models/stt/deepgram/)
- [OpenAI plugin and compatible endpoints](https://docs.livekit.io/agents/models/llm/openai/)
- [Cartesia plugin](https://docs.livekit.io/agents/models/tts/cartesia/)
- [Agent sessions](https://docs.livekit.io/agents/logic/sessions/)
- [Agent dispatch](https://docs.livekit.io/agents/server/agent-dispatch/)

Implementation follows `AgentServer`, `rtc_session`, `AgentSession`, `Agent`, and
`cli.run_app` conventions. Chat Completions is selected for replaceable compatible
LLM endpoints. No MCP, business API, database, cache, or extra agent is started.
