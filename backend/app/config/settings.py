"""Environment-only configuration; credentials never enter frontend code."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from app.agents.instructions import DEFAULT_INSTRUCTIONS
from app.providers.registry import Category, ProviderError, registry

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class ConfigurationError(ValueError):
    """Invalid or missing environment configuration."""


@dataclass(frozen=True)
class ProviderConfig:
    category: Category
    provider: str
    model: str
    api_key: str = field(repr=False)
    base_url: str = ""
    language: str = "en"
    voice: str = ""


def validate_url(name: str, value: str, schemes: set[str]) -> None:
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in schemes
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ConfigurationError(
            f"{name} must be a valid URL without credentials/query"
        )


def boolean(values: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = values.get(name, "").strip().lower()
    if not raw:
        return default
    if raw not in ("true", "false"):
        raise ConfigurationError(f"{name} must be true or false")
    return raw == "true"


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
    allow_batch_stt: bool = False
    require_interim: bool = False
    turn_detection: str = "vad"
    mcp_enabled: bool = False
    mcp_config_file: str = "mcp.servers.json"
    tool_allowlist: tuple[str, ...] = (
        "get_current_time",
        "calculate_expression",
        "time_and_calculate",
    )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        values = os.environ if env is None else env

        def optional(key: str, default: str = "") -> str:
            return values.get(key, "").strip() or default

        missing = [
            k
            for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
            if not optional(k)
        ]
        configs = {}
        for category, default in (
            ("stt", "deepgram"),
            ("llm", "openai_compatible"),
            ("tts", "cartesia"),
        ):
            prefix = category.upper()
            name = optional(f"{prefix}_PROVIDER", default).lower()
            try:
                spec = registry.get(category, name)
            except ProviderError as error:
                raise ConfigurationError(str(error)) from None
            key = optional(spec.api_key_env)
            if name == "openai_compatible":
                key = key or optional("OPENAI_API_KEY")
            if not key:
                missing.append(
                    "LLM_API_KEY (or OPENAI_API_KEY)"
                    if name == "openai_compatible"
                    else spec.api_key_env
                )
            model = optional(f"{prefix}_MODEL", spec.model)
            if spec.models and model not in spec.models:
                raise ConfigurationError(
                    f"{prefix}_MODEL is unsupported for {name}; "
                    f"supported: {', '.join(spec.models)}"
                )
            base_url = optional(f"{prefix}_BASE_URL", spec.base_url)
            if category == "llm" and name == "gemini" and base_url:
                raise ConfigurationError("LLM_BASE_URL is not supported for gemini")
            if category == "stt" and name != "whisper" and base_url:
                raise ConfigurationError(f"STT_BASE_URL is not supported for {name}")
            if category == "tts" and base_url:
                raise ConfigurationError(
                    "TTS_BASE_URL is not configured by these adapters"
                )
            if base_url:
                validate_url(f"{prefix}_BASE_URL", base_url, {"http", "https"})
            if category == "llm" and name == "openai_compatible":
                if base_url.rstrip("/") != spec.base_url and not optional("LLM_MODEL"):
                    raise ConfigurationError(
                        "LLM_MODEL is required for a custom LLM_BASE_URL"
                    )
            configs[category] = ProviderConfig(
                category=category,
                provider=name,
                model=model,
                api_key=key,
                base_url=base_url,
                language=optional(f"{prefix}_LANGUAGE", "en"),
                voice=optional(f"{prefix}_VOICE", spec.voice),
            )
        if missing:
            raise ConfigurationError(
                "Missing required environment variables: " + ", ".join(missing)
            )
        validate_url("LIVEKIT_URL", optional("LIVEKIT_URL"), {"ws", "wss"})
        allow_batch = boolean(values, "STT_ALLOW_BATCH")
        require_interim = boolean(values, "STT_REQUIRE_INTERIM")
        turn_detection = optional("TURN_DETECTION", "vad")
        if turn_detection not in ("vad", "stt"):
            raise ConfigurationError("TURN_DETECTION must be vad or stt")
        caps = registry.get("stt", configs["stt"].provider).capabilities
        if not caps.streaming and not allow_batch:
            raise ConfigurationError(
                "Batch STT requires STT_ALLOW_BATCH=true; no live interim results"
            )
        if require_interim and caps.interim_transcription is not True:
            raise ConfigurationError(
                "Selected STT does not support interim transcription"
            )
        if turn_detection == "stt" and caps.turn_detection is not True:
            raise ConfigurationError(
                "Selected STT does not support provider turn detection; use vad"
            )
        return cls(
            livekit_url=optional("LIVEKIT_URL"),
            livekit_api_key=optional("LIVEKIT_API_KEY"),
            livekit_api_secret=optional("LIVEKIT_API_SECRET"),
            stt=configs["stt"],
            llm=configs["llm"],
            tts=configs["tts"],
            agent_name=optional("AGENT_NAME"),
            instructions=optional("AGENT_INSTRUCTIONS", DEFAULT_INSTRUCTIONS),
            allow_batch_stt=allow_batch,
            require_interim=require_interim,
            turn_detection=turn_detection,
            mcp_enabled=boolean(values, "MCP_ENABLED"),
            mcp_config_file=optional("MCP_CONFIG_FILE", "mcp.servers.json"),
            tool_allowlist=tuple(
                name.strip()
                for name in values.get(
                    "TOOL_ALLOWLIST",
                    "get_current_time,calculate_expression,time_and_calculate",
                ).split(",")
                if name.strip()
            ),
        )


def load_settings() -> Settings:
    """Process environment overrides backend/.env."""
    load_dotenv(ENV_FILE, override=False)
    return Settings.from_env()
