# Voice Workbench

The root Next.js app remains in place. `components/app/view-controller.tsx` composes
the domain-neutral shell in `components/voice/voice-workbench.tsx`. The existing
Agents UI remains available; there is no separate audio, chat or WebRTC stack.

## Components

- `voice-controls.tsx`: VoiceControls composes the existing AgentControlBar for
  microphone mute, device selection and optional text input. Adds connect,
  text-only connect, cancel connection, interrupt (also Escape) and end controls.
- `audio-visualizer.tsx`: AudioVisualizer composes the existing aura, bar, grid,
  radial and wave components. Input and output have **separate track references**.
- `panels.tsx`: LiveTranscript wraps AgentChatTranscript; AgentStatus,
  ConnectionStatus, ConversationTimeline, ToolActivityCard and ResultCard are
  reusable presentation components. ResultCard renders plain text, not HTML.
  LanguageSelector accepts verified options and an application-provided callback.
- `state.ts`: pure, testable state mapping and bounded worker-event validation.
- `use-voice-workbench.ts`: public facade, native state mapping and bounded timeline.
- `hooks/use-voice-lifecycle.ts`: serialized commands, startup cancellation and
  lifecycle error handling, using the existing LiveKit session methods.
- `hooks/use-workbench-sync.ts`: generation-scoped room listeners, snapshots,
  confirmation/interruption RPC and verified public application configuration.
  See [frontend lifecycle refactoring](frontend-session-lifecycle.md).
- `backend/app/services/workbench.py`: authenticated interruption RPC, actual
  tool/interruption event forwarding, human confirmation RPC and language metadata.
  No activity or results are fabricated. See [tool orchestration](tool-orchestration.md).

## State model

LiveKit remains authoritative. `useSessionContext().connectionState` controls
connected, connecting and reconnecting; `useAgent().state` controls listening,
thinking and speaking. The reducer tracks explicit command phases, errors and
confirmed interruptions, not unrelated loading booleans.

Priority: ending → reconnecting → error → starting/connecting → disconnected/idle
→ confirmed interrupted → human confirmation → actual running tool → agent state. Agent initializing
or waiting for dispatch displays connecting. A confirmed interruption persists
until the next native agent-state transition. Muting does not claim interruption.

The timeline records these derived transitions in memory (last 80), not analytics
or persistent records. Tool and result lists are bounded; a new session clears
them. Disconnect marks unfinished tool displays unknown; it does not claim that
remote operations were cancelled or business side effects rolled back.

`voice.interrupt` authenticates the caller against `session.room_io.linked_participant`.
It cancels safe tool work and pending approvals, refuses to force-stop protected
operations, then awaits `session.interrupt(force=True)`, which cancels agent speech
and updates interrupted conversation history. It does not merely hide a waveform
or mute browser output. LiveKit retains automatic spoken barge-in handling.
Interruption cannot undo external tool side effects already committed.

## Real audio and transcripts

`useSessionContext().local.microphoneTrack` supplies microphone input;
`useAgent().microphoneTrack` supplies the agent's subscribed output track.
Track publications and mute state determine whether a meter is active. Missing,
unsubscribed or muted tracks render a static line. No random data is supplied.

Bar/grid/radial use the existing LiveKit multiband analyser. Aura/wave use
`useTrackVolume` and measured energy to modulate their shaders. Their previous
session-state idle pulses were removed: speed/amplitude are zero at zero volume.
These are **stylized energy visualizations, not PCM oscilloscope waveforms**.
Reduced-motion preference uses the analyser-based bar meter instead of moving shader fields.
The wrapper selects the audio-driven rendering branch instead of synthetic
thinking/listening loader animations. Device/audio handling remains SDK-owned.

`useSessionMessages` owns transcription subscriptions and native `lk.chat` text.
We do not register a competing `lk.transcription` stream handler. The existing
transcript displays `lk.transcription_final=false` as live/partial and marks final
transcripts separately from text messages. Interim availability depends on the
chosen STT integration/configuration. No partials are invented for batch STT.

## Tools, results and language

Worker events use reliable data topic `voice.workbench.v1`. The frontend accepts
only packets from the currently connected agent, bounds payloads and validates
schemas. The deterministic executor supplies real action states; SDK
`tool_execution_updated` events cover native selection and SDK-level failures;
raw arguments, result contents and provider exceptions are never auto-forwarded.
The current agent exposes safe clock/calculator tools and a sequential workflow.
Approval cards appear only for real sensitive tool definitions, not fabricated writes.

An application can explicitly publish a reviewed, non-sensitive result to the
linked participant with `{type:"result", id, title, text}` on the same topic, or
reuse ResultCard with its own data. Do not forward private domain data by default.

**Live language switching is not enabled by this worker.** LanguageSelector
therefore displays the actual worker's STT language read-only (or Worker default
before dispatch). Configure provider language on the backend and restart it.
An application may pass `languages` and `onChange` only after implementing a
verified server-side STT/TTS update for its providers. Changing a browser dropdown
alone must never pretend to change remote speech models.

## Run on Windows

Use the existing root `.env.local` and `backend/.env` setup described in README.
Never put provider keys or LiveKit API secrets in `NEXT_PUBLIC_*` variables.

Terminal 1, from the repository root:

```powershell
corepack pnpm install --frozen-lockfile
corepack pnpm dev
```

Terminal 2, from the repository root:

```powershell
cd backend
uv sync --locked --group dev
uv run python -m app.main download-files
uv run python -m app.main dev
```

Open http://localhost:3000. The existing token endpoint remains development-only.

## Verification

```powershell
# repository root
corepack pnpm test
corepack pnpm exec tsc --noEmit --incremental false
corepack pnpm build
cd backend
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app/services/workbench.py tests/test_workbench.py tests/test_worker_lifecycle.py
```

Offline tests cover derived states, reconnecting, interruption RPC authorization,
actual SDK cancellation invocation, event validation, sanitized tool events,
configuration errors and token security. Mocks verify contracts, **not** audio
quality, provider inference, live cancellation or successful room dispatch.

Credentialed manual checks required:

1. Start voice, confirm worker job; speak and check partial → final user text,
   LLM output, audible TTS and separate input/output meters for all five styles.
2. Mute/unmute and change microphone; confirm input stops while output continues.
3. Interrupt a long reply using the button, Escape and spoken barge-in; confirm
   audible cancellation, no obsolete queued reply, then ask another question.
4. Connect with text with microphone permission denied; send with Enter, newline
   with Shift+Enter, and recover a failed send without losing the draft.
5. Test denied/no/busy microphone, offline network, expired/invalid credentials,
   agent failure and reconnect; end and restart without stale tracks/messages.
6. Ask for time, arithmetic and a time-stamped calculation; verify actual tool
   selection/running/completed/error cards. Test sensitive approvals only with a
   reviewed use-case tool; no fake write is registered for UI demonstration.
7. Test mobile/desktop, light/dark/system theme, keyboard focus and screen reader
   labels. Changing visualizer without a track must not create audio activity.

Do not claim the live pipeline or every interaction is verified without real
credentials, an actual microphone/speaker and the credentialed checks above.

### Initial workbench checks performed in this workspace

The subsequent tool-orchestration phase adds further tests described in
[tool orchestration](tool-orchestration.md).

- Backend: 59 tests passed, including linked-participant RPC authorization,
  SDK interruption invocation, tool event sanitization and shutdown cleanup.
- Frontend: offline token/state/event/error contracts; TypeScript and production
  build checks. Two existing visualizer lint warnings remain.
- Browser: desktop and 390px mobile layout (no horizontal overflow), all five
  selectors with no track (no canvas/audio animation), light/dark/system theme,
  keyboard focus, failed voice/text startup with controls available for retry,
  and the production token endpoint's intentional 403 restriction.
- No root `.env.local` or `backend/.env` was present. Live dispatch, actual partial
  transcription, microphone/device changes, audible TTS, barge-in, network
  reconnection and real tool execution remain unverified without credentials.
