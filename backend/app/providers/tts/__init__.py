"""Native streaming TTS objects; no buffering or event conversion."""

from typing import get_args

from livekit.agents.tts import TTS

from app.config.settings import ProviderConfig
from app.providers.registry import ProviderError


def cartesia(config: ProviderConfig) -> TTS:
    from livekit.plugins import cartesia as plugin

    return plugin.TTS(
        api_key=config.api_key,
        model=config.model,
        voice=config.voice,
        language=config.language,
    )


def elevenlabs(config: ProviderConfig) -> TTS:
    from livekit.plugins import elevenlabs as plugin

    return plugin.TTS(
        api_key=config.api_key,
        model=config.model,
        voice_id=config.voice,
        language=config.language,
    )


def murf(config: ProviderConfig) -> TTS:
    from livekit.plugins import murf as plugin
    from livekit.plugins.murf.models import TTSLocales

    locale = "en-US" if config.language == "en" else config.language
    if locale not in get_args(TTSLocales):
        raise ProviderError(
            "Murf TTS_LANGUAGE requires a supported full locale, e.g. es-ES"
        )

    return plugin.TTS(
        api_key=config.api_key,
        model=config.model,
        voice=config.voice,
        streaming=True,
        locale=locale,
    )
