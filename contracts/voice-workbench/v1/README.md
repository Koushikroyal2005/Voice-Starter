# Voice Workbench v1 — protocol inventory and compatibility

## Before this refactor

Inspected `services/workbench.py`, tool executor/confirmation producers,
orchestrator revision stamping, observability errors, use-case public models,
`state.ts`, `use-voice-workbench.ts` and `lib/usecase-config.ts`.

The reliable, targeted LiveKit data topic is **`voice.workbench.v1`**. It carries
plain JSON objects, not an envelope. No event has a required version field.

- `tool`: required `type`, `id`, human-readable `name`, `status`; optional
  `description`, `revision`, `confirmation_id`. Status is selected, running,
  completed, failed, confirmation_required, unknown, done, error or cancelled.
  Confirmation-required events must contain a 20–100 character confirmation token.
  Native SDK fallback events may lack revisions; orchestrator events have them.
- `result`: required `type`, `id`, `title`, `text`; optional `card_type`, `data`,
  `revision`. Card payloads are public disclosures, not arbitrary internal results.
- `interrupted`: `type` only (optional orchestrator revision is compatible).
- `error`: `type`, `code` (provider_unavailable or transcription_timeout), with
  optional revision and safe producer `message`. Client copy is selected locally from the code; raw exception
  messages are never displayed.

Existing RPC methods (method name is LiveKit metadata, not a payload field):

- `voice.interrupt`: `{}` → `{"interrupted":true}`.
- `voice.confirm_tool`: `{confirmation_id:string,approved:boolean}` →
  `{"accepted":true}`. Approval is one-use, linked-human-only, with a 512-character
  request limit. Schema validation never grants permission or resolves approval.
- `voice.tools_state`: `{}` → array of tool events; backend selects at most 16,
  bounded to 14,000 UTF-8 bytes. The older frontend accepts up to 32 entries.
- `voice.usecase_config`: `{}` → public configuration with schema_version exactly
  1, id, name, description, languages, result_card_types and notice. No provider
  settings, instructions or credentials are public.

Existing RPC errors are LiveKit `RpcError`: 2001 linked-caller denial, 2002 invalid/
expired/replayed confirmation, 2003 non-cancellable action, 2004 interruption
timeout. They reject the RPC; they are not successful response payloads.

Validation previously lived in handwritten Python RPC checks/Pydantic public
models and independent TypeScript interfaces/parsers. Tests covered these sides
separately. ToolResult/domain schemas are NOT the browser wire contract.

## Shared contract

`events.schema.json` and `rpc.schema.json` use JSON Schema Draft 2020-12. `$defs`
and local cross-file references avoid duplicating tool events or empty requests.
The RPC root is a **test/type catalog**, not a new on-wire envelope. Definitions
validate individual request/response bodies at the actual LiveKit boundary.

Valid v1 payloads, topic, RPC names and field names are preserved. Schema `$id`
URLs identify local resources; validators never fetch those URLs. Unknown types,
methods or incompatible public-config versions fail closed. New boundary validation
rejects malformed no-argument RPC bodies that were previously ignored. Errors
2005/2006 identify invalid request/response respectively; safe optional `RpcError.data`
contains only a fixed code/method, never values or validator exception text.

Events retain the existing 16 KiB transport budget. Schema string lengths count
Unicode code points; transport budgets count UTF-8 bytes. No audio frames pass
through these validators. Business-card content retains its domain-specific parser.

Frontend parsers retain compatibility projections: unknown properties are dropped,
raw error messages are ignored, oversized result IDs are truncated, and invalid
optional card metadata falls back to generic text. Canonical outgoing backend
payloads are strict. Shared schemas do not replace sender authentication, tool
allowlists, ownership checks, permissions, confirmation or disclosure policies.

## Generation and verification

From the repository root (Node 24/pnpm 9.15.9):

```powershell
corepack pnpm install --frozen-lockfile
corepack pnpm contracts:generate
corepack pnpm contracts:check
corepack pnpm test
corepack pnpm typecheck
corepack pnpm build
```

`json-schema-to-typescript` derives one generated type module; Ajv 2020 derives
standalone CommonJS validators and declarations. No schema compilation/eval occurs
in the browser. Ajv's small runtime helpers are bundled with generated code.
`lib/workbench/generated/` is checked in, excluded from hand-authored lint rules,
and checked byte-for-byte by `contracts:check`; TypeScript still checks consumers.
Scoped `.gitattributes` rules and LF generation keep those checks stable across
Windows/Linux checkouts. The topic constant is generated from `$defs.topic`;
it is not independently maintained in Python and TypeScript.
Do not hand-edit generated files. Domain result parsers and UI view models remain
separate; their wire fields derive from generated types. Hook effects/commands
were not extracted or redesigned.

Python uses cached `jsonschema.Draft202012Validator` instances and an explicit local
reference registry. It validates events before queuing and request/response bodies
at RPC handlers, after caller authentication. Invalid outgoing messages are dropped
with fixed metadata-only warnings. No schema URL is retrieved at runtime.
`jsonschema` and its `referencing` registry are now declared core dependencies;
MCP itself remains optional. These are one Python validation stack, not competing
schema implementations.

The corpus is generated from actual production serializers/RPC handlers, executor
and confirmation events, the public Pydantic serializer, observability producers,
MCP ToolDefinitions and LiveKit error serialization. Room/session I/O and the MCP
remote call are test doubles. `unknown`/`cancelled` use the real event formatter;
their operation semantics remain covered by executor tests. No provider calls,
external MCP availability or audio latency are measured by this corpus.

```powershell
cd backend
uv sync --locked --extra mcp --extra telemetry
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
cd ..
corepack pnpm contracts:fixtures
corepack pnpm contracts:fixtures:check
```

Fixture generation needs that backend venv with the MCP extra. Both language test
suites consume `fixtures.json`; a backend test regenerates and compares it using
real serializers. Frontend CI checks schema generation without needing Python;
backend CI checks producer/fixture agreement. Schema edits must regenerate both
types/validators and (where intentional) fixtures in the same change.

## Compatibility and remaining debt

No event type, RPC method, successful JSON field, topic or required wire envelope
was added or renamed. JSON whitespace is not part of the contract. Safe validation
error metadata is additive, using the SDK error transport. Invalid payloads that
previously slipped through are now rejected. UTF-8 failures/non-finite output fail
safely. Schema string limits use Unicode code points, so valid non-BMP names now
agree with Python instead of the old JS UTF-16 length checks.

Existing Pydantic public/domain models remain intact; contract tests detect drift
at serialization rather than replacing business validation. Empty RPC bodies are
now validated (old handlers ignored them). Unknown SDK RPC methods still use the
native unsupported-method mechanism. Application error codes are covered here;
other SDK connection/network errors are not application payloads.

Contracts validate shape, not sensitive-data meaning inside explicitly public text
or card data. Sender/caller authentication, human approval, output disclosure and
domain card validation remain essential. The schema is not an authorization or
redaction system. v2 negotiation, schema registries, generic transport abstractions
and hook/lifecycle refactors are intentionally not introduced.

Malformed snapshots now fail as a whole rather than partially merging valid
entries. This is a validation tightening, not a change to valid v1 snapshots.
No real voice call, acoustic regression or container build was verified in this
phase; container packaging needs a running Docker engine.

## Files for this refactor

- Source contracts: this README, `events.schema.json`, `rpc.schema.json`, and the
  checked-in `fixtures.json` in this directory.
- Backend: new `app/workbench/__init__.py` and `app/workbench/contracts.py`;
  validation integrated only in `app/services/workbench.py`.
- Frontend: new `lib/workbench/contracts.ts` and generated `types.ts`,
  `validators.cjs`, `validators.d.cts`; existing `components/voice/state.ts`,
  `use-voice-workbench.ts` and `lib/usecase-config.ts` consume them.
- Tooling: two `scripts/generate-workbench-*.mjs` scripts, package/lockfiles,
  scoped `.gitattributes`, generated-file ESLint exclusion and CI drift check.
- Tests: Python exporter and contract tests; Node contract tests and shared TS
  loader; existing voice-state/use-case tests now load actual imported validators.
- Packaging/docs: worker Dockerfile and Compose named contract context, Docker
  guide and root README link. Existing Opportunity 1 changes were preserved.

## Executed verification — 15 November 2026

- `uv run pytest -q`: **259 passed, 10 skipped**, final run 53.73 seconds. Skips
  are two real PostgreSQL/Redis contracts and eight opt-in voice scenarios.
- `uv run ruff check app tests`: passed.
- `uv run ruff format --check app tests`: passed, 88 files.
- `pnpm test`: **70 passed**, zero failures/skips.
- `pnpm typecheck`, `pnpm lint`, `pnpm build`: passed on Next 15.5.28 / Node 24.
- `pnpm contracts:check` and `pnpm contracts:fixtures:check`: passed.
- Compose configuration including the named context and Redis profile: passed;
  Docker engine unavailable, so no image build/start verification.
- Changed-file formatting and `git diff --check`: passed. Tracked-file secret
  heuristic found no matching patterns; this is not exhaustive secret detection.

A local CPU-only sample of 2,000 synthetic tool events measured **0.339 ms/event**
for cached validation plus JSON serialization. This is not an acoustic latency
benchmark or a guarantee under production load. The final build reports about
606 kB first-load JS versus 600 kB at the preceding audit; no bundle optimization
or UI redesign was attempted.
