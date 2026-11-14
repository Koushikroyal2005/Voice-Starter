# Repeatable voice evaluation

The checked-in [scenario manifest](../backend/app/evaluation/scenarios.json) covers
English, multilingual speech, Telugu-English code switching, noise, long pauses,
interruption, ambiguous speech, tool failure, model timeout, TTS failure and four
simultaneous sessions. These are **test definitions**, not benchmark results.

## Deterministic tests (no API calls)

```powershell
cd 'E:\voice agent starter\voice-agent-starter\backend'
uv sync --extra mcp --extra telemetry
uv run pytest -q
uv run python -m app.evaluation.run --list
```

Mocked SDK events test timing definitions, out-of-order turn attribution, missing
measurements, concurrent ID isolation and safe browser errors. Test-only native
LiveKit LLM/TTS subclasses inject timeout/connection errors to verify bounded retry,
native fallback, no fallback after partial text, and error events. Tool faults use
the real executor and structured failures. Synthetic timings in assertions are
fixtures, never measured acoustic performance. These tests do not prove recognition
quality under noise, multilingual accuracy or genuine browser interruption quality.

## Opt-in real-provider audio replay

Supply your own consented mono, 16-bit PCM, 16 kHz WAV files, at most 90 seconds
each. Name them `english.wav`, `multilingual.wav`, `telugu_english.wav`,
`background_noise.wav`, `long_pauses.wav`, `interruption.wav`, `ambiguous.wav` and
`simultaneous.wav` in an ignored local directory. The English/default reference
phrases are in the manifest. A same-named UTF-8 `.txt` file overrides the reference.
Use a fixed recording, speaker, volume, noise source/SNR and pause schedule across
runs; record those fixture properties/version in your private experiment notes.
Do not check private audio or transcripts into this repository.

```powershell
# Existing backend/.env must contain real LiveKit/STT/LLM/TTS configuration.
uv run python -m app.main download-files
$env:RUN_REAL_VOICE_EVAL = 'true'
$env:VOICE_EVAL_FIXTURES = (Resolve-Path '.\evaluation.local').Path
uv run python -m app.evaluation.run --fixtures "$env:VOICE_EVAL_FIXTURES" --scenario english
uv run pytest tests/test_voice_integration.py -q
# Run all audio scenarios, bounded concurrency (1–8):
uv run python -m app.evaluation.run --fixtures "$env:VOICE_EVAL_FIXTURES" --concurrency 4
```

This sends real audio through the existing STT → LLM/tools → TTS `AgentSession`
pipeline and consumes actual generated audio frames in a timed, in-memory sink.
Nothing is played or recorded. It is a **roomless server replay**, not a room join,
microphone device test, network load test or browser playback benchmark. It needs
provider credentials/quota but does not join LiveKit rooms; shared Settings still
validates LiveKit credentials. MCP, persistence and provider fallback are omitted
from this controlled replay; only the three safe built-in tools are allowlisted.
Calls incur charges. Each replay has a 120-second deadline and local input is paced
at real-time speed. Missing fixtures are `not_run`/skipped, not successful tests.
Failures and absent first audio are not reported as successful measurements.

The three injected-fault cases are unit-only and explicitly `not_run` by the real
runner; do not intentionally break production provider accounts. Simultaneous runs
use four independent sessions with a shared concurrency cap. An interruption WAV
must include a second utterance timed to overlap a long answer; inspect actual
`interruption_stop` events rather than assuming overlap happened. Long-pause tests
must be reviewed for premature replies. No bundled corpus or measured baseline is
claimed. Real replay integration remains unverified until credentials/fixtures exist.

The manifest uses Spanish for the multilingual case and `multi` for code switching.
Not all STT models support that tag, Telugu, or Telugu-English switching. Choose a
verified provider/model/language setup for each case, and adapt the fixture/manifest
for that configuration. Unsupported coverage is a failure/limitation to report, not
an English-only mock to present as Telugu speech recognition. Likewise validate TTS
language/voice support and review output with a fluent speaker.

## Scores and human review

Reports contain metadata and numeric scores, not transcript or generated text:

- NFC-normalized, case-folded word and character error rates against the reference.
  Punctuation is retained; freeze a normalization policy when comparing runs.
  WER/CER are imperfect for Telugu orthography/code-switching; retain fluent review.
- Tool success rate: completed calls divided by terminal observed calls. Unrun or
  denied calls remain visible; an empty denominator is `null`, not 100%.
- First-audio and full-turn latencies: arrays of actual SDK observations, in seconds.
  Keep interrupted/failed outcomes separate; do not omit them when publishing a study.
- Intent accuracy and task completion: `null` until independently reviewed. The
  manifest's expected tool is a scenario specification, not an inferred success.

You can supply a private JSON review file to `--reviews`:

```json
{"english:0":{"intent_correct":true,"task_completed":true}}
```

Only real JSON booleans are accepted as review scores. Review the actual session in
a separate consented environment before assigning them; the score report deliberately
does not retain conversation text. Aggregate intent/task scores only over reviewed
cases and publish the reviewed/unreviewed counts. Repeat fixtures across model/provider
configurations and report sample counts, failure rates and p50/p95 rather than treating
a single call as a benchmark. Reports define no numeric targets: set product-specific
targets in experiment notes and keep them labeled separately from measured values.

For a complete browser test, start the existing frontend and worker, speak each
scenario, inspect the correlated SDK timeline, verify transcript and tool outcome,
listen to TTS, test mute/disconnect/reconnect, and compare interruption handling.
That manual path and browser microphone-to-ear latency are not validated by roomless
replay. See the [observability guide](observability.md) for debugging stages.
