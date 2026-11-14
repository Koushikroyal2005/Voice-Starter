"""Application configuration assembly; credentials never enter frontend code."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from app.agents.instructions import DEFAULT_INSTRUCTIONS
from app.config.infrastructure import InfrastructureSettings
from app.config.providers import (
    ProviderConfig,
    resolve_fallbacks,
    resolve_provider,
    resolve_stt_requirements,
)
from app.config.validation import (
    ConfigurationError,
    boolean,
    require_credentials,
    validate_url,
)
from app.observability.config import ObservabilitySettings
from app.providers.registry import Category

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


@dataclass(frozen=True)
class Settings:
    livekit_url: str
    livekit_api_key: str = field(repr=False)
    livekit_api_secret: str = field(repr=False)
    stt: ProviderConfig
    llm: ProviderConfig
    tts: ProviderConfig
    agent_name: str = ""
    instructions: str = DEFAULT_INSTRUCTIONS
    use_case: str = "general_assistant"
    allow_batch_stt: bool = False
    require_interim: bool = False
    turn_detection: str = "vad"
    observability: ObservabilitySettings = field(default_factory=ObservabilitySettings)
    fallbacks: tuple[ProviderConfig, ...] = ()
    infrastructure: InfrastructureSettings = field(
        default_factory=InfrastructureSettings
    )
    mcp_enabled: bool = False
    mcp_config_file: str = "mcp.servers.json"
    tool_allowlist: tuple[str, ...] = (
        "get_current_time",
        "calculate_expression",
        "time_and_calculate",
    )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        from app.usecases.registry import registry as usecases

        supplied = os.environ if env is None else env
        try:
            use_case = usecases.get(supplied.get("USE_CASE", "").strip())
        except ValueError as error:
            raise ConfigurationError(str(error)) from None
        values = {**use_case.provider_defaults, **supplied}

        def optional(key: str, default: str = "") -> str:
            return values.get(key, "").strip() or default

        missing = [
            key
            for key in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
            if not optional(key)
        ]
        configs = {
            category: resolve_provider(category, values, missing=missing)
            for category in ("stt", "llm", "tts")
        }
        require_credentials(missing)
        validate_url("LIVEKIT_URL", optional("LIVEKIT_URL"), {"ws", "wss"})
        stt_requirements = resolve_stt_requirements(values, configs["stt"])
        try:
            infrastructure = InfrastructureSettings.from_env(values)
            observability = ObservabilitySettings.from_env(values)
        except ValueError as error:
            raise ConfigurationError(str(error)) from None
        tools = tuple(
            name.strip()
            for name in values.get(
                "TOOL_ALLOWLIST", ",".join(use_case.default_tools)
            ).split(",")
            if name.strip()
        )
        fallbacks = cls.parse_fallbacks(values, configs)
        try:
            use_case.validate_selection(configs, tools, infrastructure)
            for fallback in fallbacks:
                use_case.validate_selection(
                    {fallback.category: fallback}, tools, infrastructure
                )
        except ValueError as error:
            raise ConfigurationError(str(error)) from None
        return cls(
            use_case=use_case.id,
            observability=observability,
            fallbacks=fallbacks,
            infrastructure=infrastructure,
            livekit_url=optional("LIVEKIT_URL"),
            livekit_api_key=optional("LIVEKIT_API_KEY"),
            livekit_api_secret=optional("LIVEKIT_API_SECRET"),
            stt=configs["stt"],
            llm=configs["llm"],
            tts=configs["tts"],
            agent_name=optional("AGENT_NAME"),
            instructions=optional("AGENT_INSTRUCTIONS", use_case.instructions),
            allow_batch_stt=stt_requirements.allow_batch,
            require_interim=stt_requirements.require_interim,
            turn_detection=stt_requirements.turn_detection,
            mcp_enabled=boolean(values, "MCP_ENABLED"),
            mcp_config_file=optional(
                "MCP_CONFIG_FILE", use_case.mcp_config_file or "mcp.servers.json"
            ),
            tool_allowlist=tools,
        )

    @classmethod
    def parse_fallbacks(
        cls,
        values: Mapping[str, str],
        configs: Mapping[Category, ProviderConfig],
    ) -> tuple[ProviderConfig, ...]:
        """Compatibility entry point; provider resolution never reassembles Settings."""
        return resolve_fallbacks(values, configs)


def load_settings() -> Settings:
    """Process environment overrides backend/.env."""
    load_dotenv(ENV_FILE, override=False)
    return Settings.from_env()
