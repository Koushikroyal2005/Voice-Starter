# Tool calling and orchestration

One voice agent, one provider-independent execution boundary. LiveKit Agents
1.8.12 owns the LLM tool loop, conversation history, speech and automatic turn
handling. We do not implement a second LLM loop or introduce multiple agents.

## Files and responsibilities

```text
backend/app/
  bootstrap.py                 # Application composition / use-case extension point
  main.py                      # Existing worker and dispatch lifecycle
  agents/
    orchestrator.py            # MainAgent, native tool adapters, runtime registration
    conversation.py            # Session actor, permissions, closed state (not chat history)
    state_manager.py           # Bounded, per-session operation/idempotency ledger
    demo.py                    # Backward-compatible alias, not a second agent
  tools/
    base.py                    # Pydantic schemas, definition, context, result and domain error
    registry.py                # Explicit registration/removal, no dynamic imports
    executor.py                # Policy, validation, deadlines, deduplication, execution
    presentation.py            # Opt-in public summary/card formatting and size/disclosure gates
    permissions.py             # Allowlist + trusted backend permission checks
    confirmation.py            # Expiring, one-use approvals from the linked human
    common/
      time.py                  # Real current time, configurable UTC offset in minutes
      calculator.py            # Bounded arithmetic AST interpreter, never eval
  workflows/
    base.py                    # Structural workflow protocol
    time_calculation.py        # Sequential time check then calculation through executor
  services/workbench.py        # Ordered reliable UI events, authenticated LiveKit RPC
```

`Schema` rejects unknown fields, coerced string numbers and non-finite values.
`ToolDefinition` contains input/output schemas, handler, reviewed UI title and
description, required permission, timeout, sensitivity and cancellation policy.
The adapter derives JSON schemas and creates native `function_tool(raw_schema=...)`
objects. `RunContext` and SDK tool flags are used only in the adapter; handlers do
not import an LLM/provider SDK. LiveKit may expose its native task-management
companions for cancellable tools; those manage only SDK cancellable calls and do
not grant additional business actions.

## Configuration and demo

```dotenv
TOOL_ALLOWLIST=get_current_time,calculate_expression,time_and_calculate
```

An explicitly empty value disables all application tools. Unknown names fail
closed when constructing the orchestrator. Registration alone grants nothing:
only allowlisted tools are exposed and the executor re-checks authorization for
every call (including workflow children and calls resuming after confirmation).
`Orchestrator.register/remove` also uses native `agent.update_tools` so the model's
available tool set changes. Removal immediately revokes execution even if the
provider is still holding an older schema.

With the usual LiveKit/provider credentials configured, run in two PowerShell
terminals from the repository root:

```powershell
corepack pnpm install --frozen-lockfile
corepack pnpm dev
```

```powershell
cd backend
uv sync --locked --group dev
uv run python -m app.main download-files
uv run python -m app.main dev
```

Try “What time is it in UTC?”, “Calculate (18 + 6) / 3”, or “Run a time-stamped
calculation of 6 times 7”. A tool-capable LLM model/endpoint is required; an arbitrary
OpenAI-compatible service is not guaranteed to implement tool calling correctly.

- Clock output is actual wall-clock time. `utc_offset_minutes` is bounded to
  -720…840; no IANA timezone database or location inference is implied.
- Arithmetic supports numeric literals, parentheses, unary signs and
  `+ - * / // % **`. Input length, AST nodes/depth, exponent and intermediate
  magnitude are bounded. Names, calls, attributes, subscripts, comprehensions,
  strings, booleans and complex/non-finite values are rejected. It uses floating
  point and is not a financial-precision calculator.
- The workflow checks the clock, then calculates. Each child operation passes
  through the same policy/executor; a failed first step stops subsequent work.
  It is deterministic sequencing, not a transaction or another agent.

## Execution and results

The execution path is: native tool selected → explicit allowlist and permission
check → Pydantic input validation → operation-key/digest check → optional human
confirmation → re-check permissions/registration → bounded handler execution →
output validation → structured result and reviewed UI result.

Results contain `call_id`, `tool`, `status`, `message`, optional `data` and `code`.
Statuses are `completed`, `failed`, `denied`, `cancelled`, `timeout` or `unknown`.
Invalid arguments and reviewed `ToolFailure` errors have useful public messages;
unexpected failures never expose raw exception text, credentials or arguments.
Cancellation propagates `asyncio.CancelledError` so LiveKit does not narrate an
obsolete successful response. A handler must never swallow cancellation.

Timeouts default to 10 seconds (definition maximum 120), with a separate 45-second
approval deadline. Up to eight operations may be active; the ledger holds up to
256 operation keys and does not silently evict deduplication records. Async timeouts
are cooperative, not CPU/process isolation: use bounded computation and real
client-side network deadlines in handlers; never block the event loop.

## Public presentation boundary

Before Opportunity 5, ToolExecutor owned both execution safety and public result
formatting. `tools/presentation.py` now owns the latter through one synchronous
Interface: `present_result(definition, validated_output, call_id, approved_cards)`
returns an event dictionary or None. It cannot execute a handler, authorize a tool,
obtain confirmation, manage the ledger, cancel tasks, publish events or retry writes.
There is no new service, executor hierarchy, middleware or event schema.

ToolExecutor still owns permission/input validation, operation key/digest claiming,
concurrent waiter shielding, confirmation and post-approval rechecks, handler timeout,
output validation/private serialization, outcome classification, cancellation and
shutdown. It delegates optional formatting, emits completed, optionally emits the
public result, then returns/stores the structured operation result. Event delivery
stays in the existing emitter/workbench bridge; the presenter performs no I/O beyond
the existing fixed warning. This Seam gives pure formatting tests Leverage without
rebuilding the asynchronous execution harness; execution invariants retain Locality.

### Preserved behavior (characterized before extraction)

The existing executor validates handler output and serializes private `ToolResult.data`
before optional public formatting. Only `public_result` opts into a result event;
`public_card` alone does not publish anything. Private output is not an automatic
fallback when presentation is absent or fails. The reviewed definition title is
used unchanged, including an explicitly empty title; no title is inferred from
internal function names or output fields.

The summary is sliced to 4,000 Python characters before serialization. An optional
`PublicCard` must use a type in the executor's use-case-owned card allowlist (default
`text`); its data is serialized with the existing Pydantic model. Unapproved cards,
formatter/card exceptions, non-serializable public data, non-finite values remaining
after JSON-mode Pydantic serialization and
events larger than 12,000 bytes under `json.dumps(..., allow_nan=False)` are dropped
as a whole. This size check retains Python's default ASCII escaping, including for
Unicode. It is not the transport's separate 16 KiB UTF-8 budget. Card data is never
silently truncated to make it fit.
Pydantic's existing JSON-mode serialization normalizes `NaN` inside ordinary card
data to JSON null before the size/JSON check; that behavior is retained.

Presentation exceptions produce only the fixed warning `Tool public result unavailable`,
without arguments, data, credentials, exception details or a traceback. Formatting
failure does not change a completed operation or trigger retries. The existing order
is selected -> optional approval -> running -> completed -> optional result. Cached
duplicates do not rerun the formatter or republish the original result card.

Output-schema validation/private-output JSON serialization happen outside that
presentation guard and retain existing failure/unknown-write classification.
`services/workbench.py` remains the transport Adapter: it validates the emitted
dictionary with shared v1 contracts, queues it and publishes only to the linked user.
No separate hand-maintained result-event schema is needed in the presenter.

The exact existing order is retained: output model validation and private JSON
serialization -> optional presentation -> completed activity -> optional result
event -> completed ToolResult. Presentation failure returns None and logs a safe
warning, without turning success into failure or asking for a second approval.
The successful ledger result remains reusable under the same operation key.

### Add a use-case result card

Define a reviewed `public_result` summary and, if needed, a `public_card` callback
returning the existing `PublicCard(card_type="your_card", data={...})` model. Include
only explicitly public fields, not an arbitrary private-output dump. Add the card
identifier to that use case's `result_card_types`; the orchestrator supplies this
allowlist to the executor/presenter. A custom renderer belongs in the application
result-card registry, not the common voice shell. The existing education example
uses `study_plan`; no engine/executor change is required for another reviewed card.
See [creating a use case](creating-a-new-usecase.md) for the domain service, card
parser and application renderer example.

Generic and custom cards keep the same v1 `type/id/title/text/card_type/data` fields.
The presenter retains existing `PublicCard` validation and JSON budgets; the
workbench Adapter retains shared-schema validation, packet limits, ordering and
linked-participant delivery. The frontend still validates public event/card data
and falls back to its existing generic text rendering. No generated types, schemas,
protocol versions, RPCs, card identifiers or frontend components change here.

### Limits deliberately not redesigned

Formatting failure is not handler/output-validation failure, transport delivery
failure or external transaction reconciliation. Private-output serialization still
happens before formatting; an invalid output can retain a failed/unknown outcome.
An emitter/listener that unexpectedly raises is still governed by the executor's
existing error handling, not swallowed by the presenter. Making event delivery
fully independent of execution outcomes is a separate future task. Reviewed
formatters are synchronous trusted backend code and must remain bounded and pure;
this module is not a sandbox or a data-loss-prevention engine. In-memory idempotency
and external write reconciliation retain their existing limitations below.

## Permissions and human confirmation

The default session grants **only `tools:read`**, bound to RoomIO's linked participant.
Neither the model nor tool arguments may choose permissions or actor identity.
Side-effecting definitions must declare a non-read permission, `sensitive=True`,
`cancellation_safe=False` and a reviewed `confirmation_summary`. Sensitive read
operations can also require confirmation. Server composition must grant the exact
scope only after authenticating/authorizing the business user; LiveKit room
membership alone is not production business authorization. The existing token
endpoint remains development-only.

Confirmation is a random, single-use request bound to the exact validated operation,
argument digest and actor. Only `voice.confirm_tool` from the linked participant
can answer it. There is deliberately no LLM “approve” tool or trusted `confirmed`
argument. The UI shows the reviewed action summary, Approve and Decline buttons.
Expiry, denial, permission revocation, tool removal, session shutdown and cancellation
prevent the pending operation from executing. Summaries must include every material
detail a human needs to decide, without leaking secrets or unnecessary private data.

The demo intentionally has no sensitive/write tool: no fake appointment, payment,
database change or pretend side effect was added just to produce an approval card.
Tests use clearly test-only handlers to verify the real approval/execution machinery.

## Cancellation and side effects

Safe reads use LiveKit's native cancellable flag and
`speech_handle.wait_if_not_interrupted`. Spoken interruption or the Interrupt
button cancels safe active work and pending approvals. The native speech session
is interrupted so obsolete audio is not simply hidden in the browser.

Non-cancellable execution calls `RunContext.disallow_interruptions`. The explicit
interrupt RPC refuses to force-stop an already-running protected operation.
Disconnect/shutdown cancels safe work but waits for protected work's bounded
deadline. Ending a call does **not** undo an external action.

A timeout or unexpected failure after a write started returns `unknown`, not a
claim of rollback. Reconcile the external system before another attempt. There
are no automatic retries of mutations. A workflow containing mutations needs
explicit business transaction/compensation rules; a generic orchestrator cannot
invent them.

## Idempotency limitations

Side effects require a stable `idempotency_key`; it is an execution-envelope field,
not a handler input field. The ledger scopes it by conversation, actor and tool,
and compares canonical validated-argument digests. Concurrent duplicates share
one execution. Completed, denied, failed and unknown outcomes are retained;
reusing a key with different arguments is rejected. Handlers receive the key in
`ExecutionContext` to forward to their business service.

**This ledger is in memory and per session. It is not durable exactly-once execution.**
A new room, worker restart or another process does not share it. Before enabling
real writes, use a durable operation store with a unique business operation ID,
transactional claim/outcome persistence and external API idempotency where available.
Derive that operation ID from trusted business/UI context, not just a fresh model
call ID. New keys represent new operations and will require a new human approval.
No database or Redis was introduced in this phase.

## UI events

The existing workbench consumes reliable `voice.workbench.v1` packets only from
the connected agent. Cards show meaningful reviewed titles/descriptions, with
`selected`, `running`, `completed`, `failed`, `confirmation_required`, `cancelled`
or `unknown` status. They retain actual observed phases, not synthetic delays.
The executor's result is authoritative: SDK transport completion cannot turn a
denied or failed business operation into a successful card.

Packets are published in order. Monotonic revisions prevent a reconnect snapshot
from overwriting newer live events. `voice.tools_state` restores recent/current
statuses and pending approvals for the linked user. A disconnected browser marks
unfinished displays unknown, not “cancelled successfully.” `public_result` is an
explicit opt-in formatter; arbitrary raw arguments/results are never auto-forwarded.

## Add a use-case tool without changing the voice engine

1. Add an input model, output model and deterministic async handler in a use-case
   module under `app/tools/`. Keep domain rules in backend services, not prompts.
2. Create a `ToolDefinition`. For a read-only example, a distance-conversion
   handler can compute `miles = kilometers / 1.609344` from a bounded numeric input.
   Use typed schemas, a human-readable title, a bounded timeout and a permission.
3. Return the definition from your use-case module's `tool_factory` and register
   the module in the reviewed use-case registry. `app/bootstrap.py` assembles
   builtin, use-case and approved MCP definitions and applies initial policy once
   per definition before passing them explicitly to `Orchestrator`. Add its name
   to the use-case tool policy and `TOOL_ALLOWLIST`. No change to `MainAgent`,
   provider factories, the executor, transport bridge or React shell is needed.
4. For a write, inject a deterministic business service, require an application
   permission and human confirmation, and implement durable/external idempotency.
   Never expose SQL, table names, unrestricted query tools or database credentials
   to the LLM. Only reviewed backend functions may modify persistent data.
5. Add tests for schemas, permission denial, confirmation binding/replay/expiry,
   timeout, safe cancellation, duplicate/conflicting keys, failure and reviewed UI
   payloads. Supply `public_result` only after reviewing its disclosure policy.

## Checks

```powershell
# repository root
corepack pnpm test
corepack pnpm exec tsc --noEmit --incremental false
corepack pnpm build
cd backend
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
```

Offline tests exercise actual native SDK registration and adapters plus deterministic
execution, workflows, interruption, permissions, confirmation RPC authentication,
replay/expiry, concurrent duplicates, conflicting keys, timeout and failure paths.
They do not prove a particular hosted model will select a tool or that voice/audio
will work without LiveKit and speech-provider credentials. Verify live selection,
spoken interruption, event cards and audible results with the configured worker.

Opportunity 5 verification (15 November 2026): 68 characterization/execution tests
passed before extracting production code. The completed backend suite passed
**346 tests, 10 skipped**, including 33 new presentation cases (16 pure presenter
cases plus execution-boundary characterization). Ruff lint and formatting passed
for 93 files. Both contract generation/actual Python fixture agreement checks,
all 99 frontend unit tests and `git diff --check` passed. The skips remain external
PostgreSQL/Redis checks and opt-in voice scenarios. No frontend or protocol files
changed, and no external booking, database write, provider request or live voice
session was claimed verified. The write/duplicate proof uses an explicitly
test-only in-memory operation, not a real external business integration.

The existing `test_tools.py` regression tests retain confirmation identity/replay/
expiry, permission revocation/removal while waiting, owner and duplicate-waiter
cancellation, concurrent idempotency, timed-out unknown writes and shutdown checks.
The new `test_tool_presentation.py` focuses on public/private separation, rejected
cards/formatters, serialization budgets, reviewed metadata and successful-write
outcomes when presentation fails; it does not reimplement execution safety tests.

Official API references checked against the installed SDK:
[function tools](https://docs.livekit.io/agents/logic/tools/definition/) and
[async/cancellable tools](https://docs.livekit.io/agents/logic/tools/async/).
