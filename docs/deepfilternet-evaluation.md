# DeepFilterNet versus RNNoise: local CPU experiment

16 November 2026, `voice-optimization`, baseline
`0ac8a20f4c382500562ef897f4e0b947b3a9178b`.
No LiveKit integration, provider API calls, env changes or changes to main.

## Inspected implementation, licenses and Windows support

Official sources inspected:

- [DeepFilterNet v0.5.6](https://github.com/Rikorose/DeepFilterNet/tree/v0.5.6),
  [released binaries](https://github.com/Rikorose/DeepFilterNet/releases/tag/v0.5.6),
  [CLI implementation](https://github.com/Rikorose/DeepFilterNet/blob/v0.5.6/libDF/src/bin/enhance_wav.rs)
  and [WAV conversion](https://github.com/Rikorose/DeepFilterNet/blob/v0.5.6/libDF/src/wav_utils.rs).
- [Pretrained models](https://github.com/Rikorose/DeepFilterNet/tree/v0.5.6/models),
  [native inference/default model](https://github.com/Rikorose/DeepFilterNet/blob/v0.5.6/libDF/src/tract.rs),
  [C API](https://github.com/Rikorose/DeepFilterNet/blob/v0.5.6/libDF/src/capi.rs)
  and [LADSPA worker](https://github.com/Rikorose/DeepFilterNet/blob/v0.5.6/ladspa/src/lib.rs).
- [DeepFilterLib 0.5.6 wheels](https://pypi.org/project/DeepFilterLib/0.5.6/),
  [MIT](https://github.com/Rikorose/DeepFilterNet/blob/v0.5.6/LICENSE-MIT)
  and [Apache-2.0](https://github.com/Rikorose/DeepFilterNet/blob/v0.5.6/LICENSE-APACHE).

Upstream code is dual MIT/Apache-2.0, at the user's option. The pretrained
artifacts are published in that upstream repository; no separate model license
was established in this inspection. Do not treat this as a legal determination
for redistributing weights. No executable or model is committed here; retain
upstream notices and confirm model redistribution terms before distributing it.

The verified smallest practical setup **for this environment** is the official
Windows x64 v0.5.6 executable, **26,912,256 bytes**, containing the default
DeepFilterNet3 ONNX model and Rust/tract CPU inference. It ran on Windows 11 AMD64,
Intel Core i5-1035G1, 8 logical CPUs, alongside Python 3.13.14. No Python model
package, PyTorch, GPU, compiler or separate weights were installed. Existing
isolated NumPy is used only for evaluation/scoring.

The default DFN3 ONNX archive is about **7.98 MB** compressed upstream. Other
published variants include DFN2 ONNX (~8.63 MB), original DFN checkpoint (~6.65 MB)
and DFN3 low-latency ONNX (~36.36 MB). They were not downloaded or benchmarked.
This is not a claim that default DFN3 is the globally smallest/fastest model.

The published Python native wheels include Windows CPython 3.8–3.11, but not this
backend's Python 3.13. The Python path also requires torch/torchaudio; it was not
installed. The Windows LADSPA DLL is available, but the inspected worker loops
indefinitely without a termination path; wrapping it here would not establish
safe cleanup. No native C-API DLL is supplied by the inspected release assets.
Building one would require a separate Rust/MSVC investigation. Those streaming
paths remain unverified, rather than silently substituting a fake implementation.

Observed HTTPS-downloaded executable SHA-256, checked on every construction:
`75e11fa16445f560cb6b021521ddb89e89270d13b83089705d98776f58fd7915`.
This is a locally recorded fingerprint, not an upstream signature verification.

## Adapter and reuse

`backend/app/audio/processors/deepfilternet.py` uses the existing `AudioProcessor`,
`PCMChunk` and `AudioFormat`. **It is batch-only.** `process()` validates and buffers
mono 48 kHz little-endian PCM16, at most 1 second per call and 15 seconds total.
It returns empty output until `flush()`, which invokes the real official engine.
No inference occurs per input chunk. It does not masquerade as a streaming model.

Flush pads a partial 480-sample native hop, runs one bounded child process, checks
PCM16/rate/channels/duration and trims only padding. It retains native delay and
does not emit the filter tail beyond input duration, matching RNNoise's evaluation
convention. CLI delay compensation is deliberately off. Postfilter is off and
thresholds/attenuation are upstream defaults. Enrollment is explicitly unsupported.

Temporary WAV files are placed in an OS temporary directory and removed on
success/failure. Calls use argument lists, not a shell; native diagnostics are
discarded, errors sanitized, and subprocess timeout is 60 seconds. Flush/close
are idempotent; no resume after close. Abandoning a buffered stream clears it.
This synchronous adapter is not an interruptible real-time processing component.
Timeout kills only its owned child. A new subprocess/model is initialized per
flush, not for each 40 ms chunk.

Evaluation reuses the existing 48 kHz WAV reader, manifests, fixtures, stream
measurement loop, resource window and ignored-output guard. No new registry,
audio interface, telemetry system or evaluation framework was introduced.
`audio_scoring.py` extracts the actual shared signal comparison and alignment
logic. Interval seconds now use an explicit sample rate rather than RNNoise's
previous 3x coordinate workaround. VoxLock still imports the same function name
with a 16 kHz default; its processor, inference, lifecycle and scoring semantics
are unchanged. RNNoise's 48 kHz scoring and four-sample alignment resolution are
preserved.

The resource helper can measure an **owned child** independently. Windows child
CPU uses GetProcessTimes; peak working set is sampled every ~10 ms while alive,
so an allocation occurring entirely between samples may be missed. Child metrics
include startup/model loading and I/O. Parent metrics explicitly exclude the
child. No production sampler was added.

## Reproduce in PowerShell

From the repository root; the RNNoise isolated environment/fixtures must exist
(see [RNNoise guide](rnnoise-evaluation.md)):

```powershell
New-Item -ItemType Directory -Force .local/deepfilternet | Out-Null
if (Test-Path .local/deepfilternet/deep-filter.exe) { throw 'Already exists; verify rather than overwrite' }
Invoke-WebRequest -UseBasicParsing -TimeoutSec 120 https://github.com/Rikorose/DeepFilterNet/releases/download/v0.5.6/deep-filter-0.5.6-x86_64-pc-windows-msvc.exe -OutFile .local/deepfilternet/deep-filter.exe
Get-FileHash .local/deepfilternet/deep-filter.exe -Algorithm SHA256
$env:PYTHONPATH = 'backend'
foreach ($case in @('clean', 'quiet', 'noise', 'background', 'overlap')) {
    .local/rnnoise/.venv/Scripts/python.exe -m app.evaluation.deepfilternet --manifest .local/rnnoise/fixtures/manifest.json --case $case --executable .local/deepfilternet/deep-filter.exe --output-dir .local/deepfilternet/results/$case
    if ($LASTEXITCODE -ne 0) { throw "Failed: $case" }
}
```

Outputs must be in an ignored, previously absent directory. Each run produces
`output.wav` and structured `report.json`; none are committed. Reruns need fresh
directories. Use the same consent/format/reference rules as the RNNoise guide
for private recordings. No credentials are loaded and no paid APIs are called.

## Actual measurements and comparison

Five real local native inference runs, each using the **unchanged RNNoise WAV
fixtures**, 12 seconds/576,000 samples. Inputs are synthetic David/Zira speech;
quiet means 20% target amplitude without background. Noise is deterministic
low-pass Gaussian noise, not recorded fan noise. Inputs were not recorded again
or resampled again. One unpaced run per case; laptop background load was not
controlled. RNNoise numbers are the earlier checkpoint's runs, not simultaneous
controlled A/B trials. Timing/resource scopes differ as described below.

Processing/RTF includes full batch flush, subprocess startup, model load, WAV I/O
and resource checks; binary fingerprint validation is separate:

- **Clean:** DFN3 **1.013 s / RTF 0.084**, flush **0.921 s**;
  RNNoise **2.097 s / 0.175**.
- **Quiet:** DFN3 **0.874 s / 0.073**, flush **0.842 s**;
  RNNoise **1.061 s / 0.088**.
- **Stationary noise:** DFN3 **2.199 s / 0.183**, flush **2.168 s**;
  RNNoise **1.564 s / 0.130**.
- **Background speech:** DFN3 **1.344 s / 0.112**, flush **1.309 s**;
  RNNoise **1.381 s / 0.115**.
- **Overlapping speakers:** DFN3 **1.210 s / 0.101**, flush **1.159 s**;
  RNNoise **1.142 s / 0.095**.

DFN3 child CPU seconds in that order: **0.813, 0.750, 2.063, 1.172, 1.031**.
Average child CPU during its busy lifetime: **90.3%, 90.4%, 95.8%, 90.5%, 90.4% of
one core**, not whole-laptop CPU or paced live CPU. RNNoise measured **1.938,
1.109, 1.578, 1.438, 1.156 CPU seconds**, including its parent initialization.
DFN3 sampled child peak working sets: **53.63, 53.77, 53.83, 54.00, 53.86 MiB**;
its separate evaluator RSS was **43.65–44.45 MiB**. Do not compare the child alone
to RNNoise's entire evaluator peak (**69.7–70.3 MiB**) or claim lower total memory.

**Per-chunk inference latency and worst-case inference spikes are unavailable
from this CLI and are null in the reports.** Its `process()` times measure buffer
copies only and are named accordingly. The measured flush duration is a whole
file stall, not one processing spike in a live stream. RNNoise previously measured
40 ms batch p95 **6.07–10.89 ms**, maxima **9.36–232.13 ms**, with two budget
overruns across 1,500 batches. No equivalent DFN3 streaming deadline result exists.
Both RTFs <1 do not establish real-time safety.

All DFN3 outputs preserved input duration. Estimated native delay was **1,440
samples / 30 ms**, versus RNNoise **960 / 20 ms**. This is bounded offline signal
alignment, not acoustic latency. Scale-sensitive SDR below uses each model's
delay-aligned output, excluding that delay from the end of the reference; retained
reference windows consequently differ by 10 ms. This is not SI-SDR, intelligibility,
speaker identification or transcription accuracy:

- Clean target: exact-reference input; DFN3 output **25.44 dB**, RNNoise **12.05 dB**.
- Quiet target: exact-reference input; DFN3 **16.00 dB**, RNNoise **12.05 dB**.
- Stationary noise: input about **7.40 dB**; DFN3 **14.44 dB**, RNNoise **10.48 dB**.
- Background speech: input **3.39 dB**; DFN3 **3.55 dB**, RNNoise **3.08 dB**.
- Overlap: input **3.39 dB**; DFN3 **5.84 dB**, RNNoise **3.33 dB**.

Background-only energy attenuation: DFN3 **45.39 dB** versus RNNoise **87.47 dB**
on synthetic noise; DFN3 **0.19 dB** versus RNNoise **0.28 dB** on sequential speech.
Silence suppression is not speech preservation: DFN3's lower noise-only suppression
coexists with a better overall target-reference score here. Neither meaningfully
suppressed the separate background voice. Quantization and annotated intervals
affect these energy ratios. No human quality judgment was recorded.

## Recommendation and unverified work

For **the current laptop's existing streaming experiment**, RNNoise is the more
practical adapter: it has verified incremental frame inference and deterministic
native state release. Its worst-case outliers still prevent integration approval.
For **these offline signal-reference fixtures**, DFN3 is the stronger quality
candidate; its throughput is broadly competitive, not uniformly faster. This
does not establish which model sounds better to a human or performs better in a
voice session. Do not reject DFN3 based on an interface limitation of its CLI,
and do not present this batch adapter as ready for live microphone processing.

**Integrate neither into LiveKit yet.** A separately scoped DFN3 native streaming
build/binding would need correct persistent state, cancellation, tail/delay handling,
cleanup and actual per-frame timing. Both need consented real recordings, human
listening, paced sustained/concurrent-load tests, quiet/reverberant microphones,
accents and measured downstream STT/turn/interruption effects. No transcription,
browser interaction, physical latency or target-speaker identity improvement has
been verified. No provider/model selection or live audio behavior changed here.

## Checks

Focused processor/scoring/resource tests: **79 passed**. Tests mock executable
inference only for deterministic contract checks; the five benchmark runs used
the real downloaded executable. Covered buffering/partial hops, rate/channels,
limits, enrollment rejection, binary integrity, native failures/timeouts, temporary
audio cleanup, close/flush, sample-rate-aware scoring and child-process timeouts.
Final backend regression: **563 passed, 10 skipped in 81.48 seconds**, with
`RUN_REAL_VOICE_EVAL=false`. `uv run ruff check app tests` passed;
`uv run ruff format --check app tests` passed for **124 files**. The extracted
scoring also exactly reproduced **all five existing RNNoise reports and all four
existing VoxLock reports** using their saved local input/reference/output WAVs.
No model rerun or provider API call was needed for that migration verification.

Commands from `backend/`:

```powershell
$env:RUN_REAL_VOICE_EVAL = 'false'
uv run pytest -q tests/test_deepfilternet_processor.py tests/test_rnnoise_processor.py tests/test_audio_processors.py
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
```

No frontend build/browser test was repeated because frontend and live-session
contracts were unchanged. Git whitespace and secret-pattern checks are included
in checkpoint review. Native binaries, weights, temporary/private WAVs, generated
reports and ignored env files are not checkpoint files.
