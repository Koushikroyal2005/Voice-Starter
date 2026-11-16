# Audio refactor verification

Scope: `voice-optimization`; offline only. No LiveKit integration, provider API
calls, new dependencies or credentials changes. Synthetic audio does not prove
microphone quality, target-speaker preservation or transcription accuracy.

## Regression criteria

The requested criteria map to public-interface tests as follows:

- **Invalid sample rates**: `test_audio_processors.py` format validation,
  processor wrong-format tests and `test_audio_scoring.py` invalid-rate tests.
- **Incorrect chunk sizes**: PCM alignment, processor duration limits and
  RNNoise arbitrary-size tests.
- **Empty audio**: processors' empty-input contracts, sustained WAV rejection,
  scoring rejection (not NaN output).
- **Silent audio**: repeated RNNoise silence processing and finite scoring JSON;
  no fabricated alignment or attenuation for zero-energy signals.
- **Clipping and PCM boundaries**: RNNoise clipping, VoxLock conversion tests,
  signed little-endian scoring boundary test.
- **Processor failures**: existing injected native/stream/subprocess failures,
  sanitized errors and cleanup tests.
- **Repeated initialization and cleanup**: RNNoise twenty-instance cycle,
  idempotent close/flush and existing VoxLock/DeepFilterNet lifecycle tests.
- **Concurrent processor calls**: simultaneous independent RNNoise instances
  with an injected ABI. Shared-instance concurrency is unsupported, not proven.
- **Incomplete final chunks**: RNNoise padding/trimming, DeepFilterNet duration
  tests and partial-chunk deadline-budget tests.
- **Missing model files**: existing VoxLock model verification and DeepFilterNet
  executable presence/hash tests; RNNoise missing distribution tests.
- **Processor bypass/fallback behavior**: not implemented in the current
  evaluation-only subsystem. Failures raise and release resources; there is no
  production LiveKit bypass policy to test. No policy was added for this task.

## Changes and red/green evidence

New scoring tests initially produced **8 failures, 4 passes**, exposing invalid
sample rates being accepted and empty PCM yielding NaN. Validation now rejects
nonpositive/noninteger rates and empty/misaligned PCM16 with clear exceptions.
Aligned scoring explicitly retains the supplied rate. Valid PCM behavior is
unchanged. The new scoring and RNNoise test selection passed **38 tests**.

## Actual CLI checks

Existing local environments/models were reused, without downloads. Outputs stay
under ignored `.local/audio-test-verification/`:

- Baseline inventory: completed, without `--replay` or provider consent flags.
- RNNoise clean synthesis fixture: completed.
- RNNoise paced 1-second noise replays: completed for 10/20/40 ms chunks.
- VoxLock clean fixture, 40 ms chunks: completed genuine local inference.
- DeepFilterNet clean fixture: first CLI attempt raised `AudioProcessingError`;
  direct diagnostic and one CLI retry completed. Initial cause is not established.
- `--help` passed for baseline, VoxLock, RNNoise, sustained RNNoise,
  DeepFilterNet and both fixture generators.

These are command compatibility checks, not new quality benchmarks. The earlier
sustained measurements remain documented in `rnnoise-evaluation.md`. Recording
hardware, human listening, real speech accuracy, simultaneous native inference
load, long-duration leaks and live interruption remain unverified. No physical
microphone recording was started.

## Check results

Initial full backend run: **587 passed, 10 skipped**. Final full runs after
the additional regressions: **600 passed, 10 skipped, 1 failed**. The existing
`test_fresh_interpreter_can_construct_pipeline_in_job_thread` exceeded its
45-second subprocess timeout. It was not weakened or changed. Diagnostic stack
dumps also captured slow native provider imports; the underlying machine-level
cause is not established. One run disabled pytest's optional cache plugin after
a diagnostic captured it blocked reading its cache.

Ruff lint passed; Ruff formatting passed for **128 files**. Frontend tests:
**101 passed**. Frontend ESLint and TypeScript passed using installed Node entry
points. Contract schemas compiled/current; tracked-secret heuristic passed.
The final audio selection (`test_audio_baseline`, `test_audio_processors`,
`test_audio_scoring`, `test_rnnoise_processor`, `test_deepfilternet_processor`,
`test_rnnoise_sustained`) passed **147 tests** with cacheprovider disabled.
Root Prettier found **15 existing style issues** in architecture documentation,
evaluation JSON, provider YAML and contract fixtures; unrelated files were not
reformatted. Prettier's local environment/cache/output exclusions were corrected
after the first attempt scanned third-party Python packages.

Environment issues were not hidden: sandbox uv cache access failed; `pnpm` was
absent from PATH and Corepack could not resolve the registry. Installed Python,
Ruff and Node entry points were used instead. The production build stalled at
optimized compilation and was stopped after its bounded diagnostic window.
Contract fixture generation initially hit its existing Python subprocess timeout;
one standalone retry passed with fixture agreement verified.
No application timeout/security restriction was changed to make checks pass.

Commands used from `backend/`: `.venv/Scripts/python.exe -m pytest -q
-p no:cacheprovider`, the six-file audio selection above, and
`.venv/Scripts/ruff.exe check app tests` / `format --check app tests`.
From the root: `node --test tests/*.test.cjs`, local ESLint and TypeScript
entry points, contract generation scripts with `--check`, `check-secrets.mjs`,
Prettier `--check .`, and the bounded Next.js build. Standard package-script
equivalents remain unchanged.
