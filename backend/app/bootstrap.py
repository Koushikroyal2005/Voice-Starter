"""Application composition root: add reviewed use-case tools here, not in the engine."""

from app.agents.orchestrator import Orchestrator
from app.config.settings import Settings
from app.usecases.base import apply_tool_policies
from app.usecases.registry import registry as usecases


def build_orchestrator(settings: Settings) -> Orchestrator:
    profile = usecases.get(getattr(settings, "use_case", "general_assistant"))
    if isinstance(settings, Settings):
        profile.validate_selection(
            {"stt": settings.stt, "llm": settings.llm, "tts": settings.tts},
            settings.tool_allowlist,
            settings.infrastructure,
        )
    definitions = apply_tool_policies(profile, profile.tool_factory())
    if not getattr(settings, "mcp_enabled", False):
        return Orchestrator(settings, additional_tools=definitions)
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
        config = load_config(settings.mcp_config_file)
        if profile.mcp_servers is not None:
            config = config.model_copy(
                update={
                    "servers": [
                        server
                        for server in config.servers
                        if server.id in profile.mcp_servers
                    ]
                }
            )
        registry = MCPRegistry(config, frozenset(settings.tool_allowlist))
        registry.definitions = {
            tool.name: tool
            for tool in apply_tool_policies(
                profile, tuple(registry.definitions.values())
            )
        }
    except Exception:
        from app.config.settings import ConfigurationError

        raise ConfigurationError(
            "Invalid MCP policy/configuration; review the backend schemas and MCP guide"
        ) from None
    orchestrator = Orchestrator(
        settings,
        additional_tools=(*definitions, *registry.definitions.values()),
        deferred_tools=frozenset(registry.definitions),
    )
    registry.orchestrator = orchestrator
    orchestrator.external_tools = registry
    return orchestrator
