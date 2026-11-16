# RNNoise local Windows evaluation

Date: 16 November 2026. Branch: `voice-optimization`, starting at
`42f6380c279834f98b3ef182c68959cdedea2607`. No LiveKit integration, provider API
calls, credentials, frontend or runtime configuration changes.

## Implementation and compatibility

The optional processor uses the genuine RNNoise C ABI from the Windows x64
`pyrnnoise==0.4.5` wheel. The wheel loaded and synthesized all five outputs on
Windows 11 AMD64, Python 3.13.14, Intel i5-1035G1, eight logical CPUs.
No compiler, GPU, ONNX Runtime, PyTorch or separate model download was needed.
Other operating systems have library names in the loader but were not tested.
Windows ARM64 and 32-bit Windows were not tested or established as supported.

Sources inspected:

- [Xiph RNNoise](https://github.com/xiph/rnnoise),
  [C API](https://github.com/xiph/rnnoise/blob/70f1d25/include/rnnoise.h),
  [algorithm implementation](https://github.com/xiph/rnnoise/blob/70f1d25/src/denoise.c).
- [pyrnnoise implementation and Windows library loading](https://github.com/pengzhendong/pyrnnoise/blob/master/pyrnnoise/rnnoise.py)
  and [0.4.5 distribution](https://pypi.org/project/pyrnnoise/0.4.5/).
- [RNNoise BSD-3-Clause license](https://github.com/xiph/rnnoise/blob/70f1d25/COPYING)
  and [wrapper Apache-2.0 license](https://github.com/pengzhendong/pyrnnoise/blob/master/LICENSE).

Preserve upstream notices if redistributing the DLL. The DLL/default model is
third-party binary code; this experiment does not vendor or redistribute it.
The compressed Windows wheel is 13,263,766 bytes; its DLL is 14,825,472 bytes.
Measured DLL SHA-256:
`06770aeb8855ef942b5dcdb436f84dfdd5867b716ba4b4c8a2c66ade03197f31`.

`backend/app/audio/processors/rnnoise.py` implements the existing processor
contract. It accepts only mono little-endian PCM16 at 48 kHz, at most one second
per call. Internally it buffers 480 samples (10 ms). Incomplete frames return
empty output until enough samples arrive. Flush zero-pads a partial frame and
trims only that padding. It is idempotent and releases native state. Close also
releases state, once; a closed/flushed stream cannot resume. Use a context manager
or explicit close, including when abandoning a stream. Enrollment is explicitly
unsupported: RNNoise cannot identify an enrolled target speaker.

The C API receives floating-point values in **PCM16 amplitude units**, not
normalized amplitudes. Non-finite output/probabilities fail closed; output is
clipped rather than integer-wrapped. Errors are sanitized. The native frame size
is checked before allocation. Each instance owns one stream; concurrent use of
one instance is unsupported.

The existing `AudioFormat` already supports 48 kHz, so no shared interface change
or implicit resampling was necessary. The evaluator has a strict 48 kHz reader
because the existing baseline/VoxLock readers deliberately require 16 kHz. It
reuses the existing manifest validation, processor timing, resource window,
hardware/revision reporting, ignored-output guard and signal comparison. Existing
VoxLock code is unchanged. No new telemetry system or processor registry exists.

Native output is delayed. Estimated alignment was **960 samples / 20 ms** in all
five fixtures, obtained using bounded offline cross-correlation against each
known target (0–40 ms, four-sample resolution). This is not physical microphone
latency or a promise of future callback timing. The processor emits uncorrected
native output of the same total duration as the input: it does not emit the
filter tail after that duration. The report retains raw scores and separately
reports delay-aligned scores, excluding the last 20 ms of the reference. First
output after 1,920 input samples here reflects the evaluator's 40 ms batches,
not the native 10 ms frame size or a measured speech-detection delay.

## Optional environment and commands

From the repository root in PowerShell:

```powershell
uv venv .local/rnnoise/.venv --python 3.13
uv pip install --python .local/rnnoise/.venv/Scripts/python.exe --no-deps -r backend/requirements-rnnoise.txt
$env:PYTHONPATH = 'backend'
```

The adapter locates only the installed wheel's native library with distribution
metadata; it does not import the package's plotting/file-conversion frontend.
`--no-deps` intentionally avoids its unrelated audiolab/FFmpeg, matplotlib, click
and tqdm dependency stack. NumPy is used for scoring; soxr is used only to prepare
48 kHz fixtures. Neither is required by the processor's ctypes/stdlib runtime.
These three packages are not added to the normal backend dependency graph.

Reuse the existing ignored synthetic fixtures (see the VoxLock guide to generate
them locally if absent), without altering those originals:

```powershell
.local/rnnoise/.venv/Scripts/python.exe -m app.evaluation.rnnoise_fixtures --source .local/voxlock/synthetic/fixtures --output-dir .local/rnnoise/fixtures
foreach ($case in @('clean', 'quiet', 'noise', 'background', 'overlap')) {
    .local/rnnoise/.venv/Scripts/python.exe -m app.evaluation.rnnoise --manifest .local/rnnoise/fixtures/manifest.json --case $case --output-dir .local/rnnoise/results/$case
    if ($LASTEXITCODE -ne 0) { throw "Evaluation failed: $case" }
}
```

Each destination must be Git-ignored and absent; use new output directories for
repeat runs. Each run writes private `output.wav` and structured `report.json`.
Never stage recordings, binaries, model files, generated manifests or reports.
The evaluator does not read `.env` or make provider inference calls.

To supply consented local recordings, create an ignored version-1 baseline
manifest with `fixtures`, each containing `id`, supported `category`, and `wav`.
Supply mono 48 kHz PCM16 WAVs, nonempty and at most 15 seconds. Optional
`target_wav` must be an equal-length, aligned clean target; do not substitute an
unrelated recording. Optional `background_only_intervals` contains start/end
seconds during which the target is genuinely silent. Scores without references
do not establish target preservation. Use the same CLI with that manifest.

## Actual measurements

Five separate, unpaced, local CPU runs, each 12 seconds including silence,
300 batches of 40 ms, one native stream per process. Timing covers the ctypes
adapter plus reused resource checks and flush, not just the neural network.
Initialization is separately recorded. These are single runs, not confidence
intervals, controlled-load tests or guarantees of hard real-time operation.
Results below were read from generated reports, not hardcoded into the evaluator.

- Clean synthetic David speech: processing **2.097 s**, RTF **0.175**;
  batch p95 **10.89 ms**, max **232.13 ms**, **1/300** over 40 ms.
- Quiet synthetic target (20% clean amplitude, no background): **1.061 s**,
  RTF **0.088**; p95 **7.37 ms**, max **9.36 ms**, **0/300** overruns.
- Synthetic stationary low-pass Gaussian noise plus target: **1.564 s**,
  RTF **0.130**; p95 **6.07 ms**, max **14.28 ms**, **0/300** overruns.
- Sequential background Zira speech: **1.381 s**, RTF **0.115**;
  p95 **8.12 ms**, max **11.54 ms**, **0/300** overruns.
- Overlapping David/Zira speech: **1.142 s**, RTF **0.095**;
  p95 **6.53 ms**, max **48.52 ms**, **1/300** overruns.

Observed initialization: **0.065–0.711 s**. Process CPU seconds, respectively:
**1.938, 1.109, 1.578, 1.438, 1.156**. Average busy-process CPU during the resource
window: **68.9%, 92.4%, 96.7%, 98.2%, 95.1% of one core**, not percentages of all
eight logical CPUs and not continuously paced live CPU measurements. Post-run
RSS: **58.3–58.9 MiB**; process-lifetime peak RSS **69.7–70.3 MiB**, including
imports/offline validation. This is not an isolated native-model memory size.
All outputs preserved 576,000 samples, with **zero clipped samples**.

Aligned, scale-sensitive target SDR (higher is better; not an intelligibility or
transcription score):

- Clean: input exactly equals reference (null/infinite SDR), output **12.05 dB**.
- Quiet: input exactly equals reference (null/infinite SDR), output **12.05 dB**.
- Stationary noise: **7.39 → 10.48 dB**. Background-only interval energy fell
  **87.47 dB** in this synthetic, quantized-PCM fixture; this is not a general
  suppression guarantee and does not describe speech-active noise attenuation.
- Sequential background speech: **3.39 → 3.08 dB**; background-only attenuation
  just **0.28 dB**. Background speech was not meaningfully removed.
- Overlapping speech: **3.39 → 3.33 dB**. No target-isolation improvement shown.

Raw clean SDR was -3.04 dB because the native delay is uncompensated; compare the
separately aligned score instead. Even aligned clean audio differs from the
reference: noise reduction is not a transparent identity operation.

## Limits, VoxLock comparison and recommendation

These are offline Windows synthetic voices, not private microphone recordings.
Noise is deterministic synthetic stationary noise, **not recorded fan noise**.
No human listening judgments, transcription, word-error rates, false activations,
turn acceptance, interruptions, genuine quiet microphones, music, television,
accents, room reverberation or long-duration paced stability were evaluated.
Reports leave human quality, physical latency and transcription fields null.
Resource/deadline checks are cooperative between calls, not native-code preemption.
The adapter's startup and worst batch outliers require further investigation
before any hard real-time claims. No audio quality or STT improvement is assumed.

The previous VoxLock experiment measured RTF **1.26–1.90**, versus RNNoise
**0.088–0.175** here; RNNoise is substantially more CPU-practical on this laptop.
This is not an apples-to-apples model-quality comparison: rates, model purposes,
quiet fixture construction and timing conditions differ. Both use existing local
David/Zira material; VoxLock requires enrollment and aims to isolate a target,
whereas RNNoise suppresses non-speech noise. Neither experiment removed sequential
background speech meaningfully. VoxLock improved its overlapping-target SDR;
RNNoise did not. Do not replace target-speaker isolation with RNNoise.

Recommendation: **retain as an optional evaluation candidate, not integrate yet**.
First listen to consented input/output pairs, add recorded noise/quiet speech,
and repeat paced, concurrent-load tests to investigate worst-case batch stalls.
If those pass, a separately authorized LiveKit experiment could evaluate actual
STT accuracy and end-to-end latency. No such integration is included here.

## Automated verification

From `backend/`, with real-provider evaluation disabled:

```powershell
$env:RUN_REAL_VOICE_EVAL = 'false'
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
```

Final results: **544 passed, 10 skipped**; Ruff lint passed and **120 files**
passed formatting. The 24 added RNNoise cases cover PCM amplitude units, buffering,
padding, duration, unsupported formats/enrollment, bounds, clipping, failed native
calls, flush/close cleanup, missing/incompatible binaries, strict WAV input and
48 kHz quality alignment/interval handling. Native ABI mocks test contracts only;
the five separately reported local runs used the real DLL. Frontend code was not
changed, so no frontend build or browser voice test was performed for this
offline-only experiment. The repository secret heuristic also passed; it is not
a substitute for reviewing the staged file list.

## Sustained replay and microphone workflow (later checkpoint)

Added after `693ff1cbfd929f24b7b85508634a86c44c60c236` on `voice-optimization`.
The processor itself and all other processors remain unchanged. This is a
workflow/sustained-processing checkpoint, **not completed real-microphone quality
acceptance**. No consented microphone files were supplied. Having a microphone
does not establish a recording or listening result; capture was not activated
unattended.

### Record five local clips

The optional Windows PowerShell helper uses built-in WinMM/MCI, not a new Python
dependency. It is based on Microsoft's [record](https://learn.microsoft.com/en-us/windows/win32/multimedia/record),
[set](https://learn.microsoft.com/en-us/windows/win32/multimedia/set) and
[mciSendString](https://learn.microsoft.com/en-us/previous-versions/dd757161(v=vs.85))
documentation. It opens only when explicitly executed, records the Windows default
input, closes it in `finally`, refuses nonignored/existing output paths, and
requests mono 48 kHz PCM16. Device/permission/format failures return an MCI code.
Its syntax and nonignored-path rejection were tested **without opening the mic**;
actual device capture remains unverified. MCI is a legacy Windows interface and
some devices may reject the requested format. Check Windows microphone privacy
and the selected default input if it fails; no fallback fake audio is generated.

From the repository root, select your input in Windows Sound settings, then run
each command only when ready. Obtain consent from other speakers and avoid private
TV content or conversations you do not have permission to record.

```powershell
New-Item -ItemType Directory -Force .local/rnnoise/recordings | Out-Null
./scripts/record-rnnoise.ps1 -OutputFile .local/rnnoise/recordings/clean.wav -Seconds 30
./scripts/record-rnnoise.ps1 -OutputFile .local/rnnoise/recordings/fan.wav -Seconds 30
./scripts/record-rnnoise.ps1 -OutputFile .local/rnnoise/recordings/television.wav -Seconds 30
./scripts/record-rnnoise.ps1 -OutputFile .local/rnnoise/recordings/quiet.wav -Seconds 30
./scripts/record-rnnoise.ps1 -OutputFile .local/rnnoise/recordings/overlap.wav -Seconds 30
Copy-Item backend/app/evaluation/rnnoise-recordings.example.json .local/rnnoise/recordings/manifest.json
```

Run these individually, not as an unattended recording sequence. Do not overwrite
an existing private manifest; skip the copy if one exists. For clean speech use
normal speaking volume; for fan/TV include background-only intervals followed by
speech; for quiet speech use a soft voice at a consistent distance; for overlap
have a consenting second speaker speak simultaneously. Note device, distance,
noise source and any Windows/driver noise suppression locally. This workflow
does not disable driver processing or claim raw hardware capture.

Existing user-provided WAV files can be placed in that ignored directory and
referenced by the same manifest. The sustained reader requires nonempty **mono
48 kHz PCM16, up to 60 seconds**; other rates/encodings are rejected, not silently
converted. For optional later STT evaluation, create a private `clean.txt` and add
`"reference_file": "clean.txt"` to that fixture. References are copied locally
as `reference.txt` (max 64 KiB); neither text nor audio is printed or uploaded.
The reference describes the source clip, not an automatically expanded replay.
No transcription API is invoked and no WER is reported.

### Sustained benchmark and listening

Use the existing optional RNNoise environment. For one case:

```powershell
$env:PYTHONPATH = 'backend'
foreach ($chunk in @(10, 20, 40)) {
    .local/rnnoise/.venv/Scripts/python.exe -m app.evaluation.rnnoise_sustained --manifest .local/rnnoise/recordings/manifest.json --case clean --chunk-ms $chunk --seconds 60 --output-dir .local/rnnoise/microphone-results/clean-$chunk
    if ($LASTEXITCODE -ne 0) { throw 'Replay failed' }
}
```

Repeat with `--case fan`, `television`, `quiet` and `overlap`, changing output
directories accordingly. All destinations must be ignored and absent. A run is
bounded to 1–300 seconds; recordings shorter than the requested duration loop
without resetting native state. Loop counts and source hash/duration are reported;
seams are not natural continuous speech. A final short chunk gets its actual
sample-duration budget. `--unpaced` measures maximum throughput rather than paced
deadline behavior. Every run writes `original.wav`, `processed.wav`, `report.json`
and optionally `reference.txt` locally. Partial audio may remain after a failed
run, but no success report is generated. Do not reuse a failed destination.

Listen at the same volume without normalizing away differences:

```powershell
$pair = '.local/rnnoise/microphone-results/clean-20'
(New-Object System.Media.SoundPlayer ((Resolve-Path (Join-Path $pair 'original.wav')).Path)).PlaySync()
(New-Object System.Media.SoundPlayer ((Resolve-Path (Join-Path $pair 'processed.wav')).Path)).PlaySync()
```

Record subjective notes privately: intelligibility, missing/softened syllables,
quiet-voice preservation, pumping/distortion, remaining background speech and
preferred version. Do not equate quieter output with better target preservation.
Native delay/tail handling is unchanged from the earlier experiment. Human
listening, physical latency and transcription fields remain null until separately
verified; this tool does not infer those judgments from timing metrics.

### Metrics and actual sustained measurements

The new evaluator keeps one native state throughout a run. It measures each
`process()` call using a monotonic clock, including PCM conversion/native inference,
and reports average, nearest-rank p95/p99/max and over-budget counts. Processing
RTF = summed call time plus flush divided by audio duration; **sleep, WAV I/O,
resource checks and initialization are excluded**. ResourceWindow separately
measures total paced process CPU/wall and lifetime peak RSS; current RSS is sampled
once per second of audio, with min/max/last-minus-first reported. This is not
whole-laptop CPU or a guarantee against short memory spikes.

Chunks are notionally available at fixed monotonic intervals. Two different
failures are recorded: a call exceeding its audio-duration budget, and completion
after its scheduled deadline. The second includes scheduling/sleep stalls and
accumulated backlog, not just model compute. Replay catches up without dropping
audio or resetting the clock. No OS real-time priority or spin-wait was enabled.
Unpaced runs cannot establish scheduled deadline performance. A cooperative wall
budget of requested duration +60 seconds and 1 GiB RSS check bounds ordinary
failures, but cannot preempt a stuck native call. Use an external owned-process
timeout for unattended runs; no unrelated processes should be terminated.

**Measured locally:** three sequential **60-second paced runs** of the existing
12-second synthetic `noise.wav`, replayed five times (four seams), at 48 kHz.
These are **synthetic sustained CPU tests, not realistic microphone recordings**.
Windows 11/i5-1035G1/eight logical CPUs/Python 3.13.14; background laptop load was
uncontrolled and automated checks also ran during this work. One run per chunk
size, no confidence intervals or isolated thermal/load study:

- **10 ms / 6,000 calls:** average **2.358 ms**, p95 **3.179 ms**, p99 **3.438 ms**,
  maximum **22.637 ms**, processing RTF **0.236**. **3** calls exceeded 10 ms;
  **15** scheduled deadline misses, maximum lateness **20.889 ms**. Process CPU
  **14.813 s / 24.69% of one core**; RSS **45.05–46.48 MiB**, last-minus-first
  **+1.43 MiB**, lifetime peak **46.50 MiB**.
- **20 ms / 3,000 calls:** average **4.207 ms**, p95 **5.973 ms**, p99 **6.767 ms**,
  maximum **37.012 ms**, processing RTF **0.210**. **1** call exceeded 20 ms;
  **142** scheduled misses, maximum lateness **690.331 ms**. Process CPU
  **12.406 s / 20.68% of one core**; RSS **45.02–46.06 MiB**, delta **+1.04 MiB**,
  lifetime peak **46.06 MiB**. The large scheduling stall's cause was not isolated;
  it must not be attributed to RNNoise compute or dismissed as harmless.
- **40 ms / 1,500 calls:** average **8.232 ms**, p95 **10.510 ms**, p99 **11.610 ms**,
  maximum **42.851 ms**, processing RTF **0.206**. **1** call exceeded 40 ms;
  **1** scheduled miss, maximum lateness **3.295 ms**. Process CPU
  **12.406 s / 20.69% of one core**; RSS **44.54–45.38 MiB**, delta **+0.85 MiB**,
  lifetime peak **45.38 MiB**.

Each run produced exactly **2,880,000 samples** in both listening files with zero
reported clipping. All three original PCM streams were byte-identical, and all
three processed PCM streams were byte-identical across chunk sizes. This checks
chunking consistency, not perceived quality. Modest one-minute RSS growth does not prove absence of leaks;
longer runs remain needed. Memory scope differs from earlier NumPy-heavy scoring
runs: do not infer a model memory improvement from the lower peak here.

**Decision remains: do not integrate yet.** Average throughput is adequate here,
but measured deadline misses remain, especially under scheduling interference.
Actual clean/fan/TV/quiet/overlapping microphone capture, human listening,
long-duration thermal behavior, concurrent voice-service load, STT accuracy and
live interruption effects are still unverified. The workflow enables those
tests; it does not mark them passed merely because synthetic replay completed.

Verification for this workflow: **74 focused tests passed**, **577 full backend
tests passed, 10 skipped** with real-provider tests disabled. Ruff lint passed;
formatting passed for **126 files**. New tests cover replay boundaries (including
one-sample sources), WAV pairs/duration, bounds, formats, nearest-rank percentiles,
virtual-clock pacing/deadlines, failure cleanup and ignored-output enforcement.
Unpaced scheduled-deadline fields are null, not a claim of zero misses. PowerShell
syntax and nonignored-output guards passed; the guard test did not open the mic.
No frontend/build checks were repeated because frontend and session code did not
change. Source/docs/examples only are checkpoint files; ignored env files,
recordings and reports remain local.
