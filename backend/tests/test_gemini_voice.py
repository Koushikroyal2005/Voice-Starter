"""Pinned Google plugin contract; no credentials or network calls."""

import asyncio
from unittest.mock import patch

import pytest

from app.config.settings import ConfigurationError, Settings
from app.providers.factory import create_stt, create_tts
from app.providers.registry import ProviderError, registry
from tests.test_providers import environment


def configuration(**overrides):
    return Settings.from_env(
        environment()
        | {
            "STT_PROVIDER": "gemini",
            "TTS_PROVIDER": "gemini",
            "GOOGLE_API_KEY": "synthetic-google",
            "LLM_BASE_URL": "https://api.groq.com/openai/v1",
            "LLM_MODEL": "openai/gpt-oss-20b",
            "STT_REQUIRE_INTERIM": "true",
        }
        | overrides
    )


def test_constructor_arguments():
    from app.providers.stt import gemini as speech
    from app.providers.tts import gemini as synthesis

    settings = configuration()
    with patch("livekit.plugins.google.beta.GeminiSTT") as constructor:
        speech(settings.stt)
        constructor.assert_called_once_with(
            api_key="synthetic-google",
            model="gemini-3.5-transcribe-live",
            language="en",
            vertexai=False,
        )
    with patch("livekit.plugins.google.beta.GeminiTTS") as constructor:
        synthesis(settings.tts)
        constructor.assert_called_once_with(
            api_key="synthetic-google",
            model="gemini-3.1-flash-tts-preview",
            voice_name="Kore",
            vertexai=False,
        )


def test_native_capabilities():
    settings = configuration()
    speech = create_stt(settings.stt)
    assert speech.capabilities.streaming
    assert speech.capabilities.interim_results
    assert not speech.capabilities.offline_recognize
    assert registry.get("tts", "gemini").capabilities.streaming is False


@pytest.mark.parametrize(
    "values",
    [
        {"GOOGLE_API_KEY": ""},
        {"STT_MODEL": "gemini-2.5-flash"},
        {"TURN_DETECTION": "stt"},
    ],
)
def test_invalid_configuration(values):
    with pytest.raises(ConfigurationError):
        configuration(**values)


def test_invalid_voice():
    with pytest.raises(ProviderError, match="TTS_VOICE"):
        create_tts(configuration(TTS_VOICE="unknown").tts)


def test_voice_pipeline_uses_native_providers():
    from livekit.plugins.google.beta import GeminiSTT, GeminiTTS

    from app.providers.pipeline import create_session

    async def check():
        session = create_session(configuration())
        try:
            assert isinstance(session.stt, GeminiSTT)
            assert isinstance(session.tts, GeminiTTS)
            assert session.llm.model == "openai/gpt-oss-20b"
            assert session.stt.capabilities.interim_results
        finally:
            await session.aclose()
            await session.stt.aclose()
            await session.tts.aclose()
            await session.llm.aclose()

    asyncio.run(check())
