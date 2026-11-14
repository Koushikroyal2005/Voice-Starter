"""Application composition root: add reviewed use-case tools here, not in the engine."""

from app.agents.orchestrator import Orchestrator
from app.config.settings import Settings


def build_orchestrator(settings: Settings) -> Orchestrator:
    if not settings.mcp_enabled:
        return Orchestrator(settings, additional_tools=())
    # Lazy imports: MCP-disabled conversations need neither package nor config file.
    from app.mcp.config import load_config

    try:
        from app.mcp.registry import MCPRegistry
    except ImportError:
        from app.config.settings import ConfigurationError

        raise ConfigurationError(
            "MCP requires: uv sync --extra mcp --group dev"
        ) from None
    try:
        registry = MCPRegistry(
            load_config(settings.mcp_config_file), frozenset(settings.tool_allowlist)
        )
    except Exception:
        from app.config.settings import ConfigurationError

        raise ConfigurationError(
            "Invalid MCP policy/configuration; review the backend schemas and MCP guide"
        ) from None
    orchestrator = Orchestrator(
        settings,
        additional_tools=tuple(registry.definitions.values()),
        deferred_tools=frozenset(registry.definitions),
    )
    registry.orchestrator = orchestrator
    orchestrator.external_tools = registry
    return orchestrator
