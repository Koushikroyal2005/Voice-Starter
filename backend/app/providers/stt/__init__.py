"""Thin constructors returning native LiveKit STT interfaces and events."""

from livekit.agents.stt import STT

from app.config.settings import ProviderConfig


def deepgram(config: ProviderConfig) -> STT:
    from livekit.plugins import deepgram as plugin

    return plugin.STT(
        api_key=config.api_key,
        model=config.model,
        language=config.language,
        interim_results=True,
    )


def assemblyai(config: ProviderConfig) -> STT:
    from livekit.plugins import assemblyai as plugin

    options = {}
    if config.model in ("universal-3-6-pro", "universal-3-5-pro"):
        options = {"max_turn_silence": 1000, "language_codes": config.language}
    return plugin.STT(
        api_key=config.api_key,
        model=config.model,
        vad_threshold=0.3,
        **options,
    )


def whisper(config: ProviderConfig) -> STT:
    from livekit.plugins import openai

    return openai.STT(
        api_key=config.api_key,
        model=config.model,
        language=config.language,
        base_url=config.base_url,
        use_realtime=False,
    )


def gemini(config: ProviderConfig) -> STT:
    from livekit.plugins.google.beta import GeminiSTT

    return GeminiSTT(
        api_key=config.api_key,
        model=config.model,
        language=config.language,
        vertexai=False,
    )


def groq(config: ProviderConfig) -> STT:
    from livekit.plugins import openai

    return openai.STT(
        api_key=config.api_key,
        model=config.model,
        language=config.language,
        base_url="https://api.groq.com/openai/v1",
        use_realtime=False,
    )
