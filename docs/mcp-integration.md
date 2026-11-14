# MCP integration guide

MCP is an optional **external tool** integration, not a speech/LLM provider. The
[detailed MCP guide](mcp.md) covers official SDK versions, stdio/Streamable HTTP,
schemas, permissions, discovery, reconnects and example policies.

Quick Windows demo (no external maps/database/business server is assumed):

```powershell
cd 'E:\voice agent starter\voice-agent-starter\backend'
uv sync --locked --extra mcp --extra telemetry
if (!(Test-Path -LiteralPath mcp.servers.json)) { Copy-Item mcp.demo.example.json mcp.servers.json }
$env:MCP_ENABLED = 'true'
$env:TOOL_ALLOWLIST = 'get_current_time,calculate_expression,time_and_calculate,mcp_clock_get_current_time'
$env:USE_CASE = 'general_assistant'
uv run --extra mcp python -m app.mcp.client --config mcp.servers.json --server clock
# With real voice credentials:
uv run --extra mcp --extra telemetry python -m app.main dev
```

The inspection command connects to the real local official-SDK server and
discovers the approved UTC tool; it does not execute it. The voice worker can
invoke it after the session starts. For another
server, inspect its input schema in a trusted terminal, pin it in the reviewed
policy, approve exact aliases, disclose only selected output fields, and add its
namespaced tool to executor/use-case allowlists. Unknown/drifted schemas stay
disabled. Writes need permission, confirmation and remote idempotency. No raw
native MCP toolset bypasses the deterministic executor.

`mcp.external.example.json` contains **placeholders**, not working maps/database/
business integrations. Credentials use environment references. Never give an LLM
broad SQL access or trust server annotations as permission. Runtime policy belongs
in ignored `mcp.servers.json`; mount it read-only in Docker (excluded from images).

Stdio commands are trusted local programs with worker-user OS access, not sandboxed
plugins. Remote data remains untrusted after schema validation. Reconnect never
automatically replays a failed operation. Handle changed schemas and unknown write
outcomes explicitly; these controls are not a universal external-tool safety proof.

```powershell
uv run --extra mcp pytest tests/test_mcp.py -q
```

Those tests prove only exercised harmless local transports and policies, not your
external deployment, authorization, account access or data residency.
