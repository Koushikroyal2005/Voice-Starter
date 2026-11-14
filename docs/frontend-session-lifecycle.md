# Frontend session lifecycle and workbench synchronization

Opportunity 3 preserves the `useVoiceWorkbench()` public Interface, UI, native
LiveKit audio/transcription hooks, `deriveVoiceState()` and v1 wire contracts.
There are two internal Modules, not one hook per RPC or a replacement session
state machine. No backend files or generated contracts changed in this phase.

## Characterized behavior before refactoring

The single facade owned SDK preparation/start/end, a start AbortController and
one command lock shared with interruption; a reducer for command/error/interruption
display; room packet/media/disconnect listeners; snapshots and confirmation;
public use-case loading; tool/result arrays and an 80-entry timeline.

Start cleared the conversation, prepared the connection, then called native
`start` with the microphone enabled unless text-only. Cancel aborted startup and
disconnected the room but retained the lock until startup settled. Start failures
disconnected and showed safe microphone/network guidance. Double commands were
ignored while another command held the lock (including end during interruption).
End called native `end`; interruption waited for a validated worker acknowledgement.
Disconnect marked unfinished tools unknown and removed approval tokens. Unexpected
disconnects showed a fixed error. Live data authenticated topic and agent identity.
Snapshots were optional and merged with live tools using their existing revisions.
Effect cleanup removed listeners. Only configuration loading had a cancellation flag.

Before changing production code, 16 real React hook tests were run with deferred
promises and lightweight room/session test doubles: **10 passed, 6 failed**. The
failures reproduced late snapshots after disconnect, new conversation start,
reconnect and Strict Mode replay; a late confirmation starting a stale follow-up
snapshot; and an old interruption acknowledgement marking a disconnected session
interrupted. These were correctness failures, not acoustic/provider benchmarks.

## Responsibility map and Seams

Before: `UI -> useVoiceWorkbench -> lifecycle + RPC + listeners + public config + timeline`.

After:

```text
UI (unchanged)
  -> useVoiceWorkbench (same public Interface; native state mapping, timeline)
      -> useVoiceLifecycle (command ownership, start/cancel/end, interruption lock)
      -> useWorkbenchSync (LiveKit transport Adapter, scoped listeners and RPC)
          -> existing shared parsers/generated validators
      -> native useSessionContext / useAgent / useSessionMessages
```

The lifecycle Module receives narrow operation callbacks, rather than accessing
the synchronization Module's internals. The synchronization Module can invalidate
an outstanding interruption command through one callback. That Seam releases the
old command immediately, without letting its eventual RPC completion clear a new
session's error or mark it interrupted. The facade composes these callbacks.

The depth is in ownership and ordering guarantees, not generic interfaces. Locality
keeps transport rules in one Module. Tests have Leverage at the public hook boundary:
they execute real React effects/reducers with only the LiveKit boundary doubled.

## Generation ownership

Each committed room/agent identity/connection state/use-case binding receives a
new private scope object. Object identity is its epoch token. Cleanup invalidates
the object and removes each listener once; old scopes never become valid again,
including during Strict Mode effect replay. Layout effects establish ownership at
commit, before passive effects or subsequent asynchronous callbacks.

Start, cancel and end also invalidate synchronization immediately. Native connection
events fence responses synchronously, without waiting for React to rerender.
LiveKit emits `ConnectionStateChanged(disconnected)` before `Disconnected(reason)`;
the first fences RPC/data, while the lifecycle listener remains until the reason
arrives or the scope is disposed. Unexpected-disconnect feedback is preserved.

Every noncancelable RPC checks its captured scope after awaiting, including failure
paths. State updater functions check scope ownership too. Confirmation cannot start
a follow-up snapshot in another scope. Invalidated confirmation promises quietly
settle; they neither approve a new request nor surface a stale error in a reused
card. Authorization and one-use confirmation tokens remain backend-owned.

Snapshots have a latest-issued request sequence within the scope. Older overlapping
requests cannot append obsolete tools. Existing per-tool revision handling remains;
live updates received while a snapshot is pending also win over equal/absent
revisions. A strictly newer snapshot revision can still advance a tool.

Lifecycle operations have their own private owner token. A start must survive native
disconnected/connecting/connected transitions, so it cannot use a synchronization
epoch as its sole cancellation signal. Commands remain mutually exclusive.
Native startup receives its AbortSignal; preparation has no signal parameter.
Unmount/room replacement aborts unfinished startup and invalidates its owner.
Late errors, finally blocks and preparation completions cannot affect a remount.
Established sessions are not automatically ended by this hook's cleanup.

If native end rejects while the room remains connected, a new synchronization
generation restores listeners and snapshots; the invalidated one is never revived.

## Verification

From the repository root on Windows PowerShell:

```powershell
corepack pnpm install --frozen-lockfile
corepack pnpm test
corepack pnpm typecheck
corepack pnpm lint
corepack pnpm build
corepack pnpm contracts:check
corepack pnpm contracts:fixtures:check
```

`tests/voice-workbench-lifecycle.test.cjs` mounts the actual public hook using
React DOM and test-only jsdom. It controls promises explicitly, without sleeps.
Coverage includes all six reproduced races plus startup cancellation at both
awaits, double commands, interrupt/end exclusion, snapshot/live ordering (including
legacy revisions), overlapping snapshots, current and obsolete confirmations,
unmount/remount, Strict Mode, room replacement, permission failure, RPC rejection,
safe public configuration, result-card data and native state transitions.
Existing state, card/config, token security and shared-contract suites are retained.

Verification on 15 November 2026: all 99 frontend tests passed (29 new hook tests);
TypeScript, ESLint, the production build, formatting, generation drift and actual
Python fixture agreement checks passed. The initial 16-test run against the old facade had six failures,
as described above. No credentialed voice session was performed in this phase.

## Remaining boundaries

- Ignoring a late RPC response cannot undo an approval/action already received by
  the worker. Existing backend permissions, confirmation, idempotency and cancellation
  semantics remain authoritative. No new retry was added.
- SDK preparation and RPC do not expose AbortSignal parameters. A canceled startup
  retains its lock until the outstanding SDK call settles; this deliberately avoids
  overlapping native connections. SDK/network timeouts still govern those calls.
- RPC requests retain the existing `responseTimeout: 5000`; LiveKit's current JS
  implementation clamps small values to a transport minimum. Tests inject timeout
  rejections; they do not claim to measure a five-second wall-clock timeout.
- Reconnect snapshots can still fail; authenticated live events remain the fallback.
  Legacy revisionless events have no absolute global order across the transport.
- Real network reconnection, microphone/audio playback, spoken interruption and
  provider behavior still need credentialed browser checks. jsdom tests prove local
  asynchronous ownership, not successful LiveKit dispatch or voice quality.

API references checked against installed SDK source/types and official documentation:
[useSession](https://docs.livekit.io/reference/components/react/hook/usesession/) and
[PerformRpcParams](https://docs.livekit.io/reference/client-sdk-js/interfaces/PerformRpcParams.html).
