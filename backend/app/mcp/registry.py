"""Reviewed MCP policy -> ordinary ToolDefinitions behind the existing executor."""

from app.mcp.config import MCPConfig, Policy, ServerConfig
from app.mcp.connection_manager import ConnectionManager
from app.mcp.permissions import argument_model, check_schema, validate_json
from app.tools.base import ExecutionContext, Schema, ToolDefinition


class MCPOutput(Schema):
    data: dict


def tool_name(server_id: str, alias: str) -> str:
    return f"mcp_{server_id}_{alias}"


class MCPRegistry:
    def __init__(self, config: MCPConfig, allowlist: frozenset[str]):
        # Unselected servers are not launched, contacted or given any secrets.
        self.servers = []
        for server in config.servers:
            selected = {
                alias: policy
                for alias, policy in server.approved_tools.items()
                if tool_name(server.id, alias) in allowlist
            }
            if server.enabled and selected:
                self.servers.append(
                    server.model_copy(update={"approved_tools": selected})
                )
        self.manager = ConnectionManager(self.servers)
        self.definitions: dict[str, ToolDefinition] = {}
        self.scopes: dict[str, set[str]] = {}
        for server in self.servers:
            for alias, policy in server.approved_tools.items():
                name = tool_name(server.id, alias)
                if name in allowlist:
                    if name in self.definitions:
                        raise ValueError("MCP tool namespace collision")
                    check_schema(policy.input_schema)
                    check_schema(policy.output_schema)
                    self.definitions[name] = self.definition(server, alias, policy)
                    self.scopes.setdefault(server.id, set()).add(name)
        self.orchestrator = None

    def definition(
        self, server: ServerConfig, alias: str, policy: Policy
    ) -> ToolDefinition:
        def confirmation(args):
            import json

            from app.tools.base import ToolFailure

            values = args.model_dump(mode="json")
            summary = policy.confirmation_summary
            if policy.confirmation_fields:
                summary += " " + json.dumps(
                    {field: values.get(field) for field in policy.confirmation_fields},
                    ensure_ascii=False,
                )
            if len(summary) > 500:
                raise ToolFailure(
                    "mcp_confirmation_too_large",
                    "The action details cannot be safely displayed for confirmation.",
                )
            return summary

        async def handler(args: Schema, context: ExecutionContext):
            arguments = args.model_dump(mode="json")
            if policy.idempotency_argument:
                arguments[policy.idempotency_argument] = context.idempotency_key
            validate_json(arguments, policy.input_schema)
            return MCPOutput(data=await self.manager.call(server.id, alias, arguments))

        return ToolDefinition(
            name=tool_name(server.id, alias),
            title=policy.title,
            description=policy.description,
            input_schema=argument_model(policy),
            output_schema=MCPOutput,
            handler=handler,
            permission=policy.permission,
            timeout_seconds=policy.timeout_seconds,
            sensitive=policy.sensitive,
            side_effects=policy.side_effects,
            cancellation_safe=policy.cancellation_safe,
            confirmation_summary=confirmation if policy.sensitive else None,
            public_result=None,
        )

    def start(self, agent):
        async def availability(server_id, aliases):
            scope = self.scopes[server_id]
            available = {tool_name(server_id, alias) for alias in aliases} & scope
            await self.orchestrator.set_tool_availability(agent, scope, available)

        self.manager.start(availability)

    async def aclose(self):
        await self.manager.aclose()
