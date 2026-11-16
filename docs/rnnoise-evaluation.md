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
