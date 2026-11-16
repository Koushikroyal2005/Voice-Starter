# Audio optimization baseline (Phase 1)

This branch adds an opt-in evaluation workflow, not an audio optimization. Normal
worker/frontend sessions, provider construction, VAD settings, tools, MCP and
configuration are unchanged. No noise removal, isolation or diarization is added.
Stable comparison commit: `ea46b1911a3f0c186c3d092f9289c2f85fdf8d2d`.
No measured voice benchmark is bundled. Automated synthetic/mock tests are not
accuracy or acoustic latency results.

## Local fixtures and offline inventory

Use consented WAV recordings outside Git or in ignored `backend/evaluation.local/`.
Report destinations must also be Git-ignored (for example `evaluation.local/`
when running from `backend/`, or repository-root `.local/`). The CLI validates
the exact report path before starting evaluation and continues to refuse overwrites.
Do not add private audio, reference text, reviews or reports to Git. The default
report directory is ignored; other destinations must be kept private by you.
Reports omit filenames, paths, reference text, transcripts, prompts and keys, but
hashes, hardware and model metadata can still identify an experiment. Keep them
local. No audio is copied or saved by this command.

From the repository root in PowerShell:

```powershell
cd backend
New-Item -ItemType Directory -Force evaluation.local | Out-Null
Copy-Item app/evaluation/baseline.example.json evaluation.local/manifest.json
notepad evaluation.local/manifest.json
# Put consented WAVs and optional UTF-8 reference .txt files beside the manifest.
uv run python -m app.evaluation.baseline --manifest evaluation.local/manifest.json --output evaluation.local/inventory-01.json
```

This default mode makes **no provider requests**, constructs no providers and does
not load credentials/settings. Configuration is therefore `null`, not a claimed
active profile. It validates files and inventories duration, format and SHA-256;
all latency samples are empty, not zero. Missing/invalid fixtures produce explicit
records and exit code 1. Invalid input/consent/configuration gives exit 2. A valid
inventory gives exit 0, meaning inventory only, not voice success. Output must be
a new `.json` file; overwriting is refused to preserve earlier evidence.

Input requirements match the existing replay runner: nonempty mono, 16-bit PCM,
16 kHz WAV, maximum 90 seconds per fixture. No implicit resampling or processing
is performed. Each manifest path is relative to the manifest (absolute local
paths also work). Use a benign fixture ID, never a person's name. Up to 50 unique
fixtures and 1–10 repeats are supported, sequentially, with no automatic retries.

The example covers clean, quiet, fan, television, music/chanting, multiple speakers
and overlapping speakers. It is a template, not seven available recordings.
For each condition include both intended-user speech and a separate no-intended-
user-speech control. A TV voice really is speech: detecting it is not inherently
a VAD false positive. Decide and document whether it should count as an accepted
user turn. For overlap, define whose words belong in the reference before testing.

Keep private experiment notes for microphone/device, gain/distance, speaker count,
languages, playback level, noise/SNR if measured, expected utterances and pause
schedule. Do not invent SNR from an uncalibrated recording. Reuse identical WAV
hashes across comparisons; do not regenerate noise randomly each run.

## Explicitly authorized real-provider replay

Only run the following after approving provider usage/costs and upload consent.
Audio goes to the configured STT provider; resulting text goes to the LLM/TTS
providers. Local infrastructure does not make provider inference offline.
The command itself never accepts provider terms or buys quota.

```powershell
# Configure existing ignored .env; retain your chosen voice profile.
uv run python -m app.cli providers doctor --offline
# If model assets are missing, separately authorize/download them first:
# uv run python -m app.main download-files
$env:RUN_REAL_VOICE_EVAL = 'true'
try {
    uv run python -m app.evaluation.baseline --manifest evaluation.local/manifest.json --replay --allow-provider-calls --repeats 3 --output evaluation.local/baseline-01.json
} finally {
    Remove-Item Env:RUN_REAL_VOICE_EVAL -ErrorAction SilentlyContinue
}
```

Both consent controls are required, even if an earlier shell enabled real tests.
No real API calls were made while implementing this phase. Live replay remains
unverified here until an operator authorizes and runs it with consented fixtures.

This reuses `evaluation.voice.run_voice`, `SessionObserver`, the existing provider
factory/pipeline, safe tools and scoring; it adds no second telemetry exporter.
The replay is roomless, with real-time-paced input and an in-memory paced TTS sink.
It does not touch running frontend/worker processes or change ignored env files.
As in the existing controlled runner, MCP, fallback and installed persistence are
not exercised; only time, calculator and the demo sequential tool are allowlisted.
That evaluation boundary is recorded in the report, not applied to normal sessions.
The actual resolved profile/models/languages/voices and acknowledged overrides are
allowlisted into the report; no endpoint, credential or complete Settings dump is
serialized. Each replay has the existing 120-second deadline; the existing runner
waits for two seconds of stable listening/idle after input. Very late transcripts
can therefore be missed: inspect incomplete runs rather than calling them silence.

## Metric definitions and limits

Metrics come from installed LiveKit Agents 1.8.12 events through the existing
observer. See [LiveKit data hooks](https://docs.livekit.io/testing/observability/data/)
and [session traces](https://docs.livekit.io/reference/agents/session-traces/).
SDK turn metrics and provider request metrics are different boundaries; do not
add overlapping stages to manufacture an end-to-end total.

- `stt_final`: SDK final transcription delay from the end of speech, when supplied.
  `stt_final_from_speech_start` includes utterance duration and is **not** pure STT
  service time. `stt_interim` is absent for batch Whisper; no interim is fabricated.
- `llm_ttft`: existing SDK `llm_node_ttft`; `tts_first_audio`: SDK `tts_node_ttfb`.
  NVIDIA's adapter validates the complete WAV before emitting PCM, so this includes
  that boundary, not a promise of native request streaming.
- `response_first_audio`: SDK end-of-user-speech to first response audio. `full_turn`
  includes response playback in the paced server sink, not the laptop speakers.
- `interruption_stop`: the existing user-speaking to agent-no-longer-speaking
  **state-transition proxy**. It is not confirmed physical audio-stop latency,
  nor proof that speaking was an intentional interruption. Some interruptions
  have no valid sample. Explicit RPC playback timing is not measured by replay.
- Actual VAD speech-start **detection delay** is unmeasured: there is no calibrated
  acoustic-onset timestamp in these captured events. A user-state event timestamp
  or VAD inference duration is not interchangeable with onset detection delay.
  Physical interruption-to-audio-stop and microphone-to-ear latency also remain
  explicitly unmeasured, not zero. They require synchronized acoustic/reference
  capture and human acceptance; this phase adds no recording or timestamp guesses.
- `observations`: session speech-start transitions, unique committed user messages,
  interrupted assistant messages. These are counts, not judgments of correctness.
- Resource window: actual `process_time` CPU seconds over `perf_counter` wall
  seconds, average percent of **one logical core** (can exceed 100 with threads).
  Windows exposes working-set snapshots before/after and process-lifetime peak
  RSS via native APIs. Unix reports lifetime peak RSS and `null` for current RSS.
  These are not per-fixture peak sampling, GPU usage, remote provider usage,
  whole-laptop usage or child/browser process totals. Initial import cost before
  the window is excluded; provider/session creation and cleanup are included.

Each stage reports valid samples, count, invalid/missing count and nearest-rank
p50/p95 in seconds. Missing/non-finite/negative samples are not coerced to zero.
Aligned `sample_context` retains status, turn and tool-call IDs so interrupted and
completed samples can be separated rather than silently pooled.
No sample means `null` quantiles. A tiny sample's p95 is not statistically robust.
Failures remain explicit; do not remove them from a performance comparison.
Report source hashes distinguish uncommitted runner/pipeline versions at the same
Git commit. Hardware, Python/SDK version, concurrency, repeats and fixture hashes
are included. Background load, network and hosted-model revisions remain factors.

## Accuracy and human judgment

Optional `reference_file` supplies exact intended user text. Existing NFC,
case-folded WER/CER scoring is reused, with punctuation retained. No reference
means no accuracy score, not perfect recognition. WER can exceed 1.0. Review
language/tokenization and overlap boundaries with a fluent speaker.

Use private reviews keyed by fixture ID and zero-based repeat index:

```json
{
  "fan:0": {
    "false_speech_activations": 2,
    "false_accepted_user_turns": 1,
    "false_interruptions": 0,
    "missed_genuine_speech": 0
  }
}
```

These numbers are an **illustrative review format, not measured results**. Supply
`--reviews evaluation.local/reviews.json` on a subsequent explicitly authorized
run, or compare privately with the already saved JSON; do not rerun paid inference
just to attach review labels. Leave unreviewed values absent/null. Zero means
reviewed and none observed. Only nonnegative integer counts are accepted.
Counts are marked human-review judgments separately from observed SDK counts.
Never infer false positives just from a filename, noise category or empty text.
Define the denominator (expected utterances, control duration, interruption
opportunities) in private notes before deriving rates. No rate is invented here.

False activation means an SDK speech-start without intended speech; false accepted
turn means a committed unwanted message; false interruption means unintended
cancellation/playback interruption; a missed utterance requires a reviewed genuine
speech opportunity. Fan/TV/music labels alone cannot establish these outcomes.
Roomless replay has no audible playback for review: use consented browser tests
and correlated local telemetry for intended-vs-background and interruption labels.

## Comparing future optimizations

Freeze the same manifest/reference policy, file hashes, provider profile, tool
policy, hardware, warm/cold conditions, concurrency and background load. Record
each code revision and source hashes. Run repeats and retain all successes,
timeouts, failures, nulls and human review coverage. Compare per condition and per
stage; never pool clean/overlap, interrupted/completed or different model runs
without labeling them. Account for lifetime RSS contamination from earlier trials;
use a fresh process for each fixture when comparing memory.
Noise-only controls may legitimately have no response: `incomplete_or_failed`
means no complete response was observed, not proof that the control failed its
human-defined acceptance criteria. Keep the observations and review them.

This establishes a reproducible measurement workflow, not claimed performance
targets. Before any future audio-model changes, collect authorized baseline JSON
and manual accuracy/physical timing evidence. Existing runtime regression checks:

```powershell
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
cd ..
corepack pnpm test
corepack pnpm typecheck
corepack pnpm lint
corepack pnpm contracts:check
corepack pnpm contracts:fixtures:check
corepack pnpm security:secrets
```

## Implementation verification (16 November 2026)

Full backend regression run: 482 passed, 10 skipped. After two final evaluation
hook cleanup tests and streamed fixture hashing were added, the focused baseline
and existing bootstrap suite passed 44 tests. Ruff lint and format checks passed.
Frontend regression tests: 101 passed; TypeScript, ESLint, contracts, Python/TS
fixtures and the existing tracked-secret heuristic passed. Git whitespace checks
passed. No frontend or production runtime modules were modified.

The offline CLI was executed against the pre-existing 1.56-second synthetic local
WAV: it reported inventory only and zero latency samples, as intended. Its JSON
and manifest remain ignored local artifacts. These are tool-validation results,
not voice performance/accuracy benchmarks. No provider calls, private recordings,
physical timing tests or model downloads were performed for this implementation.
