"""Application composition root: add reviewed use-case tools here, not in the engine."""

from app.agents.orchestrator import Orchestrator
from app.config.settings import Settings
from app.tools.common.calculator import CALCULATOR_TOOL
from app.tools.common.time import TIME_TOOL
from app.usecases.base import apply_tool_policies
from app.usecases.registry import registry as usecases
from app.workflows.time_calculation import WORKFLOW_TOOL


def build_orchestrator(settings: Settings) -> Orchestrator:
    profile = usecases.get(getattr(settings, "use_case", "general_assistant"))
    if isinstance(settings, Settings):
        profile.validate_selection(
            {"stt": settings.stt, "llm": settings.llm, "tts": settings.tts},
            settings.tool_allowlist,
            settings.infrastructure,
        )
    definitions = (TIME_TOOL, CALCULATOR_TOOL, WORKFLOW_TOOL, *profile.tool_factory())
    external = (
        _approved_mcp(settings, profile)
        if getattr(settings, "mcp_enabled", False)
        else None
    )
    if external:
        definitions = (*definitions, *external.definitions.values())

    # The single initial policy boundary. Each definition is prepared exactly
    # once; keep external policy errors sanitized as before.
    prepared = []
    for definition in definitions:
        try:
            prepared.extend(apply_tool_policies(profile, (definition,)))
        except ValueError:
            if external and definition is external.definitions.get(definition.name):
                _invalid_mcp()
            raise
    if external:
        external.definitions = {
            tool.name: tool for tool in prepared if tool.name in external.definitions
        }
    orchestrator = Orchestrator(
        use_case=profile,
        tool_definitions=tuple(prepared),
        allowlist=frozenset(settings.tool_allowlist),
        language=getattr(getattr(settings, "stt", None), "language", None),
        deferred_tools=frozenset(external.definitions) if external else frozenset(),
    )
    if external:
        external.orchestrator = orchestrator
        orchestrator.external_tools = external
    return orchestrator


def _invalid_mcp():
    from app.config.settings import ConfigurationError

    raise ConfigurationError(
        "Invalid MCP policy/configuration; review the backend schemas and MCP guide"
    ) from None


def _approved_mcp(settings, profile):
    """Prepare reviewed definitions without launching or connecting any servers."""
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
        return MCPRegistry(config, frozenset(settings.tool_allowlist))
    except Exception:
        _invalid_mcp()
