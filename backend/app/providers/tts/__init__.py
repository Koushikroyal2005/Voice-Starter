"""Native TTS objects; LiveKit owns sentence adaptation and audio events."""

from typing import get_args

from livekit.agents.tts import TTS

from app.config.settings import ProviderConfig
from app.providers.registry import ProviderError


def groq_tts(config: ProviderConfig) -> TTS:
    from app.providers.tts.groq import GroqTTS

    if config.voice not in ("autumn", "diana", "hannah", "austin", "daniel", "troy"):
        raise ProviderError("Groq TTS_VOICE requires an English Orpheus voice")
    if config.language not in ("en", "en-US", "en-GB"):
        raise ProviderError("Groq Orpheus English requires TTS_LANGUAGE=en")
    return GroqTTS(api_key=config.api_key, model=config.model, voice=config.voice)


def gemini(config: ProviderConfig) -> TTS:
    """Use native audio synthesis; google-genai 3.x needs the v1beta env setting.

    Set GOOGLE_GENAI_API_VERSION=v1beta before construction. The installed plugin
    has no http_options argument, and SDK 3.3.0 otherwise selects stable v1,
    which rejects its speechConfig. Do not patch the plugin's private client.
    """
    from livekit.plugins.google.beta import GeminiTTS
    from livekit.plugins.google.beta.gemini_tts import GEMINI_VOICES

    if config.voice not in get_args(GEMINI_VOICES):
        raise ProviderError(
            "Gemini TTS_VOICE must be a supported prebuilt voice, e.g. Kore"
        )
    return GeminiTTS(
        api_key=config.api_key,
        model=config.model,
        voice_name=config.voice,
        vertexai=False,
    )


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
