"""Supported LiveKit MCPToolset transports backed by the official MCP Python SDK."""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from livekit.agents import mcp as livekit_mcp
from mcp import stdio_client
from mcp.client.stdio import StdioServerParameters

from app.mcp.config import BACKEND_ROOT, Policy, ServerConfig, required_env
from app.mcp.permissions import matches_schema, validate_json
from app.tools.base import ToolFailure


class QuietStdioServer(livekit_mcp.MCPServerStdio):
    @asynccontextmanager
    async def client_streams(self):
        # Subprocess stderr may contain credentials; do not relay it to UI/logs.
        with open(os.devnull, "w") as errlog:
            async with stdio_client(
                StdioServerParameters(
                    command=self.command, args=self.args, env=self.env, cwd=self.cwd
                ),
                errlog=errlog,
            ) as streams:
                yield streams


class LiveKitMCPClient:
    def __init__(self, config: ServerConfig):
        self.config = config
        self.toolset = None
        self.approved = {}
        self.discovered_schemas = {}
        self._protected_values: set[str] = set()

    def make_toolset(self):
        for variable in [*self.config.env.values(), *self.config.headers_env.values()]:
            value = required_env(variable)
            self._protected_values.add(value)
            if value.lower().startswith("bearer "):
                self._protected_values.add(value[7:])
        kwargs = {
            "client_session_timeout_seconds": max(
                self.config.connect_timeout_seconds, self.config.request_timeout_seconds
            ),
            "tool_result_resolver": self.resolve_result,
        }
        if self.config.transport == "stdio":
            cwd = Path(self.config.cwd) if self.config.cwd else BACKEND_ROOT
            if not cwd.is_absolute():
                cwd = BACKEND_ROOT / cwd
            server = QuietStdioServer(
                command=sys.executable
                if self.config.command == "$python"
                else self.config.command,
                args=self.config.args,
                cwd=cwd,
                env={
                    name: required_env(variable)
                    for name, variable in self.config.env.items()
                },
                **kwargs,
            )
        else:
            server = livekit_mcp.MCPServerHTTP(
                self.config.endpoint(),
                transport_type="streamable_http",
                allowed_tools=[
                    p.remote_name for p in self.config.approved_tools.values()
                ],
                headers={
                    name: required_env(variable)
                    for name, variable in self.config.headers_env.items()
                },
                timeout=self.config.connect_timeout_seconds,
                **kwargs,
            )
        return livekit_mcp.MCPToolset(id=f"mcp_{self.config.id}", mcp_server=server)

    async def discover(self) -> set[str]:
        if self.toolset is None:
            self.toolset = self.make_toolset()
        await self.toolset.setup(reload=True)
        discovered = {tool.id: tool for tool in self.toolset.tools}
        self.discovered_schemas = {
            name: tool.info.raw_schema["parameters"]
            for name, tool in discovered.items()
        }
        self.approved = {}
        for alias, policy in self.config.approved_tools.items():
            tool = discovered.get(policy.remote_name)
            if tool and matches_schema(
                tool.info.raw_schema["parameters"], policy.input_schema
            ):
                self.approved[alias] = tool
        self.toolset.filter_tools(
            lambda tool: any(tool is approved for approved in self.approved.values())
        )
        return set(self.approved)

    def policy_for_remote(self, name: str) -> Policy:
        for policy in self.config.approved_tools.values():
            if policy.remote_name == name:
                return policy
        raise ToolFailure("mcp_not_approved", "This external action is not approved.")

    def resolve_result(self, context):
        policy = self.policy_for_remote(context.tool_name)
        result = context.result
        value = result.structured_content
        # Structured JSON only; never fetch resources or forward media/text.
        if not isinstance(value, dict):
            raise ToolFailure(
                "mcp_output_invalid",
                "External tool did not return approved structured JSON.",
            )
        validate_json(value, policy.output_schema)
        disclosed = {
            field: value[field] for field in policy.llm_fields if field in value
        }
        serialized = json.dumps(disclosed, ensure_ascii=False)
        if any(secret in serialized for secret in self._protected_values if secret):
            raise ToolFailure(
                "mcp_disclosure_blocked",
                "External tool returned protected credential data.",
            )
        return disclosed

    async def call(self, alias: str, arguments: dict):
        tool = self.approved.get(alias)
        if tool is None:
            raise ToolFailure(
                "mcp_not_approved",
                "External action is unavailable or its schema changed.",
            )
        return await tool(raw_arguments=arguments)

    async def aclose(self):
        toolset, self.toolset = self.toolset, None
        self.approved = {}
        if toolset:
            await toolset.aclose()


async def inspect_server(config_path: str, server_id: str):
    from app.mcp.config import load_config

    config = next(
        server
        for server in load_config(config_path).servers
        if server.id == server_id and server.enabled
    )
    client = LiveKitMCPClient(config)
    try:
        async with asyncio.timeout(config.connect_timeout_seconds):
            approved = await client.discover()
        # Operator-only discovery metadata. No endpoints, headers or tool calls/results.
        print(
            json.dumps(
                {
                    "server": server_id,
                    "input_schemas": client.discovered_schemas,
                    "approved": sorted(approved),
                },
                indent=2,
            )
        )
    finally:
        await client.aclose()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Inspect MCP schemas in a trusted backend terminal"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--server", required=True)
    arguments = parser.parse_args()
    try:
        asyncio.run(inspect_server(arguments.config, arguments.server))
    except Exception:
        raise SystemExit(
            "MCP inspection failed. Check server setup and optional dependencies."
        ) from None
