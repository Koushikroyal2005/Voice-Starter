# Optional MCP tools

MCP is an external tool protocol, **not an STT, LLM or TTS provider**. Speech
providers and the existing Next.js app remain unchanged. One LiveKit agent and
the existing deterministic executor remain responsible for every action.

## SDKs and architecture

This implementation uses the official `mcp` Python SDK 2.3.0 and the installed
LiveKit Agents 1.8.12 MCP integration. Both are locked in `uv.lock` through the
optional `mcp` extra. LiveKit's public `MCPServerStdio`, `MCPServerHTTP` and
`MCPToolset` implement the real transport/discovery/calling layer; we do not write
another JSON-RPC client. The deprecated `Agent(mcp_servers=...)` API is not used.

The native MCPToolset is deliberately **not exposed directly to the agent**:
that would bypass application permission, confirmation and idempotency checks.
Only reviewed, discovered tools are wrapped as ordinary application ToolDefinitions
and exposed through the existing native `function_tool` adapters.

Files under `backend/app/mcp/`:

- `config.py`: validated backend JSON configuration and environment references.
- `permissions.py`: pinned JSON schemas, argument validation and disclosure rules.
- `client.py`: supported LiveKit transports/toolsets, result validation and a
  trusted-operator schema inspection command.
- `connection_manager.py`: independent server connections, deadlines, serialized
  calls, health checks, reconnects and cleanup.
- `registry.py`: reviewed policies → namespaced ToolDefinitions; discovery-driven
  activation/revocation through `agent.update_tools`.
- `demo_server.py`: real official-SDK server with one harmless UTC clock tool.

`app/bootstrap.py` loads this layer only when `MCP_ENABLED=true`. With MCP disabled,
no MCP configuration file, optional SDK, server connection or subprocess is needed.
Configured servers connect in the background **after the voice session starts**.
An unavailable external server leaves its tools disabled without preventing normal
voice conversations and local tools. Invalid enabled configuration fails clearly;
it is not silently treated as a working integration.

## Working local demo: Windows PowerShell

From the repository root:

```powershell
cd backend
uv sync --locked --extra mcp --group dev
# Do not overwrite an existing private configuration without reviewing it.
Copy-Item mcp.demo.example.json mcp.servers.json
notepad .env
```

Add/update the following in `backend/.env`, retaining your existing LiveKit and
speech-provider credentials:

```dotenv
MCP_ENABLED=true
MCP_CONFIG_FILE=mcp.servers.json
TOOL_ALLOWLIST=get_current_time,calculate_expression,time_and_calculate,mcp_clock_get_current_time
```

Inspect the actual local server schema without calling its tool:

```powershell
uv run --extra mcp python -m app.mcp.client --config mcp.servers.json --server clock
```

Run the existing worker (stdio launches the clock subprocess automatically):

```powershell
uv run --extra mcp python -m app.main download-files
uv run --extra mcp python -m app.main dev
```

Run the existing frontend in another PowerShell terminal from the repository root:

```powershell
corepack pnpm dev
```

Ask for the **external demo clock**, not just the local clock. Both local and MCP
clock tools are real; their UI display titles distinguish them. The MCP result
passes through the configured LLM for the spoken response. It is not automatically
published as a raw ResultCard.

Use `--extra mcp` on `uv run` commands: running without the extra can remove optional
packages during environment synchronization. Default non-MCP worker commands remain
`uv run python -m app.main dev` with `MCP_ENABLED=false`.

## Streamable HTTP demo

Start a local server in a separate backend terminal:

```powershell
uv run --extra mcp python -m app.mcp.demo_server --transport streamable-http --port 8765
```

In your private JSON, change the clock server's transport fields to:

```json
{
  "id": "clock",
  "enabled": true,
  "transport": "streamable_http",
  "url": "http://127.0.0.1:8765/mcp",
  "allow_http_loopback": true,
  "approved_tools": {}
}
```

The snippet above shows only transport fields: **retain the actual clock
`approved_tools` policy from `mcp.demo.example.json`**, rather than leaving it empty.
Remove `command`, `args`, `cwd` and `env` when changing to HTTP. Restart the worker.
The demo binds only to loopback and has no production authentication; do not expose it
publicly. Remote servers require HTTPS. Legacy SSE is not exposed by this starter;
stdio and Streamable HTTP are the supported configuration transports.

## Approval and authorization

There are two explicit gates before the model can use an MCP tool:

1. `server.approved_tools` contains a reviewed local policy for that exact remote
   tool, including pinned input schema, reviewed output schema, title/description,
   permission, sensitivity and cancellation behavior.
2. `TOOL_ALLOWLIST` includes its exact namespaced name: `mcp_<server-id>_<alias>`.

Only selected, enabled servers are launched/contacted. A tool becomes visible only
after discovery confirms that its remote name and complete input schema match the
reviewed policy. New tools, changed schemas and server-provided read-only/safety hints
do not grant approval. Titles/descriptions come from the local policy, not untrusted
server prose. Temporary failures or schema drift revoke availability; cached model
calls still pass through the executor and are checked again.

The existing executor validates arguments and backend permissions before invocation,
including after a human confirmation wait. Default sessions grant only `tools:read`.
Maps/database/business scopes in the sample are **not automatically granted**.
Applications must authenticate and authorize the business user in trusted backend
composition. The existing frontend token endpoint remains development-only.

Sensitive operations use the same expiring, one-use, linked-human confirmation RPC
and UI as local tools. `confirmation_fields` explicitly selects reviewed input fields
to show alongside the local action summary. Include all material action details;
do not include secrets. Oversized summaries fail rather than silently truncating
material details. There is no LLM confirmation bypass. Side effects require:

- `sensitive=true`, `cancellation_safe=false` and a non-read application permission;
- a stable idempotency key in the executor's existing envelope;
- `idempotency_argument`, naming a real remote API field that supports idempotency.

The remote idempotency field is removed from model arguments and injected from the
executor context, then validated before transmission. Merely naming a field does
not make a server idempotent: verify its documented semantics. The current ledger
is per-session/in-memory; production writes require durable/external idempotency
and reconciliation, as described in [tool orchestration](tool-orchestration.md).

## Validation and disclosure

Reviewed schemas use JSON Schema validation with format checking. External/dynamic
schema references are rejected. Input/output objects and payload sizes are bounded;
unknown top-level input fields are rejected. Input schemas are checked again against
fresh discovery before every invocation. Schema drift requires a deliberate policy
review and worker restart, not automatic acceptance.

Only structured JSON results are accepted. Text-only, image, audio and resource-link
results are not blindly forwarded or fetched. Missing/invalid structured results
fail. The reviewed `output_schema` applies to the full object; `llm_fields` then
projects only explicitly approved top-level fields. The default is no disclosed
fields. Choose tight schemas and review nested fields and prose for private data and
prompt injection. This starter does not provide a general-purpose DLP guarantee.

MCP tool results are **not automatically sent to the browser**. Workbench packets
contain local action descriptions and status only, plus explicitly reviewed human
confirmation fields. No raw MCP progress, exception text, credentials, arguments,
resources or result blobs are auto-forwarded. Known credential literals are blocked
from LLM disclosures as a defense in depth, including bearer-token values; encoded
or transformed secrets still require a trustworthy server and a proper disclosure
policy. Anything intentionally disclosed to the LLM may be spoken/transcribed, so
never approve sensitive fields merely because the raw result stays server-side.

## Connection handling and security

Connections have separate initialization and operation deadlines. A short operation
deadline does not truncate subprocess startup. Calls to a given server are serialized;
servers are independent. Background health checks rediscover tools and reconnect
failed connections. A failed tool call is **not replayed** after reconnect. For a
potentially executed write, errors/invalid results yield `unknown`, not a claim of
rollback. Protocol cancellation does not guarantee remote side-effect cancellation.

The existing executor cancels safe work and approvals on interruption/shutdown;
protected work reaches its bounded deadline before MCP sessions are closed.
Subprocesses and HTTP sessions are closed on job shutdown.

Configuration uses environment-variable **names**, not literal credentials:

```json
{
  "headers_env": {"Authorization": "MAPS_MCP_AUTHORIZATION"},
  "url_env": "MAPS_MCP_URL"
}
```

Store the complete authorization header value (such as `Bearer <token>`) in the
backend process environment or an ignored `.env`. For stdio, `env` maps child
variable names to backend variable names, forwarding only selected application
values on top of the official SDK's minimal OS environment. `$python` resolves to
the worker's exact interpreter, avoiding Windows PATH/virtual-environment ambiguity.
Relative working directories resolve from `backend/`.

This starter configures header-based authentication; interactive OAuth login and
token-refresh flows are not implemented. Provision/refresh scoped tokens in trusted
backend infrastructure, never in the voice UI. Restart the worker after changing
configuration/environment credentials.

Private `backend/mcp.servers.json`, `mcp.*.local.json` and environment files are
Git-ignored. Protect their OS file permissions and use a deployment secret manager
for real credentials. Never use `NEXT_PUBLIC_*`, URL query/userinfo tokens, CLI
argument secrets, committed JSON secrets or raw secrets in pinned schemas. URLs
reject embedded credentials/query/fragment and plaintext remote HTTP. Standard
authentication/proxy routing must not be replaced with untrusted Host headers.

Stdio launches configured executable code with the worker's OS privileges: it is
**not a sandbox**. Only a trusted backend operator may configure commands, endpoints,
credentials or policies. Do not auto-install packages from a server/model prompt.
Use network egress rules, least-privilege accounts, scoped database credentials,
TLS and isolated processes/containers for untrusted integrations. SDK schema checks
are application limits, not complete network-memory or CPU isolation.

## External example configurations: not working integrations

`backend/mcp.external.example.json` shows three **disabled illustrative contracts**:

- maps: a scoped route lookup with origin/destination and a distance result;
- database: a confirmed authorized record-status lookup, **not generic SQL**;
- custom business: a confirmed service request with an injected operation ID.

No external server URL, vendor, tool name or schema in that file has been verified
as a working service. They do not connect until an operator supplies a real endpoint,
credentials, reviewed discovered schemas, permissions and an explicit allowlist.
Do not enable them unchanged or assume those illustrative remote tool names exist.
Never give an LLM a generic database/query/write tool: expose narrowly scoped,
deterministic business functions with server-side row/tenant authorization.

## Connect another hackathon server

1. Verify the server's maintained implementation, transport, authentication,
   deployment boundaries and actual tool contracts using its official docs.
2. Install the optional extra. Create a private backend JSON with one enabled server
   and explicit environment references. Review stdio executable/args before launch.
3. In a trusted backend terminal, use the inspection command to view configured
   remote tool input schemas. HTTP discovery is restricted to locally named policy
   tools by LiveKit's server filter. Use the official MCP Inspector separately if
   you need a broader operator-only inventory. Never feed discovery prose into
   privileged instructions or treat an inspector listing as an approval.
4. Pin the actual schema exactly (including titles/defaults/descriptions), define
   a tight output schema, minimal `llm_fields`, local labels, permissions and any
   confirmation/idempotency rules. Reject new tools by omission.
5. Add the namespaced name to `TOOL_ALLOWLIST`; grant its business scope only through
   trusted authorization. Restart the worker. No provider or frontend changes are needed.
6. Verify permission denial, invalid data, cancellation, external failure and
   credential handling locally before enabling sensitive operations.

## Verification

```powershell
cd backend
uv sync --locked --extra mcp --group dev
uv run --extra mcp pytest -q
uv run --extra mcp ruff check app tests
uv run --extra mcp ruff format --check app tests
```

The test suite launches actual local official-SDK servers over stdio and loopback
Streamable HTTP. It verifies discovery, native-agent adapter calls, schema filtering,
permissions, human approval, malformed output, literal-credential blocking, deadlines,
multiple servers, reconnect and cleanup. Test-only server tools and simulated business
calls are confined to test fixtures, never registered by the application demo.

Local MCP verification requires no LiveKit/STT/LLM/TTS API keys. Complete browser
voice sessions, hosted-model tool selection and any external maps/database/business
service still require real credentials and manual verification.

References checked against the installed SDK:
[LiveKit MCP integration](https://docs.livekit.io/agents/logic/tools/mcp/),
[official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), and
[MCP 2.x release/migration notes](https://github.com/modelcontextprotocol/python-sdk/releases).
