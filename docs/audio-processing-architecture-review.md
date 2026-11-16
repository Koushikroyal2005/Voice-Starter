# Audio architecture review

Date: 2026-11-16. Scope: [root proposal](../ARCHITECTURE.md) on
`voice-optimization`, source `bf477d13e3358bd74405330666356e29f729a684`.
The author used Blueprint architecture; a separate reviewer then used Blueprint
architecture-review. There is no root REQUIREMENTS.md; the user's optional-audio
requirements and inspected code supplied the review criteria.

## Outcome

The initial review requested changes for two Important design gaps. Both were
resolved in the document and independently re-reviewed. Final verdict: **Approve
the proposed direction**, with runtime acceptance gates still open. The root
document remains **Proposed** because no human approval or implementation is
implied by that verdict. Application code and processor behavior were not changed.

The request walk-through covered microphone input through RoomIO, common STT/VAD/
interruption consumers, inference and raw fallback, concurrent sessions, track
replacement and partial initialization/shutdown. The main tradeoff is bounded
failure recovery through process isolation versus startup, IPC, memory and fixed
playout delay. No new service or generic processing framework is justified.

## Findings and disposition

1. **Important, resolved: spawned children can inherit credentials.**
   Original decision: session-owned spawned process plus a statement not to send
   credentials. `app/config/settings.py` loads dotenv into the parent environment;
   ordinary child creation inherits it. Installed SDK Windows jobs use threads,
   so temporarily clearing the environment also races other voice sessions.
   Evidence: traced settings and installed SDK worker source; no child launched.
   Resolution: controlled subprocess with an explicit minimal environment
   allowlist, no child dotenv/settings loading, and no parent environment mutation.
   INV-8 requires concurrent child-environment checks while parent credentials
   remain intact. Runtime enforcement is still unimplemented.

2. **Important, resolved: per-session limits cannot enforce aggregate capacity.**
   Original ownership did not identify who caps children across sessions. Each
   supervisor could independently admit its own child. SDK development load
   defaults do not establish a hard audio-child cap.
   Evidence: traced job execution/load defaults and proposal ownership; no load
   experiment run. Resolution: one shared admission owner per Windows AgentServer,
   reserve before model startup, release only after reaping, and use raw mode when
   full. Multiple servers need divided operator quotas; cross-platform job-process
   coordination remains a portability gate. INV-4 covers concurrent admission,
   failed initialization and capacity release without adding a resource service.

No further Blocker or Important contradiction was found after these revisions.

## Implementation risks and acceptance gates

- **SDK attachment and common audio:** RoomIO assigns `session.input.audio` during
  startup. A public wrapper must be proven to attach before consumption and detach
  cleanly; `stt_node` alone does not change audio reaching VAD/interruption. The
  synchronous FrameProcessor callback cannot perform expensive inference on the
  event loop. Verify pinned SDK 1.8.12 with pass-through/slow-worker contract tests.
- **Timeline/fallback:** RNNoise and DFN3 experiment outputs have measured 20/30 ms
  delays. Raw fallback must represent the same capture window under fixed bounded
  scheduling; drop late processed results and invalidate the epoch. Check startup,
  resampling, partial frames, buffered output, overload and reconnect without
  duplicate or missing words. No timestamp mapping is claimed implemented.
- **Lifecycle/isolation:** test module-level Windows child entrypoints, sanitized
  environment, partial startup, native hangs, cleanup failures and process reaping.
  Cancellation of an await does not stop native inference. Serialize model close
  with inference; the parent must never free a model still in use.
- **Evidence/budgets:** concrete deadlines, queue/capacity limits and laptop
  concurrency remain unapproved. RNNoise sustained synthetic tests include compute
  overruns and a 690 ms scheduling outlier. VoxLock measured RTF >1; the current
  DFN3 adapter is batch-only. Require real recordings, listening and controlled
  concurrent-load tests; no synthetic result establishes identity or speech quality.
- **Speaker policy:** verification/separation/detection remain disabled. Enrollment
  requires explicit consent and track/session scope. Unknown scores do not grant
  tool rights; optional quality bypass cannot bypass a future authorization gate.

These gates block enabling production processing, not documenting the direction.
The subsequent Blueprint improve pass addressed the earlier code-review findings:
roomless replay cleanup before/after failures (`app/evaluation/voice.py`), actual
final-chunk deadlines (`evaluation/voxlock.py`) and ignored baseline report output
(`evaluation/baseline.py`). Regression tests reproduced all seven original failure
cases before the fixes. The implementation retains the existing shutdown order
while attempting all acquired-resource cleanup, measures final chunks against
their actual audio duration, and validates the exact baseline output path before
evaluation starts. Shared artifact guards now live in `evaluation/artifacts.py`.
The architecture's future runtime processing remains unimplemented.

The subsequent independent Blueprint code review approved these fixes: **133
focused tests passed**, Ruff lint/format passed, and replacing the corrected
functions with their original implementations in memory made all eight targeted
regression cases fail. This checks regression sensitivity without changing the
source tree. Optional defensive scoring validation remains outside these fixes.
Full backend verification with real-provider evaluation disabled: **587 passed,
10 skipped**; Ruff lint passed and formatting passed for **127 files**. No models
or microphone/provider calls were required for this improvement pass.

## Verification and limits

Current claims were checked against main/session composition, provider pipeline,
configuration, observability, audio interfaces/processors, evaluator callers and
model guides, plus installed LiveKit input/recognition/worker source. Both Mermaid
diagrams rendered successfully and their labels matched the documented paths.
Source code did not change, so application tests/builds and inference were not
rerun. No paid provider calls or microphone capture occurred.

```text
VERDICT: Approve
UNVERIFIED: Runtime SDK attachment; delay-correct fallback; concrete latency/capacity limits; sanitized subprocess launch; real-microphone and concurrent-load behavior
REVIEWED_AT: bf477d13e3358bd74405330666356e29f729a684 + proposed ARCHITECTURE.md dated 2026-11-16
```
