"""Native streaming TTS objects; no buffering or event conversion."""

from livekit.agents.tts import TTS

from app.config.settings import ProviderConfig


def cartesia(config: ProviderConfig) -> TTS:
    from livekit.plugins import cartesia as plugin

    return plugin.TTS(api_key=config.api_key, model=config.model, voice=config.voice)


def elevenlabs(config: ProviderConfig) -> TTS:
    from livekit.plugins import elevenlabs as plugin

    return plugin.TTS(api_key=config.api_key, model=config.model, voice_id=config.voice)


def murf(config: ProviderConfig) -> TTS:
    from livekit.plugins import murf as plugin

    return plugin.TTS(
        api_key=config.api_key, model=config.model, voice=config.voice, streaming=True
    )
