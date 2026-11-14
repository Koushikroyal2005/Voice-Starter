"""Read environment settings without exposing secret values in errors or repr."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from app.agents.instructions import DEFAULT_INSTRUCTIONS

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class ConfigurationError(ValueError):
    """Invalid or missing environment configuration."""


@dataclass(frozen=True)
class Settings:
    livekit_url: str
    livekit_api_key: str = field(repr=False)
    livekit_api_secret: str = field(repr=False)
    deepgram_api_key: str = field(repr=False)
    openai_api_key: str = field(repr=False)
    cartesia_api_key: str = field(repr=False)
    agent_name: str = ""
    stt_model: str = "nova-3"
    stt_language: str = "en"
    llm_model: str = "gpt-4.1-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    tts_model: str = "sonic-3"
    tts_voice: str = "f786b574-daa5-4673-aa0c-cbe3e8534c02"
    instructions: str = DEFAULT_INSTRUCTIONS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        values = os.environ if env is None else env
        required = (
            "LIVEKIT_URL",
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
            "DEEPGRAM_API_KEY",
            "OPENAI_API_KEY",
            "CARTESIA_API_KEY",
        )
        missing = [key for key in required if not values.get(key, "").strip()]
        if missing:
            raise ConfigurationError(
                "Missing required environment variables: " + ", ".join(missing)
            )

        def optional(key: str, default: str) -> str:
            return values.get(key, "").strip() or default

        url = values["LIVEKIT_URL"].strip()
        base_url = optional("LLM_BASE_URL", "https://api.openai.com/v1")
        for name, value, schemes in (
            ("LIVEKIT_URL", url, {"ws", "wss"}),
            ("LLM_BASE_URL", base_url, {"http", "https"}),
        ):
            parsed = urlsplit(value)
            if (
                parsed.scheme not in schemes
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ConfigurationError(
                    f"{name} must be a valid URL without embedded credentials"
                )
        return cls(
            livekit_url=url,
            livekit_api_key=values["LIVEKIT_API_KEY"].strip(),
            livekit_api_secret=values["LIVEKIT_API_SECRET"].strip(),
            deepgram_api_key=values["DEEPGRAM_API_KEY"].strip(),
            openai_api_key=values["OPENAI_API_KEY"].strip(),
            cartesia_api_key=values["CARTESIA_API_KEY"].strip(),
            agent_name=values.get("AGENT_NAME", "").strip(),
            stt_model=optional("STT_MODEL", "nova-3"),
            stt_language=optional("STT_LANGUAGE", "en"),
            llm_model=optional("LLM_MODEL", "gpt-4.1-mini"),
            llm_base_url=base_url,
            tts_model=optional("TTS_MODEL", "sonic-3"),
            tts_voice=optional("TTS_VOICE", cls.tts_voice),
            instructions=optional("AGENT_INSTRUCTIONS", DEFAULT_INSTRUCTIONS),
        )


def load_settings() -> Settings:
    """Load backend/.env; existing process environment always takes precedence."""
    load_dotenv(ENV_FILE, override=False)
    return Settings.from_env()
