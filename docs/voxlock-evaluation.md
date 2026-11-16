# VoxLock: source inspection and evaluation decision

Date: 16 November 2026. Branch: `voice-optimization`.
Phase 1 baseline was committed and pushed first as
`353cf0fbc450889addc676203836ac8939ee5357`.
Main remains `ea46b1911a3f0c186c3d092f9289c2f85fdf8d2d`.

**Latest status:** the later task authorized installation, official INT8 weights
and local inference. The [authorized experiment](#authorized-implementation-and-first-inference)
below supersedes the initial inspection-only status while preserving its research.
Four real model runs on local synthetic speech succeeded technically, but measured
throughput and the background-only failure do **not** justify LiveKit integration.

## Initial inspection scope and decision (historical)

The operator selected **Inspect and document only** after being told the model
and dependency requirements. Consequently no VoxLock package was installed, no
model weights were downloaded, and no VoxLock inference was run. A draft adapter
was removed before completing this inspection; it is not a usable integration or
claimed test result. No Groq, Google or NVIDIA inference calls were made.

Recommendation: **do not integrate yet**. VoxLock is technically a plausible
local CPU candidate, not a validated improvement for this laptop. Defer acceptance
until an explicitly authorized, isolated inference experiment measures speed and
target preservation. This rejects immediate integration, not the model itself.

## What was inspected

- [Repository](https://github.com/arbazsiddiqui/voxlock), pinned for inspection at
  `48b9a71e9b6ce853670c9a4dbc64ddb532638d53`.
- [Core implementation](https://github.com/arbazsiddiqui/voxlock/blob/48b9a71e9b6ce853670c9a4dbc64ddb532638d53/voxlock/core.py),
  including constructors, chunk state, enrollment, flush and automatic selection.
- [Package metadata](https://github.com/arbazsiddiqui/voxlock/blob/48b9a71e9b6ce853670c9a4dbc64ddb532638d53/pyproject.toml),
  [PyPI 1.3.0](https://pypi.org/project/voxlock/1.3.0/),
  [CI](https://github.com/arbazsiddiqui/voxlock/blob/48b9a71e9b6ce853670c9a4dbc64ddb532638d53/.github/workflows/tests.yml),
  [NOTICE](https://github.com/arbazsiddiqui/voxlock/blob/48b9a71e9b6ce853670c9a4dbc64ddb532638d53/NOTICE)
  and the [model card](https://huggingface.co/arbazsiddiqui/voxlock).
- Published ONNX file-size metadata at the source-pinned model revision
  `2413b292bc2c337bfc19a9802aaf3e011e68e9c4`.

GitHub/Hugging Face/PyPI metadata and small source files were accessed; these are
not provider inference requests or model downloads. The baseline instrumentation
and existing local ONNX Runtime installation were inspected without changing them.

## Dependencies, license and size

VoxLock 1.3.0 declares Python >=3.9 and these core dependencies:
NumPy >=1.24, ONNX Runtime >=1.17, Hugging Face Hub >=0.20, SoundFile >=0.12 and
soxr >=0.3. ONNX inference does not require the training/PyTorch stack or a GPU.
Do not install the LiveKit/Pipecat extras for the isolated experiment.

Local NumPy 2.5.4 and ONNX Runtime 1.32.0 are present. VoxLock, Hugging Face Hub,
SoundFile and soxr were absent. Published artifacts inspected include a roughly
26 KB VoxLock wheel, a roughly 1.02 MB Windows SoundFile wheel, a 174 KB soxr ABI3
Windows wheel and an 857 KB Hugging Face Hub universal wheel. These are compressed
artifact sizes, not an installation-size guarantee; transitive dependencies and
a fresh environment add more. No installation resolver or DLL loading test for
the missing packages was performed.

Default v2 INT8 inference requires:

- `enroll.onnx`: 21,023,799 bytes.
- `chunk_int8.onnx`: 56,560,589 bytes.
- Combined: 77,584,388 bytes, approximately **77.6 MB / 74.0 MiB**; the upstream
  documentation describes this as 74 MB. Config/cache metadata adds a little more.

Code and model card declare Apache-2.0. Upstream NOTICE attributes the REAL-TSE
checkpoint and associated inference code. Demo data has separate terms, including
CC BY-NC for the Krisp benchmark; do not assume the model license covers demo
recordings. Future testing should use consented recordings or genuinely local
synthetic speech, not unreviewed third-party samples. This inspection is not legal
clearance for every upstream dataset or dependency.

## Can it stream locally on CPU?

Yes at the API/implementation level: the ONNX path maintains recurrent state and
accepts 16 kHz mono float32 chunks through `stream(sample).push(...)`, followed by
`flush()`. Explicit enrollment requires at least three seconds of the target.
This is causal chunked inference, not STT, diarization or a remote service.

Important source-level caveats:

- `model_dir=None` implicitly downloads weights. A future evaluator must require
  existing local model files and fail closed if either INT8 file is missing.
- File-mode automatic sampling chooses a loud segment; it does not know which
  person the application intends. Quiet-target tests need explicit enrollment.
- `live()` passes audio through before collecting its enrollment sample. Selection
  uses an energy/noise-floor heuristic, not an authenticated speaker identity.
- Automatic locking can synchronously warm the model over buffered call history.
  A streaming signature does not establish a bounded worst-case chunk time.
- Output delay and target attenuation must be measured with enrollment and chunk
  mode fixed. Do not treat an algorithmic-delay claim as laptop microphone-to-ear
  latency, or overall quieter audio as proof that the correct voice survived.

Upstream CPU throughput is a benchmark on different hardware, not measured here.
No local real-time factor, chunk latency, isolation attenuation or speech-quality
number is available from this inspection.

## Windows findings

Actual local import check passed on Windows AMD64, Python 3.13.14:
ONNX Runtime 1.32.0 reported `AzureExecutionProvider` and `CPUExecutionProvider`.
This verifies the already-installed runtime can load, **not** that VoxLock's model
graphs execute correctly. A future test should explicitly use CPU execution.

Upstream CI inspected runs Ubuntu with Python 3.10/3.12; it does not demonstrate
Windows/Python 3.13 coverage. Windows/ABI3 wheels were present in package metadata,
but missing packages and their native libraries were not installed or imported.
No definitive Windows blocker was reproduced, and Windows compatibility must not
be claimed as end-to-end verified. If installation/model execution fails on this
platform, stop and document that failure rather than modifying the voice engine.

Two installed offline Windows synthesis voices were enumerated (David and Zira).
No speech recordings were generated. They are an available future synthetic test
source, not evidence that the model isolates real overlapping speakers.

## Proposed bounded experiment — not implemented or run

Keep this separate from `providers/`, the frontend and LiveKit session startup.
Use a disposable local environment, pin VoxLock 1.3.0, pre-download only the two
approved INT8 files, select one CPU thread and require explicit enrollment.
Do not upgrade backend dependencies or change `uv.lock`. Avoid automatic downloads
inside the evaluator. No install/download command was executed in this phase.

A future small adapter can reuse `evaluation.baseline.wav_metadata`,
`evaluation.resources.ResourceWindow`/`hardware`, revision reporting and ignored
local JSON outputs. It should take local input/enrollment/reference paths, local
model directory and chunk size; return local processed audio and numeric metadata.
It must never call the STT/LLM/TTS baseline replay path for this experiment.

Bound the experiment to four <=15-second mono PCM16/16kHz inputs, separate
three-second clean enrollment, one trial each, 40ms chunks, one CPU thread and a
120-second **external process timeout** per trial. Do not equate unpaced throughput
with real-time scheduling. Consider 80ms only in a separately labeled follow-up;
do not repeatedly rerun slow cases or install alternate runtimes on failure.

Required cases and current status:

- Clean target speech: **not run**. Compare dry target versus output for distortion,
  level loss, clipping and missing consonants.
- Background speech: **not run**. Include target-only and background-only intervals;
  determine whether the background is attenuated without silencing the target.
- Two overlapping speakers: **not run**. Keep separate original stems and the
  known mixture; judge target preservation as well as interference reduction.
- Quiet target: **not run**. Reduce the target stem by a documented fixed gain,
  keep background gain constant and enroll the intended target explicitly.

Use known public text with two distinct local synthetic voices if consented human
recordings are unavailable; disclose the synthetic-domain limitation. A sinusoid,
random noise, repeated single voice or a mock filter is not a two-speaker isolation
test. Do not tune gain/enrollment separately to hide a failing condition.

Measure model loading/enrollment separately from processing. Per-chunk wall times
and p50/p95/max/budget misses, flush time and total processing/audio-duration RTF
can be collected with a monotonic clock. Reuse the baseline process CPU/memory
window, noting its lifetime RSS peak and exclusion of remote/child processes.
Keep input/output hashes, fixture gains, model hashes/revision, precision, threads,
sample rate, code version and hardware in each local report.

For quality, compare sample-aligned target references, clipping and appropriately
defined SDR/error metrics, plus background-only attenuation. Separate energy
measurements from human intelligibility/identity judgment. Do not run cloud ASR
to obtain a WER score. Listen to input and output locally; do not upload recordings
or commit private audio. Check model output length/finite samples and report any
output clipping, rather than silently calling invalid output successful inference.

Acceptance requires sustained CPU headroom, acceptable added buffering and no
material loss of intended speech in all four conditions. Product thresholds must
be agreed before running; none are claimed achieved here. A good result would
justify a separate integration proposal, not automatic insertion into LiveKit.

## Actual checks and limitations

Verified by inspection: supported source API, dependency declarations, model/file
licenses, published size metadata and absence of Windows CI in the inspected job.
Verified locally: existing ONNX Runtime imports and exposes CPU execution; offline
Windows synthesis voices can be enumerated. These are compatibility preflight
checks, **not model inference tests**.

VoxLock CPU performance, memory during inference, background suppression and target
preservation remain **unmeasured** because the operator chose not to install or
download. All four requested audio conditions remain not run. No mock processing,
claimed Windows inference success, provider calls or new audio pipeline behavior
is substituted for those missing results.

Focused existing baseline/bootstrap tests: **44 passed in 23.21 seconds** with
real replay disabled. Ruff lint passed; formatting check reported 109 files
already formatted. Git whitespace check passed. These validate existing tooling,
not VoxLock behavior. Only this document is left uncommitted; no evaluation
adapter, optional dependency, lockfile or runtime configuration change remains.

## Authorized implementation and first inference

The subsequent task explicitly authorized minimal optional dependencies, the
official INT8 download, genuine local CPU inference and a verified experimental
checkpoint. No paid inference was authorized or used. The inspection-only decision
above is historical; the results below are new measured evidence, not upstream
benchmark claims. No existing STT/LLM/TTS, MCP, orchestrator, frontend or LiveKit
audio-input implementation was changed.

### Architecture and responsibility map

- `backend/app/audio/interfaces.py`: dependency-free `AudioFormat`, `PCMChunk`,
  `AudioProcessor` protocol and safe `AudioProcessingError`. The initial contract
  is signed little-endian interleaved PCM16 bytes with explicit rate/channels.
  Empty output means buffered audio, not fabricated silence.
- `backend/app/audio/processors/voxlock.py`: frozen `VoxLockConfig`, official-model
  integrity verification, lazy optional imports, CPU-only native VoxLock stream,
  explicit enrollment, finite-output checks, PCM conversion/clipping accounting,
  lifecycle and cleanup. No fallback or automatic download on construction.
- `backend/app/evaluation/voxlock.py`: explicit download command and bounded local
  experiment. Reuses baseline manifest/WAV validation, revision/hardware metadata
  and process resource measurement. Its `measure_stream` function consumes only
  the processor protocol; model-specific construction remains in `evaluate_case`.
- `backend/app/evaluation/voxlock_fixtures.py` and
  `scripts/create-voxlock-fixtures.ps1`: repeatable offline Windows synthetic speech
  and known target/background mixtures. No provider requests or user recording.
- `backend/requirements-voxlock.txt`: optional isolated environment pins. The
  backend's normal dependency manifest, lockfile and environment remain unchanged.
- `backend/tests/test_audio_processors.py`: deterministic mock/unit tests only;
  not a substitute for the separately executed real ONNX runs.

There is no audio registry yet: one implementation and one explicit evaluator do
not justify duplicating the provider registry. Construct the processor explicitly.
Future PCM processors can implement the same small interface with their own typed
configuration. Add selection only when a second real consumer needs it. A
diarization result is not PCM: do not force future speaker annotations into this
interface or implement speculative processors now.

Lifecycle: construct with reviewed local weights, `enroll(PCMChunk(...))`, call
`process` on chunks, `flush` at end, and `close` in `finally` or a context manager.
VoxLock requires mono 16kHz and 3–15 seconds of target enrollment. It rejects other
rates/channels instead of silently resampling; each processing chunk is <=1 second.
Flush is idempotent; new audio after flush requires new enrollment. Native failures
close the stream. ONNX Runtime has no public session-close method, so cleanup
releases owned model/stream references; allocator/process RSS need not drop at once.

### Installation and verified download

Executed in a separate ignored environment, not `backend/.venv`:

```powershell
# Repository root; these commands install optional local inference dependencies.
uv venv --python 3.13 .local/voxlock/.venv
uv pip install --python .local/voxlock/.venv/Scripts/python.exe -r backend/requirements-voxlock.txt
cd backend
../.local/voxlock/.venv/Scripts/python.exe -m app.evaluation.voxlock download --model-dir ../.local/voxlock/models
cd ..
```

Installed primary versions: VoxLock 1.3.0, NumPy 2.5.4, ONNX Runtime 1.32.0,
Hugging Face Hub 2.4.0, SoundFile 0.14.0 and soxr 1.1.0 (25 packages including
transitive dependencies). No PyTorch, CUDA or GPU model containers were installed.
The installed package's constructor and model revision were checked directly.

Both official weights passed exact byte-count and SHA-256 checks, matching the
published LFS metadata at revision `2413b292bc2c337bfc19a9802aaf3e011e68e9c4`:

- `enroll.onnx`, 21,023,799 bytes:
  `81f305c9b7a32f13d1401f53bb4c6301826a607c9e807e60912f36ef1b9fae29`.
- `chunk_int8.onnx`, 56,560,589 bytes:
  `c50ffdc8d723fd4f91cb08889f3d0143491f95967b705f35c444a0b4afe88172`.

Total weights: 77,584,388 bytes (74.0 MiB). The downloader verifies size/hash before
renaming its own temporary file, refuses invalid existing weights and reuses valid
files. Construction checks both INT8 files again, preventing upstream's implicit
download or silent fp32 fallback. TLS plus published hashes verifies provenance
against the publisher's metadata; no signed release attestation is claimed.
The evaluator explicitly selects `CPUExecutionProvider` for both sessions.

### Reproducing the four conditions

```powershell
# Run from root in Windows PowerShell (System.Speech and David/Zira required).
powershell -NoProfile -File scripts/create-voxlock-fixtures.ps1
cd backend
# Choose a NEW ignored output directory on each invocation; no overwrites.
../.local/voxlock/.venv/Scripts/python.exe -m app.evaluation.voxlock run --manifest ../.local/voxlock/synthetic/fixtures/manifest.json --model-dir ../.local/voxlock/models --output-dir ../.local/voxlock/results/clean-new --case clean
# Repeat separately with --case quiet, background or overlap and new output paths.
```

The command consumes no provider settings or credentials. For consented recordings,
copy the baseline manifest shape into ignored storage and supply per-case
`enrollment` and optional `target_wav` paths. Optional `background_only_intervals`
are `[start_seconds,end_seconds]` pairs known to contain no intended target speech.
All evaluation files must be nonempty mono PCM16/16kHz WAVs, <=15 seconds, with
sample-aligned equal-length target references. Do not infer suppression from total
energy alone when reference signals or reviewed intervals are absent.

Models, manifests, raw speech, target references, outputs and raw JSON reports
remain under ignored `.local/voxlock/`. No generated audio or weights are committed.
Other output/model destinations must pass ignore checks for audio, ONNX, JSON and
temporary files. Inputs are read-only; no user recording was modified or uploaded.
The CLI refuses existing output directories rather than overwriting experiments.

The experiment used Microsoft David Desktop as target and Microsoft Zira Desktop
as background, rate 0 and volume 100, generated by local Windows System.Speech.
Enrollment was a separate target-only phrase. Four 12-second fixtures contain
192,000 samples each. Target starts at 0.5 seconds; sequential background starts
at 6 seconds, overlapping background at 0.5 seconds. The generator preserves
separate, sample-aligned target references and refuses clipping/truncation.
Clean/background/overlap target gain is 0.6; quiet-target gain is 0.12; background
gain is 0.35. Quiet target is tested against overlapping background, not silence.
Silence padding is included in RTF duration, so active-speech throughput can be
worse. These controlled synthetic voices are not representative human microphones.

One fresh process was used per case, one model thread, INT8, 40ms chunks (640
samples), no tuning/retries, no physical recording/playback. Each process had an
external 120-second deadline during execution. The evaluator additionally checks
a 120-second cooperative deadline and a 1GiB working-set budget between chunks.
Those checks cannot preempt a stuck native call or enforce an OS allocation cap;
keep the external timeout when running manually. A PowerShell harness can use
`Start-Process -PassThru -WindowStyle Hidden`, poll `WaitForExit(1000)` and kill only
that owned process after 120 seconds. Never kill unrelated worker/frontend jobs.

### Actual measured results, 16 November 2026

Windows 11 AMD64, Python 3.13.14, 8 logical CPUs, reported processor
`Intel64 Family 6 Model 126 Stepping 5, GenuineIntel`; ONNX Runtime 1.32.0.
Windows hardware inventory identified Intel Core i5-1035G1 (4 cores/8 threads).
Existing laptop services/background load were not controlled. One run per case
is not a statistical study; warm filesystem/model caches can affect initialization.
The measurement loop includes PCM conversion, resource checks and flush. Chunk
timing covers the `process` call. Initialization includes local hash checks and CPU
session setup; enrollment is measured separately. No microphone-to-ear or acoustic
latency was measured. All cases emitted first output after 640 input samples;
that is an input-buffer observation, not 40ms measured physical latency.

- **Clean:** initialization 3.364s, enrollment 0.223s; processing 22.768s for 12s
  audio, **RTF 1.897**. Chunk p50/p95/max: 73.08/99.20/176.30ms; 298/300 exceeded
  40ms. Resource-window CPU 23.188s, average 87.81% of one core; lifetime peak
  working set 184.30 MiB. Output scale-sensitive SDR against the target: 22.14dB.
  Input SDR is null because the input equals its reference exactly (zero error),
  not because the reference was missing. Processing adds measurable clean error.
- **Quiet target + overlap:** initialization 1.724s, enrollment 0.092s; processing
  18.762s, **RTF 1.563**. Chunk p50/p95/max: 63.91/82.91/110.25ms; 270/300 over
  budget. CPU 18.844s, average 91.36%; peak 184.59 MiB. Overall target-reference SDR
  improved from -10.59dB to 2.94dB; this is not a guarantee of intelligible speech.
- **Sequential background speech:** initialization 3.188s, enrollment 0.158s;
  processing 16.467s, **RTF 1.372**. Chunk p50/p95/max: 54.11/79.23/92.79ms;
  237/300 over budget. CPU 17.438s, average 87.81%; peak 184.70 MiB. Target-reference
  SDR worsened from 3.39dB to 2.95dB. Background-only attenuation was **-0.39dB**:
  the background interval became slightly louder, not suppressed. This condition
  failed the intended isolation outcome; it must not be omitted from the report.
- **Overlapping speakers:** initialization 0.830s, enrollment 0.087s; processing
  15.166s, **RTF 1.264**. Chunk p50/p95/max: 51.08/72.72/83.98ms; 212/300 over
  budget. CPU 15.766s, average 97.74%; peak 184.69 MiB. Overall target-reference SDR
  improved from 3.39dB to 13.12dB. This does not independently identify every leaked
  word or establish human target-preservation acceptance.

All four real ONNX calls completed, emitted equal-length 192,000-sample outputs
and reported zero clipped samples. Raw measurements and hashes are in ignored
`.local/voxlock/results/<case>/report.json`; processed audio is alongside them.
No observations were substituted with mocks. Percent CPU is the evaluator's
process CPU/wall window including initialization, not whole-laptop CPU or the
CPU budget of a correctly paced live call. RSS peaks are process-lifetime peaks;
separate processes avoid cross-case lifetime accumulation.

SDR here is scale-sensitive signal/reference energy divided by error energy; it
combines gain/distortion/interference and is not SI-SDR, WER or speaker identity.
Null SDR can also mean zero reference energy; null attenuation can mean zero
denominator. Human preservation/suppression judgments remain null: no physical
listening acceptance or real microphone test occurred. Real target/background
recordings, reverberation, speaker changes and automatic enrollment still require
future authorized tests. No claim is made about those conditions from synthetic
speech.

### Decision and checkpoint scope

Windows CPU inference is now verified for these pinned weights and this optional
environment. **Do not integrate this configuration into LiveKit:** every measured
RTF exceeded 1 and most chunks missed their budget; the sequential-background
condition did not suppress the unwanted voice. This is a verified experiment with
negative suitability findings, not a successful real-time optimization milestone.
Keep the modular foundation and evidence for future decisions. No two-thread,
larger-chunk, alternate-model or runtime tuning experiments were performed.

Focused checks after implementation: 80 passed (36 processor tests plus existing
baseline/bootstrap coverage); Ruff lint/format passed. The full backend suite and
checkpoint review are recorded below after completion. CI does not install VoxLock
or download weights: unit tests mock the optional model dependency, and genuine
inference remains an explicitly invoked local command.

Final backend regression: **520 passed, 10 skipped in 108.81 seconds**, with paid
voice evaluation disabled. Ruff lint passed and formatting check covered 116
Python files. No frontend check/build was rerun: frontend code and shared session
contracts are unchanged. The existing secret heuristic and Git whitespace checks
passed. The checkpoint contains source, optional dependency pins, tests, fixture
generation tooling and this preserved/updated research document only. Stable main
and ignored env files were not modified. Private outputs are not checkpoint files.
