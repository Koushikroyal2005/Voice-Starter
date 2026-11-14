# Creating a new use case

A use case is a small, trusted Python module, not a downloaded plugin, a separate
agent or a new voice engine. The Next.js app stays at the root; common LiveKit,
provider, tools, MCP, persistence and telemetry code stays shared.

## Try the complete education example

In `backend/.env`, retain your real provider and LiveKit credentials. In PowerShell:

```powershell
cd 'E:\voice agent starter\voice-agent-starter\backend'
uv sync --extra mcp --extra telemetry
$env:USE_CASE = 'education'
$env:TOOL_ALLOWLIST = 'get_current_time,calculate_expression,time_and_calculate,create_study_plan'
$env:STT_LANGUAGE = 'en'
$env:TTS_LANGUAGE = 'en'
uv run python -m app.main dev
```

In another terminal:

```powershell
cd 'E:\voice agent starter\voice-agent-starter'
corepack pnpm dev
```

The existing frontend and worker still need the same `LIVEKIT_URL`, key/secret and
`AGENT_NAME`. The latter is a **dispatch registration name**, not the assistant's
display name. Do not change it just because a use case is called Study Companion.
An empty `AGENT_NAME` retains automatic dispatch. Existing development-token security
restrictions remain unchanged; production still needs authenticated token issuance.

Connect and ask: “Create a three-day study plan for fractions, twenty minutes per
day.” The model must select `create_study_plan`; the real deterministic service
returns a suggested routine, and an approved `study_plan` event renders its card.
This creates no student record, calendar event or external action. API credentials
are required for voice; the tool/service/card contract itself is tested offline.

Use `USE_CASE=general_assistant` (or omit it) for the original assistant. Unsupported
IDs fail configuration instead of importing arbitrary paths. Restart the worker to
change modules. This is deployment-time selection, not a browser-controlled switch.

## Where the example lives

```text
backend/app/usecases/
  base.py                           UseCase, policies and allowlisted public schema
  registry.py                       explicit reviewed module imports
  examples/
    general_assistant/__init__.py   original prompt and tools
    healthcare/__init__.py          health-information conversation scaffold
    education/
      __init__.py                   name, prompt, configuration and tool factory
      services.py                   deterministic StudyPlanService and typed schemas
      tools.py                      one provider-independent tool and UI disclosure
    finance/__init__.py             financial-concepts scaffold
    small_business/__init__.py      business-ideas scaffold
components/usecases/
  result-cards.tsx                   trusted application renderer registration
  education/
    study-plan.ts                   untrusted payload validation
    study-plan-card.tsx             custom React result card
lib/usecase-config.ts               public schema parser and general display fallback
```

Healthcare/finance/business are examples, **not** complete products. Prompts and
notices are not clinical validation, financial suitability, emergency handling,
regulatory compliance or a guarantee against harmful model output. There are no
patient/account/customer integrations. They intentionally do not invent tools.
Healthcare and finance disallow transcript persistence; all specialized examples
disallow side-effecting tools. Those are technical restrictions, not safety claims.

## Add your module

1. Copy the education example to `backend/app/usecases/examples/reading_coach/`.
   Give it `id="reading_coach"`, `name="Reading Coach"`, a new description and a
   new prompt. For example: “Help build a suggested reading routine. Ask for the
   topic and available days, then use create_reading_plan. Never claim anything was
   scheduled or saved.”
2. Rename `StudyPlanService` to your domain service, e.g. `ReadingPlanService`.
   Keep deterministic rules and typed Pydantic inputs/outputs there. A service can
   call an ownership-scoped repository if needed; do not expose SQL or database
   mutations to the LLM. Business tables/migrations belong outside common voice tables.
3. Rename the one tool to `create_reading_plan`, update the factory imports and
   `default_tools`/`allowed_tools`. The factory constructs a service and closes over
   it in its async handler. No DI container or provider-specific tool implementation
   is necessary. Keep real external operations honest; a demo must not claim a write.
4. Return an explicitly reviewed `PublicCard(card_type="reading_plan", data=...)`
   plus a plain-text `public_result` fallback. Never publish an arbitrary internal
   response object, credentials, private records or unreviewed MCP results. The
   existing executor bounds UI events, validates approved types and preserves real
   operation success if presentation fails; it never retries an action to fix a card.
5. Add `reading_plan` to the module's `result_card_types`. Copy/adapt the frontend
   education validator and card into `components/usecases/reading_coach/`. Register
   its renderer in `components/usecases/result-cards.tsx`. No voice-shell domain
   conditionals are needed. Render plain React text, not arbitrary HTML from tools.
6. Import the module's `USE_CASE` in `backend/app/usecases/registry.py` and register
   it in the explicit tuple. Set `USE_CASE=reading_coach`, configure credentials,
   restart, then test. Do not add dynamic imports based on request input.

The education module is the executable reference for all these steps: a different
name/description and prompt, one tool, one service and one custom card. No main-agent
logic or STT/LLM/TTS implementation changes are needed to add another such module.

## Configuration and policies

`UseCase` provides:

- Identity/instructions: `id`, `name`, `description`, `instructions`.
- Languages: `supported_languages`, with enforcement by default. Examples declare
  only English; add a language only after verifying the chosen models/voices and
  evaluation scenarios. The general assistant retains provider-configured languages.
  The frontend language list is informational; live provider switching is not enabled.
- Providers: backend-only `provider_defaults` for `STT/LLM/TTS_PROVIDER`, `MODEL`,
  `LANGUAGE`, `VOICE`, `BASE_URL`; optional `allowed_providers` by lowercase category.
  Environment values override defaults but cannot bypass restrictions. Credentials
  stay exclusively in the existing backend environment variables. Registry capability
  checks and fallback compatibility checks still apply to selected providers.
- Tools: `tool_factory`, `default_tools`, and `allowed_tools`. An explicit
  `TOOL_ALLOWLIST` is authoritative, including blank (disable all). If an existing
  `.env` lists only the three old tools, add the new tool or remove that override
  to inherit module defaults. Never silently expand an operator's allowlist.
- MCP: `mcp_servers` is the approved server-ID tuple; `mcp_tool_allowlist` lists exact
  names such as `mcp_maps_lookup_place`; `mcp_config_file` can select a private policy
  file. You must also enable `MCP_ENABLED=true` and select the tools in the ordinary
  allowlist/defaults. Both the module scope and existing MCP schema/permission/
  confirmation policy apply. Unapproved servers are not contacted. No example
  automatically connects to an external server. General-assistant `mcp_servers=None`
  preserves the previous explicit MCP-file/tool-allowlist configuration.
- Conversation policies: additional always-appended policy instructions,
  `allow_transcript_storage`, `allow_side_effects`, `require_confirmation_for`.
  `AGENT_INSTRUCTIONS` can override the main prompt, not these deterministic policy
  checks. To require approval for a tool, supply its reviewed `confirmation_summary`
  and include its exact name in `require_confirmation_for`; missing summaries fail
  composition. Existing sensitive tools always require confirmation. A module cannot
  disable that requirement, grant a user write permission or remove idempotency rules.
- Domain services: construct them in the tool factory, optionally document their
  names in `service_names`. This is documentation, not automatic service discovery.
- UI: public display fields, `notice`, and `result_card_types`. The frontend app
  boundary supplies renderers to the reusable shell.

## Public configuration boundary

After connection, the browser calls `voice.usecase_config` on the authenticated agent
participant. The worker authorizes only the session's linked participant. It returns
only `schema_version`, `id`, `name`, `description`, `languages`, `result_card_types`,
and `notice`. It does not serialize Settings, prompts, provider URLs/models/keys,
MCP connection details, services or permissions. Client parsing selects fields and
validates size/schema. Never replace this with `dataclasses.asdict(settings)`.

Before connecting, the UI uses a checked-in neutral general display configuration.
The worker is authoritative once connected. Unknown/malformed card payloads fall
back to the existing text ResultCard. Renderer code is checked in and trusted;
configuration cannot download components or enable tools. A display name is not an
authentication or authorization decision. Backend policy remains the authority.
If RPC configuration cannot be verified, the UI shows a warning and permits only
generic result rendering; it does not keep a stale specialized module's display.

## Tests and verification

```powershell
cd 'E:\voice agent starter\voice-agent-starter\backend'
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
cd ..
corepack pnpm test
node node_modules/typescript/bin/tsc --noEmit
corepack pnpm build
```

Backend tests cover default/specialized composition, denied language/tool/provider
selection, private/public separation, domain validation, real executor output,
confirmation, MCP scope/deferred activation and authenticated UI RPC. Frontend tests
cover public parsing, payload validation and generic fallback contracts. None of
these offline tests prove live speech quality, model tool selection, clinical or
financial safety. Verify actual voice/audio and custom-card display with real
credentials using the existing [voice evaluation](voice-evaluation.md) and
[observability](observability.md) guides; report untested integrations explicitly.
