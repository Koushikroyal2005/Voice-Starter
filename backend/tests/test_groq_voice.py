"""Groq speech contracts and native decoding using test-only WAV bytes."""

import asyncio
import io
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import openai
import pytest
from livekit import rtc
from livekit.agents import APIConnectOptions, APIStatusError, APITimeoutError
from livekit.agents.stt import StreamAdapter

from app.config.settings import ConfigurationError, Settings
from app.providers.factory import create_stt, create_tts
from app.providers.pipeline import create_session
from app.providers.registry import ProviderError, registry
from tests.test_providers import environment


def configuration(**values):
    return Settings.from_env(
        environment()
        | {
            "STT_PROVIDER": "groq",
            "TTS_PROVIDER": "groq",
            "GROQ_API_KEY": "synthetic-groq",
            "STT_ALLOW_BATCH": "true",
        }
        | values
    )


def test_selection_and_capabilities():
    settings = configuration()
    assert settings.stt.model == "whisper-large-v3-turbo"
    assert settings.tts.model == "canopylabs/orpheus-v1-english"
    assert settings.tts.voice == "troy"
    for category in ("stt", "tts"):
        assert getattr(settings, category).api_key == "synthetic-groq"
        assert not registry.get(category, "groq").capabilities.streaming
    assert not registry.get("stt", "groq").capabilities.interim_transcription


@pytest.mark.parametrize(
    "values",
    [
        {"GROQ_API_KEY": ""},
        {"STT_ALLOW_BATCH": "false"},
        {"STT_REQUIRE_INTERIM": "true"},
        {"TURN_DETECTION": "stt"},
        {"STT_MODEL": "whisper-1"},
        {"TTS_MODEL": "unsupported"},
    ],
)
def test_configuration_failures(values):
    with pytest.raises(ConfigurationError):
        configuration(**values)


@pytest.mark.parametrize("values", [{"TTS_VOICE": "Kore"}, {"TTS_LANGUAGE": "te"}])
def test_voice_language_validation(values):
    with pytest.raises(ProviderError):
        create_tts(configuration(**values).tts)


def test_stt_constructor():
    from app.providers.stt import groq

    with patch("livekit.plugins.openai.STT") as constructor:
        groq(configuration(STT_LANGUAGE="te").stt)
        constructor.assert_called_once_with(
            api_key="synthetic-groq",
            model="whisper-large-v3-turbo",
            language="te",
            base_url="https://api.groq.com/openai/v1",
            use_realtime=False,
        )


def test_native_batch_pipeline():
    async def check():
        session = create_session(configuration())
        try:
            assert isinstance(session.stt, StreamAdapter)
            assert not session.stt.wrapped_stt.capabilities.streaming
            assert not session.stt.capabilities.interim_results
        finally:
            await session.aclose()
            await session.stt.wrapped_stt.aclose()
            await session.stt.aclose()
            await session.llm.aclose()
            await session.tts.aclose()

    asyncio.run(check())


def wav_bytes():
    target = io.BytesIO()
    with wave.open(target, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0\0" * 2400)
    return target.getvalue()


class Response:
    def __init__(self, *, block=False, failure=None):
        self.block, self.failure = block, failure
        self.entered = asyncio.Event()
        self.closed = False

    async def __aenter__(self):
        self.entered.set()
        if self.failure:
            raise self.failure
        return self

    async def __aexit__(self, *_args):
        self.closed = True

    async def iter_bytes(self):
        if self.block:
            await asyncio.Event().wait()
        yield wav_bytes()


def test_wav_decoding_request_and_long_text():
    async def check():
        provider = create_tts(configuration().tts)
        responses, requests = [], []

        def request(**kwargs):
            requests.append(kwargs)
            response = Response()
            responses.append(response)
            return response

        provider.client.audio.speech.with_streaming_response.create = request
        try:
            frames = []
            async with provider.synthesize("A long test sentence. " * 25) as stream:
                async for event in stream:
                    frames.append(event.frame)
            assert len(requests) > 1
            assert all(len(r["input"]) <= 200 for r in requests)
            assert all(r["response_format"] == "wav" for r in requests)
            assert all("stream_format" not in r for r in requests)
            assert all(r["voice"] == "troy" for r in requests)
            assert all(r.closed for r in responses)
            assert frames and all(f.sample_rate == 24000 for f in frames)
            assert sum(f.samples_per_channel for f in frames) >= 2400 * len(requests)
        finally:
            await provider.aclose()

    asyncio.run(check())


def test_failure_is_sanitized_and_not_retried():
    async def check():
        import httpx2 as httpx

        provider = create_tts(configuration().tts)
        error = openai.BadRequestError(
            "private input",
            response=httpx.Response(400, request=httpx.Request("POST", "https://test")),
            body={"message": "private input"},
        )
        calls = []

        def request(**_kwargs):
            calls.append(True)
            return Response(failure=error)

        provider.client.audio.speech.with_streaming_response.create = request
        try:
            with pytest.raises(APIStatusError) as caught:
                async with provider.synthesize(
                    "private input", conn_options=APIConnectOptions(max_retry=0)
                ) as stream:
                    async for _ in stream:
                        pass
            assert caught.value.status_code == 400
            assert "private input" not in str(caught.value)
            assert caught.value.body is None
            assert len(calls) == 1
        finally:
            await provider.aclose()

    asyncio.run(check())


def test_native_stream_cancellation_closes_response():
    async def check():
        provider = create_tts(configuration().tts)
        response = Response(block=True)
        provider.client.audio.speech.with_streaming_response.create = lambda **_: (
            response
        )
        stream = provider.synthesize("Hello.")
        try:
            await asyncio.wait_for(response.entered.wait(), timeout=2)
            await asyncio.wait_for(stream.aclose(), timeout=2)
            assert response.closed
        finally:
            await stream.aclose()
            await provider.aclose()

    asyncio.run(check())


def test_timeout_is_bounded_and_closes_response():
    async def check():
        provider = create_tts(configuration().tts)
        response = Response(block=True)
        provider.client.audio.speech.with_streaming_response.create = lambda **_: (
            response
        )
        try:
            with pytest.raises(APITimeoutError):
                async with provider.synthesize(
                    "Hello.",
                    conn_options=APIConnectOptions(max_retry=0, timeout=0.01),
                ) as stream:
                    async for _ in stream:
                        pass
            assert response.closed
        finally:
            await provider.aclose()

    asyncio.run(check())


def test_stt_native_final_transcript_and_transport():
    async def check():
        provider = create_stt(configuration().stt)
        request = AsyncMock(
            return_value=SimpleNamespace(text="Synthetic test.", languages=[])
        )
        provider._client.audio.transcriptions.create = request
        try:
            frame = rtc.AudioFrame(
                data=b"\0\0" * 1600,
                sample_rate=16000,
                num_channels=1,
                samples_per_channel=1600,
            )
            result = await provider.recognize(frame)
            assert result.alternatives[0].text == "Synthetic test."
            kwargs = request.call_args.kwargs
            assert kwargs["model"] == "whisper-large-v3-turbo"
            assert kwargs["file"][1].startswith(b"RIFF")
        finally:
            await provider.aclose()

    asyncio.run(check())
