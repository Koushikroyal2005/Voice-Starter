"""Select plugins without wrapping away LiveKit's streaming interfaces."""

from importlib import import_module
from typing import cast

from livekit.agents import llm, stt, tts

from app.config.settings import ProviderConfig
from app.providers.registry import ProviderError, registry


def create_provider(config: ProviderConfig) -> stt.STT | llm.LLM | tts.TTS:
    spec = registry.get(config.category, config.provider)
    if not config.api_key.strip():
        raise ProviderError(
            f"{config.category}/{config.provider} requires {spec.api_key_env}"
        )
    if not config.model.strip():
        raise ProviderError(f"{config.category}/{config.provider} requires a model")
    if spec.models and config.model not in spec.models:
        raise ProviderError(f"Unsupported model for {config.provider}: {config.model}")
    module, function = spec.builder.split(":")
    try:
        provider = getattr(import_module(module), function)(config)
    except ImportError as error:
        raise ProviderError(
            f"Plugin for {config.provider} is unavailable; run uv sync --locked"
        ) from error
    expected = {"stt": stt.STT, "llm": llm.LLM, "tts": tts.TTS}[config.category]
    if not isinstance(provider, expected):
        raise ProviderError(
            f"{config.provider} did not return a LiveKit {config.category} interface"
        )
    return provider


def create_stt(config: ProviderConfig) -> stt.STT:
    if config.category != "stt":
        raise ProviderError("Expected STT configuration")
    return cast(stt.STT, create_provider(config))


def create_llm(config: ProviderConfig) -> llm.LLM:
    if config.category != "llm":
        raise ProviderError("Expected LLM configuration")
    return cast(llm.LLM, create_provider(config))


def create_tts(config: ProviderConfig) -> tts.TTS:
    if config.category != "tts":
        raise ProviderError("Expected TTS configuration")
    return cast(tts.TTS, create_provider(config))
