# Main stabilization findings

- High: raw VAD `user_state_changed(speaking)` cancelled safe tools and pending
  confirmations before native interruption handling. Removed the duplicate bridge
  listener. The orchestrator already uses native SpeechHandle interruption and
  ToolFlag.CANCELLABLE. Explicit interrupt RPC and shutdown retain cancel_safe()
  and protection for running non-cancellable writes. No new timers/state machine.
- Medium: microphone switching did not await its SDK promise. Await switching
  before persisting the chosen device and forward errors to existing error UI.
- Low: compact device selection lacked an accessible name. Added one, and explicit
  Mute/Unmute labels. Existing LiveKit controls and real audio visualization remain.
- Medium DX: quick start mixed Cloud/legacy defaults with the verified local
  pipeline. Example envs and README now start with local LiveKit and groq_nvidia.
  Real ignored env files remain untouched.

## Installed SDK semantics

Inspected LiveKit Agents 1.8.12 voice/events.py, speech_handle.py,
agent_activity.py and the existing orchestrator adapter. VAD speaking is an audio
observation, not reliable proof of intended interruption. Actual tool interruption
remains owned by LiveKit SpeechHandle.wait_if_not_interrupted and interrupted.
Removing the earlier blanket cancellation preserves native thresholds without
adding a delay. No perfect noise/speaker distinction is claimed. Existing tests
exercise actual adapter in-flight cancellation and non-cancellable write protection.

## Known limits and optional work

A browser microphone permission prompt can outlive cancellation. The native API
cannot dismiss that dialog; startup remains serialized until SDK startup settles.
Allow/deny the prompt or reload if pending indefinitely. This is not a completed
permission-dialog cancellation guarantee.

Push-to-talk is deferred to voice-optimization. Correct optional support requires
release on pointer cancel, focus loss, keyup, device switching, room replacement and
errors while coordinating asynchronous microphone toggles. Adding another mute
owner is not sufficient. Hands-free behavior remains the default; no acoustic
optimization or new dependencies were introduced.

CI already uses locked Node24/Python3.13 dependencies and runs tests, lint,
contracts, secret checks and build without real provider calls. Follow
[local smoke tests](local-smoke-tests.md). Freeze readiness depends on current
checks plus manual microphone, speaker, device switching, spoken interruption and
mobile acceptance. Hosted quotas/endpoints and preview models remain external risks.

## Executed checks, 16 November 2026

Backend pytest: 454 passed, 10 skipped. Ruff lint and formatting passed.
Frontend unit tests: 101 passed, zero failed; TypeScript checking passed.
Offline provider doctor resolved
groq_nvidia without overrides. The initial offline pass made no real provider
calls; follow-up live and manual results are recorded below.
ESLint, shared schema and Python/TypeScript fixture agreement, secret scan and
Git whitespace checks passed. The first fixture invocation hit its 60-second
subprocess timeout; the subsequent check passed without changing fixtures.
Follow-up verification: stopped the concurrent Next.js development server and
ran one isolated production build, capturing stdout/stderr and inspecting the
compiler/validation child processes and `.next` diagnostic stages. It completed:
compilation in 91 seconds, lint/types, four static pages, tracing and route summary.
No compiler error or application fix was needed. The previous stall's exact cause
cannot be established retrospectively. Concurrent dev/build shared `.next`, and
only about 2.2 GB RAM was initially free; these are observed environmental risks,
not proof of a specific deadlock. Stop dev before building. The built server's
token endpoint returned HTTP 403 as required; the development server was restored.

Repeated backend tests: 454 passed, 10 skipped in 93.92 seconds. Ruff lint and
format passed. Repeated frontend tests: 101 passed; contracts, fixture agreement,
secret scan and whitespace checks passed. Production build included lint/type
validation. No credentials or ignored env files were changed.

Live doctor: Groq STT and streaming LLM passed; NVIDIA TTS timed out (doctor uses
a bounded 10-second provider request, no retries). This is not an audio success.
Initial local room attempts timed out: two during frontend cold compilation,
then RTC failed against the old local server. Restarting the same local LiveKit
configuration restored browser RTC connection. Worker dispatch and complete
audio acceptance still need the results below; do not infer success from a
listening port. At 390px width idle and connected controls fit without horizontal
overflow. Physical microphone/speaker and spoken interruption require a person.

Final browser check: the restarted server accepted RTC and End Session returned
the UI to Not connected. Connected mobile text/mute/interrupt/end controls stayed
within the viewport. Worker startup eventually registered at 01:06:34 after a
slow cold import; there was no configuration error. A subsequent native RTC
diagnostic passed dispatch, synthetic microphone speech (one final transcript),
tool selected/running/completed, 4,166 nonempty received audio frames, explicit
interrupt RPC, disconnect, fresh-room redispatch and second disconnect. This is
software media-path evidence, not physical microphone/speaker acceptance.

The browser then completed calculator 2+3 with result 5.0, showed speaking and
listening states, and had an unmuted, non-paused audio element with readyState 4,
a live enabled track and advancing playback. A second text turn was submitted
and the explicit Interrupt button exercised; this is not spoken barge-in.
The earlier doctor NVIDIA timeout remains a failed diagnostic, not silently
reclassified as passed because subsequent room synthesis worked.

The dev process used roughly 3.6 GB RAM with about 1.7 GB free. This is measured
resource pressure, not a proven explanation of worker startup. No unrelated
source refactor or provider-timeout increase was made.

## User-confirmed manual acceptance

On 16 November 2026 the user confirmed the final manual voice tests completed
successfully: microphone selection, mute/unmute, voice transcription, audible
TTS, normal tool execution, genuine spoken interruption, explicit interruption,
multiple conversation turns, disconnect/reconnect and mobile controls. These are
user-reported physical/browser acceptance results, not automated measurements.

Freeze decision: accepted for the stable local-development main baseline after
successful production build, automated regressions, software pipeline checks and
user-confirmed manual acceptance. The earlier NVIDIA diagnostic timeout and slow
cold startup remain documented reliability limitations, not erased test failures.
This is not production deployment certification or a guarantee of hosted quotas.

Finalization checks: backend 454 passed, 10 skipped (69.79 seconds); Ruff lint
and formatting passed. Frontend 101 passed, contracts and Python fixtures agreed,
and staged-file secret/whitespace checks passed. The successful production build
above remains applicable: no application source changed during finalization.
Final TypeScript and ESLint checks also passed.

Stabilization is committed on main only. Existing changes and ignored credentials
are preserved; voice-optimization remains at 45d7587 and is neither modified nor
merged. No additional features were introduced during finalization.
