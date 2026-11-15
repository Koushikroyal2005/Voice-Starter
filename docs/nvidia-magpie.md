# NVIDIA Magpie hosted TTS

Magpie was added only after a real authenticated request returned HTTP 200 and a
valid, nonempty mono 16-bit PCM WAV at 44,100 Hz. The test phrase was synthetic;
no private conversation or physical microphone recording was used for that check.

## Local configuration

Keep keys in ignored `backend/.env`:

```dotenv
GROQ_API_KEY=replace-with-groq-key
NVIDIA_API_KEY=replace-with-nvidia-key
VOICE_PROFILE=groq_nvidia
```

Do not add STT/LLM/TTS overrides. `config/profiles/groq_nvidia.yaml` selects Groq
Whisper, Groq GPT-OSS and NVIDIA Magpie. `config/providers/nvidia.yaml` supplies
Magpie model, endpoint, language and voice. Existing profiles remain available.

From `backend/` in PowerShell:

```powershell
uv sync --locked --all-extras
uv run python -m app.cli providers doctor --offline
# Opt-in real inference using your provider allowance:
uv run python -m app.cli providers doctor --live
uv run python -m app.main dev
```

Run only one worker. Keep the existing Next.js server and local LiveKit server;
the native LiveKit command from the repository root is:

```powershell
.\.local\livekit\livekit-server.exe --dev --config livekit.local.yaml
```

## Verified speech API contract

The [official hosted API](https://build.nvidia.com/nvidia/magpie-tts-multilingual/api)
documents the function-specific host:

`https://877104f7-e885-42b9-8de8-f6e4c6303969.invocation.api.nvcf.nvidia.com`

Authentication is `Authorization: Bearer <NVIDIA_API_KEY>`. The adapter posts
multipart form fields to `/v1/audio/synthesize`: `text`, `language=en-US`,
`voice=Magpie-Multilingual.EN-US.Aria`, `encoding=LINEAR_PCM`, and
`sample_rate_hz=44100`. The model is selected by the function endpoint, not by an
OpenAI LLM request. No LLM inference endpoint is reused for speech.

`GET /v1/audio/list_voices` returned HTTP 200 and these English voices: Aria,
Diego, Isabela, Jason, Leo, Louise, Mia, Pascal, Ray and Sofia (each prefixed with
`Magpie-Multilingual.EN-US.`). These names are listed in the catalog. Available
voice locales were AR-XA, DE-DE, EN-US, ES-US, FR-FR, HI-IN, IT-IT, JA-JP, KO-KR,
PT-BR, VI-VN and ZH-CN. Only English Aria synthesis was tested; Telugu is not in
that returned locale list. Do not claim tested speech quality for other locales.

## LiveKit behavior

`NvidiaMagpieTTS` implements the installed LiveKit 1.8.12 `tts.TTS` and
`tts.ChunkedStream` interfaces. This adapter uses the verified HTTP full-text
request, **not native streaming text input**. LiveKit retains sentence adaptation,
audio events, interruption, playback cancellation and SDK retry policy.

The response must be uncompressed mono 16-bit PCM WAV at 44.1 kHz. The adapter
validates headers, frame count, complete PCM data and a 16 MiB response bound,
strips the WAV container and emits signed little-endian PCM through LiveKit's
native `AudioEmitter`. No lossy conversion, external decoder or GPU is needed.
Audio becomes available after the HTTP response is validated. LiveKit handles
resampling for room output. The separate Riva gRPC API supports streamed output;
it is not implemented or claimed by this HTTP adapter.

Each request has the configured deadline. Cancellation closes the HTTP response;
remote inference already accepted may continue. HTTP error bodies and private text
are never propagated. 401 means credential rejection; 403 indicates restricted
access; 402 indicates payment required; 404 may indicate a stale function/model
endpoint; 429 is quota exhaustion. No paid plan is enabled automatically.

## Browser acceptance

Open `http://localhost:3000`, start a new session and permit microphone access.
Ask to calculate two plus three, verify a final user transcript, completed tool
card, agent transcript and audible answer. Interrupt during a long reply, ask a
second question, end and reconnect. Physical microphone and speaker behavior
requires the laptop user if browser automation cannot access the audio devices.

Provider doctor checks are not browser acceptance, voice quality benchmarks,
physical interruption tests or fallback verification. Real test outcomes are
reported separately in the implementation handoff.

## Verification on 15 November 2026

- Hosted access probe: HTTP 200; 24,576 frames / 0.557 seconds of valid mono
  16-bit PCM WAV at 44,100 Hz. Voice listing also returned HTTP 200.
- Provider doctor: offline passed with no overrides; live Groq STT, Groq LLM
  streaming and native NVIDIA adapter synthesis all passed. The native adapter
  emitted 15 audio frames for the short doctor phrase.
- Local room diagnostic: public synthetic WAV input produced one final STT
  transcript, completed tool events and 4,171 nonempty received audio frames.
  Interrupt RPC, disconnect and reconnect dispatch passed. Frame count is an
  observed transport result, not a latency or quality benchmark.
- Browser: connected, completed calculator (2 + 3 = 5) and time tools across two
  turns, showed final agent transcripts and a playing, unmuted live audio track.
  Interrupt control acknowledged and ending returned to the idle screen.
- Backend: 450 passed, 10 skipped; Ruff lint and formatting passed. Public
  contracts and tracked-secret checks passed. Skipped service/scenario tests were
  not counted as real provider or browser verification.
- Physical microphone input, speaker audibility and spoken barge-in require user
  confirmation; synthetic audio and a playing audio element do not verify these.
